import asyncio
from playwright.async_api import async_playwright
from apify import Actor

# --- CONFIGURATION ---
TIMEOUT = 15000  # 15 secondes pour laisser le temps aux sites lents
CONCURRENCY_LIMIT = 10 # Stable pour 4GB de RAM

async def get_text_from_page(page, url):
    try:
        # Bloque les éléments lourds pour la vitesse
        await page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        
        response = await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        if not response or response.status >= 400: return ""

        return await page.evaluate('''() => {
            ['script','style','nav','footer','header'].forEach(t => document.querySelectorAll(t).forEach(e => e.remove()));
            return document.body.innerText.replace(/\\s+/g, ' ').trim().substring(0, 3000);
        }''')
    except: return ""

async def process_site(semaphore, browser, domain, emails, processed_list):
    if domain in processed_list: return

    async with semaphore:
        context = await browser.new_context(user_agent="Mozilla/5.0", ignore_https_errors=True)
        try:
            page = await context.new_page()
            # 1. Tentative de connexion
            try:
                res = await page.goto(f'https://{domain}', wait_until="domcontentloaded", timeout=TIMEOUT)
            except: return

            # 2. Extraction des liens avec SÉCURITÉ (C'est ici que ça plantait)
            links = []
            try:
                # On attend 1 seconde que la page soit stable
                await asyncio.sleep(1) 
                anchors = await page.query_selector_all("a[href]")
                for a in anchors:
                    href = await a.get_attribute("href")
                    if href and any(k in href.lower() for k in ['contact', 'about', 'propos']) and domain in href:
                        links.append(href)
                links = list(set(links))[:2] # Max 2 pages supp.
            except: pass # Si le contexte meurt ici, on ignore et on garde la page d'accueil

            # 3. Récupération du contenu
            all_urls = [f'https://{domain}'] + links
            content_parts = []
            for u in all_urls:
                txt = await get_text_from_page(page, u)
                if txt: content_parts.append(f"--- {u} ---\n{txt}")

            if content_parts:
                await Actor.push_data({"site": domain, "emails": emails, "content": "\n".join(content_parts)})
                print(f"✅ OK: {domain}")

        except Exception as e: print(f"⚠️ Erreur {domain}: {str(e)}")
        finally: await context.close()

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        data = actor_input.get("sites", {})
        if not data: return

        # Récupération de l'avancement pour éviter les doublons
        dataset = await Actor.open_dataset()
        existing_items = await dataset.get_data()
        processed_list = {item['site'] for item in existing_items.items if 'site' in item}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            tasks = [process_site(semaphore, browser, dom, mail, processed_list) for dom, mail in data.items()]
            await asyncio.gather(*tasks)
            await browser.close()


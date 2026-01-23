import asyncio
import json
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from apify import Actor

TIMEOUT = 12000  
CONCURRENCY_LIMIT = 10 
KEYWORDS = ['contact', 'about', 'propos', 'legal', 'team']

async def get_text_from_page(page, url):
    try:
        await page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        response = await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        if not response or response.status >= 400: return ""
        text = await page.evaluate('''() => {
            ['script','style','nav','footer','header','iframe'].forEach(t => document.querySelectorAll(t).forEach(e => e.remove()));
            return (document.querySelector('main') || document.body).innerText.replace(/\\s+/g, ' ').trim();
        }''')
        return f"--- {url} ---\n{text[:2000]}\n"
    except: return ""

async def process_site(semaphore, browser, domain, emails, processed_list):
    # SI LE SITE EST DÉJÀ DANS LA LISTE, ON PASSE
    if domain in processed_list:
        return

    async with semaphore:
        context = await browser.new_context(user_agent="Mozilla/5.0", ignore_https_errors=True)
        try:
            page = await context.new_page()
            target_url = f'https://{domain}'
            try:
                res = await page.goto(target_url, wait_until="domcontentloaded", timeout=10000)
                if not res or res.status >= 400: return
            except: return

            # Correction de l'erreur context destroyed : on entoure l'extraction
            try:
                links = await page.eval_on_selector_all("a[href]", f"""(anchors) => {{
                    const regex = /{'|'.join(KEYWORDS)}/i;
                    return anchors.map(a => a.href).filter(h => h.includes("{domain}") && regex.test(h)).slice(0, 2);
                }}""")
            except: links = []

            all_urls = list(set([target_url] + links))
            tasks = [get_text_from_page(page, u) for u in all_urls]
            pages_content = await asyncio.gather(*tasks)
            
            final_content = "".join(pages_content).strip()
            if final_content:
                await Actor.push_data({"site": domain, "emails": emails, "content": final_content})
                print(f"✅ OK: {domain}")
        except Exception as e:
            print(f"⚠️ Erreur sur {domain}")
        finally:
            await context.close()

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        data = actor_input.get("sites", {})
        if not data: return

        # RÉCUPÉRATION DES SITES DÉJÀ FAITS (Anti-doublon après crash)
        dataset = await Actor.open_dataset()
        dataset_info = await dataset.get_info()
        processed_list = set()
        
        if dataset_info and dataset_info.get('itemCount', 0) > 0:
            print("🔍 Chargement de l'avancement...")
            # On récupère les noms des sites déjà présents dans le dataset
            existing_items = await dataset.get_data()
            for item in existing_items.items:
                processed_list.add(item.get('site'))
            print(f"⏭️ {len(processed_list)} sites déjà traités, on les ignore.")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            tasks = [process_site(semaphore, browser, dom, mail, processed_list) for dom, mail in data.items()]
            await asyncio.gather(*tasks)
            await browser.close()

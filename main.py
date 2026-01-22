import asyncio
import json
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from apify import Actor

# --- CONFIGURATION OPTIMISÉE ---
TIMEOUT = 25000  # 25s pour ne pas bloquer trop longtemps sur un site lent
CONCURRENCY_LIMIT = 10  # Traite 10 sites en même temps
KEYWORDS = ['contact', 'about', 'propos', 'service', 'equipe', 'team', 'offre', 'legal']

async def get_text_from_page(page, url):
    try:
        # Blocage agressif des ressources pour la vitesse
        await page.route("**/*.{png,jpg,jpeg,pdf,css,woff,svg,gif,ico,mp4,webp,ttf}", lambda route: route.abort())
        
        response = await page.goto(url, wait_until="commit", timeout=TIMEOUT) # "commit" est plus rapide que "domcontentloaded"
        
        if not response or response.status >= 400:
            return ""

        text = await page.evaluate('''() => {
            const toRemove = ['script', 'style', 'nav', 'footer', 'header', 'iframe', 'noscript', 'svg', 'aside'];
            toRemove.forEach(tag => {
                const els = document.querySelectorAll(tag);
                els.forEach(el => el.remove());
            });
            const content = document.querySelector('main') || document.querySelector('article') || document.body;
            return content ? content.innerText.replace(/\\s+/g, ' ').trim() : "";
        }''')
        
        return f"--- URL: {url} ---\n{text}\n" if len(text) > 100 else ""
    except:
        return ""

async def process_site(semaphore, browser, domain, emails):
    """Gère un site avec une limite de concurrence."""
    async with semaphore: # Empêche de lancer 5000 navigateurs en même temps
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            ignore_https_errors=True
        )
        try:
            page = await context.new_page()
            target_url = None

            # Test rapide HTTPS/HTTP
            for proto in [f'https://{domain}', f'http://{domain}']:
                try:
                    res = await page.goto(proto, wait_until="commit", timeout=15000)
                    if res and res.status < 400:
                        target_url = proto
                        break
                except:
                    continue

            if not target_url:
                await context.close()
                return

            # Extraction des liens
            domain_part = urlparse(target_url).netloc.replace('www.', '')
            links = await page.eval_on_selector_all("a[href]", f"""(anchors) => {{
                const keys = {json.dumps(KEYWORDS)};
                const regex = new RegExp(keys.join('|'), 'i');
                return anchors
                    .map(a => a.href)
                    .filter(h => h.includes("{domain_part}") && regex.test(h))
                    .slice(0, 3); // Limité à 3 sous-pages pour gagner du temps
            }}""")

            all_urls = list(set([target_url] + links))
            
            # Scrape les pages du site en parallèle également
            tasks = [get_text_from_page(page, u) for u in all_urls]
            pages_content = await asyncio.gather(*tasks)
            
            content = "".join(pages_content)
            
            if content.strip():
                await Actor.push_data({"site": domain, "emails": emails, "content": content})
                print(f"✅ Terminé: {domain}")

        except Exception as e:
            print(f"❌ Erreur {domain}: {e}")
        finally:
            await context.close()

async def main():
    async with Actor:
        store = await Actor.open_key_value_store()
        data = await store.get_value("SITES_LIST")

        if not data:
            Actor.log.error("Fichier SITES_LIST vide ou introuvable.")
            return

        print(f"🚀 Lancement du boost : {len(data)} sites avec {CONCURRENCY_LIMIT} workers.")

        async with async_playwright() as p:
            # On utilise un seul navigateur mais plusieurs contextes (plus léger)
            browser = await p.chromium.launch(headless=True)
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            
            # Création de toutes les tâches
            tasks = [process_site(semaphore, browser, domain, emails) for domain, emails in data.items()]
            
            # Lancement global
            await asyncio.gather(*tasks)

            await browser.close()
        
        print("🏁 Scraping terminé.")

if __name__ == "__main__":
    asyncio.run(main())

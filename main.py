import asyncio
import json
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from apify import Actor

# --- CONFIGURATION EXTRÊME ---
TIMEOUT = 10000  # 10 secondes max par page
CONCURRENCY_LIMIT = 15 # Boosté pour 4GB RAM
KEYWORDS = ['contact', 'about', 'propos', 'legal', 'team']

async def get_text_from_page(page, url):
    try:
        # Bloque absolument TOUT sauf le texte HTML
        await page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["image", "media", "font", "style", "stylesheet", "other"] 
            else route.continue_())
        
        response = await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        if not response or response.status >= 400: return ""

        text = await page.evaluate('''() => {
            ['script','style','nav','footer','header','iframe','svg'].forEach(t => document.querySelectorAll(t).forEach(e => e.remove()));
            return (document.querySelector('main') || document.body).innerText.replace(/\\s+/g, ' ').trim();
        }''')
        return f"--- {url} ---\n{text[:2000]}\n" # On limite à 2000 caractères pour gagner du temps
    except: return ""

async def process_site(semaphore, browser, domain, emails):
    async with semaphore:
        context = await browser.new_context(user_agent="Mozilla/5.0", ignore_https_errors=True)
        try:
            page = await context.new_page()
            target_url = None
            # On ne teste que le HTTPS pour aller plus vite
            try:
                res = await page.goto(f'https://{domain}', wait_until="domcontentloaded", timeout=8000)
                if res and res.status < 400: target_url = f'https://{domain}'
            except: pass

            if not target_url: return

            # Extraction rapide des liens de contact
            links = await page.eval_on_selector_all("a[href]", f"""(anchors) => {{
                const regex = /{'|'.join(KEYWORDS)}/i;
                return anchors.map(a => a.href).filter(h => h.includes("{domain}") && regex.test(h)).slice(0, 2);
            }}""")

            all_urls = list(set([target_url] + links))
            tasks = [get_text_from_page(page, u) for u in all_urls]
            pages_content = await asyncio.gather(*tasks)
            
            final_content = "".join(pages_content).strip()
            if final_content:
                await Actor.push_data({"site": domain, "emails": emails, "content": final_content})
                print(f"🚀 {domain} terminé")
        finally: await context.close()

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        data = actor_input.get("sites", {})
        if not data: return

        async with async_playwright() as p:
            # Lancement du navigateur avec optimisation CPU
            browser = await p.chromium.launch(headless=True, args=['--disable-gpu', '--disable-dev-shm-usage'])
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            tasks = [process_site(semaphore, browser, dom, mail) for dom, mail in data.items()]
            await asyncio.gather(*tasks)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

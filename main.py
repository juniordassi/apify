import asyncio
import json
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from apify import Actor

# --- CONFIGURATION ---
TIMEOUT = 25000  
CONCURRENCY_LIMIT = 8 
KEYWORDS = ['contact', 'about', 'propos', 'service', 'equipe', 'team', 'offre', 'legal']

async def get_text_from_page(page, url):
    try:
        await page.route("**/*.{png,jpg,jpeg,pdf,css,woff,svg,gif,ico,mp4,webp,ttf}", lambda route: route.abort())
        response = await page.goto(url, wait_until="commit", timeout=TIMEOUT)
        if not response or response.status >= 400: return ""
        text = await page.evaluate('''() => {
            const toRemove = ['script', 'style', 'nav', 'footer', 'header', 'iframe', 'noscript', 'svg', 'aside'];
            toRemove.forEach(tag => { const els = document.querySelectorAll(tag); els.forEach(el => el.remove()); });
            const content = document.querySelector('main') || document.querySelector('article') || document.body;
            return content ? content.innerText.replace(/\\s+/g, ' ').trim() : "";
        }''')
        return f"--- URL: {url} ---\n{text}\n" if len(text) > 100 else ""
    except: return ""

async def process_site(semaphore, browser, domain, emails):
    async with semaphore:
        context = await browser.new_context(user_agent="Mozilla/5.0...", ignore_https_errors=True)
        try:
            page = await context.new_page()
            target_url = None
            for proto in [f'https://{domain}', f'http://{domain}']:
                try:
                    res = await page.goto(proto, wait_until="commit", timeout=15000)
                    if res and res.status < 400:
                        target_url = proto
                        break
                except: continue
            if not target_url: return
            domain_part = urlparse(target_url).netloc.replace('www.', '')
            links = await page.eval_on_selector_all("a[href]", f"""(anchors) => {{
                const keys = {json.dumps(KEYWORDS)};
                const regex = new RegExp(keys.join('|'), 'i');
                return anchors.map(a => a.href).filter(h => h.includes("{domain_part}") && regex.test(h)).slice(0, 3);
            }}""")
            all_urls = list(set([target_url] + links))
            tasks = [get_text_from_page(page, u) for u in all_urls]
            pages_content = await asyncio.gather(*tasks)
            content = "".join(pages_content)
            if content.strip():
                await Actor.push_data({"site": domain, "emails": emails, "content": content})
                print(f"✅ OK: {domain}")
        finally: await context.close()

async def main():
    async with Actor:
        # L'ACTOR LIT DIRECTEMENT CE QUE TU COLLES DANS L'ONGLET INPUT
        actor_input = await Actor.get_input() or {}
        data = actor_input.get("sites", {})

        if not data:
            Actor.log.error("ERREUR : L'entrée 'sites' est vide. Colle ton JSON dans l'onglet Input.")
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            tasks = [process_site(semaphore, browser, domain, emails) for domain, emails in data.items()]
            await asyncio.gather(*tasks)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

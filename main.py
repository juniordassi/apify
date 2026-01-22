import asyncio
import json
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from apify import Actor

async def get_text_from_page(page, url, timeout):
    try:
        await page.route("**/*.{png,jpg,jpeg,pdf,css,woff,svg,gif,ico}", lambda route: route.abort())
        response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        if not response or response.status >= 400:
            return ""

        text = await page.evaluate('''() => {
            const toRemove = ['script', 'style', 'nav', 'footer', 'header', 'iframe', 'noscript', 'svg'];
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

async def main():
    async with Actor:
        # 1. Récupérer l'entrée (ton JSON d'emails)
        # Sur Apify, on passe les données via l'interface "Input"
        actor_input = await Actor.get_input() or {}
        sites_to_process = actor_input.get("sites", {})
        
        if not sites_to_process:
            print("Aucune donnée d'entrée trouvée.")
            return

        keywords = ['contact', 'about', 'propos', 'service', 'equipe', 'team', 'offre', 'legal']
        timeout = 30000

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            for domain, emails in sites_to_process.items():
                print(f"Traitement de : {domain}")
                
                context = await browser.new_context(
                    user_agent="Mozilla/5.0...",
                    ignore_https_errors=True
                )
                
                # ... (ton code de traitement process_site ici) ...
                # Une fois le résultat obtenu :
                
                result = {"site": domain, "emails": emails, "content": "..."} # Ton résultat
                
                # 2. Sauvegarder dans le Dataset d'Apify (au lieu d'un fichier .jsonl)
                await Actor.push_data(result)
                
                await context.close()

            await browser.close()

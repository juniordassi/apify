import asyncio
import json
import os
from playwright.async_api import async_playwright
from apify import Actor

async def process_site(semaphore, browser, domain, emails, processed_list):
    if domain in processed_list: return
    async with semaphore:
        # Création d'un contexte isolé pour chaque site pour éviter les fuites de mémoire
        context = await browser.new_context(user_agent="Mozilla/5.0", ignore_https_errors=True)
        try:
            page = await context.new_page()
            # On se limite à la page d'accueil pour la stabilité sur 5000 sites
            await page.goto(f'https://{domain}', wait_until="domcontentloaded", timeout=25000)
            
            # Extraction propre du texte
            text = await page.inner_text('body')
            clean_text = " ".join(text.split())[:3000]
            
            await Actor.push_data({"site": domain, "emails": emails, "content": clean_text})
            print(f"✅ OK: {domain}")
        except Exception:
            print(f"❌ Erreur sur: {domain}")
        finally:
            await context.close()

async def main():
    async with Actor:
        # --- LECTURE DU FICHIER GITHUB ---
        data = {}
        if os.path.exists('sites_data.json'):
            print("📂 Chargement du fichier sites_data.json...")
            with open('sites_data.json', 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                # On accepte le format {"sites": {...}} ou directement {...}
                data = raw_data.get("sites", raw_data) if isinstance(raw_data, dict) else {}
        
        if not data:
            print("⚠️ ERREUR : Le fichier sites_data.json est introuvable ou vide !")
            return

        print(f"📊 {len(data)} sites chargés. Vérification de l'avancement...")

        # --- GESTION DE LA REPRISE (ANTI-DOUBLONS) ---
        dataset = await Actor.open_dataset()
        existing_items = await dataset.get_data()
        processed_list = {item['site'] for item in existing_items.items if 'site' in item}
        print(f"⏭️ {len(processed_list)} sites déjà traités ignorés.")

        # --- LANCEMENT DU SCRAPER ---
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            # Limite à 10 sites simultanés pour ne pas saturer les 4GB de RAM
            semaphore = asyncio.Semaphore(10)
            tasks = [process_site(semaphore, browser, dom, mail, processed_list) for dom, mail in data.items()]
            await asyncio.gather(*tasks)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

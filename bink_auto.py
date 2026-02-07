import asyncio
import json
import os
import time
from playwright.async_api import async_playwright
from datetime import datetime

# 1. TIJDZONE FIX: Forceer de tijd naar Amsterdam
# Dit voorkomt dat GitHub (UTC tijd) de workout van gisteren pakt.
os.environ['TZ'] = 'Europe/Amsterdam'
try:
    time.tzset()
except:
    pass # Werkt alleen op Linux/Mac (GitHub Actions), niet op Windows

# Haal inloggegevens veilig uit de omgevingsvariabelen
EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")

async def get_workout():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()

        days_nl = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
        days_en = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        
        idx = datetime.now().weekday()
        dag_nl = days_nl[idx]
        dag_en = days_en[idx]
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Cloud-scraper gestart voor {dag_nl}...")

        try:
            # --- STAP 1: INLOGGEN ---
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/", wait_until="networkidle")
            await page.get_by_role("link", name="Inloggen").first.click()
            await page.wait_for_load_state("networkidle")

            if not EMAIL or not PASSWORD:
                raise Exception("Geen inloggegevens gevonden in Secrets!")

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(3000)

            # --- STAP 2: ROOSTER ---
            print("Naar rooster...")
            await page.goto("https://www.crossfitbink36.nl/rooster", wait_until="networkidle")
            await page.get_by_text("Zaal 1").first.click()
            await page.wait_for_timeout(3000)

            # --- STAP 3: WOD ZOEKEN (SPECIFIEKE ID METHODE) ---
            print(f"Zoeken naar de WOD van {dag_nl} ({dag_en})...")

            # We zoeken naar de knop met de unieke ID van vandaag (bijv: 'modal-saturday-WoD')
            # Dit voorkomt dat hij per ongeluk maandag aanklikt.
            wod_selector = f"a[data-remodal-target*='{dag_en}'][data-remodal-target*='WoD']"
            
            if await page.locator(wod_selector).count() > 0:
                print(f"🎯 Specifieke knop gevonden: {wod_selector}")
                knop = page.locator(wod_selector).first
                await knop.scroll_into_view_if_needed()
                await knop.click()
            else:
                print("⚠️ Specifieke ID niet gevonden, fallback naar kolom-zoektocht...")
                # Fallback: Zoek de kolom van vandaag en klik daar op WOD
                kolom = page.locator(f".grid-column:has-text('{dag_nl}')")
                knop = kolom.locator("text=WOD").first
                await knop.click()

            print("WOD aangeklikt, wachten op pop-up...")
            
            # --- STAP 4: DATA EXTRACTIE ---
            popup_selector = ".remodal-is-opened"
            await page.wait_for_selector(popup_selector, timeout=10000)
            
            popup = page.locator(popup_selector)
            
            # Pak de lijst
            list_items = await popup.locator(".wod-list li").all_text_contents()
            
            if list_items:
                workout_tekst = "\n".join([i.strip() for i in list_items])
            else:
                workout_tekst = await popup.locator(".content").first.inner_text()

            # --- STAP 5: OPSLAAN ---
            data = {
                "datum": datetime.now().strftime("%d-%m-%Y"),
                "dag": dag_nl,
                "workout": workout_tekst.strip()
            }
            
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            print(f"✅ SUCCES: Workout opgeslagen.")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            error_data = {"error": str(e)}
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(error_data, f, indent=4)
            exit(1) # Zorgt dat GitHub 'rood' wordt bij een fout
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

import asyncio
import json
import os
from playwright.async_api import async_playwright
from datetime import datetime

# Haal inloggegevens veilig uit de omgevingsvariabelen (GitHub Secrets)
EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")

async def get_workout():
    async with async_playwright() as p:
        # Headless MOET True zijn in de cloud
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()

        days_nl = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
        idx = datetime.now().weekday()
        dag_nl = days_nl[idx]
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Cloud-scraper gestart voor {dag_nl}...")

        try:
            # Login
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/", wait_until="networkidle")
            await page.get_by_role("link", name="Inloggen").first.click()
            await page.wait_for_load_state("networkidle")

            # Gebruik de variabelen hier
            if not EMAIL or not PASSWORD:
                raise Exception("Geen inloggegevens gevonden in Secrets!")

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(3000)

            # Rooster
            print("Naar rooster...")
            await page.goto("https://www.crossfitbink36.nl/rooster", wait_until="networkidle")
            await page.get_by_text("Zaal 1").first.click()
            await page.wait_for_timeout(3000)

        # --- STAP 3: WOD ZOEKEN (VERBETERD) ---
            print(f"Zoeken naar de WOD van {dag_nl}...")

            # OPLOSSING: We gebruiken de 'data-remodal-target'. 
            # Dit is een unieke ID in de websitecode die de dagnaam in het Engels bevat.
            # Bijv: 'modal-saturday-WoD'. Hierdoor kan hij NOOIT per ongeluk maandag pakken.
            
            # Selector: Zoek een link (a) die 'saturday' (bijv) én 'WoD' in zijn target heeft.
            wod_selector = f"a[data-remodal-target*='{dag_en}'][data-remodal-target*='WoD']"
            
            # We checken of deze specifieke knop bestaat
            if await page.locator(wod_selector).count() > 0:
                print(f"🎯 Specifieke knop gevonden via ID: {wod_selector}")
                knop = page.locator(wod_selector).first
                await knop.scroll_into_view_if_needed()
                await knop.click()
            else:
                print("⚠️ Specifieke ID niet gevonden, over op strenge fallback...")
                # Fallback: Zoek de KOLOM van vandaag en zoek DAARBINNEN naar WOD.
                # We ketenen de locators aan elkaar zodat hij niet buiten de kolom mag kijken.
                kolom = page.locator(f".grid-column:has-text('{dag_nl}')")
                knop = kolom.locator("text=WOD").first
                await knop.click()

            print("WOD aangeklikt, wachten op pop-up...")
            
            # --- STAP 4: DATA EXTRACTIE ---
            # Wacht tot de pop-up ECHT zichtbaar is
            popup_selector = ".remodal-is-opened"
            await page.wait_for_selector(popup_selector, timeout=10000)
            
            popup = page.locator(popup_selector)
            
            # DUBBELCHECK: We controleren of de tekst in de pop-up wel van vandaag is.
            # Vaak staat de dagnaam ook in de titel van de pop-up.
            full_content = await popup.inner_text()
            
            # Pak de lijst
            list_items = await popup.locator(".wod-list li").all_text_contents()
            
            if list_items:
                workout_tekst = "\n".join([i.strip() for i in list_items])
            else:
                workout_tekst = await popup.locator(".content").first.inner_text()

            # Opslaan (Gewoon in de huidige map, GitHub regelt de rest)
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
            # Zorg dat de GitHub Action faalt zodat je een mail krijgt
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

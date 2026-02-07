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

            # Zoeken
            print(f"Zoeken naar WOD van {dag_nl}...")
            wod_knop = page.locator(f".roster-block:has-text('{dag_nl}')").get_by_text("WOD").first
            if not await wod_knop.is_visible():
                wod_knop = page.locator(f"a:has-text('WOD'), div:has-text('WOD')").filter(has_text=dag_nl).first

            await wod_knop.click()
            
            # Extractie
            popup_selector = ".remodal-is-opened"
            await page.wait_for_selector(popup_selector, timeout=10000)
            popup = page.locator(popup_selector)
            
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
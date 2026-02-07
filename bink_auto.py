import asyncio
import json
import os
import time
from playwright.async_api import async_playwright
from datetime import datetime

# 1. TIJDZONE FIX
os.environ['TZ'] = 'Europe/Amsterdam'
try:
    time.tzset()
except:
    pass

# Haal inloggegevens uit Secrets
EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")

async def get_workout():
    async with async_playwright() as p:
        # Headless True voor cloud
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()

        days_nl = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
        idx = datetime.now().weekday()
        dag_nl = days_nl[idx]
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Cloud-scraper gestart voor {dag_nl}...")

        try:
            # --- STAP 1: INLOGGEN ---
            print("Inloggen...")
            # We gaan eerst naar home om in te loggen
            await page.goto("https://www.crossfitbink36.nl/", wait_until="networkidle")
            
            # Probeer inlogknop te klikken
            try:
                await page.get_by_role("link", name="Inloggen").first.click(timeout=5000)
            except:
                print("Inlogknop niet gevonden, direct naar /login...")
                await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")

            if not EMAIL or not PASSWORD:
                raise Exception("Geen inloggegevens in Secrets!")

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(4000)

            # --- STAP 2: DIRECT NAAR DE WOD PAGINA ---
            # Dit is jouw gouden vondst: direct naar de pagina met de workout!
            target_url = "https://www.crossfitbink36.nl/?workout=wod"
            print(f"Navigeren naar: {target_url}")
            
            await page.goto(target_url, wait_until="networkidle")
            
            # --- STAP 3: DATA EXTRACTIE ---
            print("Pagina geladen, zoeken naar workout tekst...")

            # We wachten tot het label "WOD:" zichtbaar is (zie je screenshot)
            # Of tot "Share this Workout" zichtbaar is, dat staat onderaan het blok.
            await page.get_by_text("Share this Workout").first.wait_for(state="visible", timeout=15000)

            # STRATEGIE:
            # We zoeken het element dat de tekst "WOD:" bevat.
            # In je screenshot staat: "WOD: emom 32min..."
            # We pakken de container (parent) van dat stukje tekst.
            
            # Locator: Zoek naar tekst 'WOD:', en pak de ouder (het blok eromheen)
            content_block = page.locator("text=WOD:").first.locator("xpath=..")
            
            workout_tekst = await content_block.inner_text()
            
            # Schoonmaak: Als er 'Share this Workout' in de tekst zit, halen we dat weg
            if "Share this Workout" in workout_tekst:
                workout_tekst = workout_tekst.split("Share this Workout")[0]

            print("Workout gevonden!")
            print("-" * 20)
            print(workout_tekst[:100] + "...") # Print eerste stukje ter controle

            # --- STAP 4: OPSLAAN ---
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
            error_data = {"error": str(e), "datum": datetime.now().strftime("%d-%m-%Y")}
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(error_data, f, indent=4)
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

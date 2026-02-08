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
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Scraper gestart voor {dag_nl}...")

        try:
            # --- STAP 1: INLOGGEN ---
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/", wait_until="networkidle")
            
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

            # --- STAP 2: DIRECT NAAR DE WOD URL ---
            target_url = "https://www.crossfitbink36.nl/?workout=wod"
            print(f"Navigeren naar: {target_url}")
            await page.goto(target_url, wait_until="networkidle")
            
            # --- STAP 3: DATA EXTRACTIE (ALLES OPHALEN) ---
            print("Zoeken naar workout container...")

            # We wachten tot de lijst zichtbaar is (bevestiging dat WOD geladen is)
            await page.wait_for_selector(".wod-list", timeout=15000)

            # TRUCJE: We pakken de lijst (.wod-list) en gaan één niveau omhoog (xpath=..)
            # Hierdoor hebben we de 'container' (het grijze vlak) te pakken.
            # Dit bevat dus OOK de headers ("Strength", "WOD") die boven de lijst staan.
            container = page.locator(".wod-list").first.locator("xpath=..")
            
            # Pak alle tekst uit dit blok (inclusief enters en witregels)
            full_text = await container.inner_text()
            
            # --- SCHOONMAAK ---
            # Soms staat er "Share this Workout" of social media knoppen onderaan. Die halen we weg.
            if "Share this Workout" in full_text:
                full_text = full_text.split("Share this Workout")[0]
            
            # Dubbele witregels opschonen voor netheid
            lines = [line.strip() for line in full_text.splitlines() if line.strip()]
            workout_tekst = "\n".join(lines)

            # Resultaat printen ter controle in GitHub logs
            print("-" * 20)
            print(workout_tekst)
            print("-" * 20)

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

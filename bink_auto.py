import asyncio
import json
import os
import time
import urllib.request
import urllib.parse
import csv
from playwright.async_api import async_playwright
from datetime import datetime, timedelta
from openai import OpenAI

os.environ['TZ'] = 'Europe/Amsterdam'
try: time.tzset()
except: pass

EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_KEY = os.environ.get("OPENAI_API_KEY")

def update_history_csv(datum, dag, workout, coach):
    file_name = "history.csv"
    file_exists = os.path.isfile(file_name)
    with open(file_name, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists: writer.writerow(["Datum", "Dag", "Workout", "AI Coach Advies"])
        writer.writerow([datum, dag, workout.replace("\n", " | "), coach.replace("\n", " ")])

def get_ai_coach_advice(wod_text):
    if not API_KEY: return "Geen AI Key."
    try:
        client = OpenAI(api_key=API_KEY)
        prompt = (f"Hier is de WOD van vandaag:\n\n{wod_text}\n\n"
                  "Geef mij (de atleet) kort advies. Namen in de tekst verwijzen naar workouts, niet personen! "
                  "Praat niet over namen als mensen. Spreek mij direct aan met 'je'.\n"
                  "Format:\n🔥 **Focus:** [zin]\n💡 **Strategie:** [zin]\n🩹 **Tip:** [zin]")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Je bent een CrossFit coach."}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except: return "AI Error."

async def check_dag_status(page, dag_en):
    status = {
        "ingeschreven": False,
        "tijd": "",
        "deelnemers": "",
        "wachtlijst": False,
        "wachtlijst_plek": "?",
        "wachtlijst_totaal": "?"
    }
    
    zalen = [
        "https://www.crossfitbink36.nl/rooster", 
        "https://www.crossfitbink36.nl/rooster?hall=Zaal%202", 
        "https://www.crossfitbink36.nl/rooster?hall=Buiten"
    ]
    
    for zaal_url in zalen:
        await page.goto(zaal_url, wait_until="networkidle")
        await page.wait_for_timeout(1000)
        
        # --- WACHTLIJST CHECK ---
        selector_wachtlijst = f"li.on-waiting-list[data-remodal-target*='{dag_en}']"
        les_wachtlijst = page.locator(selector_wachtlijst).first
        
        if await les_wachtlijst.count() > 0:
            status["ingeschreven"] = True
            status["wachtlijst"] = True
            try: status["tijd"] = (await les_wachtlijst.locator(".event-date").first.inner_text()).strip()
            except: pass
            
            # Bot klikt op de les om de pop-up te openen
            await les_wachtlijst.click()
            try:
                await page.wait_for_selector(".remodal-is-opened", timeout=5000)
                await page.wait_for_timeout(1500) # Geef de pop-up tijd om in te laden
                
                # Lees de tekst en splits het op per regel, precies zoals in je screenshot
                modal_text = await page.locator(".remodal-is-opened").inner_text()
                lines = [line.strip() for line in modal_text.split("\n") if line.strip()]
                
                for i, line in enumerate(lines):
                    if "Aanmeldingen" in line:
                        status["deelnemers"] = lines[i+1]
                    elif "Positie op wachtlijst" in line:
                        status["wachtlijst_plek"] = lines[i+1]
                    elif line == "Wachtlijst:":
                        status["wachtlijst_totaal"] = lines[i+1]
            except Exception as e:
                print("Fout bij uitlezen wachtlijst modal:", e)
            
            # Belangrijk: Druk op 'Escape' om de pop-up weer te sluiten
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)
                
            return status # Gevonden! Stop met zoeken in andere zalen.

        # --- NORMALE INSCHRIJVING CHECK ---
        selector_ingeschreven = f"li.workout-signedup[data-remodal-target*='{dag_en}'], li[class*='signed'][data-remodal-target*='{dag_en}'], li[class*='booked'][data-remodal-target*='{dag_en}']"
        les_ingeschreven = page.locator(selector_ingeschreven).first
        
        if await les_ingeschreven.count() > 0:
            status["ingeschreven"] = True
            try: status["tijd"] = (await les_ingeschreven.locator(".event-date").first.inner_text()).strip()
            except: pass
            
            # Bot klikt op de les om deelnemersaantal uit pop-up te halen
            await les_ingeschreven.click()
            try:
                await page.wait_for_selector(".remodal-is-opened", timeout=5000)
                await page.wait_for_timeout(1500)
                
                modal_text = await page.locator(".remodal-is-opened").inner_text()
                lines = [line.strip() for line in modal_text.split("\n") if line.strip()]
                for i, line in enumerate(lines):
                    if "Aanmeldingen" in line:
                        status["deelnemers"] = lines[i+1]
            except: pass
            
            # Druk op 'Escape' om de pop-up weer te sluiten
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)
                
            return status

    return status

async def get_workout():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        days_nl = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
        days_en = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        
        dag_nl_vandaag = days_nl[now.weekday()]
        dag_en_vandaag = days_en[now.weekday()]
        datum_vandaag_str = now.strftime("%d-%m-%Y")
        
        dag_nl_morgen = days_nl[tomorrow.weekday()]
        dag_en_morgen = days_en[tomorrow.weekday()]

        try:
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/", wait_until="networkidle")
            try: await page.get_by_role("link", name="Inloggen").first.click(timeout=5000)
            except: await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000) 
            await page.locator("input[name*='user

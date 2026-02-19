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

async def check_dag_status_en_rooster(page, dag_en, is_volgende_week=False):
    status = {
        "ingeschreven": False,
        "tijd": "",
        "type": "",
        "deelnemers": "",
        "wachtlijst": False,
        "wachtlijst_plek": "?",
        "wachtlijst_totaal": "?"
    }
    
    volledig_rooster = [] # <-- NIEUW: Hier slaan we alle lessen van de dag in op
    
    zalen = {
        "Zaal 1": "https://www.crossfitbink36.nl/rooster", 
        "Zaal 2": "https://www.crossfitbink36.nl/rooster?hall=Zaal%202", 
        "Buiten": "https://www.crossfitbink36.nl/rooster?hall=Buiten"
    }
    
    for zaal_naam, zaal_url in zalen.items():
        if is_volgende_week:
            url = f"{zaal_url}&week=next" if "?" in zaal_url else f"{zaal_url}?week=next"
        else:
            url = zaal_url

        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(1000)
        
        # --- NIEUW: ALLE LESSEN VAN DEZE DAG IN DEZE ZAAL SCRAPEN ---
        selector_alle_lessen = f"li[data-remodal-target*='{dag_en}']"
        alle_lessen_elementen = await page.locator(selector_alle_lessen).all()
        
        for les in alle_lessen_elementen:
            try:
                les_tijd = (await les.locator(".event-date").first.inner_text()).strip()
                les_type = (await les.locator(".event-name").first.inner_text()).strip()
                
                # Probeer het aantal deelnemers (bijv. 14/16) direct van het blokje te lezen
                les_deelnemers = ""
                try: les_deelnemers = (await les.locator(".event-registrations").first.inner_text()).strip()
                except: pass
                
                # Bepaal of de les vol is
                les_class = await les.get_attribute("class") or ""
                les_status = "Open"
                if "full" in les_class: les_status = "Vol (Wachtlijst)"
                if "signedup" in les_class or "booked" in les_class: les_status = "Jij bent Ingeschreven"
                if "on-waiting-list" in les_class: les_status = "Jij staat op Wachtlijst"
                
                volledig_rooster.append({
                    "tijd": les_tijd,
                    "type": les_type,
                    "zaal": zaal_naam,
                    "deelnemers": les_deelnemers,
                    "status": les_status
                })
            except: pass

        # --- JOUW PERSOONLIJKE INSCHRIJVING CHECK (Wachtlijst) ---
        selector_wachtlijst = f"li.on-waiting-list[data-remodal-target*='{dag_en}']"
        les_wachtlijst = page.locator(selector_wachtlijst).first
        
        if not status["ingeschreven"] and await les_wachtlijst.count() > 0:
            status["ingeschreven"] = True
            status["wachtlijst"] = True
            try: status["tijd"] = (await les_wachtlijst.locator(".event-date").first.inner_text()).strip()
            except: pass
            try: status["type"] = (await les_wachtlijst.locator(".event-name").first.inner_text()).strip()
            except: pass
            
            await les_wachtlijst.click()
            try:
                await page.wait_for_selector(".remodal-is-opened", timeout=5000)
                await page.wait_for_timeout(1500) 
                modal_data = await page.evaluate('''() => {
                    let res = {};
                    let cols = Array.from(document.querySelectorAll('.remodal-is-opened .grid .col'));
                    for (let i = 0; i < cols.length; i++) {
                        let text = cols[i].innerText.trim();
                        if (text.includes('Aanmeldingen')) res.deelnemers = cols[i+1] ? cols[i+1].innerText.trim() : '';
                        else if (text.includes('Positie op wachtlijst')) res.wachtlijst_plek = cols[i+1] ? cols[i+1].innerText.trim() : '';
                        else if (text === 'Wachtlijst:' || text === 'Wachtlijst') res.wachtlijst_totaal = cols[i+1] ? cols[i+1].innerText.trim() : '';
                    }
                    return res;
                }''')
                if modal_data.get("deelnemers"): status["deelnemers"] = modal_data["deelnemers"]
                if modal_data.get("wachtlijst_plek"): status["wachtlijst_plek"] = modal_data["wachtlijst_plek"]
                if modal_data.get("wachtlijst_totaal"): status["wachtlijst_totaal"] = modal_data["wachtlijst_totaal"]
            except: pass
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)

        # --- JOUW PERSOONLIJKE INSCHRIJVING CHECK (Normaal) ---
        selector_ingeschreven = f"li.workout-signedup[data-remodal-target*='{dag_en}'], li[class*='signed'][data-remodal-target*='{dag_en}'], li[class*='booked'][data-remodal-target*='{dag_en}']"
        les_ingeschreven = page.locator(selector_ingeschreven).first
        
        if not status["ingeschreven"] and await les_ingeschreven.count() > 0:
            status["ingeschreven"] = True
            try: status["tijd"] = (await les_ingeschreven.locator(".event-date").first.inner_text()).strip()
            except: pass
            try: status["type"] = (await les_ingeschreven.locator(".event-name").first.inner_text()).strip()
            except: pass
            
            await les_ingeschreven.click()
            try:
                await page.wait_for_selector(".remodal-is-opened", timeout=5000)
                await page.wait_for_timeout(1500)
                modal_data = await page.evaluate('''() => {
                    let res = {};
                    let cols = Array.from(document.querySelectorAll('.remodal-is-opened .grid .col'));
                    for (let i = 0; i < cols.length; i++) {
                        if (cols[i].innerText.includes('Aanmeldingen')) res.deelnemers = cols[i+1] ? cols[i+1].innerText.trim() : '';
                    }
                    return res;
                }''')
                if modal_data.get("deelnemers"): status["deelnemers"] = modal_data["deelnemers"]
            except: pass
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)

    # Sorteer het rooster netjes op tijdstip
    volledig_rooster = sorted(volledig_rooster, key=lambda x: x['tijd'])
    
    return status, volledig_rooster

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

        morgen_is_volgende_week = (now.weekday() == 6)

        try:
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/", wait_until="networkidle")
            try: await page.get_by_role("link", name="Inloggen").first.click(timeout=5000)
            except: await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000) 
            
            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(4000)

            print("WOD checken...")
            await page.goto("https://www.crossfitbink36.nl/?workout=wod", wait_until="domcontentloaded")
            try:
                await page.wait_for_selector(".wod-list", timeout=5000)
                container = page.locator(".wod-list").first.locator("xpath=..")
                full_text = await container.inner_text()
                if "Share this Workout" in full_text: full_text = full_text.split("Share this Workout")[0]
            except: full_text = "Geen WOD tekst gevonden."

            print("Naar Rooster voor status vandaag & morgen (Inclusief Compleet Rooster)...")
            status_vandaag, rooster_vandaag = await check_dag_status_en_rooster(page, dag_en_vandaag, is_volgende_week=False)
            status_morgen, rooster_morgen = await check_dag_status_en_rooster(page, dag_en_morgen, is_volgende_week=morgen_is_volgende_week)

            ai_advies = get_ai_coach_advice(full_text)

            bestaande_post_workout = None
            try:
                if os.path.exists("workout.json"):
                    with open("workout.json", "r", encoding="utf-8") as f:
                        oud_data = json.load(f)
                        if oud_data.get("datum") == datum_vandaag_str:
                            bestaande_post_workout = oud_data.get("post_workout")
            except: pass

            data = {
                "datum": datum_vandaag_str,
                "dag": dag_nl_vandaag,
                "workout": full_text.strip(),
                "coach": ai_advies,
                "status_vandaag": status_vandaag,
                "rooster_vandaag": rooster_vandaag, # <-- NIEUW
                "dag_morgen": dag_nl_morgen,
                "status_morgen": status_morgen,
                "rooster_morgen": rooster_morgen    # <-- NIEUW
            }
            if bestaande_post_workout: data["post_workout"] = bestaande_post_workout
            
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            if len(full_text) > 10:
                update_history_csv(datum_vandaag_str, dag_nl_vandaag, full_text.strip(), ai_advies)
            print("✅ Succesvol!")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            exit(1)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

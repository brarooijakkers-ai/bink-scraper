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
    
    # We checken nu alle drie de tabbladen (Zaal 1, Zaal 2 en Buiten)
    zalen = [
        "https://www.crossfitbink36.nl/rooster", 
        "https://www.crossfitbink36.nl/rooster?hall=Zaal%202", 
        "https://www.crossfitbink36.nl/rooster?hall=Buiten"
    ]
    
    for zaal_url in zalen:
        await page.goto(zaal_url, wait_until="networkidle")
        await page.wait_for_timeout(1000)
        
        # --- WACHTLIJST CHECK (Op basis van je screenshot) ---
        selector_wachtlijst = f"li.on-waiting-list[data-remodal-target*='{dag_en}']"
        les_wachtlijst = page.locator(selector_wachtlijst).first
        
        if await les_wachtlijst.count() > 0:
            status["ingeschreven"] = True
            status["wachtlijst"] = True
            try: status["tijd"] = (await les_wachtlijst.locator(".event-date").first.inner_text()).strip()
            except: pass
            
            # Bot klikt op de les om de pop-up te openen
            await les_wachtlijst.click()
            await page.wait_for_timeout(1500)
            
            try:
                # Leest exact de getallen af uit het schema in je screenshot
                modal_text = await page.locator(".remodal-is-opened").inner_text()
                for line in modal_text.split("\n"):
                    if "Aanmeldingen:" in line:
                        status["deelnemers"] = line.split(":")[-1].strip()
                    elif "Positie op wachtlijst:" in line:
                        status["wachtlijst_plek"] = line.split(":")[-1].strip()
                    elif "Wachtlijst:" in line and "Positie" not in line:
                        status["wachtlijst_totaal"] = line.split(":")[-1].strip()
            except Exception as e:
                print("Fout bij uitlezen wachtlijst modal:", e)
                
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
            await page.wait_for_timeout(1500)
            try:
                modal_text = await page.locator(".remodal-is-opened").inner_text()
                for line in modal_text.split("\n"):
                    if "Aanmeldingen:" in line:
                        status["deelnemers"] = line.split(":")[-1].strip()
            except:
                try: status["deelnemers"] = (await les_ingeschreven.locator(".event-registrations").first.inner_text()).strip()
                except: pass
                
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

            print("Naar Rooster voor status vandaag & morgen (checkt alle zalen)...")
            status_vandaag = await check_dag_status(page, dag_en_vandaag)
            status_morgen = await check_dag_status(page, dag_en_morgen)

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
                "dag_morgen": dag_nl_morgen,
                "status_morgen": status_morgen
            }
            if bestaande_post_workout: data["post_workout"] = bestaande_post_workout
            
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            if len(full_text) > 10:
                update_history_csv(datum_vandaag_str, dag_nl_vandaag, full_text.strip(), ai_advies)
            print("✅ Succesvol beide dagen en alle zalen verwerkt!")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            exit(1)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

import asyncio
import json
import os
import time
import urllib.request
import urllib.parse
import csv
from playwright.async_api import async_playwright
from datetime import datetime
from openai import OpenAI

# Tijdzone instellen
os.environ['TZ'] = 'Europe/Amsterdam'
try:
    time.tzset()
except:
    pass

EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_KEY = os.environ.get("OPENAI_API_KEY")

def stuur_telegram(bericht):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": bericht, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req)
    except: pass

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
        prompt = (f"Je bent een CrossFit coach. Analyseer kort:\n{wod_text}\n"
                  "Format:\n🔥 **Focus:** [zin]\n💡 **Strategie:** [zin]\n🩹 **Tip:** [zin]")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Coach mode."}, {"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except: return "AI Error."

async def get_workout():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        days_nl = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
        now = datetime.now()
        dag_nl = days_nl[now.weekday()]
        datum_str = now.strftime("%d-%m-%Y")

        mijn_status = {
            "ingeschreven": False,
            "tijd": "",
            "deelnemers": "",
            "wachtlijst": False,
            "wachtlijst_plek": "?"
        }

        try:
            # 1. Inloggen (Nu met extra geduld en slimmere selectors)
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/login", wait_until="networkidle")
            
            # Extra wachtstap voor vertraagde inlogformulieren
            await page.wait_for_timeout(2000)
            
            # Eventuele cookie banner wegklikken als die er is
            try:
                await page.locator("text=Akkoord, text=Accepteer, text=Begrepen").first.click(timeout=1000)
            except:
                pass # Geen banner gevonden, we gaan gewoon door

            # Zoek het e-mail veld en wacht tot het écht zichtbaar is
            email_veld = page.locator("input[type='email'], input[name*='email'], input[name*='user']").first
            await email_veld.wait_for(state="visible", timeout=20000)
            
            await email_veld.fill(EMAIL)
            await page.locator("input[type='password'], input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            
            print("Wachten op dashboard na inloggen...")
            await page.wait_for_timeout(3000)

            # 2. WOD Ophalen
            print("WOD checken...")
            await page.goto("https://www.crossfitbink36.nl/?workout=wod", wait_until="domcontentloaded")
            try:
                await page.wait_for_selector(".wod-list", timeout=10000) # Ook hier iets meer geduld
                container = page.locator(".wod-list").first.locator("xpath=..")
                full_text = await container.inner_text()
                if "Share this Workout" in full_text: full_text = full_text.split("Share this Workout")[0]
            except:
                full_text = "Geen WOD tekst gevonden (rustdag?)."

            # 3. Status Checken via de HTML Classes (Jouw eerdere ontdekking)
            print("Naar Rooster voor status...")
            await page.goto("https://www.crossfitbink36.nl/rooster", wait_until="networkidle")
            await page.wait_for_timeout(2000) 
            
            les_ingeschreven = page.locator("li.workout-signedup").first
            
            if await les_ingeschreven.count() > 0:
                print("✅ Inschrijving gevonden!")
                mijn_status["ingeschreven"] = True
                try:
                    tijd = await les_ingeschreven.locator(".event-date").first.inner_text()
                    mijn_status["tijd"] = tijd.strip()
                except: pass
                
                try:
                    deelnemers = await les_ingeschreven.locator(".event-registrations").first.inner_text()
                    mijn_status["deelnemers"] = deelnemers.strip()
                except: pass

            else:
                les_wachtlijst = page.locator("li[class*='waitlist']").first
                if await les_wachtlijst.count() > 0:
                    print("⏳ Wachtlijst gevonden!")
                    mijn_status["ingeschreven"] = True
                    mijn_status["wachtlijst"] = True
                    try:
                        tijd = await les_wachtlijst.locator(".event-date").first.inner_text()
                        mijn_status["tijd"] = tijd.strip()
                    except: pass
                else:
                    print("❌ Niet ingeschreven.")

            # --- AI & OPSLAAN ---
            ai_advies = get_ai_coach_advice(full_text)

            data = {
                "datum": datum_str,
                "dag": dag_nl,
                "workout": full_text.strip(),
                "coach": ai_advies,
                "status": mijn_status 
            }
            
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            if len(full_text) > 10:
                update_history_csv(datum_str, dag_nl, full_text.strip(), ai_advies)
            
            print(f"✅ Opgeslagen! Status: {mijn_status}")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

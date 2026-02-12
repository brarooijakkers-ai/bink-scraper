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

# Gegevens
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

        # Voor opslag van persoonlijke status
        mijn_status = {
            "ingeschreven": False,
            "tijd": "",
            "deelnemers": "",
            "wachtlijst": False,
            "wachtlijst_plek": 0
        }

        try:
            # --- 1. ROBUUST INLOGGEN ---
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/login", wait_until="networkidle")
            
            try:
                login_field = page.locator("input[type='email'], input[name*='user'], input[name*='login'], input[name*='email']").first
                await login_field.fill(EMAIL)
            except Exception as e:
                print(f"⚠️ Eerste poging mislukt, fallback gebruiken... ({e})")
                await page.locator("input:not([type='hidden'])").first.fill(EMAIL)

            await page.locator("input[type='password']").first.fill(PASSWORD)
            submit_btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Inloggen')").first
            await submit_btn.click()
            await page.wait_for_timeout(4000)

            # --- 2. WOD OPHALEN ---
            print("Naar WOD URL...")
            await page.goto("https://www.crossfitbink36.nl/?workout=wod", wait_until="domcontentloaded")
            try:
                await page.wait_for_selector(".wod-list", timeout=5000)
                container = page.locator(".wod-list").first.locator("xpath=..")
                full_text = await container.inner_text()
                if "Share this Workout" in full_text: full_text = full_text.split("Share this Workout")[0]
            except:
                full_text = "Geen WOD tekst gevonden (rustdag?)."

            # --- 3. ROOSTER CHECKEN (WIDGET DATA) ---
            print("Rooster checken voor inschrijvingen...")
            await page.goto("https://www.crossfitbink36.nl/rooster", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            
            page_content = await page.content()
            
            if "UITSCHRIJVEN" in page_content or "ingeschreven" in page_content.lower():
                print("✅ Inschrijving gevonden, details zoeken...")
                les_blokken = await page.locator(".event, .fc-event").all()
                
                for blok in les_blokken:
                    try:
                        await blok.click()
                        await page.wait_for_timeout(500)
                        modal_text = await page.locator("body").inner_text()
                        
                        if "UITSCHRIJVEN" in modal_text:
                            mijn_status["ingeschreven"] = True
                            
                            # Tijd
                            if "tot" in modal_text:
                                for line in modal_text.split('\n'):
                                    if "tot" in line and ":" in line:
                                        mijn_status["tijd"] = line.strip()
                                        break
                            
                            # Deelnemers
                            if "/" in modal_text:
                                for line in modal_text.split('\n'):
                                    if "/" in line and any(c.isdigit() for c in line):
                                        mijn_status["deelnemers"] = line.split(":")[-1].strip()
                            
                            # Wachtlijst check
                            if "Wachtlijst" in modal_text or "wachtlijst" in modal_text.lower():
                                mijn_status["wachtlijst"] = True
                                import re
                                match = re.search(r'achtlijst.*?(\d+)', modal_text, re.IGNORECASE)
                                mijn_status["wachtlijst_plek"] = match.group(1) if match else "?"
                            
                            break # Klaar, we hebben de les
                        
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(200)
                    except:
                        continue

            # --- 4. AI & OPSLAAN ---
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
            
            print(f"✅ SUCCES opgeslagen. Status: {mijn_status['ingeschreven']}")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

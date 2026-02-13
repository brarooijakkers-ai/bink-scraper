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

# Tijdzone
os.environ['TZ'] = 'Europe/Amsterdam'
try: time.tzset()
except: pass

# Gegevens
EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_KEY = os.environ.get("OPENAI_API_KEY")

def update_history_csv(datum, dag, workout, coach):
    file_name = "history.csv"
    exists = os.path.isfile(file_name)
    with open(file_name, mode='a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if not exists: w.writerow(["Datum", "Dag", "Workout", "AI Coach"])
        w.writerow([datum, dag, workout.replace("\n", " | "), coach.replace("\n", " ")])

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
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()

        days = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
        now = datetime.now()
        dag_nl = days[now.weekday()]
        datum_str = now.strftime("%d-%m-%Y")
        mijn_status = {"ingeschreven": False, "tijd": "", "deelnemers": "", "wachtlijst": False, "wachtlijst_plek": 0}

        try:
            # --- STAP 1: INLOGGEN ---
            print("1. Naar homepage...")
            await page.goto("https://www.crossfitbink36.nl/", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            print("2. Inloggen...")
            try: await page.locator("a:has-text('Inloggen'), a:has-text('Login'), button:has-text('Inloggen')").first.click(timeout=5000)
            except: await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            
            try: await page.locator("input[type='email'], input[name*='user'], input[name*='mail']").first.fill(EMAIL)
            except: await page.locator("input").first.fill(EMAIL)
                
            await page.locator("input[type='password']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(4000)

            # --- STAP 2: WOD OPHALEN ---
            print("4. WOD Ophalen...")
            await page.goto("https://www.crossfitbink36.nl/?workout=wod", wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)
            try:
                container = page.locator(".wod-list").first.locator("xpath=..")
                full_text = await container.inner_text()
                if "Share this" in full_text: full_text = full_text.split("Share this")[0]
            except: full_text = "Geen WOD tekst gevonden."

            # --- STAP 3: ROOSTER CHECK (OP BASIS VAN JOUW SCREENSHOT) ---
            print("5. Rooster checken...")
            await page.goto("https://www.crossfitbink36.nl/rooster", wait_until="networkidle")
            await page.wait_for_timeout(3000)

            # We zoeken naar de class uit jouw foto!
            print("   Zoeken naar '.workout-signedup'...")
            signed_up_elements = await page.locator(".workout-signedup").all()

            if len(signed_up_elements) > 0:
                print("   ✅ Inschrijving gevonden!")
                mijn_status["ingeschreven"] = True
                les = signed_up_elements[0] # Pak de eerste les waar je voor ingeschreven staat

                # Lees tijd uit (.event-date)
                try: mijn_status["tijd"] = (await les.locator(".event-date").inner_text()).strip()
                except: pass

                # Lees deelnemers uit (.event-registrations)
                try: mijn_status["deelnemers"] = (await les.locator(".event-registrations").inner_text()).strip()
                except: pass

                # Klik hem toch even open om de wachtlijst te checken in de popup
                try:
                    await les.click()
                    await page.wait_for_timeout(1000)
                    modal_text = await page.locator("body").inner_text()
                    
                    if "achtlijst" in modal_text.lower():
                        mijn_status["wachtlijst"] = True
                        import re
                        m = re.search(r'achtlijst.*?(\d+)', modal_text, re.IGNORECASE)
                        mijn_status["wachtlijst_plek"] = m.group(1) if m else "?"
                    await page.keyboard.press("Escape")
                except: pass

            else:
                # Fallback: Voor het geval een Wachtlijst geen 'workout-signedup' class krijgt
                print("   Geen directe class gevonden. Fallback check...")
                content = await page.content()
                if "UITSCHRIJVEN" in content or "achtlijst" in content.lower():
                    events = await page.locator(".single-event.clickable").all()
                    for e in events:
                        try:
                            if await e.is_visible():
                                await e.click()
                                await page.wait_for_timeout(500)
                                txt = await page.locator("body").inner_text()
                                if "UITSCHRIJVEN" in txt:
                                    mijn_status["ingeschreven"] = True
                                    for line in txt.split('\n'):
                                        if "tot" in line and ":" in line: mijn_status["tijd"] = line.strip()
                                        if "/" in line and any(c.isdigit() for c in line): mijn_status["deelnemers"] = line.split(":")[-1].strip()
                                    if "achtlijst" in txt.lower():
                                        mijn_status["wachtlijst"] = True
                                        import re
                                        m = re.search(r'achtlijst.*?(\d+)', txt, re.IGNORECASE)
                                        mijn_status["wachtlijst_plek"] = m.group(1) if m else "?"
                                    break
                                await page.keyboard.press("Escape")
                        except: continue

            # --- STAP 4: OPSLAAN ---
            ai_advies = get_ai_coach_advice(full_text)
            
            data = {
                "datum": datum_str, "dag": dag_nl,
                "workout": full_text.strip(), "coach": ai_advies,
                "status": mijn_status
            }
            
            with open("workout.json", "w") as f: json.dump(data, f, indent=4)
            if len(full_text) > 10: update_history_csv(datum_str, dag_nl, full_text.strip(), ai_advies)
            
            print(f"✅ KLAAR! Status: {mijn_status['ingeschreven']}")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            exit(1)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

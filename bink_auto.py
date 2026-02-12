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
            # 1. Inloggen
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")
            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(3000)

            # 2. Naar Rooster gaan
            print("Naar Rooster...")
            await page.goto("https://www.crossfitbink36.nl/rooster", wait_until="networkidle")
            await page.wait_for_timeout(2000)

            # 3. Checken of we ingeschreven zijn
            # We zoeken naar lessen van VANDAAG. Dit is vaak lastig te vinden in grids.
            # Strategie: We klikken op lessen die 'ingeschreven' lijken of we openen modals.
            # Omdat ik de classnames niet exact weet, proberen we een generieke scan van de dag.
            
            print("Zoeken naar inschrijvingen...")
            # Dit is een gok voor de selector op basis van je screenshot (modal)
            # We zoeken naar elementen die 'jouw' inschrijving kunnen zijn.
            # Vaak hebben die een andere kleur.
            
            # ALTERNATIEF: We klikken gewoon de eerste paar lessen van vandaag open en checken de knop.
            # (Dit kan geoptimaliseerd worden als we de HTML code van het rooster zien)
            
            # Voor nu: We halen eerst de WOD op (zoals altijd)
            await page.goto("https://www.crossfitbink36.nl/?workout=wod", wait_until="domcontentloaded")
            try:
                await page.wait_for_selector(".wod-list", timeout=5000)
                container = page.locator(".wod-list").first.locator("xpath=..")
                full_text = await container.inner_text()
                if "Share this Workout" in full_text: full_text = full_text.split("Share this Workout")[0]
            except:
                full_text = "Geen WOD tekst gevonden (rustdag?)."

            # 4. Nu specifiek rooster checken voor status (Terug naar rooster)
            await page.goto("https://www.crossfitbink36.nl/rooster", wait_until="networkidle")
            await page.wait_for_timeout(2000)

            # We zoeken alle blokken die 'vandaag' zijn. 
            # Omdat dit lastig is zonder HTML, zoeken we naar de tekst "UITSCHRIJVEN" in de pagina bron code
            # Als die er staat, zijn we ergens ingeschreven.
            
            page_content = await page.content()
            
            if "UITSCHRIJVEN" in page_content or "ingeschreven" in page_content.lower():
                print("✅ Je staat ergens ingeschreven! We proberen details te vinden.")
                
                # Probeer de les te openen waar je ingeschreven staat.
                # We klikken op alle zichtbare les-blokken.
                les_blokken = await page.locator(".event, .fc-event").all() # Veelgebruikte classes in roosters
                
                for blok in les_blokken:
                    try:
                        await blok.click()
                        await page.wait_for_timeout(500)
                        
                        # Check Modal Inhoud
                        modal_text = await page.locator("body").inner_text()
                        
                        if "UITSCHRIJVEN" in modal_text:
                            # GEVONDEN!
                            mijn_status["ingeschreven"] = True
                            
                            # Tijd extracten (uit screenshot: "17:30 tot 18:30")
                            if "tot" in modal_text:
                                lines = modal_text.split('\n')
                                for line in lines:
                                    if "tot" in line and ":" in line:
                                        mijn_status["tijd"] = line.strip()
                                        break
                            
                            # Deelnemers (uit screenshot: "6/14")
                            if "/" in modal_text:
                                lines = modal_text.split('\n')
                                for line in lines:
                                    if "/" in line and any(c.isdigit() for c in line):
                                        # Zoek naar iets als "Aanmeldingen: 6/14"
                                        parts = line.split(":")[-1].strip()
                                        mijn_status["deelnemers"] = parts
                            
                            # Wachtlijst check
                            if "Wachtlijst" in modal_text or "wachtlijst" in modal_text.lower():
                                mijn_status["wachtlijst"] = True
                                # Probeer plek te vinden
                                # Vaak staat er "Positie: 2" of "Wachtlijst: 2"
                                import re
                                match = re.search(r'achtlijst.*?(\d+)', modal_text, re.IGNORECASE)
                                if match:
                                    mijn_status["wachtlijst_plek"] = match.group(1)
                                else:
                                    mijn_status["wachtlijst_plek"] = "?"
                            
                            break # Klaar, we hebben de les gevonden
                        
                        # Sluit modal (vaak escape of klik ernaast)
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(200)
                    except:
                        continue

            # --- AI & OPSLAAN ---
            # We halen AI advies alleen op als de WOD tekst nieuw is of nog niet bestaat
            # Om kosten te besparen. Maar voor nu doen we het gewoon.
            ai_advies = get_ai_coach_advice(full_text)

            data = {
                "datum": datum_str,
                "dag": dag_nl,
                "workout": full_text.strip(),
                "coach": ai_advies,
                "status": mijn_status # <--- HIER ZIT JE NIEUWE DATA
            }
            
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            # CSV Updaten (alleen als WOD tekst lang genoeg is)
            if len(full_text) > 10:
                update_history_csv(datum_str, dag_nl, full_text.strip(), ai_advies)
            
            print(f"✅ SUCCES: Status={mijn_status['ingeschreven']}")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

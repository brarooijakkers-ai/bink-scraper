import asyncio
import json
import os
import time
import urllib.request
import urllib.parse
import csv
import re  # Toegevoegd om slim te kunnen zoeken in tekst
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

        mijn_status = {
            "ingeschreven": False,
            "tijd": "",
            "deelnemers": "",
            "wachtlijst": False,
            "wachtlijst_plek": "?"
        }

        try:
            # 1. Inloggen (De originele, werkende methode)
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            
            # We klikken weer netjes op de link op de homepage
            try:
                await page.get_by_role("link", name="Inloggen").first.click(timeout=5000)
            except:
                print("Inlogknop niet direct gevonden, fallback naar /login...")
                await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")

            await page.wait_for_timeout(3000) # Even wachten tot de popup/pagina er is

            # Velden invullen
            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            
            inlog_knop = page.locator("button[type='submit'], input[type='submit'], button:has-text('Inloggen')").first
            await inlog_knop.click()
            await page.wait_for_timeout(4000) # Wacht tot we succesvol zijn ingelogd

            # 2. WOD Ophalen
            print("WOD checken...")
            await page.goto("https://www.crossfitbink36.nl/?workout=wod", wait_until="domcontentloaded")
            try:
                await page.wait_for_selector(".wod-list", timeout=5000)
                container = page.locator(".wod-list").first.locator("xpath=..")
                full_text = await container.inner_text()
                if "Share this Workout" in full_text: full_text = full_text.split("Share this Workout")[0]
            except:
                full_text = "Geen WOD tekst gevonden (rustdag?)."

            # 3. Status Checken (Het rooster induiken)
            print("Naar Rooster voor status...")
            await page.goto("https://www.crossfitbink36.nl/rooster", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            
            page_content = await page.content()
            
            # Eerste grove check of we überhaupt ergens in staan vandaag
            if "UITSCHRIJVEN" in page_content or "ingeschreven" in page_content.lower():
                print("✅ Inschrijving gedetecteerd. Details zoeken...")
                mijn_status["ingeschreven"] = True
                
                # We pakken alle blokjes op de kalender en klikken ze één voor één open
                les_blokken = await page.locator("a, div[class*='event'], div[class*='grid']").all()
                
                for blok in les_blokken:
                    try:
                        # Zweven en klikken om de popup te forceren
                        await blok.hover()
                        await blok.click(timeout=1000)
                        await page.wait_for_timeout(500)
                        
                        # NU HET BELANGRIJKSTE: We zoeken de 'UITSCHRIJVEN' knop die NU ZICHTBAAR is
                        uitschrijf_knop = page.locator("text=UITSCHRIJVEN").locator("visible=true").first
                        
                        if await uitschrijf_knop.count() > 0:
                            # Gevonden! We pakken nu STRIKT de tekst van de openstaande popup, 
                            # op basis van de titel uit jouw screenshot.
                            popup = page.locator("text=WoD workout details:").locator("xpath=..")
                            
                            if await popup.count() > 0:
                                popup_tekst = await popup.inner_text()
                            else:
                                # Fallback als de titel net anders is
                                popup_tekst = await uitschrijf_knop.locator("xpath=ancestor::div[3]").inner_text()
                            
                            # Tijd zoeken (bijv "17:30 tot 18:30")
                            tijd_match = re.search(r'\d{2}:\d{2}\s+tot\s+\d{2}:\d{2}', popup_tekst)
                            if tijd_match: 
                                mijn_status["tijd"] = tijd_match.group(0).strip()
                            
                            # Aanmeldingen zoeken (bijv "6/14")
                            deelnemers_match = re.search(r'(\d+/\d+)', popup_tekst)
                            if deelnemers_match: 
                                mijn_status["deelnemers"] = deelnemers_match.group(1).strip()
                            
                            # Wachtlijst check (alleen binnen de tekst van DEZE specifieke popup)
                            if "wachtlijst" in popup_tekst.lower() and "uitschrijven" not in popup_tekst.lower():
                                mijn_status["wachtlijst"] = True
                                wl_match = re.search(r'wachtlijst.*?(\d+)', popup_tekst, re.IGNORECASE)
                                if wl_match: 
                                    mijn_status["wachtlijst_plek"] = wl_match.group(1)
                            else:
                                mijn_status["wachtlijst"] = False
                            
                            # We hebben alles, we breken uit de loop
                            break 
                            
                        # Sluit popup (Escape toets) en ga door naar het volgende blokje
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(200)
                        
                    except Exception as e:
                        # Dit blokje was niet klikbaar, we gaan door
                        continue

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

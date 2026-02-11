import asyncio
import json
import os
import time
import urllib.request
import urllib.parse
import csv  # <--- NIEUW: Nodig voor Excel bestand
from playwright.async_api import async_playwright
from datetime import datetime
from openai import OpenAI

# 1. TIJDZONE FIX
os.environ['TZ'] = 'Europe/Amsterdam'
try:
    time.tzset()
except:
    pass

# Gegevens ophalen
EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_KEY = os.environ.get("OPENAI_API_KEY")

# --- TELEGRAM FUNCTIE ---
def stuur_telegram(bericht):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": bericht}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req)
    except:
        pass

# --- CSV HISTORIE FUNCTIE (NIEUW) 📊 ---
def update_history_csv(datum, dag, workout, coach):
    file_name = "history.csv"
    file_exists = os.path.isfile(file_name)
    
    # We openen het bestand in 'append' modus (toevoegen)
    with open(file_name, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        # Als het bestand nieuw is, schrijven we eerst de kolomkoppen
        if not file_exists:
            writer.writerow(["Datum", "Dag", "Workout", "AI Coach Advies"])
            
        # Nu schrijven we de data van vandaag
        # We vervangen newlines in de workout even door een | teken, zodat het in 1 cel past in Excel
        workout_flat = workout.replace("\n", " | ")
        coach_flat = coach.replace("\n", " ")
        
        writer.writerow([datum, dag, workout_flat, coach_flat])
    print(f"✅ Historie bijgewerkt in {file_name}")

# --- AI COACH FUNCTIE ---
def get_ai_coach_advice(wod_text):
    if not API_KEY:
        return "Geen OpenAI Key gevonden."
    
    print("🧠 AI Coach aan het nadenken...")
    try:
        client = OpenAI(api_key=API_KEY)
        prompt = (
            f"Je bent een CrossFit coach. Analyseer deze WOD:\n\n{wod_text}\n\n"
            "Geef antwoord in deze structuur (max 3 regels):\n"
            "🔥 **Focus:** [korte zin]\n"
            "💡 **Strategie:** [korte zin]\n"
            "🩹 **Tip:** [korte zin]"
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Je bent een behulpzame CrossFit coach."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Fout: {e}")
        return "Coach is even koffie halen (AI Error)."

async def get_workout():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()

        days_nl = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
        idx = datetime.now().weekday()
        dag_nl = days_nl[idx]
        datum_str = datetime.now().strftime("%d-%m-%Y")

        try:
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/", wait_until="networkidle")
            
            try:
                await page.get_by_role("link", name="Inloggen").first.click(timeout=5000)
            except:
                await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")

            if not EMAIL or not PASSWORD:
                raise Exception("Geen inloggegevens!")

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(4000)

            print("Naar WOD URL...")
            await page.goto("https://www.crossfitbink36.nl/?workout=wod", wait_until="networkidle")
            
            await page.wait_for_selector(".wod-list", timeout=15000)
            container = page.locator(".wod-list").first.locator("xpath=..")
            full_text = await container.inner_text()
            
            if "Share this Workout" in full_text:
                full_text = full_text.split("Share this Workout")[0]
            
            lines = [line.strip() for line in full_text.splitlines() if line.strip()]
            workout_tekst = "\n".join(lines)

            # --- AI COACH ---
            ai_advies = get_ai_coach_advice(workout_tekst)
            print("-" * 20)
            print(ai_advies)

            # --- OPSLAAN JSON (Voor Widget) ---
            data = {
                "datum": datum_str,
                "dag": dag_nl,
                "workout": workout_tekst.strip(),
                "coach": ai_advies
            }
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            # --- OPSLAAN CSV (Voor Historie/Excel) ---
            update_history_csv(datum_str, dag_nl, workout_tekst.strip(), ai_advies)

            # --- TELEGRAM ---
            tg_bericht = f"🏋️‍♂️ *WOD {dag_nl}:*\n\n{workout_tekst}\n\n🤖 *AI Coach:*\n{ai_advies}"
            stuur_telegram(tg_bericht)
            
            print(f"✅ SUCCES: Alles opgeslagen.")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            stuur_telegram(f"❌ WOD Ophalen mislukt: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

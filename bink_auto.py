import asyncio
import json
import os
import time
import urllib.request
import urllib.parse
from playwright.async_api import async_playwright
from datetime import datetime
from openai import OpenAI  # Nieuwe import voor de AI Coach

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
API_KEY = os.environ.get("OPENAI_API_KEY") # OpenAI Sleutel

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

# --- AI COACH FUNCTIE 🧠 ---
def get_ai_coach_advice(wod_text):
    if not API_KEY:
        return "Geen OpenAI Key gevonden."
    
    print("🧠 AI Coach aan het nadenken...")
    try:
        client = OpenAI(api_key=API_KEY)
        
        prompt = (
            f"Je bent een ervaren CrossFit coach. Analyseer deze WOD kort en bondig:\n\n{wod_text}\n\n"
            "Geef antwoord in precies deze structuur (max 3 korte zinnen totaal):\n"
            "🔥 **Focus:** [1 zin over de prikkel/doel]\n"
            "💡 **Strategie:** [1 zin over pacing of opbreken]\n"
            "🩹 **Tip:** [1 technische tip of warming-up suggestie]"
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini", # Slim, snel en goedkoop
            messages=[
                {"role": "system", "content": "Je bent een behulpzame, motiverende CrossFit coach."},
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

            # --- AI COACH AANROEPEN ---
            ai_advies = get_ai_coach_advice(workout_tekst)
            print("-" * 20)
            print(ai_advies)
            print("-" * 20)

            # OPSLAAN (Nu met extra veld 'coach')
            data = {
                "datum": datetime.now().strftime("%d-%m-%Y"),
                "dag": dag_nl,
                "workout": workout_tekst.strip(),
                "coach": ai_advies
            }
            
            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            # --- TELEGRAM MET COACH ---
            tg_bericht = f"🏋️‍♂️ *WOD {dag_nl}:*\n\n{workout_tekst}\n\n🤖 *AI Coach:*\n{ai_advies}"
            stuur_telegram(tg_bericht)
            
            print(f"✅ SUCCES: Opgeslagen en verstuurd.")

        except Exception as e:
            print(f"❌ FOUT: {e}")
            stuur_telegram(f"❌ WOD Ophalen mislukt: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(get_workout())

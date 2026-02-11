import os
import json
import urllib.request
import urllib.parse
from openai import OpenAI

# Instellingen
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_KEY = os.environ.get("OPENAI_API_KEY")

# Prestatie data (komt van je iPhone via de 'Deurbel')
DURATION = os.environ.get("WORKOUT_DURATION", "0") # in minuten
AVG_HR = os.environ.get("WORKOUT_AVG_HR", "0")
MAX_HR = os.environ.get("WORKOUT_MAX_HR", "0")
CALORIES = os.environ.get("WORKOUT_CALORIES", "0")

def stuur_telegram(bericht):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": bericht, "parse_mode": "Markdown"}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req)
    except: pass

def analyze_performance():
    # 1. Lees de WOD van vandaag
    try:
        with open("workout.json", "r", encoding="utf-8") as f:
            wod_data = json.load(f)
            wod_text = wod_data.get("workout", "Geen WOD gevonden.")
            wod_coach_plan = wod_data.get("coach", "")
    except:
        stuur_telegram("⚠️ Kon WOD bestand niet vinden voor analyse.")
        return

    # 2. De AI Prompt
    print("🧠 Coach analyseert je prestatie...")
    client = OpenAI(api_key=API_KEY)
    
    prompt = (
        f"Je bent een strenge maar rechtvaardige CrossFit coach.\n"
        f"Dit was het plan (de WOD):\n---\n{wod_text}\n---\n"
        f"Dit was jouw vooraf bedachte strategie:\n{wod_coach_plan}\n\n"
        f"DIT ZIJN DE ECHTE RESULTATEN VAN DE ATLEET:\n"
        f"- Duur: {DURATION} minuten\n"
        f"- Gemiddelde Hartslag: {AVG_HR} bpm\n"
        f"- Maximale Hartslag: {MAX_HR} bpm\n"
        f"- Calorieën: {CALORIES}\n\n"
        "Geef een evaluatie van max 4 zinnen.\n"
        "1. Heb ik de juiste intensiteit gehaald voor deze workout? (Bijv: was het te langzaam voor een sprint, of te hard voor een duurtraining?)\n"
        "2. Geef 1 specifiek verbeterpunt op basis van de hartslag/tijd data."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Je bent een top CrossFit coach."}, {"role": "user", "content": prompt}]
        )
        advies = response.choices[0].message.content
        
        # 3. Stuur naar Telegram
        msg = (
            f"📊 **Post-Workout Analyse**\n\n"
            f"⏱️ {DURATION} min | ❤️ {AVG_HR} bpm\n\n"
            f"{advies}"
        )
        stuur_telegram(msg)
        print("✅ Analyse verstuurd.")
        
    except Exception as e:
        print(f"Error: {e}")
        stuur_telegram(f"❌ Analyse mislukt: {e}")

if __name__ == "__main__":
    analyze_performance()

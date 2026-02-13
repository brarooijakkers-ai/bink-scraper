import os
import json
import urllib.request
import urllib.parse
from openai import OpenAI

# Haal de geheime sleutels op
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
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    print("Post-workout analyse gestart!")
    
    # 1. Lees de payload data (de cijfers van je Apple Watch)
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    calories, avg_hr, duration = "?", "?", "?"
    
    if event_path and os.path.exists(event_path):
        with open(event_path, "r") as f:
            event_data = json.load(f)
            payload = event_data.get("client_payload", {})
            
            # Formatteer de getallen netjes (bijv 450.553 -> 450)
            try: calories = round(float(payload.get("calories", 0))) 
            except: pass
            
            try: avg_hr = round(float(payload.get("avg_hr", 0))) 
            except: pass
            
            try: duration = round(float(payload.get("duration", 0))) 
            except: pass

    # 2. Lees de WOD van vandaag op uit ons json bestand
    workout_text = "Onbekende workout"
    try:
        if os.path.exists("workout.json"):
            with open("workout.json", "r") as f:
                data = json.load(f)
                workout_text = data.get("workout", "Geen WOD gevonden")
    except:
        pass

    # 3. Vraag de AI Coach om een prestatie-analyse
    ai_bericht = "Lekker gewerkt! 💪 Zorg voor een goede recovery."
    if API_KEY:
        try:
            client = OpenAI(api_key=API_KEY)
            prompt = (
                f"Ik heb zojuist deze CrossFit WOD afgerond:\n{workout_text}\n\n"
                f"Mijn stats van mijn Apple Watch:\n"
                f"⏱️ Duur: {duration} minuten\n"
                f"🔥 Calorieën: {calories} kcal\n"
                f"❤️ Gemiddelde hartslag: {avg_hr} bpm\n\n"
                "Je bent mijn no-nonsense CrossFit coach. Schrijf een motiverend bericht (max 3 zinnen). "
                "Betrek mijn hartslag of calorieën in je beoordeling over mijn inzet vandaag, en geef me "
                "één sportspecifieke tip voor herstel op basis van de bewegingen in de WOD. Spreek me direct aan met 'je'."
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Je bent een ervaren en motiverende CrossFit coach."},
                    {"role": "user", "content": prompt}
                ]
            )
            ai_bericht = response.choices[0].message.content
        except Exception as e:
            print(f"AI Error: {e}")

    # 4. Maak het Telegram bericht
    telegram_bericht = (
        f"✅ *Workout Voltooid!*\n\n"
        f"⏱️ *Duur:* {duration} min\n"
        f"🔥 *Calorieën:* {calories} kcal\n"
        f"❤️ *Gem. Hartslag:* {avg_hr} bpm\n\n"
        f"🗣️ *Coach Analyse:*\n{ai_bericht}"
    )

    # 5. Sturen!
    stuur_telegram(telegram_bericht)
    print("Bericht succesvol naar Telegram gestuurd!")

if __name__ == "__main__":
    main()

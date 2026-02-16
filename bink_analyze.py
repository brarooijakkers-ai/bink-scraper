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
    
    # 1. Lees de payload data
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    calories, avg_hr, max_hr, duration = 0, 0, 0, 0
    
    if event_path and os.path.exists(event_path):
        with open(event_path, "r") as f:
            event_data = json.load(f)
            payload = event_data.get("client_payload", {})
            
            try: calories = round(float(payload.get("calories", 0))) 
            except: pass
            
            try: avg_hr = round(float(payload.get("avg_hr", 0))) 
            except: pass

            try: max_hr = round(float(payload.get("max_hr", 0))) # <-- NIEUW
            except: pass
            
            try: duration = round(float(payload.get("duration", 0))) 
            except: pass

    if duration < 20:
        print(f"Workout was {duration} minuten. Korter dan 20 minuten. Script stopt.")
        return 

    # 2. Lees de WOD van vandaag op
    workout_text = "Onbekende workout"
    workout_data = {}
    try:
        if os.path.exists("workout.json"):
            with open("workout.json", "r") as f:
                workout_data = json.load(f)
                workout_text = workout_data.get("workout", "Geen WOD gevonden")
    except:
        pass

    # 3. Vraag de AI Coach (nu mét max_hr!)
    ai_bericht = "Lekker gewerkt! 💪 Zorg voor een goede recovery."
    if API_KEY:
        try:
            client = OpenAI(api_key=API_KEY)
            prompt = (
                f"Ik heb zojuist deze CrossFit WOD afgerond:\n{workout_text}\n\n"
                f"Mijn stats van mijn Apple Watch:\n"
                f"⏱️ Duur: {duration} minuten\n"
                f"🔥 Calorieën: {calories} kcal\n"
                f"❤️ Gemiddelde hartslag: {avg_hr} bpm\n"
                f"🚀 Maximale hartslag: {max_hr} bpm\n\n"
                "Je bent mijn no-nonsense CrossFit coach. Schrijf een kort, motiverend bericht "
                "als recap van mijn training. Geef me één specifieke tip voor herstel op basis van "
                "de bewegingen in de WOD of mijn hartslag-piek. Spreek me aan met 'je'."
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

    # 4. Sla de post-workout data op
    workout_data["post_workout"] = {
        "completed": True,
        "duration": duration,
        "calories": calories,
        "avg_hr": avg_hr,
        "max_hr": max_hr, # <-- NIEUW
        "post_coach": ai_bericht
    }
    
    with open("workout.json", "w", encoding="utf-8") as f:
        json.dump(workout_data, f, indent=4)

    # 5. Telegram bericht (Nu ook met max HR)
    telegram_bericht = (
        f"✅ *Workout Voltooid!*\n\n"
        f"⏱️ *Duur:* {duration} min\n"
        f"🔥 *Calorieën:* {calories} kcal\n"
        f"❤️ *Gem. HR:* {avg_hr} bpm | 🚀 *Max HR:* {max_hr} bpm\n\n"
        f"🗣️ *Coach Analyse:*\n{ai_bericht}"
    )
    stuur_telegram(telegram_bericht)

if __name__ == "__main__":
    main()

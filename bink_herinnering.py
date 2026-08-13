"""Stuurt ~UUR_VOORAF uur voor een ingeschreven les een Telegram-herinnering.

Leest de reeds gescrapete workout.json (geen login nodig) en houdt in
reminders.json bij welke lessen al herinnerd zijn, zodat er nooit dubbel
gepingd wordt. Draait via cron (zie .github/workflows/herinnering.yml)."""
import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

os.environ['TZ'] = 'Europe/Amsterdam'
try:
    time.tzset()
except Exception:
    pass

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

UUR_VOORAF = 3          # hoeveel uur van tevoren we herinneren
STATE_FILE = "reminders.json"
INGESCHREVEN = {"Jij bent Ingeschreven", "Jij staat op Wachtlijst"}


def stuur_telegram(bericht):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("Geen Telegram-gegevens, bericht niet verstuurd.")
        return
    print(f"Telegram: {bericht}")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": TG_CHAT_ID, "text": bericht, "parse_mode": "Markdown"}
    ).encode("utf-8")
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except Exception as e:
        print(f"Telegram fout: {e}")


def lees_json(pad, default):
    try:
        with open(pad, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def parse_start(datum, tijd):
    """datum 'dd-mm-yyyy' + tijd '18:30 - 19:30' -> datetime van de starttijd."""
    if not datum or not tijd:
        return None
    start = tijd.split("-")[0].strip()
    try:
        return datetime.strptime(f"{datum} {start}", "%d-%m-%Y %H:%M")
    except Exception:
        return None


def verzamel_ingeschreven(data):
    """Alle lessen waar je in/op wachtlijst staat, als (datum, les)-tuples."""
    now = datetime.now()
    result = []

    # Vandaag (datum uit de JSON).
    for les in data.get("rooster_vandaag", []):
        if les.get("status") in INGESCHREVEN:
            result.append((data.get("datum"), les))

    # Morgen.
    morgen = (now + timedelta(days=1)).strftime("%d-%m-%Y")
    for les in data.get("rooster_morgen", []):
        if les.get("status") in INGESCHREVEN:
            result.append((morgen, les))

    # Rest van deze week + volgende week (dag draagt eigen datum).
    for dag in (data.get("rooster_deze_week", []) or []) + (data.get("rooster_week", []) or []):
        for les in dag.get("lessen", []):
            if les.get("status") in INGESCHREVEN:
                result.append((dag.get("datum"), les))

    # Fallback: status_vandaag/morgen die (nog) niet in het rooster stond.
    sv = data.get("status_vandaag") or {}
    if sv.get("ingeschreven") and sv.get("tijd"):
        result.append((data.get("datum"), {
            "tijd": sv.get("tijd"), "type": sv.get("type") or "les",
            "zaal": "", "status": "Jij staat op Wachtlijst" if sv.get("wachtlijst") else "Jij bent Ingeschreven",
        }))
    sm = data.get("status_morgen") or {}
    if sm.get("ingeschreven") and sm.get("tijd"):
        result.append((morgen, {
            "tijd": sm.get("tijd"), "type": sm.get("type") or "les",
            "zaal": "", "status": "Jij staat op Wachtlijst" if sm.get("wachtlijst") else "Jij bent Ingeschreven",
        }))

    return result


def main():
    data = lees_json("workout.json", {})
    if not data:
        print("Geen workout.json.")
        return

    state = lees_json(STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    reminded = set(state.get("reminded", []))

    now = datetime.now()
    grens = now + timedelta(hours=UUR_VOORAF)

    nieuw = False
    seen = set()
    for datum, les in verzamel_ingeschreven(data):
        tijd = les.get("tijd", "")
        # Dedup per tijdslot (niet per zaal): je zit maar in één les per slot,
        # en het rooster + de status-fallback mogen niet dubbel pingen.
        key = f"{datum} {tijd}".strip()
        if key in seen:
            continue
        seen.add(key)

        start = parse_start(datum, tijd)
        if not start:
            continue

        # Herinner zodra de les binnen UUR_VOORAF valt en nog niet gepingd is.
        if now < start <= grens and key not in reminded:
            resterend = start - now
            uren = int(resterend.total_seconds() // 3600)
            mins = int((resterend.total_seconds() % 3600) // 60)
            wachtlijst = " (wachtlijst)" if les.get("status") == "Jij staat op Wachtlijst" else ""
            zaal = f" in *{les.get('zaal')}*" if les.get("zaal") else ""
            stuur_telegram(
                f"⏰ *Bink-herinnering* — over ~{uren}u{mins:02d}m:\n"
                f"*{les.get('type', 'les')}* om *{tijd}*{zaal}{wachtlijst}."
            )
            reminded.add(key)
            nieuw = True

    # Oude keys opruimen (datum ouder dan gisteren).
    gisteren = (now - timedelta(days=1)).date()
    schoon = set()
    for key in reminded:
        try:
            d = datetime.strptime(key.split(" ")[0], "%d-%m-%Y").date()
            if d >= gisteren:
                schoon.add(key)
        except Exception:
            schoon.add(key)  # onbekend formaat: behouden

    if nieuw or schoon != reminded:
        state["reminded"] = sorted(schoon)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        print("reminders.json bijgewerkt.")
    else:
        print("Niets te herinneren.")


if __name__ == "__main__":
    main()

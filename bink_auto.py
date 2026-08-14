import asyncio
import json
import os
import time
import urllib.request
import urllib.parse
import csv
import difflib
from playwright.async_api import async_playwright
from datetime import datetime, timedelta

os.environ['TZ'] = 'Europe/Amsterdam'
try: time.tzset()
except: pass

EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Hoeveel keer proberen we de hele scrape voordat we opgeven?
MAX_POGINGEN = 3
# Minimaal aantal uur tussen twee "het blijft falen"-alerts (throttle).
ALERT_THROTTLE_UUR = 3

def stuur_telegram(bericht):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("⚠️ Geen Telegram gegevens, bericht niet verstuurd.")
        return
    print(f"📨 Telegram: {bericht}")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": bericht}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"❌ Telegram fout: {e}")

def lees_workout_json():
    try:
        if os.path.exists("workout.json"):
            with open("workout.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def schoon_wod_tekst(tekst):
    """Maakt de ruwe kaart-tekst netjes: verwijdert de 'Share'-knop, de losse
    kaarttitel 'WOD', het label 'Fundamentals', en klapt dubbele lege regels in."""
    if not tekst:
        return ""
    if "Share this Workout" in tekst:
        tekst = tekst.split("Share this Workout")[0]
    # Losse label-regels die we nooit willen tonen.
    overbodige_labels = {"wod", "fundamentals"}
    regels = [r.strip() for r in tekst.split("\n")]
    resultaat = []
    for r in regels:
        if r.lower() in overbodige_labels:
            continue
        if r == "" and (not resultaat or resultaat[-1] == ""):
            continue
        resultaat.append(r)
    while resultaat and resultaat[-1] == "":
        resultaat.pop()
    return "\n".join(resultaat)

def _normaliseer_wod(tekst):
    """Maakt een WOD-tekst vergelijkbaar: kleine letters, leestekens weg,
    scheidingstekens ('|', nieuwe regels) naar spaties, dubbele spaties inklappen."""
    if not tekst:
        return ""
    t = tekst.lower().replace("|", " ").replace("\n", " ")
    t = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in t)
    return " ".join(t.split())

def _parse_dmy(datum):
    try:
        return datetime.strptime(datum, "%d-%m-%Y")
    except Exception:
        return None

def bereken_deja_vu(vandaag_workout, datum_vandaag, history_file="history.csv"):
    """Zoekt in history.csv de meest gelijkende WOD van een EERDERE datum.
    Retourneert {'datum','gelijkenis','soort'} of None. Groepeert per datum
    (history bevat dezelfde WOD meerdere keren door de uurlijkse runs)."""
    doel = _normaliseer_wod(vandaag_workout)
    if len(doel) < 15:
        return None

    per_datum = {}
    try:
        with open(history_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # header overslaan
            for rij in reader:
                if len(rij) < 3:
                    continue
                datum, workout = rij[0], rij[2]
                if not datum or datum == datum_vandaag:
                    continue
                n = _normaliseer_wod(workout)
                if len(n) >= 15:
                    per_datum[datum] = n  # zelfde datum = zelfde WOD, laatste wint
    except FileNotFoundError:
        return None

    beste_datum, beste_ratio = None, 0.0
    for datum, n in per_datum.items():
        ratio = difflib.SequenceMatcher(None, doel, n).ratio()
        if ratio > beste_ratio:
            beste_datum, beste_ratio = datum, ratio
        elif ratio == beste_ratio and beste_datum:
            # Gelijke score: kies de meest recente datum.
            d_new, d_old = _parse_dmy(datum), _parse_dmy(beste_datum)
            if d_new and d_old and d_new > d_old:
                beste_datum = datum

    if not beste_datum or beste_ratio < 0.55:
        return None
    return {
        "datum": beste_datum,
        "gelijkenis": round(beste_ratio * 100),
        "soort": "identiek" if beste_ratio >= 0.9 else "lijkt op",
    }

def update_history_csv(datum, dag, workout, coach=""):
    file_name = "history.csv"
    file_exists = os.path.isfile(file_name)
    with open(file_name, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists: writer.writerow(["Datum", "Dag", "Workout", "AI Coach Advies"])
        writer.writerow([datum, dag, workout.replace("\n", " | "), (coach or "").replace("\n", " ")])

async def extract_les(les, zaal_naam):
    """Leest 1 les-blokje uit tot een dict, of None bij een fout."""
    try:
        les_tijd = (await les.locator(".event-date").first.inner_text()).strip()
        les_type = (await les.locator(".event-name").first.inner_text()).strip()

        les_deelnemers = ""
        try: les_deelnemers = (await les.locator(".event-registrations").first.inner_text()).strip()
        except: pass

        les_class = await les.get_attribute("class") or ""
        les_status = "Open"
        if "full" in les_class: les_status = "Vol (Wachtlijst)"
        if "signedup" in les_class or "booked" in les_class: les_status = "Jij bent Ingeschreven"
        if "on-waiting-list" in les_class: les_status = "Jij staat op Wachtlijst"

        return {
            "tijd": les_tijd,
            "type": les_type,
            "zaal": zaal_naam,
            "deelnemers": les_deelnemers,
            "status": les_status,
        }
    except:
        return None

# Zalen + roosterpagina's (1 pagina toont een hele week per zaal).
ZALEN = {
    "Zaal 1": "https://www.crossfitbink36.nl/rooster",
    "Zaal 2": "https://www.crossfitbink36.nl/rooster?hall=Zaal%202",
    "Buiten": "https://www.crossfitbink36.nl/rooster?hall=Buiten",
}

DAGEN_NL = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
DAGEN_EN = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

async def scrape_rooster_dagen(page, doel_dagen, week_param):
    """Scrapet de lessen voor een set dagen op één roosterweek.
    - doel_dagen: lijst van (datum_obj, dag_nl, dag_en)
    - week_param: None voor de huidige week, 'next' voor volgende week.
    Elke dag krijgt dag/dag_en/datum/week + lessen mee zodat de widget er direct
    voor kan in-/uitschrijven."""
    week_label = "next" if week_param == "next" else "current"
    dag_objs = {}
    volgorde = []
    for datum_obj, nl, en in doel_dagen:
        dag_objs[en] = {
            "dag": nl,
            "dag_en": en,
            "datum": datum_obj.strftime("%d-%m-%Y"),
            "week": week_label,
            "lessen": [],
        }
        volgorde.append(en)

    if not volgorde:
        return []

    for zaal_naam, zaal_url in ZALEN.items():
        if week_param == "next":
            url = f"{zaal_url}&week=next" if "?" in zaal_url else f"{zaal_url}?week=next"
        else:
            url = zaal_url
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            await page.wait_for_selector("li[data-remodal-target]", timeout=8000)
        except:
            pass

        for en in volgorde:
            elementen = await page.locator(f"li[data-remodal-target*='{en}']").all()
            for les in elementen:
                d = await extract_les(les, zaal_naam)
                if d:
                    dag_objs[en]["lessen"].append(d)

    for en in volgorde:
        dag_objs[en]["lessen"] = sorted(dag_objs[en]["lessen"], key=lambda x: x["tijd"])

    return [dag_objs[en] for en in volgorde]

async def scrape_deze_week_rooster(page):
    """Resterende dagen van de HUIDIGE week: vanaf overmorgen t/m zondag.
    (Vandaag en morgen hebben al hun eigen status/rooster.)"""
    now = datetime.now()
    dagen = []
    for offset in range(2, 7 - now.weekday()):  # overmorgen .. zondag deze week
        datum_obj = now + timedelta(days=offset)
        wd = datum_obj.weekday()
        dagen.append((datum_obj, DAGEN_NL[wd], DAGEN_EN[wd]))
    return await scrape_rooster_dagen(page, dagen, week_param=None)

async def scrape_week_rooster(page):
    """Volledige AANKOMENDE week (week=next), alle 7 dagen."""
    now = datetime.now()
    maandag_deze_week = now - timedelta(days=now.weekday())
    maandag_volgende = maandag_deze_week + timedelta(days=7)
    dagen = []
    for i in range(7):
        datum_obj = maandag_volgende + timedelta(days=i)
        dagen.append((datum_obj, DAGEN_NL[i], DAGEN_EN[i]))
    return await scrape_rooster_dagen(page, dagen, week_param="next")

async def check_dag_status_en_rooster(page, dag_en, is_volgende_week=False):
    status = {
        "ingeschreven": False,
        "tijd": "",
        "type": "",
        "deelnemers": "",
        "wachtlijst": False,
        "wachtlijst_plek": "?",
        "wachtlijst_totaal": "?"
    }

    volledig_rooster = [] # <-- Hier slaan we alle lessen van de dag in op

    zalen = {
        "Zaal 1": "https://www.crossfitbink36.nl/rooster",
        "Zaal 2": "https://www.crossfitbink36.nl/rooster?hall=Zaal%202",
        "Buiten": "https://www.crossfitbink36.nl/rooster?hall=Buiten"
    }

    for zaal_naam, zaal_url in zalen.items():
        if is_volgende_week:
            url = f"{zaal_url}&week=next" if "?" in zaal_url else f"{zaal_url}?week=next"
        else:
            url = zaal_url

        # domcontentloaded i.p.v. networkidle (networkidle timeout't vaak in Actions).
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Wacht kort op het rooster; ontbreken mag (lege dag/zaal), dan gaan we door.
        try:
            await page.wait_for_selector("li[data-remodal-target]", timeout=8000)
        except:
            pass

        # --- ALLE LESSEN VAN DEZE DAG IN DEZE ZAAL SCRAPEN ---
        selector_alle_lessen = f"li[data-remodal-target*='{dag_en}']"
        alle_lessen_elementen = await page.locator(selector_alle_lessen).all()

        for les in alle_lessen_elementen:
            try:
                les_tijd = (await les.locator(".event-date").first.inner_text()).strip()
                les_type = (await les.locator(".event-name").first.inner_text()).strip()

                # Probeer het aantal deelnemers (bijv. 14/16) direct van het blokje te lezen
                les_deelnemers = ""
                try: les_deelnemers = (await les.locator(".event-registrations").first.inner_text()).strip()
                except: pass

                # Bepaal of de les vol is
                les_class = await les.get_attribute("class") or ""
                les_status = "Open"
                if "full" in les_class: les_status = "Vol (Wachtlijst)"
                if "signedup" in les_class or "booked" in les_class: les_status = "Jij bent Ingeschreven"
                if "on-waiting-list" in les_class: les_status = "Jij staat op Wachtlijst"

                volledig_rooster.append({
                    "tijd": les_tijd,
                    "type": les_type,
                    "zaal": zaal_naam,
                    "deelnemers": les_deelnemers,
                    "status": les_status
                })
            except: pass

        # --- JOUW PERSOONLIJKE INSCHRIJVING CHECK (Wachtlijst) ---
        selector_wachtlijst = f"li.on-waiting-list[data-remodal-target*='{dag_en}']"
        les_wachtlijst = page.locator(selector_wachtlijst).first

        if not status["ingeschreven"] and await les_wachtlijst.count() > 0:
            status["ingeschreven"] = True
            status["wachtlijst"] = True
            try: status["tijd"] = (await les_wachtlijst.locator(".event-date").first.inner_text()).strip()
            except: pass
            try: status["type"] = (await les_wachtlijst.locator(".event-name").first.inner_text()).strip()
            except: pass

            await les_wachtlijst.click()
            try:
                await page.wait_for_selector(".remodal-is-opened", timeout=5000)
                await page.wait_for_timeout(1500)
                modal_data = await page.evaluate('''() => {
                    let res = {};
                    let cols = Array.from(document.querySelectorAll('.remodal-is-opened .grid .col'));
                    for (let i = 0; i < cols.length; i++) {
                        let text = cols[i].innerText.trim();
                        if (text.includes('Aanmeldingen')) res.deelnemers = cols[i+1] ? cols[i+1].innerText.trim() : '';
                        else if (text.includes('Positie op wachtlijst')) res.wachtlijst_plek = cols[i+1] ? cols[i+1].innerText.trim() : '';
                        else if (text === 'Wachtlijst:' || text === 'Wachtlijst') res.wachtlijst_totaal = cols[i+1] ? cols[i+1].innerText.trim() : '';
                    }
                    return res;
                }''')
                if modal_data.get("deelnemers"): status["deelnemers"] = modal_data["deelnemers"]
                if modal_data.get("wachtlijst_plek"): status["wachtlijst_plek"] = modal_data["wachtlijst_plek"]
                if modal_data.get("wachtlijst_totaal"): status["wachtlijst_totaal"] = modal_data["wachtlijst_totaal"]
            except: pass
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)

        # --- JOUW PERSOONLIJKE INSCHRIJVING CHECK (Normaal) ---
        selector_ingeschreven = f"li.workout-signedup[data-remodal-target*='{dag_en}'], li[class*='signed'][data-remodal-target*='{dag_en}'], li[class*='booked'][data-remodal-target*='{dag_en}']"
        les_ingeschreven = page.locator(selector_ingeschreven).first

        if not status["ingeschreven"] and await les_ingeschreven.count() > 0:
            status["ingeschreven"] = True
            try: status["tijd"] = (await les_ingeschreven.locator(".event-date").first.inner_text()).strip()
            except: pass
            try: status["type"] = (await les_ingeschreven.locator(".event-name").first.inner_text()).strip()
            except: pass

            await les_ingeschreven.click()
            try:
                await page.wait_for_selector(".remodal-is-opened", timeout=5000)
                await page.wait_for_timeout(1500)
                modal_data = await page.evaluate('''() => {
                    let res = {};
                    let cols = Array.from(document.querySelectorAll('.remodal-is-opened .grid .col'));
                    for (let i = 0; i < cols.length; i++) {
                        if (cols[i].innerText.includes('Aanmeldingen')) res.deelnemers = cols[i+1] ? cols[i+1].innerText.trim() : '';
                    }
                    return res;
                }''')
                if modal_data.get("deelnemers"): status["deelnemers"] = modal_data["deelnemers"]
            except: pass
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(1000)

    # Sorteer het rooster netjes op tijdstip
    volledig_rooster = sorted(volledig_rooster, key=lambda x: x['tijd'])

    return status, volledig_rooster

async def scrape_once():
    """Doet 1 volledige scrape. Schrijft bij succes workout.json + history.csv.
    Gooit een exception als er iets misgaat (zodat de retry-lus opnieuw kan proberen)."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(20000)

        try:
            days_nl = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
            days_en = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

            now = datetime.now()
            tomorrow = now + timedelta(days=1)

            dag_nl_vandaag = days_nl[now.weekday()]
            dag_en_vandaag = days_en[now.weekday()]
            datum_vandaag_str = now.strftime("%d-%m-%Y")

            dag_nl_morgen = days_nl[tomorrow.weekday()]
            dag_en_morgen = days_en[tomorrow.weekday()]

            morgen_is_volgende_week = (now.weekday() == 6)

            print("Inloggen...")
            # '/login' is een 404; de echte loginpagina is '/inloggen-voor-leden'.
            await page.goto("https://www.crossfitbink36.nl/inloggen-voor-leden", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector("input[name*='user'], input[name*='email']", timeout=25000)

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(4000)

            print("WOD checken...")
            await page.goto("https://www.crossfitbink36.nl/?workout=wod", wait_until="domcontentloaded", timeout=45000)
            try:
                await page.wait_for_selector(".wod-card, .wod-list", timeout=8000)
                # De hele les-kaart (.wod-card) bevat naast het metcon-blok (.wod-list)
                # ook Strength/Techniek/Accessory, die BUITEN .wod-list staan.
                # Daarom pakken we de hele kaart i.p.v. alleen het eerste .wod-list.
                if await page.locator(".wod-card").count() > 0:
                    ruwe_tekst = await page.locator(".wod-card").first.inner_text()
                else:
                    ruwe_tekst = await page.locator(".wod-list").first.locator("xpath=..").inner_text()
                full_text = schoon_wod_tekst(ruwe_tekst)
                if not full_text:
                    full_text = "Geen WOD tekst gevonden."
            except: full_text = "Geen WOD tekst gevonden."

            print("Naar Rooster voor status vandaag & morgen (Inclusief Compleet Rooster)...")
            status_vandaag, rooster_vandaag = await check_dag_status_en_rooster(page, dag_en_vandaag, is_volgende_week=False)
            status_morgen, rooster_morgen = await check_dag_status_en_rooster(page, dag_en_morgen, is_volgende_week=morgen_is_volgende_week)

            print("Rooster resterende dagen huidige week scrapen...")
            rooster_deze_week = await scrape_deze_week_rooster(page)

            print("Volledig rooster van aankomende week scrapen...")
            rooster_week = await scrape_week_rooster(page)

            oud_data = lees_workout_json()
            bestaande_post_workout = None
            if oud_data.get("datum") == datum_vandaag_str:
                bestaande_post_workout = oud_data.get("post_workout")

            data = {
                "datum": datum_vandaag_str,
                "dag": dag_nl_vandaag,
                "workout": full_text.strip(),
                "status_vandaag": status_vandaag,
                "rooster_vandaag": rooster_vandaag,
                "dag_morgen": dag_nl_morgen,
                "status_morgen": status_morgen,
                "rooster_morgen": rooster_morgen,
                "rooster_deze_week": rooster_deze_week,
                "rooster_week": rooster_week,
                "last_success": now.isoformat(timespec="seconds"),
            }
            if bestaande_post_workout: data["post_workout"] = bestaande_post_workout

            # Déjà vu: lijkt de WOD van vandaag op een eerdere uit history.csv?
            deja = bereken_deja_vu(full_text, datum_vandaag_str)
            if deja:
                data["deja_vu"] = deja

            # Bij succes eventuele oude storings-markering wissen.
            data.pop("last_alert", None)

            with open("workout.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)

            if len(full_text) > 10:
                update_history_csv(datum_vandaag_str, dag_nl_vandaag, full_text.strip())
            print("✅ Succesvol!")
        finally:
            await browser.close()

def meld_storing_indien_nodig(laatste_fout):
    """Stuurt hooguit 1 Telegram-melding per ALERT_THROTTLE_UUR uur, zodat je bij
    een langere storing niet bij elke run een ping krijgt."""
    data = lees_workout_json()
    now = datetime.now()

    mag_alerten = True
    vorige = data.get("last_alert")
    if vorige:
        try:
            if now - datetime.fromisoformat(vorige) < timedelta(hours=ALERT_THROTTLE_UUR):
                mag_alerten = False
        except Exception:
            pass

    if not mag_alerten:
        print("⏳ Storing, maar recent al gemeld — geen nieuwe Telegram-ping.")
        return

    stuur_telegram(
        "🚨 Bink WOD-scraper faalt herhaaldelijk.\n"
        f"Laatste fout: {laatste_fout}\n"
        "De widget-data wordt tijdelijk niet ververst."
    )
    # Markeer dat we net gealerteerd hebben (throttle onthouden).
    data["last_alert"] = now.isoformat(timespec="seconds")
    try:
        with open("workout.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Kon last_alert niet opslaan: {e}")

async def main():
    laatste_fout = None
    for poging in range(1, MAX_POGINGEN + 1):
        try:
            print(f"--- Poging {poging}/{MAX_POGINGEN} ---")
            await scrape_once()
            return  # Succes -> exit 0, geen mail/ping.
        except Exception as e:
            laatste_fout = str(e)
            print(f"❌ Poging {poging} mislukt: {e}")
            if poging < MAX_POGINGEN:
                await asyncio.sleep(10)

    # Alle pogingen mislukt: throttled Telegram-melding, maar GEEN exit(1)
    # (anders stuurt GitHub Actions alsnog een failure-mail).
    print(f"❌ Alle {MAX_POGINGEN} pogingen mislukt. Laatste fout: {laatste_fout}")
    meld_storing_indien_nodig(laatste_fout)

if __name__ == "__main__":
    asyncio.run(main())

import os
import json
import asyncio
import urllib.request
import urllib.parse
from playwright.async_api import async_playwright
from datetime import datetime, timedelta

EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def stuur_telegram(bericht):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": bericht}).encode("utf-8")
    try: urllib.request.urlopen(urllib.request.Request(url, data=data))
    except: pass

async def run():
    print("Inschrijf-robot gestart!")
    
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        print("Geen event data gevonden.")
        return
        
    with open(event_path, "r") as f:
        payload = json.load(f).get("client_payload", {})
    
    doel_dag = payload.get("dag")
    doel_tijd = payload.get("tijd")
    doel_zaal = payload.get("zaal")
    actie = payload.get("actie")
    payload_dag_en = payload.get("dag_en")   # bv. "monday" (nieuw: week-lessen)
    payload_week = payload.get("week")        # "next" of "current" (nieuw)

    if not doel_tijd or not actie:
        print("Commando incompleet!")
        return

    now = datetime.now()
    days_en = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    if payload_dag_en:
        # Nieuwe stijl: widget geeft de exacte weekdag + welke week door.
        dag_en = payload_dag_en
        is_volgende_week = (payload_week == "next")
    else:
        # Oude stijl (Vandaag/Morgen) — blijft werken.
        is_morgen = (doel_dag == "Morgen")
        target_date = now + timedelta(days=1) if is_morgen else now
        dag_en = days_en[target_date.weekday()]
        is_volgende_week = (now.weekday() == 6 and is_morgen)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            page.set_default_timeout(20000)
            print("Inloggen...")
            # --- ROBUUSTE LOGIN VANUIT bink_auto.py ---
            await page.goto("https://www.crossfitbink36.nl/", wait_until="domcontentloaded", timeout=45000)
            try: await page.get_by_role("link", name="Inloggen").first.click(timeout=5000)
            except: await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(4000)
            # ------------------------------------------

            print(f"Navigeren naar {doel_zaal}...")
            zalen = {
                "Zaal 1": "https://www.crossfitbink36.nl/rooster",
                "Zaal 2": "https://www.crossfitbink36.nl/rooster?hall=Zaal%202",
                "Buiten": "https://www.crossfitbink36.nl/rooster?hall=Buiten"
            }
            url = zalen.get(doel_zaal, zalen["Zaal 1"])
            if is_volgende_week:
                url = f"{url}&week=next" if "?" in url else f"{url}?week=next"

            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                await page.wait_for_selector("li[data-remodal-target]", timeout=10000)
            except:
                pass
            await page.wait_for_timeout(1000)

            # Zoek het juiste blokje
            selector = f"li[data-remodal-target*='{dag_en}']"
            lessen = await page.locator(selector).all()
            target_les = None
            for les in lessen:
                try:
                    tijd_text = (await les.locator(".event-date").first.inner_text()).strip()
                    if doel_tijd in tijd_text:
                        target_les = les
                        break
                except: pass

            if not target_les:
                stuur_telegram(f"❌ *Fout:* Kon de les van {doel_tijd} ({doel_zaal}) niet vinden in het rooster.")
                return

            print("Les gevonden! Klikken...")
            await target_les.click()
            await page.wait_for_selector(".remodal-is-opened", timeout=5000)
            await page.wait_for_timeout(1500)

            modal = page.locator(".remodal-is-opened")

            # De knoppen in de pop-up zijn <input value="INSCHRIJVEN/UITSCHRIJVEN">
            # (niet altijd <button>/<a>). We dekken daarom álle varianten af,
            # gelijk aan het bewezen werkende bink_inschrijven.py. De oude versie
            # zocht alleen op zichtbare tekst en miste zo de <input>-knoppen,
            # waardoor uit-/inschrijven stil faalde.
            INSCHRIJF_SEL = ("input[value*='INSCHRIJVEN' i]:not([value*='UITSCHRIJVEN' i]), "
                             "button:has-text('Inschrijven'), a:has-text('Inschrijven')")
            WACHTLIJST_SEL = ("input[value*='WACHTLIJST' i], "
                              "button:has-text('Wachtlijst'), a:has-text('Wachtlijst')")
            UITSCHRIJF_SEL = ("input[value*='UITSCHRIJVEN' i], input[value*='Afmelden' i], "
                              "button:has-text('Uitschrijven'), a:has-text('Uitschrijven'), "
                              "button:has-text('Afmelden'), a:has-text('Afmelden')")

            async def klik_knop(selector):
                """Klikt de eerste zichtbare/enabled knop die matcht. Geeft True bij klik."""
                knop = modal.locator(selector).first
                if await knop.count() > 0:
                    try:
                        await knop.scroll_into_view_if_needed()
                    except:
                        pass
                    await knop.click(force=True)
                    await page.wait_for_timeout(2500)
                    return True
                return False

            async def is_nog_ingeschreven():
                """Herlaadt het rooster en checkt de class van deze les. True als je
                nog steeds ingeschreven/op de wachtlijst staat."""
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_selector("li[data-remodal-target]", timeout=10000)
                except:
                    pass
                for les in await page.locator(selector).all():
                    try:
                        tijd_text = (await les.locator(".event-date").first.inner_text()).strip()
                        if doel_tijd in tijd_text:
                            cls = (await les.get_attribute("class") or "").lower()
                            return any(k in cls for k in ("signedup", "signed", "booked", "on-waiting-list"))
                    except:
                        pass
                return None  # les niet teruggevonden -> onbekend

            # --- KLIK OP DE JUISTE KNOP ---
            if actie == "inschrijven":
                geklikt = await klik_knop(INSCHRIJF_SEL) or await klik_knop(WACHTLIJST_SEL)

                if geklikt:
                    nog_in = await is_nog_ingeschreven()
                    if nog_in is True:
                        stuur_telegram(f"✅ *Ingeschreven* voor de les van *{doel_tijd}* in *{doel_zaal}* (of op de wachtlijst).")
                    elif nog_in is False:
                        stuur_telegram(f"⚠️ *Let op:* inschrijfknop geklikt voor {doel_tijd} ({doel_zaal}), maar je staat er (nog) niet in. Check het rooster.")
                    else:
                        stuur_telegram(f"✅ *Inschrijf-actie uitgevoerd* voor *{doel_tijd}* in *{doel_zaal}*.")
                else:
                    stuur_telegram(f"⚠️ *Mislukt:* geen inschrijfknop gevonden voor {doel_tijd}. Zat je er al in, of is de wachtlijst óók vol?")

            elif actie == "uitschrijven":
                geklikt = await klik_knop(UITSCHRIJF_SEL)

                if geklikt:
                    nog_in = await is_nog_ingeschreven()
                    if nog_in is False:
                        stuur_telegram(f"🗑️ *Uitgeschreven* voor de les van *{doel_tijd}* in *{doel_zaal}*.")
                    elif nog_in is True:
                        stuur_telegram(f"⚠️ *Let op:* uitschrijfknop geklikt voor {doel_tijd} ({doel_zaal}), maar je staat er NOG steeds in. De actie is niet doorgekomen.")
                    else:
                        stuur_telegram(f"🗑️ *Uitschrijf-actie uitgevoerd* voor *{doel_tijd}* in *{doel_zaal}*.")
                else:
                    stuur_telegram(f"⚠️ *Mislukt:* geen uitschrijfknop gevonden voor {doel_tijd}. Zat je er wel in?")

        except Exception as e:
            # Fout melden via Telegram, maar netjes afsluiten (exit 0) zodat GitHub
            # geen failure-mail stuurt.
            stuur_telegram(f"🚨 *Widget-actie mislukt* voor {doel_tijd} ({doel_zaal}):\n{str(e)}")
            print(f"CRITICAL: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run())

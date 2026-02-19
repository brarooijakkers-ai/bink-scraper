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

    if not doel_tijd or not actie:
        print("Commando incompleet!")
        return

    now = datetime.now()
    is_morgen = (doel_dag == "Morgen")
    target_date = now + timedelta(days=1) if is_morgen else now
    
    days_en = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    dag_en = days_en[target_date.weekday()]
    morgen_is_volgende_week = (now.weekday() == 6 and is_morgen)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("Inloggen...")
        # --- ROBUUSTE LOGIN VANUIT bink_auto.py ---
        await page.goto("https://www.crossfitbink36.nl/", wait_until="networkidle")
        try: await page.get_by_role("link", name="Inloggen").first.click(timeout=5000)
        except: await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")
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
        if morgen_is_volgende_week:
            url = f"{url}&week=next" if "?" in url else f"{url}?week=next"

        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(1500)

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
        
        # --- KLIK OP DE JUISTE KNOP ---
        if actie == "inschrijven":
            knop = modal.locator("button, a").filter(has_text="Inschrijven").first
            if await knop.count() == 0:
                knop = modal.locator("button, a").filter(has_text="wachtlijst").first
            
            if await knop.count() > 0:
                await knop.click()
                await page.wait_for_timeout(2000)
                stuur_telegram(f"✅ *Actie geslaagd!* Je bent zojuist via je widget INGESCHREVEN voor de les van *{doel_tijd}* in *{doel_zaal}*!")
            else:
                stuur_telegram(f"⚠️ *Mislukt:* Kon niet inschrijven voor {doel_tijd}. Zat je er al in, of is de wachtlijst óók helemaal vol?")

        elif actie == "uitschrijven":
            knop = modal.locator("button, a").filter(has_text="Uitschrijven").first
            if await knop.count() == 0:
                knop = modal.locator("button, a").filter(has_text="Afmelden").first
            
            if await knop.count() > 0:
                await knop.click()
                await page.wait_for_timeout(2000)
                stuur_telegram(f"🗑️ *Actie geslaagd!* Je bent succesvol UITGESCHREVEN voor de les van *{doel_tijd}* in *{doel_zaal}*.")
            else:
                stuur_telegram(f"⚠️ *Mislukt:* Kon je niet uitschrijven voor {doel_tijd}. Zat je er wel in?")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())

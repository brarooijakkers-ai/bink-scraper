import asyncio
import os
import time
import urllib.request
import urllib.parse
from playwright.async_api import async_playwright
from datetime import datetime

# 1. Tijdzone instellen op Amsterdam
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

# --- TELEGRAM FUNCTIE ---
def stuur_telegram(bericht):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("⚠️ Geen Telegram gegevens, bericht niet verstuurd.")
        return

    print(f"📨 Telegram: {bericht}")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": TG_CHAT_ID, "text": bericht}).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"❌ Telegram fout: {e}")

async def sign_up():
    # --- TIJD CHECK ---
    nu = datetime.now()
    
    # Ruime marge: mag draaien tussen 04:00 en 07:00
    if not (4 <= nu.hour <= 7):
        rede = f"⛔️ Script gestart om {nu.strftime('%H:%M')}, maar mag alleen tussen 04:00-07:00 draaien."
        print(rede)
        return

    print(f"✅ Tijd is {nu.strftime('%H:%M')}. We gaan beginnen!")
    
    messages = [] 

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")

            if not EMAIL or not PASSWORD:
                raise Exception("Geen inloggegevens!")

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(3000)

            target_url = "https://www.crossfitbink36.nl/rooster?week=next&hall=Zaal-2"
            print(f"Naar rooster: {target_url}")
            await page.goto(target_url, wait_until="networkidle")
            
            # --- INSCHRIJF FUNCTIE (NU MET WACHTLIJST) ---
            async def schrijf_in(zoek_id, beschrijving):
                print(f"\n--- {beschrijving} ---")
                try:
                    selector = f"li[data-remodal-target*='{zoek_id}']"
                    
                    # Check of de les bestaat
                    if await page.locator(selector).count() > 0:
                        knop = page.locator(selector).first
                        await knop.scroll_into_view_if_needed()
                        await knop.click(force=True)
                        
                        # Wacht op pop-up
                        await page.wait_for_selector(".remodal-is-opened", timeout=10000)
                        popup = page.locator(".remodal-is-opened")
                        
                        # Definieer de knoppen
                        # 1. Normaal inschrijven
                        inschrijf_knop = popup.locator("input[value='INSCHRIJVEN'], button:has-text('Inschrijven')")
                        # 2. Wachtlijst (Op basis van je broncode: vaak 'WACHTLIJST' of 'AANMELDEN WACHTLIJST')
                        wachtlijst_knop = popup.locator("input[value*='WACHTLIJST'], input[value*='Wachtlijst'], button:has-text('Wachtlijst')")
                        # 3. Uitschrijven (reeds ingeschreven)
                        uitschrijf_knop = popup.locator("input[value='UITSCHRIJVEN']")

                        # --- LOGICA ---
                        if await inschrijf_knop.count() > 0 and await inschrijf_knop.is_enabled():
                            # Situatie A: Plek vrij!
                            await inschrijf_knop.click()
                            await page.wait_for_timeout(3000)
                            messages.append(f"✅ Ingeschreven: {beschrijving}")
                            print("✅ Gelukt!")

                        elif await wachtlijst_knop.count() > 0 and await wachtlijst_knop.is_enabled():
                            # Situatie B: Vol, maar wachtlijst open
                            print("⚠️ Les is vol. Inschrijven op WACHTLIJST...")
                            await wachtlijst_knop.click()
                            await page.wait_for_timeout(3000)
                            messages.append(f"⏳ Op WACHTLIJST gezet: {beschrijving}")
                            print("✅ Op wachtlijst!")

                        elif await uitschrijf_knop.count() > 0:
                            # Situatie C: Al geregeld
                            messages.append(f"ℹ️ Reeds ingeschreven: {beschrijving}")
                            print("ℹ️ Was al ingeschreven")

                        else:
                            # Situatie D: Echt helemaal dicht
                            messages.append(f"❌ Geen plek/wachtlijst: {beschrijving}")
                            print("❌ Geen opties gevonden")
                        
                        # Pagina verversen om pop-up veilig te sluiten
                        await page.reload(wait_until="networkidle")
                        
                    else:
                        messages.append(f"❌ Les niet gevonden: {beschrijving}")
                        print("❌ Niet gevonden in rooster")
                        
                except Exception as e:
                    messages.append(f"❌ Fout bij {beschrijving}: {str(e)}")
                    print(f"Error: {e}")

            # --- UITVOEREN ---
            await schrijf_in("tuesday-Oly Lifting-18:30", "Dinsdag OLY (18:30)")
            await schrijf_in("saturday-Oly Lifting-11:15", "Zaterdag OLY (11:15)")

            # --- RAPPORTAGE ---
            eind_bericht = "🏋️‍♂️ *Bink Update:*\n\n" + "\n".join(messages)
            stuur_telegram(eind_bericht)

        except Exception as e:
            fout_bericht = f"🚨 *ERROR:*\nScript gecrasht!\n{str(e)}"
            stuur_telegram(fout_bericht)
            print(f"CRITICAL: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(sign_up())

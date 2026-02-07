import asyncio
import os
import time
import urllib.request
import urllib.parse
from playwright.async_api import async_playwright
from datetime import datetime

# 1. Tijdzone instellen
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
        print("⚠️ Geen Telegram gegevens gevonden, bericht niet verstuurd.")
        return

    print(f"📨 Telegram versturen: {bericht}")
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
    if nu.hour != 4:
        print(f"⛔️ Het is {nu.strftime('%H:%M')}. Wachten op 04:00 uur trigger.")
        return

    messages = [] # Hier verzamelen we de statusupdates

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
            
            # --- INSCHRIJF FUNCTIE ---
            async def schrijf_in(zoek_id, beschrijving):
                print(f"\n--- {beschrijving} ---")
                try:
                    selector = f"li[data-remodal-target*='{zoek_id}']"
                    
                    if await page.locator(selector).count() > 0:
                        knop = page.locator(selector).first
                        await knop.scroll_into_view_if_needed()
                        await knop.click(force=True)
                        
                        await page.wait_for_selector(".remodal-is-opened", timeout=10000)
                        popup = page.locator(".remodal-is-opened")
                        
                        inschrijf_knop = popup.locator("input[value='INSCHRIJVEN'], button:has-text('Inschrijven')")
                        
                        if await inschrijf_knop.count() > 0:
                            if await inschrijf_knop.is_enabled():
                                await inschrijf_knop.click()
                                await page.wait_for_timeout(3000)
                                messages.append(f"✅ Ingeschreven: {beschrijving}")
                                print("✅ Gelukt!")
                            else:
                                messages.append(f"⚠️ {beschrijving} zit VOL of is dicht.")
                                print("⚠️ Knop disabled")
                        else:
                            if await popup.locator("input[value='UITSCHRIJVEN']").count() > 0:
                                messages.append(f"ℹ️ Was al ingeschreven: {beschrijving}")
                                print("ℹ️ Reeds ingeschreven")
                            else:
                                messages.append(f"❓ Geen knop bij: {beschrijving}")
                        
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

            # --- EINDRAPPORT NAAR TELEGRAM ---
            eind_bericht = "🏋️‍♂️ *Bink Update:*\n\n" + "\n".join(messages)
            stuur_telegram(eind_bericht)

        except Exception as e:
            fout_bericht = f"🚨 *CRITCAL ERROR:*\nScript is gecrasht!\n{str(e)}"
            stuur_telegram(fout_bericht)
            print(f"CRITICAL: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(sign_up())

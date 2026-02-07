import asyncio
import os
import time
from playwright.async_api import async_playwright
from datetime import datetime

# 1. Tijdzone forceren naar Amsterdam
os.environ['TZ'] = 'Europe/Amsterdam'
try:
    time.tzset()
except:
    pass

# Haal inloggegevens uit Secrets
EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")

async def sign_up():
    # --- TIJD CHECK (Zomer/Wintertijd Fix) ---
    # We checken hoe laat het NU is in Nederland.
    nu = datetime.now()
    print(f"Huidige tijd in NL: {nu.strftime('%H:%M')}")

    # We willen dat dit script ALLEEN draait tussen 04:00 en 04:59 NL tijd.
    # Als GitHub dit script in de winter start om 03:15 UTC (wat 04:15 NL is) -> OK.
    # Als GitHub dit script in de zomer start om 02:15 UTC (wat 04:15 NL is) -> OK.
    # Maar... als GitHub in de winter óók de 'zomer-trigger' (02:15 UTC) afvuurt, is het pas 03:15 NL.
    # Dan moeten we stoppen, anders zijn we te vroeg.
    
    if nu.hour != 4:
        print(f"⛔️ Het is {nu.strftime('%H:%M')}. Het inschrijfvenster is pas om 04:00.")
        print("Script stopt nu (we wachten op de volgende trigger).")
        return # Stop het script hier

    print("✅ Tijd is correct (tussen 04:00 en 05:00). Start inschrijving!")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # --- STAP 1: INLOGGEN ---
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")

            if not EMAIL or not PASSWORD:
                raise Exception("Geen inloggegevens in Secrets!")

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(3000)

            # --- STAP 2: NAVIGEREN NAAR ROOSTER ---
            # Direct naar volgende week, Zaal 2
            target_url = "https://www.crossfitbink36.nl/rooster?week=next&hall=Zaal-2"
            print(f"Navigeren naar: {target_url}")
            await page.goto(target_url, wait_until="networkidle")
            
            # --- FUNCTIE OM IN TE SCHRIJVEN ---
            async def schrijf_in_voor_les(zoek_id, beschrijving):
                print(f"\n--- Bezig met: {beschrijving} ---")
                try:
                    # Zoek op ID (bijv: 'modal-tuesday-Oly Lifting-18:30')
                    # We gebruiken een selector die zoekt naar een LI element met deze tekst in de data-target
                    selector = f"li[data-remodal-target*='{zoek_id}']"
                    
                    if await page.locator(selector).count() > 0:
                        print(f"✅ Les gevonden. Klikken...")
                        knop = page.locator(selector).first
                        await knop.scroll_into_view_if_needed()
                        await knop.click(force=True)
                        
                        # Wacht op pop-up
                        await page.wait_for_selector(".remodal-is-opened", timeout=10000)
                        popup = page.locator(".remodal-is-opened")
                        
                        # Zoek specifieke inschrijfknop
                        inschrijf_knop = popup.locator("input[value='INSCHRIJVEN'], button:has-text('Inschrijven')")
                        
                        if await inschrijf_knop.count() > 0:
                            if await inschrijf_knop.is_enabled():
                                print("✍️  Knop gevonden! INSCHRIJVEN...")
                                await inschrijf_knop.click()
                                await page.wait_for_timeout(3000) # Wachten op save
                                print("✅  Gelukt!")
                            else:
                                print("⚠️ Knop is uitgeschakeld (vol of dicht).")
                        else:
                            # Check of we al ingeschreven zijn
                            if await popup.locator("input[value='UITSCHRIJVEN']").count() > 0:
                                print("ℹ️ Je bent AL ingeschreven.")
                            else:
                                print("❌ Geen inschrijfknop gevonden.")
                        
                        # Refresh pagina voor de volgende les (veiligste manier om pop-up te sluiten)
                        await page.reload(wait_until="networkidle")
                        
                    else:
                        print(f"❌ Les niet gevonden in het rooster.")
                        
                except Exception as e:
                    print(f"❌ Fout bij {beschrijving}: {e}")

            # --- STAP 3: UITVOEREN ---
            
            # Dinsdag OLY 18:30 (Check ID in broncode bijv: tuesday-Oly Lifting-18:30)
            await schrijf_in_voor_les("tuesday-Oly Lifting-18:30", "Dinsdag OLY (18:30)")

            # Zaterdag OLY 11:15
            await schrijf_in_voor_les("saturday-Oly Lifting-11:15", "Zaterdag OLY (11:15)")

            print("\n🏁 Script voltooid.")

        except Exception as e:
            print(f"CRITISCHE FOUT: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(sign_up())

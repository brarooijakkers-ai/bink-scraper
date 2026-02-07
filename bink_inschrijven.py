import asyncio
import os
import time
from playwright.async_api import async_playwright

# 1. Tijdzone instellen voor logboeken
os.environ['TZ'] = 'Europe/Amsterdam'
try:
    time.tzset()
except:
    pass

# Haal inloggegevens uit Secrets
EMAIL = os.environ.get("BINK_EMAIL")
PASSWORD = os.environ.get("BINK_PASSWORD")

async def sign_up():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        print("🚀 Auto-Inschrijver gestart...")

        try:
            # --- STAP 1: INLOGGEN ---
            print("Inloggen...")
            await page.goto("https://www.crossfitbink36.nl/login", wait_until="domcontentloaded")

            if not EMAIL or not PASSWORD:
                raise Exception("Geen inloggegevens in Secrets!")

            await page.locator("input[name*='user'], input[name*='email']").first.fill(EMAIL)
            await page.locator("input[name*='pass']").first.fill(PASSWORD)
            await page.locator("button[type='submit'], input[type='submit']").first.click()
            await page.wait_for_timeout(3000) # Even wachten op login

            # --- STAP 2: NAVIGEREN NAAR VOLGENDE WEEK ZAAL 2 ---
            # We gebruiken de directe URL die we in jouw screenshots vonden
            target_url = "https://www.crossfitbink36.nl/rooster?week=next&hall=Zaal-2"
            print(f"Direct naar rooster volgende week (Zaal 2): {target_url}")
            await page.goto(target_url, wait_until="networkidle")
            
            # --- FUNCTIE OM IN TE SCHRIJVEN ---
            async def schrijf_in_voor_les(dag_naam, zoek_id, beschrijving):
                print(f"\n--- Bezig met: {beschrijving} ---")
                try:
                    # Zoek het blokje in het rooster op basis van de ID in de HTML code
                    # Screenshot 5 toont: 'modal-tuesday-Oly Lifting-18:30'
                    selector = f"li[data-remodal-target*='{zoek_id}']"
                    
                    if await page.locator(selector).count() > 0:
                        print(f"✅ Les gevonden in rooster. Klikken...")
                        knop = page.locator(selector).first
                        await knop.scroll_into_view_if_needed()
                        await knop.click(force=True)
                        
                        # Wacht op pop-up
                        print("Wachten op pop-up...")
                        popup = page.locator(".remodal-is-opened")
                        await page.wait_for_selector(".remodal-is-opened", timeout=10000)
                        
                        # Zoek de INSCHRIJVEN knop
                        # We zoeken naar een button of input met de tekst 'Inschrijven'
                        inschrijf_knop = popup.locator("input[value='INSCHRIJVEN'], button:has-text('Inschrijven')")
                        
                        if await inschrijf_knop.count() > 0:
                            if await inschrijf_knop.is_enabled():
                                print("✍️  Knop gevonden! INSCHRIJVEN...")
                                await inschrijf_knop.click()
                                await page.wait_for_timeout(3000) # Wachten op verwerking
                                print("✅  Geklikt! (Controleer later je mail/app)")
                            else:
                                print("⚠️ Knop is uitgeschakeld (misschien vol of nog niet open?)")
                        else:
                            # Check of we al ingeschreven zijn
                            uitschrijf_knop = popup.locator("input[value='UITSCHRIJVEN']")
                            if await uitschrijf_knop.count() > 0:
                                print("ℹ️ Je bent AL ingeschreven voor deze les.")
                            else:
                                print("❌ Geen inschrijfknop gevonden in pop-up.")
                        
                        # Sluit pop-up door te klikken op de 'close' knop of naast de modal
                        # Of we herladen gewoon de pagina voor de volgende les, dat is veiliger
                        await page.reload(wait_until="networkidle")
                        
                    else:
                        print(f"❌ Les niet gevonden in het rooster. Check de datum/tijd.")
                        
                except Exception as e:
                    print(f"❌ Fout bij {beschrijving}: {e}")

            # --- STAP 3: DE INSCHRIJVINGEN UITVOEREN ---
            
            # 1. Dinsdag OLY (18:30)
            # ID uit screenshot 5: 'modal-tuesday-Oly Lifting-18:30'
            await schrijf_in_voor_les(
                "dinsdag", 
                "tuesday-Oly Lifting-18:30", 
                "Dinsdag OLY (18:30)"
            )

            # 2. Zaterdag OLY (11:15)
            # ID uit screenshot 4: 'modal-saturday-Oly Lifting-11:15'
            await schrijf_in_voor_les(
                "zaterdag", 
                "saturday-Oly Lifting-11:15", 
                "Zaterdag OLY (11:15)"
            )

            print("\n🏁 Klaar met inschrijf-ronde.")

        except Exception as e:
            print(f"CRITISCHE FOUT: {e}")
            exit(1)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(sign_up())

import asyncio
from playwright.async_api import async_playwright
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "backend"))
from app.db.database import SessionLocal
from app.db.models import XAccount
from app.core.crypto import get_crypto

async def main():
    crypto = get_crypto()
    with SessionLocal() as db:
        acc = db.query(XAccount).first()
        state_json = crypto.decrypt_str(acc.storage_state_enc)
        storage_state = json.loads(state_json)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=storage_state,
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        
        print("Navigating...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        
        print("Waiting for SideNav...")
        nav_button = page.locator('[data-testid="SideNav_NewTweet_Button"]').first
        await nav_button.wait_for(timeout=15000)
        
        print("Clicking SideNav_NewTweet_Button...")
        await nav_button.click()
        
        print("Waiting for editor...")
        editor = page.locator('[data-testid="tweetTextarea_0"]').first
        try:
            await editor.wait_for(timeout=5000)
            print("Editor found!")
        except Exception as e:
            print("Editor NOT found! Taking screenshot...")
            await page.screenshot(path="screenshot_error.png")
            
            # Print any dialogs/modals
            dialogs = await page.evaluate('''() => {
                const results = [];
                // Find all layers/modals
                const layers = document.querySelectorAll('#layers div[role="dialog"]');
                layers.forEach(l => {
                    results.push(l.innerText);
                });
                return results;
            }''')
            print("Dialogs open:", dialogs)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

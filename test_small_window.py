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
        args = ["--window-size=500,600"]
        browser = await pw.chromium.launch(headless=True, args=args)
        context = await browser.new_context(
            storage_state=storage_state,
            viewport=None,
            no_viewport=True,
        )
        page = await context.new_page()
        
        print("Navigating to home (window_size=500,600)...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        
        print("Waiting for SideNav...")
        try:
            nav_button = page.locator('[data-testid="SideNav_NewTweet_Button"]').first
            await nav_button.wait_for(timeout=10000)
            print("SideNav found, clicking...")
            await nav_button.click()
        except Exception:
            print("SideNav NOT found. Searching for any NewTweet buttons...")
            btns = await page.evaluate('''() => {
                const els = document.querySelectorAll('[data-testid*="NewTweet"]');
                return Array.from(els).map(e => e.getAttribute('data-testid'));
            }''')
            print("Found new tweet buttons:", btns)
            if btns:
                nav_button = page.locator(f'[data-testid="{btns[0]}"]').first
                await nav_button.click()
        
        print("Waiting for editor...")
        editor = page.locator('[data-testid="tweetTextarea_0"]').first
        try:
            await editor.wait_for(timeout=5000)
            print("Editor found!")
        except Exception as e:
            print("Editor NOT found! Taking screenshot...")
            await page.screenshot(path="screenshot_error_small.png")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

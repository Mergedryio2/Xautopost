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
        
        print("Navigating directly to /compose/tweet...")
        await page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded")
        
        print("Waiting for editor...")
        # Try finding the editor with a broader selector
        editor = page.locator('[data-testid="tweetTextarea_0"], [data-testid="tweetTextarea_0RichTextInputContainer"], [role="textbox"][contenteditable="true"]').first
        
        try:
            await editor.wait_for(timeout=10000)
            print("Editor found!")
            testid = await editor.evaluate("el => el.getAttribute('data-testid')")
            print("Matched testid:", testid)
        except Exception as e:
            print("Editor NOT found! Taking screenshot...")
            await page.screenshot(path="screenshot_compose_error.png")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

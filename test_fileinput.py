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
            viewport=None,
            no_viewport=True,
        )
        page = await context.new_page()
        
        await page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded")
        
        try:
            editor = page.locator('[data-testid="tweetTextarea_0"], [data-testid="tweetTextarea_0RichTextInputContainer"]').first
            await editor.wait_for(timeout=10000)
            
            fi = page.locator('[data-testid="fileInput"]').first
            if await fi.count() > 0:
                print("fileInput found!")
            else:
                print("fileInput NOT found!")
                
            tb = page.locator('[data-testid="tweetButton"]').first
            if await tb.count() > 0:
                print("tweetButton found!")
            else:
                print("tweetButton NOT found!")
                
        except Exception as e:
            print("Error:", e)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

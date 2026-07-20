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
        args = ["--window-size=1280,720"]
        browser = await pw.chromium.launch(headless=True, args=args)
        context = await browser.new_context(
            storage_state=storage_state,
            viewport=None,
            no_viewport=True,
        )
        page = await context.new_page()
        
        print("Navigating to home...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        
        try:
            await page.locator('[data-testid="tweet"]').first.wait_for(timeout=10000)
            href = await page.locator('[data-testid="tweet"] a[href*="/status/"]').first.get_attribute("href")
            tweet_id = href.split("/status/")[1].split("?")[0] if href else None
            
            if tweet_id:
                print(f"Navigating to tweet {tweet_id}...")
                await page.goto(f"https://x.com/i/web/status/{tweet_id}", wait_until="domcontentloaded")
                
                editor = page.locator('[data-testid="tweetTextarea_0"], [data-testid="tweetTextarea_0RichTextInputContainer"]').first
                await editor.wait_for(timeout=10000)
                
                print("Focusing editor...")
                await editor.focus()
                await asyncio.sleep(1.5)
                
                print("Typing text...")
                await page.keyboard.insert_text("Testing reply from Playwright!")
                await asyncio.sleep(2)
                
                text_content = await editor.text_content()
                print("Editor text after typing:", text_content)
                
                if "Testing reply" in text_content:
                    print("SUCCESS! Text was written.")
                else:
                    print("FAILURE! Text was not written.")
                    await page.screenshot(path="screenshot_reply_type_error.png")
            else:
                print("No tweet found.")
                
        except Exception as e:
            print("Error:", e)
            await page.screenshot(path="screenshot_reply_action_error.png")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

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
        
        # Wait for timeline to load
        try:
            await page.locator('[data-testid="tweet"]').first.wait_for(timeout=10000)
            
            # Find a tweet ID
            href = await page.locator('[data-testid="tweet"] a[href*="/status/"]').first.get_attribute("href")
            tweet_id = href.split("/status/")[1].split("?")[0] if href else None
            
            if tweet_id:
                print(f"Found tweet ID: {tweet_id}, navigating to it...")
                await page.goto(f"https://x.com/i/web/status/{tweet_id}", wait_until="domcontentloaded")
                await asyncio.sleep(4)
                
                print("Looking for reply editor testids...")
                testids = await page.evaluate('''() => {
                    const els = document.querySelectorAll('[data-testid]');
                    const ids = new Set();
                    els.forEach(el => {
                        const id = el.getAttribute('data-testid');
                        if (id.toLowerCase().includes('tweet') || id.toLowerCase().includes('text') || id.toLowerCase().includes('reply')) {
                            ids.add(id);
                        }
                    });
                    return Array.from(ids);
                }''')
                print("Found matching testids:", testids)
                
                print("Looking for contenteditable...")
                ce_testids = await page.evaluate('''() => {
                    const els = document.querySelectorAll('[contenteditable="true"]');
                    return Array.from(els).map(el => {
                        let cur = el;
                        while(cur && !cur.getAttribute('data-testid')) {
                            cur = cur.parentElement;
                        }
                        return cur ? cur.getAttribute('data-testid') : 'no-testid';
                    });
                }''')
                print("contenteditable wrapped by testids:", ce_testids)
                
                editor = page.locator('[data-testid="tweetTextarea_0"], [data-testid="tweetTextarea_0RichTextInputContainer"]').first
                if await editor.count() > 0:
                    print("SUCCESS! Editor found by existing locator!")
                else:
                    print("FAILURE! Existing locator doesn't match the editor.")
            else:
                print("No tweet found on timeline.")
                
        except Exception as e:
            print("Error:", e)
            await page.screenshot(path="screenshot_reply_error.png")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

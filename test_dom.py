import asyncio
from playwright.async_api import async_playwright
import json
import sys
from pathlib import Path

# Add backend to path so we can import app modules
sys.path.append(str(Path(__file__).parent / "backend"))

from app.db.database import SessionLocal
from app.db.models import XAccount
from app.core.crypto import get_crypto

async def main():
    crypto = get_crypto()
    with SessionLocal() as db:
        acc = db.query(XAccount).first()
        if not acc or not acc.storage_state_enc:
            print("No account with storage state found")
            return
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
        print("Navigating to home...")
        await page.goto("https://x.com/home", wait_until="domcontentloaded")
        
        try:
            nav_button = page.locator('[data-testid="SideNav_NewTweet_Button"]').first
            await nav_button.wait_for(timeout=10000)
            print("Found new tweet button, clicking...")
            await nav_button.click()
            await asyncio.sleep(3) # Wait for modal
            
            # Dump all data-testid containing 'tweetTextarea' or 'tweetButton' or just dump body
            print("Looking for testids...")
            testids = await page.evaluate('''() => {
                const els = document.querySelectorAll('[data-testid]');
                const ids = new Set();
                els.forEach(el => {
                    const id = el.getAttribute('data-testid');
                    if (id.toLowerCase().includes('tweet') || id.toLowerCase().includes('text')) {
                        ids.add(id);
                    }
                });
                return Array.from(ids);
            }''')
            print("Found matching testids:", testids)
            
            # Look for elements with contenteditable
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
            
        except Exception as e:
            print("Error:", e)
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())

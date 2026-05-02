from __future__ import annotations

import asyncio
import json
import logging
import platform
from dataclasses import dataclass
from typing import Any

from playwright.async_api import async_playwright

from app.core.crypto import get_crypto
from app.db.database import SessionLocal
from app.db.models import PostLog, Proxy, XAccount
from app.db.utils import utcnow

log = logging.getLogger(__name__)

# X's built-in keyboard shortcut for sending the composed tweet. We dispatch
# via this rather than clicking the Post button because X overlays a
# pointer-event-blocking <div data-testid="mask"> during the composer's open
# animation, which causes any locator.click() to time out (the click waits
# for pointer events to reach the target and the mask intercepts them).
# Keyboard input goes through a different pipeline — no overlay check.
_POST_HOTKEY = "Meta+Enter" if platform.system() == "Darwin" else "Control+Enter"


@dataclass
class PostResult:
    ok: bool
    error: str | None = None


async def post_tweet(
    *, account_id: int, content: str, headless: bool = False
) -> PostResult:
    """Restore the X account session and post a tweet. Logs to post_logs."""
    state, proxy_kwargs = _load_account_state(account_id)
    if state is None:
        result = PostResult(ok=False, error="ยังไม่มี session ที่บันทึกไว้")
        _write_log(account_id, content, result)
        return result

    result = await _do_post(state, content, proxy_kwargs, headless=headless)
    _write_log(account_id, content, result)
    return result


def _load_account_state(
    account_id: int,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    crypto = get_crypto()
    with SessionLocal() as db:
        acc = db.get(XAccount, account_id)
        if acc is None or acc.storage_state_enc is None:
            return None, None
        state_json = crypto.decrypt_str(acc.storage_state_enc)
        state: dict[str, Any] = json.loads(state_json)

        proxy_kwargs: dict[str, str] | None = None
        if acc.proxy_id is not None:
            proxy = db.get(Proxy, acc.proxy_id)
            if proxy is not None:
                proxy_kwargs = {"server": proxy.server}
                if proxy.username_enc:
                    proxy_kwargs["username"] = crypto.decrypt_str(proxy.username_enc)
                if proxy.password_enc:
                    proxy_kwargs["password"] = crypto.decrypt_str(proxy.password_enc)
        return state, proxy_kwargs


def _write_log(account_id: int, content: str, result: PostResult) -> None:
    with SessionLocal() as db:
        row = PostLog(
            x_account_id=account_id,
            content=content,
            status="success" if result.ok else "failed",
            detail=result.error,
        )
        db.add(row)
        if result.ok:
            acc = db.get(XAccount, account_id)
            if acc is not None:
                acc.last_post_at = utcnow()
        db.commit()


async def _do_post(
    storage_state: dict[str, Any],
    content: str,
    proxy_kwargs: dict[str, str] | None,
    headless: bool = False,
) -> PostResult:
    try:
        async with async_playwright() as pw:
            launch_kwargs: dict[str, Any] = {
                "headless": headless,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if proxy_kwargs:
                launch_kwargs["proxy"] = proxy_kwargs

            try:
                browser = await pw.chromium.launch(
                    channel="chrome", **launch_kwargs
                )
            except Exception:  # noqa: BLE001
                browser = await pw.chromium.launch(**launch_kwargs)

            try:
                context = await browser.new_context(storage_state=storage_state)
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{ get: () => undefined })"
                )
                page = await context.new_page()

                # Verify session is alive — wait for the SideNav New Post button
                await page.goto(
                    "https://x.com/home", wait_until="domcontentloaded"
                )
                nav_button = page.locator(
                    '[data-testid="SideNav_NewTweet_Button"]'
                ).first
                try:
                    await nav_button.wait_for(timeout=15_000)
                except Exception:  # noqa: BLE001
                    return PostResult(
                        ok=False,
                        error="session หมดอายุ — ลบบัญชีนี้แล้วเพิ่มใหม่ค่ะ",
                    )

                # Open composer modal (more reliable than navigating to /compose/post)
                await nav_button.click()

                editor = page.locator('[data-testid="tweetTextarea_0"]').first
                try:
                    await editor.wait_for(timeout=20_000)
                except Exception:  # noqa: BLE001
                    return PostResult(
                        ok=False,
                        error=(
                            f"หา editor ไม่เจอ (URL: {page.url}) — "
                            "อาจมี dialog อื่นเปิดอยู่ หรือ X เปลี่ยน layout"
                        ),
                    )

                # X's tweet composer has two overlapping booby-traps:
                # 1. `editor.fill()` mutates the DOM but doesn't fire the
                #    synthetic input events React listens to → Post button
                #    stays aria-disabled forever.
                # 2. `editor.click()` times out because X overlays a
                #    transient `<div data-testid="mask">` from `<div id="layers">`
                #    during the modal-open animation; pointer events get
                #    intercepted by the mask, click retries indefinitely.
                # `editor.focus()` goes through the DOM directly (no
                # pointer-events check), and `page.keyboard.type` sends real
                # keydown/keyup/input events that React's contenteditable
                # picks up — bypassing both traps.
                await editor.focus()
                await asyncio.sleep(0.3)
                await page.keyboard.type(content, delay=12)
                await asyncio.sleep(1.2)  # let React debounce + state propagate

                # Wait for the post button to flip aria-disabled=false. We
                # don't actually click it — just use it as a "content
                # registered" gate, then dispatch via Cmd/Ctrl+Enter to dodge
                # the same mask overlay that blocks editor.click(). 20s is
                # generous; on a healthy network it flips in <1s.
                button = page.locator(
                    '[data-testid="tweetButton"]:not([aria-disabled="true"])'
                ).first
                await button.wait_for(timeout=20_000)
                await page.keyboard.press(_POST_HOTKEY)

                # Poll for outcome up to ~12s. Success signals: editor gone
                # or editor cleared. Failure signal: explicit error toast/alert.
                for _ in range(24):
                    await asyncio.sleep(0.5)
                    err = await _check_for_error(page)
                    if err:
                        return PostResult(ok=False, error=err)
                    try:
                        if not await editor.is_visible(timeout=100):
                            return PostResult(ok=True)
                    except Exception:  # noqa: BLE001
                        # Editor detached from DOM — treat as success
                        return PostResult(ok=True)
                    try:
                        text = (
                            await editor.text_content(timeout=100)
                        ) or ""
                        if text.strip() == "":
                            return PostResult(ok=True)
                    except Exception:  # noqa: BLE001
                        pass

                # 12s passed without a clear success or error signal. Final
                # check: if the editor is STILL visible with text in it, the
                # post almost certainly didn't go through (X commonly drops
                # duplicate-content posts silently, or shows a hidden/late
                # error toast that didn't match our keyword list).
                # Returning ok=True here used to produce false "success" logs
                # for posts X never actually accepted.
                final_err = await _check_for_error(page)
                if final_err:
                    return PostResult(ok=False, error=final_err)
                try:
                    final_visible = await editor.is_visible(timeout=200)
                except Exception:  # noqa: BLE001
                    return PostResult(ok=True)
                if not final_visible:
                    return PostResult(ok=True)
                try:
                    final_text = (
                        await editor.text_content(timeout=200)
                    ) or ""
                except Exception:  # noqa: BLE001
                    return PostResult(ok=True)
                if final_text.strip():
                    return PostResult(
                        ok=False,
                        error=(
                            "X ไม่ได้รับโพสต์ (กล่องเขียนยังมีเนื้อหาเดิม) · "
                            "อาจเป็นเนื้อหาซ้ำที่ X เคยรับไปแล้ว, "
                            "ติด rate limit ชั่วคราว, "
                            "หรือบัญชีถูกจำกัด"
                        ),
                    )
                return PostResult(ok=True)
            finally:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001
        log.exception("post_tweet failed")
        return PostResult(ok=False, error=str(e))


async def _check_for_error(page) -> str | None:  # type: ignore[no-untyped-def]
    """Look for an explicit error toast/alert. Returns the message or None."""
    candidates = ['[data-testid="toast"]', '[role="alert"]']
    keywords = (
        "rate limit",
        "rate-limit",
        "duplicate",
        "already said",
        "you already",
        "denied",
        "violation",
        "violat",
        "blocked",
        "restricted",
        "failed to",
        "could not",
        "couldn't",
        "try again",
        "too many",
        "unable to",
        "ผิดพลาด",
        "ล้มเหลว",
        "ลองอีกครั้ง",
        "ส่งซ้ำ",
    )
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if not await loc.is_visible(timeout=100):
                continue
            text = (await loc.text_content(timeout=200)) or ""
            text_lower = text.lower()
            if any(k in text_lower for k in keywords):
                return text.strip()[:200]
        except Exception:  # noqa: BLE001
            continue
    return None

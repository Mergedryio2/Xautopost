from __future__ import annotations

import asyncio
import json
import logging
import platform
from dataclasses import dataclass
from pathlib import Path
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
    *,
    account_id: int,
    content: str,
    media_paths: list[Path] | None = None,
    headless: bool = False,
) -> PostResult:
    """Restore the X account session and post a tweet. Logs to post_logs.
    `media_paths` is an ordered list of files to attach (max 4 images, OR 1
    video — X rejects mixed combinations and posts beyond those caps)."""
    state, proxy_kwargs = _load_account_state(account_id)
    if state is None:
        result = PostResult(ok=False, error="ยังไม่มี session ที่บันทึกไว้")
        _write_log(account_id, content, result)
        return result

    result = await _do_post(
        state,
        content,
        proxy_kwargs,
        media_paths=media_paths or [],
        headless=headless,
    )
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
    media_paths: list[Path],
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

                # editor.wait_for fires the moment the element is in the DOM,
                # which is BEFORE X's composer slide-in animation completes.
                # If we focus + type immediately, the operator sees text
                # appearing while the modal is still mid-animation — looks
                # janky and sometimes the focus lands wrong because the
                # animated transform isn't settled yet. Pause for a beat so
                # the visible sequence reads cleanly: modal slides in →
                # cursor focuses → text types out.
                await asyncio.sleep(1.0)

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
                # Human-like pause between focusing the editor and starting
                # to type. With only 0.3s the cursor barely lands before
                # text streams out, which both looks bot-like and sometimes
                # races X's focus logic. ~2.5s feels natural to a watcher.
                await asyncio.sleep(2.5)
                await page.keyboard.type(content, delay=12)
                await asyncio.sleep(1.2)  # let React debounce + state propagate

                # Attach media via X's hidden composer file input. Done after
                # typing so the visible sequence reads cleanly: text first,
                # then thumbnails appear. setInputFiles bypasses the mask
                # overlay (no pointer event needed) and accepts the full set
                # in one call — X validates the count/mix server-side.
                if media_paths:
                    upload_err = await _attach_media(page, media_paths)
                    if upload_err:
                        return PostResult(ok=False, error=upload_err)

                # Wait for the post button to flip aria-disabled=false. We
                # don't actually click it — just use it as a "content
                # registered" gate, then dispatch via Cmd/Ctrl+Enter to dodge
                # the same mask overlay that blocks editor.click(). 20s is
                # generous for text-only; with media (esp. video) the button
                # stays disabled until processing finishes, so allow longer.
                button = page.locator(
                    '[data-testid="tweetButton"]:not([aria-disabled="true"])'
                ).first
                button_timeout = 120_000 if media_paths else 20_000
                await button.wait_for(timeout=button_timeout)
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


async def _attach_media(page, paths: list[Path]) -> str | None:  # type: ignore[no-untyped-def]
    """Upload files via the composer's hidden <input type="file">. Returns
    None on success or an error string for the post log.

    X uses a single fileInput inside the composer for both images and video.
    Passing all paths in one setInputFiles call is the documented Playwright
    pattern and avoids races between sequential picks. After the call the
    button stays aria-disabled until X finishes server-side processing —
    that's what the extended `button_timeout` upstream covers, so we just
    do a short sanity wait here for the first thumbnail to show up.
    """
    missing = [p for p in paths if not p.is_file()]
    if missing:
        return f"ไฟล์แนบหาย: {', '.join(p.name for p in missing)}"

    try:
        file_input = page.locator('[data-testid="fileInput"]').first
        await file_input.set_input_files([str(p) for p in paths])
    except Exception as e:  # noqa: BLE001
        log.exception("setInputFiles failed")
        return f"แนบไฟล์ไม่สำเร็จ: {e}"

    # Wait for X to acknowledge the upload — the attachments container is
    # what the composer renders thumbnails into. If it never appears, the
    # post would go out without media, which is a worse failure than just
    # bailing out here.
    try:
        await page.locator('[data-testid="attachments"]').first.wait_for(
            timeout=15_000
        )
    except Exception:  # noqa: BLE001
        return (
            "X ยังไม่ได้รับไฟล์แนบหลังจากรอ 15 วิ — "
            "อาจเปลี่ยน layout หรือไฟล์ใหญ่เกิน"
        )
    return None


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

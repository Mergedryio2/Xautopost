from __future__ import annotations

import asyncio
import json
import logging
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, PlaywrightContextManager, async_playwright
import asyncio

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
class BrowserSession:
    mgr: PlaywrightContextManager
    browser: Browser
    context: BrowserContext
    page: Page
    is_on_status_page: bool = False

_ACTIVE_SESSIONS: dict[int, BrowserSession] = {}
_SESSION_LOCK = asyncio.Lock()

async def close_session(account_id: int) -> None:
    """Safely close and remove a cached browser session for an account."""
    async with _SESSION_LOCK:
        if account_id in _ACTIVE_SESSIONS:
            session = _ACTIVE_SESSIONS.pop(account_id)
            log.info(f"Closing browser session for account_id={account_id}")
            try:
                await session.browser.close()
            except Exception:
                pass
            try:
                await session.mgr.stop()
            except Exception:
                pass


@dataclass
class PostResult:
    ok: bool
    error: str | None = None


async def post_tweet(
    *,
    account_id: int,
    content: str,
    media_paths: list[Path] | None = None,
    window_position: tuple[int, int] | None = None,
    window_size: tuple[int, int] | None = None,
    headless: bool = False,
) -> PostResult:
    """Restore the X account session and post a tweet. Logs to post_logs.
    `media_paths` is an ordered list of files to attach (max 4 images, OR 1
    video — X rejects mixed combinations and posts beyond those caps).
    `window_position` and `window_size` pin the Chromium window to a fixed
    spot — used by the parallel scheduler to tile concurrent posts in a
    deterministic grid instead of letting them stack at the OS default."""
    state, proxy_kwargs, handle = _load_account_state(account_id)
    if state is None:
        result = PostResult(ok=False, error="ยังไม่มี session ที่บันทึกไว้")
        _write_log(account_id, content, result)
        return result

    result = await _do_post(
        state,
        content,
        proxy_kwargs,
        media_paths=media_paths or [],
        window_position=window_position,
        window_size=window_size,
        headless=headless,
    )
    _write_log(account_id, content, result)
    return result


async def post_reply(
    *,
    account_id: int,
    content: str,
    target_tweet_id: str,
    media_paths: list[Path] | None = None,
    window_position: tuple[int, int] | None = None,
    window_size: tuple[int, int] | None = None,
    headless: bool = False,
) -> PostResult:
    """Reply to a specific tweet of the account's own posts. Navigates to
    https://x.com/i/web/status/{id} (canonical URL — X redirects to the
    handle-prefixed form), opens the inline reply composer, types, and
    submits via the same Cmd/Ctrl+Enter hotkey as post_tweet. The result
    is logged with reply_to_tweet_id so the scheduler can enforce
    per-target reply caps."""
    state, proxy_kwargs, handle = _load_account_state(account_id)
    if state is None:
        result = PostResult(ok=False, error="ยังไม่มี session ที่บันทึกไว้")
        _write_log(
            account_id, content, result, reply_to_tweet_id=target_tweet_id
        )
        return result

    result = await _do_reply(
        account_id,
        state,
        content,
        target_tweet_id,
        handle,
        proxy_kwargs,
        media_paths=media_paths or [],
        window_position=window_position,
        window_size=window_size,
        headless=headless,
    )
    _write_log(
        account_id, content, result, reply_to_tweet_id=target_tweet_id
    )
    return result


def _load_account_state(
    account_id: int,
) -> tuple[dict[str, Any] | None, dict[str, str] | None, str | None]:
    crypto = get_crypto()
    with SessionLocal() as db:
        acc = db.get(XAccount, account_id)
        if acc is None or acc.storage_state_enc is None:
            return None, None, None
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
        return state, proxy_kwargs, acc.handle


def _write_log(
    account_id: int,
    content: str,
    result: PostResult,
    *,
    reply_to_tweet_id: str | None = None,
) -> None:
    with SessionLocal() as db:
        row = PostLog(
            x_account_id=account_id,
            content=content,
            status="success" if result.ok else "failed",
            detail=result.error,
            reply_to_tweet_id=reply_to_tweet_id,
        )
        db.add(row)
        if result.ok:
            acc = db.get(XAccount, account_id)
            if acc is not None:
                now_ts = utcnow()
                # Independent timestamps per slot so the scheduler can run
                # both the post and reply rotations without one's cadence
                # bumping the other's "last run" gate. UI computes max
                # client-side for the "last activity" display.
                if reply_to_tweet_id is not None:
                    acc.reply_last_run_at = now_ts
                else:
                    acc.last_post_at = now_ts
        db.commit()


async def _do_post(
    storage_state: dict[str, Any],
    content: str,
    proxy_kwargs: dict[str, str] | None,
    media_paths: list[Path],
    window_position: tuple[int, int] | None = None,
    window_size: tuple[int, int] | None = None,
    headless: bool = False,
) -> PostResult:
    try:
        async with async_playwright() as pw:
            args = ["--disable-blink-features=AutomationControlled"]
            # Pin position/size when the scheduler asks — parallel posts
            # tile in a grid so the user sees a clean layout instead of
            # OS-random stacking.
            if window_position is not None:
                args.append(
                    f"--window-position={window_position[0]},{window_position[1]}"
                )
            if window_size is not None:
                args.append(
                    f"--window-size={window_size[0]},{window_size[1]}"
                )
            launch_kwargs: dict[str, Any] = {
                "headless": headless,
                "args": args,
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
                # viewport=None disables Playwright's default 1280×720
                # viewport emulation. Without this, Playwright resizes the
                # window to fit a 1280×720 page regardless of the
                # --window-size flag we passed Chromium, which made all
                # tiled windows balloon back to ~1300px wide and overlap
                # neighbors. With viewport=None the window honors
                # --window-size and the page just fills it.
                context = await browser.new_context(
                    storage_state=storage_state,
                    viewport=None,
                    no_viewport=True,
                )
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

                editor = page.locator(
                    '[data-testid="tweetTextarea_0"], [data-testid="tweetTextarea_0RichTextInputContainer"]'
                ).first
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
                await page.keyboard.insert_text(content)
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

                # Each task posts as soon as its own prep is ready. We
                # used to gate this on an asyncio.Barrier so all siblings
                # pressed POST in the same event-loop turn, but that
                # forced fast tasks to idle while slow ones caught up
                # (with 6 parallel Chromiums, prep variance is large) —
                # halving visible throughput. Independent firing also
                # spreads requests across X's anti-spam window slightly,
                # which is closer to organic posting than a sub-second
                # burst from N IPs.
                url_before = page.url
                await page.keyboard.press(_POST_HOTKEY)

                # Poll for outcome up to ~20s. Success signals:
                #   1. URL changed (X navigated away from compose = posted)
                #   2. Editor gone / detached from DOM
                #   3. Editor inner_text is empty or only placeholder text
                # Failure signal: explicit error toast/alert.
                # We use inner_text() (not text_content()) because X's
                # contenteditable keeps non-text DOM nodes even when visually
                # empty; text_content() returns those, inner_text() doesn't.
                _X_PLACEHOLDERS = (
                    "what is happening",
                    "what's happening",
                    "post your reply",
                )
                for _ in range(40):
                    await asyncio.sleep(0.5)
                    err = await _check_for_error(page)
                    if err:
                        return PostResult(ok=False, error=err)
                    # URL change = X accepted the post and navigated away
                    if page.url != url_before:
                        return PostResult(ok=True)
                    try:
                        if not await editor.is_visible(timeout=100):
                            return PostResult(ok=True)
                    except Exception:  # noqa: BLE001
                        # Editor detached from DOM — treat as success
                        return PostResult(ok=True)
                    try:
                        text = (
                            await editor.inner_text(timeout=100)
                        ) or ""
                        stripped = text.strip().lower()
                        if stripped == "" or any(
                            ph in stripped for ph in _X_PLACEHOLDERS
                        ):
                            return PostResult(ok=True)
                    except Exception:  # noqa: BLE001
                        pass

                # 20s passed without a clear success or error signal. Final
                # check: if the editor is STILL visible with the original
                # content in it, the post almost certainly didn't go through
                # (X commonly drops duplicate-content posts silently, or shows
                # a hidden/late error toast that didn't match our keyword list).
                final_err = await _check_for_error(page)
                if final_err:
                    return PostResult(ok=False, error=final_err)
                if page.url != url_before:
                    return PostResult(ok=True)
                try:
                    final_visible = await editor.is_visible(timeout=200)
                except Exception:  # noqa: BLE001
                    return PostResult(ok=True)
                if not final_visible:
                    return PostResult(ok=True)
                try:
                    final_text = (
                        await editor.inner_text(timeout=200)
                    ) or ""
                except Exception:  # noqa: BLE001
                    return PostResult(ok=True)
                final_stripped = final_text.strip().lower()
                if final_stripped and not any(
                    ph in final_stripped for ph in _X_PLACEHOLDERS
                ):
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


async def _do_reply(
    account_id: int,
    storage_state: dict[str, Any],
    content: str,
    target_tweet_id: str,
    handle: str | None,
    proxy_kwargs: dict[str, str] | None,
    media_paths: list[Path],
    window_position: tuple[int, int] | None = None,
    window_size: tuple[int, int] | None = None,
    headless: bool = False,
) -> PostResult:
    """Reply flow. The reply composer at /i/web/status/{id} differs from the
    home composer in two ways: (1) the editor is inline below the parent
    tweet rather than a modal, so there's no SideNav button + mask overlay
    to dance around; (2) the page can render a "Sorry, this page doesn't
    exist" error when the parent tweet was deleted, and we need to catch
    that before typing into a nonexistent editor. Everything else (focus,
    type, media, hotkey submit, success polling) reuses the post_tweet
    patterns."""
    try:
        async with _SESSION_LOCK:
            session = _ACTIVE_SESSIONS.get(account_id)
            if session is None:
                log.info(f"Starting new persistent browser session for account_id={account_id}")
                mgr = async_playwright()
                pw = await mgr.start()
                args = ["--disable-blink-features=AutomationControlled"]
                if window_position is not None:
                    args.append(f"--window-position={window_position[0]},{window_position[1]}")
                if window_size is not None:
                    args.append(f"--window-size={window_size[0]},{window_size[1]}")
                launch_kwargs: dict[str, Any] = {"headless": headless, "args": args}
                if proxy_kwargs:
                    launch_kwargs["proxy"] = proxy_kwargs

                try:
                    browser = await pw.chromium.launch(channel="chrome", **launch_kwargs)
                except Exception:
                    browser = await pw.chromium.launch(**launch_kwargs)

                context = await browser.new_context(
                    storage_state=storage_state,
                    viewport=None,
                    no_viewport=True,
                )
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
                )
                page = await context.new_page()
                session = BrowserSession(mgr=mgr, browser=browser, context=context, page=page)
                _ACTIVE_SESSIONS[account_id] = session
            else:
                log.info(f"Reusing existing browser session for account_id={account_id}")
                page = session.page

        # ── Self-Reply Mode Logic ────────────────────────────────────
        try:
            if session.is_on_status_page:
                log.info("Self-Reply Mode: Already on status page, skipping profile navigation")
                # On status page, the editor might already be focused or present
                # No need to click the reply button on the timeline
            else:
                log.info("Self-Reply Mode: Fetching latest tweet ID from profile")
                if handle:
                    log.info(f"Navigating directly to profile: https://x.com/{handle}")
                    await page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded")
                else:
                    await page.goto("https://x.com/", wait_until="domcontentloaded")
                    profile_link = page.locator('[data-testid="AppTabBar_Profile_Link"]').first
                    await profile_link.wait_for(state="visible", timeout=15000)
                    await profile_link.click()
                
                # Wait for timeline tweets to render
                first_tweet = page.locator('[data-testid="tweet"]').first
                await first_tweet.wait_for(state="visible", timeout=15000)
                
                # Click the reply icon on the timeline directly (no page.goto)
                log.info("Self-Reply Mode: Clicking reply on the timeline directly")
                reply_btn = first_tweet.locator('[data-testid="reply"]').first
                await reply_btn.wait_for(state="visible", timeout=10000)
                await reply_btn.click()
        except Exception as e:
            return PostResult(
                ok=False,
                error=f"ไม่พบโพสต์บนโปรไฟล์ หรือกด Reply ไม่ได้: {e}",
            )


        # Same testid as the home composer ('tweetTextarea_0') —
        # X reuses the editor component for inline replies. There
        # may be multiple matches when quote tweets nest, so
        # .first picks the top-level reply box.
        editor = page.locator(
            '[data-testid="tweetTextarea_0"], [data-testid="tweetTextarea_0RichTextInputContainer"]'
        ).first
        try:
            await editor.wait_for(timeout=20_000)
        except Exception:  # noqa: BLE001
            # Could be a permission case (protected target,
            # ourselves blocked from replying) or a layout shift.
            return PostResult(
                ok=False,
                error=(
                    "หา reply editor ไม่เจอ — "
                    "อาจไม่มีสิทธิ์ reply โพสต์นี้"
                ),
            )

        # Inline composer doesn't slide in like the modal, but
        # X's new RichTextInputContainer requires an explicit click
        # to expand from placeholder state to an active editor.
        await editor.click()
        await asyncio.sleep(1.5)
        await page.keyboard.insert_text(content)
        # Force X's rich text editor to parse hashtags by typing a space
        await page.keyboard.press("Space")
        await asyncio.sleep(1.5)

        if media_paths:
            upload_err = await _attach_media(page, media_paths)
            if upload_err:
                return PostResult(ok=False, error=upload_err)

        # Reply button uses a different testid than the main post
        # button; X renders it as "tweetButtonInline" on the
        # status page. Fall back to tweetButton if X changes back.
        button = page.locator(
            '[data-testid="tweetButtonInline"]:not([aria-disabled="true"]), '
            '[data-testid="tweetButton"]:not([aria-disabled="true"])'
        ).first
        button_timeout = 120_000 if media_paths else 20_000
        await button.wait_for(timeout=button_timeout)

        url_before_reply = page.url
        
        # Intercept CreateTweet GraphQL response to get the new tweet ID
        new_tweet_id = None
        async def handle_response(response):
            nonlocal new_tweet_id
            if "CreateTweet" in response.url and response.request.method == "POST":
                try:
                    json_data = await response.json()
                    new_tweet_id = json_data.get("data", {}).get("create_tweet", {}).get("tweet_results", {}).get("result", {}).get("rest_id")
                    if new_tweet_id:
                        log.info(f"Intercepted new tweet ID: {new_tweet_id}")
                    else:
                        # Sometimes it's nested differently (e.g. tweet object)
                        tweet = json_data.get("data", {}).get("create_tweet", {}).get("tweet_results", {}).get("result", {}).get("tweet", {})
                        if "rest_id" in tweet:
                            new_tweet_id = tweet["rest_id"]
                            log.info(f"Intercepted new tweet ID (nested): {new_tweet_id}")
                except Exception as e:
                    log.warning(f"Error parsing CreateTweet response: {e}")

        page.on("response", handle_response)
        
        await page.keyboard.press(_POST_HOTKEY)

        # Polling block — same shape as post_tweet's outcome
        # detection. The editor either disappears (replaced by the
        # newly-posted reply card), clears (X swaps inline composer
        # back to placeholder), or URL changes.
        # Use inner_text() not text_content() — X's contenteditable
        # leaves phantom DOM nodes so text_content() returns stale
        # content even when the editor looks visually empty.
        _X_REPLY_PLACEHOLDERS = (
            "post your reply",
            "tweet your reply",
            "what is happening",
            "what's happening",
        )
        post_success = False
        for _ in range(40):
            await asyncio.sleep(0.5)
            err = await _check_for_error(page)
            if err:
                return PostResult(ok=False, error=err)
            if page.url != url_before_reply:
                post_success = True
                break
            try:
                if not await editor.is_visible(timeout=100):
                    post_success = True
                    break
            except Exception:  # noqa: BLE001
                post_success = True
                break
            try:
                text = (
                    await editor.inner_text(timeout=100)
                ) or ""
                stripped = text.strip().lower()
                if stripped == "" or any(
                    ph in stripped for ph in _X_REPLY_PLACEHOLDERS
                ):
                    post_success = True
                    break
            except Exception:  # noqa: BLE001
                pass

        if not post_success:
            final_err = await _check_for_error(page)
            if final_err:
                return PostResult(ok=False, error=final_err)
            if page.url != url_before_reply:
                post_success = True
            
            if not post_success:
                try:
                    final_visible = await editor.is_visible(timeout=200)
                    if not final_visible:
                        post_success = True
                except Exception:  # noqa: BLE001
                    post_success = True
            
            if not post_success:
                try:
                    final_text = (
                        await editor.inner_text(timeout=200)
                    ) or ""
                    final_stripped = final_text.strip().lower()
                    if final_stripped and not any(
                        ph in final_stripped for ph in _X_REPLY_PLACEHOLDERS
                    ):
                        return PostResult(
                            ok=False,
                            error=(
                                "X ไม่ได้รับ reply (กล่องเขียนยังมีเนื้อหาเดิม) · "
                                "อาจเป็นเนื้อหาซ้ำ, ติด rate limit, หรือบัญชีถูกจำกัด"
                            ),
                        )
                    else:
                        post_success = True
                except Exception:  # noqa: BLE001
                    post_success = True

        if post_success:
            # Cleanup listener
            try:
                page.remove_listener("response", handle_response)
            except Exception:
                pass
                
            # ── Chain Topology Logic ────────────────────────────────────
            log.info("Self-Reply Mode: Navigating to new reply for comment-to-comment chain")
            navigated = False
            
            # We MUST use soft-navigation (clicking the Toast) if possible.
            # Hard-navigating (page.goto) hits X's edge servers, which often haven't indexed
            # the new tweet yet, resulting in "This post is unavailable".
            # Soft-navigation uses X's local state so the tweet appears instantly.
            log.info("Self-Reply Mode: Waiting for Toast to soft-navigate to new reply")
            try:
                toast_link = page.locator('[data-testid="toast"] a').first
                await toast_link.wait_for(state="attached", timeout=10000)
                
                # Give React time to bind the onClick handler on slower machines (Windows)
                # If we click too fast, the browser falls back to a standard <a href> hard-reload,
                # which triggers the eventual consistency bug!
                await asyncio.sleep(2)
                
                # Use evaluate to click so we bypass any invisible overlays
                await toast_link.evaluate('el => el.click()')
                
                # Wait for the status page to render the main tweet
                await page.locator('article[data-testid="tweet"][tabindex="-1"]').first.wait_for(state="visible", timeout=15000)
                navigated = True
                log.info("Soft-navigation via Toast succeeded.")
            except Exception as e:
                log.warning(f"Toast soft-navigation failed: {e}")
                
            if not navigated and new_tweet_id:
                log.info("Fallback: Hard-navigating using intercepted tweet ID")
                try:
                    # Give X's backend a much longer moment to index the new tweet (10s)
                    await asyncio.sleep(10)
                    clean_handle = handle.lstrip('@') if handle else None
                    target_url = f"https://x.com/{clean_handle}/status/{new_tweet_id}" if clean_handle else f"https://x.com/i/web/status/{new_tweet_id}"
                    await page.goto(target_url, wait_until="domcontentloaded")
                    await page.locator('article[data-testid="tweet"]').first.wait_for(state="visible", timeout=15000)
                    navigated = True
                except Exception as e:
                    log.warning(f"Hard-navigation failed: {e}")
            
            if navigated:
                log.info("Successfully navigated to new reply status page.")
                session.is_on_status_page = True
            else:
                log.warning("Could not navigate to new reply. Will fallback to profile next time.")
                session.is_on_status_page = False
            
            return PostResult(ok=True)
    except Exception as e:
        log.exception(f"Fatal error in _do_reply, closing session for {account_id}")
        await close_session(account_id)
        return PostResult(ok=False, error=str(e))


async def _is_target_gone(page) -> bool:  # type: ignore[no-untyped-def]
    """X renders a "this page doesn't exist" / "post unavailable" stub when
    the target tweet was deleted. Cheap probe — 1.5s ceiling — because we
    don't want to delay the common success path."""
    # 'empty_state' is X's standard testid for the deleted/unavailable stub.
    try:
        loc = page.locator('[data-testid="empty_state_header_text"]').first
        if await loc.is_visible(timeout=1500):
            return True
    except Exception:  # noqa: BLE001
        pass
    # Belt-and-suspenders: scan for the literal copy in case X changes the
    # testid. Bounded to one cheap call so it doesn't widen the hot path.
    try:
        body_text = await page.locator("body").inner_text(timeout=500)
        lowered = body_text.lower()
        for phrase in (
            "this post is from an account that doesn't exist",
            "hmm...this page doesn",
            "post unavailable",
            "this post was deleted",
            "this post is unavailable",
        ):
            if phrase in lowered:
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


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

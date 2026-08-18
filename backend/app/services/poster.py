from __future__ import annotations

import asyncio
import json
import logging
import platform
import random
import re
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

_CHAIN_TWEET_IDS: dict[int, str] = {}
_CHAIN_COUNTS: dict[int, int] = {}


async def close_session(account_id: int) -> None:  # noqa: ARG001
    """No-op stub kept for scheduler import compatibility."""
    pass


# Full browser stealth script. Patches the most common Playwright fingerprints
# that X (and other bot-detection systems) check:
#   - navigator.webdriver
#   - navigator.plugins (Playwright reports 0; real Chrome reports several)
#   - navigator.languages
#   - window.chrome (missing in Playwright)
#   - Notification / permissions query path
#   - Canvas 2D fingerprint (per-session noise)
#   - WebGL vendor/renderer (randomised per-session from a realistic pool)

# Pool of plausible desktop GPU strings — one is picked per-session at
# Python level and injected into the JS template so each Chromium instance
# presents a different hardware fingerprint.
_WEBGL_RENDERERS: list[tuple[str, str]] = [
    ("Intel Inc.", "Intel Iris OpenGL Engine"),
    ("Intel Inc.", "Intel HD Graphics 630 OpenGL Engine"),
    ("Intel Inc.", "Intel UHD Graphics 620 OpenGL Engine"),
    ("Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (AMD)",
     "ANGLE (AMD, AMD Radeon RX 5500M Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Apple Inc.", "Apple M1"),
    ("Apple Inc.", "Apple M2"),
]


def _make_stealth_script() -> str:
    """Generate a per-session stealth script with a randomised WebGL renderer
    and unique Canvas noise seed so every Chromium launch presents a distinct
    hardware fingerprint."""
    vendor, renderer = random.choice(_WEBGL_RENDERERS)
    # A small random float baked into the JS as a canvas noise seed.
    # Keeps each session's Canvas fingerprint unique without noticeable
    # visual change (shift is sub-pixel).
    canvas_noise = random.uniform(0.00001, 0.0001)
    return f"""
(function() {{
  // 1. webdriver flag
  Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});

  // 2. Fake plugin list (Chrome has ~5 built-in)
  const fakePlugins = ['Chrome PDF Plugin','Chrome PDF Viewer','Native Client',
                       'Shockwave Flash','Microsoft Edge PDF Viewer'];
  Object.defineProperty(navigator, 'plugins', {{
    get: () => fakePlugins.map(n => ({{ name: n, description: n,
      filename: 'internal', length: 1, item: () => null, namedItem: () => null }})),
  }});

  // 3. Languages
  Object.defineProperty(navigator, 'languages', {{
    get: () => ['th-TH', 'th', 'en-US', 'en'],
  }});

  // 4. chrome runtime (missing in Playwright)
  if (!window.chrome) {{ window.chrome = {{}}; }}
  if (!window.chrome.runtime) {{ window.chrome.runtime = {{}}; }}

  // 5. Permissions
  if (navigator.permissions && navigator.permissions.query) {{
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (p) =>
      p.name === 'notifications'
        ? Promise.resolve({{ state: Notification.permission, onchange: null }})
        : origQuery(p);
  }}

  // 6. Hardware / Memory spoofing
  Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => 8 }});
  Object.defineProperty(navigator, 'deviceMemory', {{ get: () => 8 }});

  // 7. WebGL spoofing — randomised per-session from a realistic GPU pool
  const getParameter = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function(parameter) {{
    if (parameter === 37445) {{ return {vendor!r}; }}
    if (parameter === 37446) {{ return {renderer!r}; }}
    return getParameter.call(this, parameter);
  }};

  // 8. Canvas 2D fingerprint noise — sub-pixel offset unique per session
  const _noise = {canvas_noise};
  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(type, quality) {{
    const ctx = this.getContext('2d');
    if (ctx) {{
      const id = ctx.getImageData(0, 0, 1, 1);
      id.data[0] = (id.data[0] + _noise * 255) & 0xff;
      ctx.putImageData(id, 0, 0);
    }}
    return origToDataURL.apply(this, arguments);
  }};
}})();
"""


async def _type_with_hashtag_parsing(page: Any, content: str) -> None:
    """Type content at human-plausible speed so X tokenizes #hashtags.

    Rhythm rules that mimic real typing:
      - Normal chars: 5–30 ms
      - After a space / newline (word boundary): 15–50 ms
      - After punctuation (.,!?;:): 80–200 ms (thinking pause between sentences)
      - Micro-break every 30–60 chars: 200–500 ms ("reading back what I wrote")
    Total for 280 chars: ~4–8 s — slower than the old version but much harder
    to distinguish from organic input by keystroke-timing analysis.
    """
    in_hashtag = False
    char_count = 0
    next_micro_break = random.randint(30, 60)
    for char in content:
        if char == '#':
            in_hashtag = True
        elif in_hashtag and not (char.isalnum() or char == '_'):
            # Non-word char ends the hashtag — close autocomplete first
            # so X seals the token before we type the next character.
            await page.keyboard.press("Escape")
            in_hashtag = False

        await page.keyboard.type(char, delay=0)
        char_count += 1

        # Micro-break — simulates glancing back at what was typed
        if char_count >= next_micro_break:
            await asyncio.sleep(random.uniform(0.20, 0.50))
            char_count = 0
            next_micro_break = random.randint(30, 60)
        elif char in (',', '.', '!', '?', ';', ':'):
            await asyncio.sleep(random.uniform(0.08, 0.20))
        elif char in (' ', '\n'):
            await asyncio.sleep(random.uniform(0.015, 0.050))
        else:
            await asyncio.sleep(random.uniform(0.005, 0.030))

    # If content ends with a hashtag, close the autocomplete popup
    # so the token is committed before submission.
    if in_hashtag:
        await page.keyboard.press("Escape")


async def _human_mouse_move(page: Any, x: float, y: float) -> None:
    """Move mouse to (x, y) via a multi-point curved path that varies speed.

    Simulates a Bezier-like arc: start → 2-3 intermediate waypoints → target.
    Speed varies inversely with remaining distance (fast start, slow approach)
    to defeat trajectory-based bot detection.
    """
    try:
        # Generate 2–4 intermediate waypoints with organic scatter
        n_waypoints = random.randint(2, 4)
        waypoints = []
        for i in range(1, n_waypoints + 1):
            t = i / (n_waypoints + 1)
            scatter_x = random.uniform(-50, 50) * (1 - abs(t - 0.5) * 2)
            scatter_y = random.uniform(-30, 30) * (1 - abs(t - 0.5) * 2)
            waypoints.append((x * t + scatter_x, y * t + scatter_y))
        waypoints.append((x, y))

        for wx, wy in waypoints:
            await page.mouse.move(wx, wy)
            # Decelerate near the end of the path
            remaining = len(waypoints) - waypoints.index((wx, wy)) - 1
            pause = random.uniform(0.02, 0.06) if remaining > 0 else random.uniform(0.05, 0.12)
            await asyncio.sleep(pause)
    except Exception:  # noqa: BLE001
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
    state, proxy_kwargs, _handle = _load_account_state(account_id)
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
    """Reply to a specific tweet. Navigates to
    https://x.com/i/web/status/{id}, opens the inline reply composer, types,
    and submits via the Cmd/Ctrl+Enter hotkey. The result is logged with
    reply_to_tweet_id so the scheduler can enforce per-target reply caps."""
    state, proxy_kwargs, _handle = _load_account_state(account_id)
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
                await context.add_init_script(_make_stealth_script())
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

                # --- Warm-up phase (Scroll feed ~2 seconds) ---
                # เลื่อนหน้าฟีดขึ้นลงสั้นๆ เพื่อให้เหมือนคนอ่านฟีดก่อนทวีต (เพิ่ม Trust Score)
                try:
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                    await page.mouse.wheel(0, random.randint(300, 800))
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                    await page.mouse.wheel(0, random.randint(-400, 200))
                    await asyncio.sleep(random.uniform(0.5, 1.0))
                except Exception:  # noqa: BLE001
                    pass
                # ----------------------------------------------

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
                await asyncio.sleep(random.uniform(0.5, 0.9))
                await _type_with_hashtag_parsing(page, content)
                await asyncio.sleep(random.uniform(0.5, 1.0))  # let React debounce + state propagate

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
                    if await _dismiss_boost_popup(page):
                        return PostResult(ok=True)
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
    proxy_kwargs: dict[str, str] | None,
    media_paths: list[Path],
    window_position: tuple[int, int] | None = None,
    window_size: tuple[int, int] | None = None,
    headless: bool = False,
) -> PostResult:
    """Reply flow (v0.2.8 style). Navigates directly to the target tweet status
    page, opens the inline reply composer, types, and submits. Fresh browser
    per run — simple, stable, works identically on Mac and Windows."""
    try:
        async with async_playwright() as pw:
            args = ["--disable-blink-features=AutomationControlled"]
            if window_position is not None:
                args.append(
                    f"--window-position={window_position[0]},{window_position[1]}"
                )
            if window_size is not None:
                args.append(
                    f"--window-size={window_size[0]},{window_size[1]}"
                )
            launch_kwargs: dict[str, Any] = {"headless": headless, "args": args}
            if proxy_kwargs:
                launch_kwargs["proxy"] = proxy_kwargs

            try:
                browser = await pw.chromium.launch(
                    channel="chrome", **launch_kwargs
                )
            except Exception:  # noqa: BLE001
                browser = await pw.chromium.launch(**launch_kwargs)

            try:
                context = await browser.new_context(
                    storage_state=storage_state,
                    viewport=None,
                    no_viewport=True,
                )
                await context.add_init_script(_make_stealth_script())
                page = await context.new_page()

                # Deferred Chain Navigation logic
                current_target_id = target_tweet_id
                if account_id in _CHAIN_TWEET_IDS:
                    chain_id = _CHAIN_TWEET_IDS[account_id]
                    chain_count = _CHAIN_COUNTS.get(account_id, 0)
                    if chain_count >= 10:
                        log.info(
                            f"Chain length reached 10 for account {account_id}, "
                            "resetting to original target"
                        )
                        _CHAIN_TWEET_IDS.pop(account_id, None)
                        _CHAIN_COUNTS.pop(account_id, None)
                    else:
                        current_target_id = chain_id
                        log.info(
                            f"Continuing chain for account {account_id}, "
                            f"target: {current_target_id} (Length: {chain_count})"
                        )

                # Canonical reply URL. X redirects this to the
                # handle-prefixed form once the page settles — that's fine.
                await page.goto(
                    f"https://x.com/i/web/status/{current_target_id}",
                    wait_until="domcontentloaded",
                )

                # Did the parent tweet vanish? X surfaces this as the
                # "Hmm...this page doesn't exist" stub. Bail fast so we
                # don't wait 20s for an editor that will never appear.
                gone = await _is_target_gone(page)
                if gone:
                    if account_id in _CHAIN_TWEET_IDS:
                        log.warning(f"Chain target {current_target_id} is gone, resetting chain.")
                        _CHAIN_TWEET_IDS.pop(account_id, None)
                        _CHAIN_COUNTS.pop(account_id, None)
                    return PostResult(
                        ok=False,
                        error=(
                            "โพสต์ต้นทางหายไปแล้ว — "
                            "อาจถูกลบ, ถูกซ่อน, หรือเข้าถึงไม่ได้"
                        ),
                    )

                # Same testid as the home composer ('tweetTextarea_0') —
                # X reuses the editor component for inline replies. There
                # may be multiple matches when quote tweets nest, so
                # .first picks the top-level reply box.
                editor = page.locator(
                    '[data-testid="tweetTextarea_0"], '
                    '[data-testid="tweetTextarea_0RichTextInputContainer"]'
                ).first
                try:
                    await editor.wait_for(timeout=20_000)
                except Exception:  # noqa: BLE001
                    return PostResult(
                        ok=False,
                        error=(
                            "หา reply editor ไม่เจอ — "
                            "อาจไม่มีสิทธิ์ reply โพสต์นี้"
                        ),
                    )

                # Simulate reading the tweet before replying (human behavior)
                await asyncio.sleep(random.uniform(1.2, 2.8))
                # Slight scroll — looks like reading the thread
                await page.mouse.wheel(0, random.randint(40, 150))
                await asyncio.sleep(random.uniform(0.3, 0.8))

                # Move mouse toward editor before clicking (no teleport)
                try:
                    box = await editor.bounding_box()
                    if box:
                        cx = box['x'] + box['width'] * random.uniform(0.2, 0.7)
                        cy = box['y'] + box['height'] * random.uniform(0.2, 0.8)
                        await _human_mouse_move(page, cx, cy)
                except Exception:  # noqa: BLE001
                    pass

                await editor.click()
                await asyncio.sleep(random.uniform(0.6, 1.4))  # pause before typing
                await _type_with_hashtag_parsing(page, content)
                await asyncio.sleep(random.uniform(0.6, 1.5))  # review before send

                if media_paths:
                    upload_err = await _attach_media(page, media_paths)
                    if upload_err:
                        return PostResult(ok=False, error=upload_err)

                button = page.locator(
                    '[data-testid="tweetButtonInline"]:not([aria-disabled="true"]), '
                    '[data-testid="tweetButton"]:not([aria-disabled="true"])'
                ).first
                button_timeout = 120_000 if media_paths else 20_000
                await button.wait_for(timeout=button_timeout)

                url_before_reply = page.url
                
                # Intercept CreateTweet GraphQL response to get the new tweet ID
                async def handle_response(response: Any) -> None:
                    if "CreateTweet" in response.url and response.request.method == "POST":
                        try:
                            json_data = await response.json()
                            results = (
                                json_data.get("data", {})
                                .get("create_tweet", {})
                                .get("tweet_results", {})
                                .get("result", {})
                            )
                            new_tweet_id = results.get("rest_id")
                            if not new_tweet_id:
                                tweet = results.get("tweet", {})
                                if isinstance(tweet, dict) and "rest_id" in tweet:
                                    new_tweet_id = tweet["rest_id"]
                            if new_tweet_id:
                                log.info(f"Intercepted new tweet ID for chain: {new_tweet_id}")
                                _CHAIN_TWEET_IDS[account_id] = new_tweet_id
                                _CHAIN_COUNTS[account_id] = _CHAIN_COUNTS.get(account_id, 0) + 1
                        except Exception as e:
                            log.warning(f"Error parsing CreateTweet response: {e}")

                page.on("response", handle_response)
                
                await page.keyboard.press(_POST_HOTKEY)

                _X_REPLY_PLACEHOLDERS = (
                    "post your reply",
                    "tweet your reply",
                    "what is happening",
                    "what's happening",
                )
                for _ in range(40):
                    await asyncio.sleep(0.5)
                    if await _dismiss_boost_popup(page):
                        return PostResult(ok=True)
                    err = await _check_for_error(page)
                    if err:
                        return PostResult(ok=False, error=err)
                    if page.url != url_before_reply:
                        return PostResult(ok=True)
                    try:
                        if not await editor.is_visible(timeout=100):
                            return PostResult(ok=True)
                    except Exception:  # noqa: BLE001
                        return PostResult(ok=True)
                    try:
                        text = (
                            await editor.inner_text(timeout=100)
                        ) or ""
                        stripped = text.strip().lower()
                        if stripped == "" or any(
                            ph in stripped for ph in _X_REPLY_PLACEHOLDERS
                        ):
                            return PostResult(ok=True)
                    except Exception:  # noqa: BLE001
                        pass

                final_err = await _check_for_error(page)
                if final_err:
                    return PostResult(ok=False, error=final_err)
                if page.url != url_before_reply:
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
                    ph in final_stripped for ph in _X_REPLY_PLACEHOLDERS
                ):
                    return PostResult(
                        ok=False,
                        error=(
                            "X ไม่ได้รับ reply (กล่องเขียนยังมีเนื้อหาเดิม) · "
                            "อาจเป็นเนื้อหาซ้ำ, ติด rate limit, หรือบัญชีถูกจำกัด"
                        ),
                    )
                return PostResult(ok=True)
            finally:
                try:
                    await browser.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception as e:  # noqa: BLE001
        log.exception("_do_reply failed")
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
            "โพสต์นี้ไม่สามารถใช้งานได้",
            "โพสต์นี้มาจากบัญชีที่ไม่มีอยู่",
            "ไม่มีหน้าเว็บนี้",
        ):
            if phrase in lowered:
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def _dismiss_boost_popup(page: Any) -> bool:
    """Dismiss the 'Subscribe to Premium and boost your responses' popup.
    Returns True if popup was found and dismissed (indicating the post succeeded)."""
    try:
        # Match "Maybe later" in English, Thai, Japanese, etc.
        loc = page.locator('button, [role="button"]').filter(
            has_text=re.compile(r"maybe later|ไว้คราวหลัง|ไว้ทีหลัง|ไม่ใช่ตอนนี้|อาจจะภายหลัง|後で|Talvez mais tarde|Später", re.IGNORECASE)
        ).first
        if await loc.is_visible(timeout=100):
            await loc.click(timeout=100)
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

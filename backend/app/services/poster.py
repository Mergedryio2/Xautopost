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

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


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
class _ReplySession:
    """One persistent Chromium per account for the reply slot. Launched on
    the first reply and kept open between replies so the rotation doesn't
    pay a full browser start (plus a fresh fingerprint) per post. Torn
    down by the scheduler via close_session() when the account is stopped
    or hits its post cap, or by _do_reply itself when the browser dies.

    `busy` is True while a reply is driving the page. close_session()
    called during that window only sets `close_requested`; the teardown
    then happens in _do_reply's finally so we never yank the browser out
    from under a half-typed reply. The record is inserted into
    _REPLY_SESSIONS *before* the launch awaits, so a stop that lands
    mid-launch is still honoured once the launch completes.

    `signature` captures launch inputs (proxy, headless). When it differs
    on the next reply (user switched the account's proxy) the old browser
    is discarded and relaunched rather than silently reusing the old
    route."""

    signature: tuple[Any, ...]
    pw: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None
    busy: bool = False
    close_requested: bool = False

    def alive(self) -> bool:
        return (
            self.browser is not None
            and self.browser.is_connected()
            and self.page is not None
            and not self.page.is_closed()
        )


_REPLY_SESSIONS: dict[int, _ReplySession] = {}


def has_reply_session(account_id: int) -> bool:
    return account_id in _REPLY_SESSIONS


def reply_session_account_ids() -> list[int]:
    return list(_REPLY_SESSIONS)


async def _teardown_reply_session(session: _ReplySession) -> None:
    for closer in (
        session.browser.close if session.browser is not None else None,
        session.pw.stop if session.pw is not None else None,
    ):
        if closer is None:
            continue
        try:
            await closer()
        except Exception:  # noqa: BLE001
            pass
    session.pw = session.browser = session.context = session.page = None


async def close_session(account_id: int) -> None:
    """Close the persistent reply browser for an account. Safe to call when
    none is open. If a reply is mid-flight the close is deferred until that
    reply finishes (see _ReplySession.busy)."""
    session = _REPLY_SESSIONS.get(account_id)
    if session is None:
        return
    if session.busy:
        session.close_requested = True
        log.info(
            "reply session for account %d busy — closing after current reply",
            account_id,
        )
        return
    _REPLY_SESSIONS.pop(account_id, None)
    log.info("closing reply session for account %d", account_id)
    await _teardown_reply_session(session)


async def close_all_sessions() -> None:
    """Sidecar shutdown hook — close every persistent reply browser."""
    for account_id in list(_REPLY_SESSIONS):
        await close_session(account_id)


async def _acquire_reply_session(
    account_id: int,
    storage_state: dict[str, Any],
    proxy_kwargs: dict[str, str] | None,
    window_position: tuple[int, int] | None,
    window_size: tuple[int, int] | None,
    headless: bool,
) -> _ReplySession:
    """Return the account's persistent reply browser, launching one when
    there is none, the previous one died (user closed the window, Chrome
    crashed), or the launch signature changed. Marks the session busy;
    the caller must release it via _release_reply_session()."""
    signature: tuple[Any, ...] = (
        tuple(sorted(proxy_kwargs.items())) if proxy_kwargs else None,
        headless,
    )
    session = _REPLY_SESSIONS.get(account_id)
    if session is not None and session.busy:
        # Scheduler guarantees one reply per account at a time; if we get
        # here anyway something upstream double-booked — fail loudly
        # rather than share a page between two flows.
        raise RuntimeError(
            f"reply session for account {account_id} is already in use"
        )
    if session is not None and (
        not session.alive() or session.signature != signature
    ):
        _REPLY_SESSIONS.pop(account_id, None)
        await _teardown_reply_session(session)
        session = None

    if session is not None:
        session.busy = True
        session.close_requested = False
        return session

    session = _ReplySession(signature=signature, busy=True)
    # Register before the launch awaits so a close_session() arriving
    # mid-launch is picked up by the finally in _do_reply.
    _REPLY_SESSIONS[account_id] = session
    try:
        args = ["--disable-blink-features=AutomationControlled"]
        if window_position is not None:
            args.append(
                f"--window-position={window_position[0]},{window_position[1]}"
            )
        if window_size is not None:
            args.append(f"--window-size={window_size[0]},{window_size[1]}")
        launch_kwargs: dict[str, Any] = {"headless": headless, "args": args}
        if proxy_kwargs:
            launch_kwargs["proxy"] = proxy_kwargs

        session.pw = await async_playwright().start()
        try:
            session.browser = await session.pw.chromium.launch(
                channel="chrome", **launch_kwargs
            )
        except Exception:  # noqa: BLE001
            session.browser = await session.pw.chromium.launch(**launch_kwargs)
        session.context = await session.browser.new_context(
            storage_state=storage_state,
            viewport=None,
            no_viewport=True,
        )
        await session.context.add_init_script(_make_stealth_script())
        session.page = await session.context.new_page()
    except Exception:
        _REPLY_SESSIONS.pop(account_id, None)
        await _teardown_reply_session(session)
        raise
    log.info("launched persistent reply session for account %d", account_id)
    return session


async def _release_reply_session(
    account_id: int, session: _ReplySession, *, discard: bool
) -> None:
    """Hand the browser back after a reply. `discard=True` (browser died
    or Playwright threw) closes it so the next reply relaunches clean."""
    session.busy = False
    if discard or session.close_requested or not session.alive():
        if _REPLY_SESSIONS.get(account_id) is session:
            _REPLY_SESSIONS.pop(account_id, None)
        await _teardown_reply_session(session)


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


async def _paste_content(page: Any, content: str) -> None:
    """Insert content in one shot via a synthetic clipboard paste event,
    instead of driving the keyboard character-by-character. Near-instant
    compared to `_type_with_hashtag_parsing`.

    Deliberately does NOT go through the OS clipboard (`navigator.clipboard`
    + Ctrl/Cmd+V): the scheduler can run several Chromium windows in
    parallel on one machine (see `parallel_posts`), and the OS clipboard is
    one global resource shared by all of them — two tasks writing to it
    around the same time would race, and account A could end up posting
    account B's text. Building the ClipboardEvent in-page and dispatching it
    straight on the focused editor keeps every session's paste isolated,
    with no shared state between concurrent browsers.

    Note: unlike the typing path, this fires a single paste event for the
    whole string, so it relies entirely on X's own paste handler to
    tokenize `#hashtags` into searchable links — that behavior hasn't been
    verified against the hashtag-feed issue the typing path was built to
    fix, so compare the two modes in practice before relying on paste for
    hashtag-heavy content."""
    await page.evaluate(
        """(text) => {
            const el = document.activeElement;
            if (!el) return;
            const dt = new DataTransfer();
            dt.setData('text/plain', text);
            const event = new ClipboardEvent('paste', {
                clipboardData: dt,
                bubbles: true,
                cancelable: true,
            });
            el.dispatchEvent(event);
        }""",
        content,
    )


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
    typing_mode: str = "simulate",
) -> PostResult:
    """Restore the X account session and post a tweet. Logs to post_logs.
    `media_paths` is an ordered list of files to attach (max 4 images, OR 1
    video — X rejects mixed combinations and posts beyond those caps).
    `window_position` and `window_size` pin the Chromium window to a fixed
    spot — used by the parallel scheduler to tile concurrent posts in a
    deterministic grid instead of letting them stack at the OS default.
    `typing_mode` is 'simulate' (character-by-character, the original
    behavior) or 'paste' (single instant paste event) — see
    `_type_with_hashtag_parsing` / `_paste_content`."""
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
        typing_mode=typing_mode,
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
    typing_mode: str = "simulate",
    pace_seconds: float = 10.0,
) -> PostResult:
    """Reply to a specific tweet. Navigates to
    https://x.com/i/web/status/{id}, opens the inline reply composer, types,
    and submits via the Cmd/Ctrl+Enter hotkey. Every reply lands directly
    under `target_tweet_id` (the main post) — never under the account's
    own previous reply. The result is logged with reply_to_tweet_id so
    the scheduler can enforce per-target reply caps. `typing_mode` — see
    `post_tweet`. `pace_seconds` is the account's configured gap between
    posts; the human-like pauses inside the flow shrink to fit it (see
    _do_reply) so a 1s interval isn't padded to 10s by reading/review
    delays."""
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
        typing_mode=typing_mode,
        pace_seconds=pace_seconds,
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
    typing_mode: str = "simulate",
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
                # See _do_reply: read text from the contenteditable, not the
                # container, so the locale-specific placeholder never counts
                # as "content".
                textarea = page.locator('[data-testid="tweetTextarea_0"]').first
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
                if typing_mode == "paste":
                    await _paste_content(page, content)
                else:
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
                #   3. contenteditable (tweetTextarea_0) inner_text is empty
                # Failure signal: explicit error toast/alert.
                # We use inner_text() (not text_content()) because X's
                # contenteditable keeps non-text DOM nodes even when visually
                # empty; text_content() returns those, inner_text() doesn't.
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
                            await textarea.inner_text(timeout=100)
                        ) or ""
                        if text.strip() == "":
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
                        await textarea.inner_text(timeout=200)
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
    typing_mode: str = "simulate",
    pace_seconds: float = 10.0,
) -> PostResult:
    """Reply flow. Navigates directly to the target tweet status page, opens
    the inline reply composer, types, and submits. Drives the account's
    persistent reply browser (see _ReplySession) — launched on the first
    reply, reused for every following one, and closed only by the
    scheduler (account stopped / post cap reached) or when Chrome dies.

    Pacing: the "human" pauses (read the tweet, scroll, hover, review
    before send) are scaled by `pace_seconds` — full length at ≥10s, gone
    at ≤1s — so the wall-clock gap between replies tracks the account's
    interval setting instead of being padded by fixed sleeps. When the
    persistent page is already sitting on the target post with an empty
    composer (same target as last time) the navigation is skipped too."""
    try:
        session = await _acquire_reply_session(
            account_id,
            storage_state,
            proxy_kwargs,
            window_position,
            window_size,
            headless,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("_do_reply: browser launch failed")
        return PostResult(ok=False, error=str(e))
    page = session.page
    assert page is not None
    discard = False
    # 0.0 at pace ≤ 1s, 1.0 at pace ≥ 10s, linear between.
    pause_scale = min(1.0, max(0.0, (pace_seconds - 1.0) / 9.0))

    async def pause(lo: float, hi: float) -> None:
        if pause_scale > 0.0:
            await asyncio.sleep(random.uniform(lo, hi) * pause_scale)

    try:
        # Same testid as the home composer ('tweetTextarea_0') —
        # X reuses the editor component for inline replies. There
        # may be multiple matches when quote tweets nest, so
        # .first picks the top-level reply box.
        editor = page.locator(
            '[data-testid="tweetTextarea_0"], '
            '[data-testid="tweetTextarea_0RichTextInputContainer"]'
        ).first
        # Text checks read the contenteditable itself, not the container:
        # the container also holds the placeholder ("Post your reply" /
        # "โพสต์การตอบกลับของคุณ" / …), so its inner_text is never empty and
        # an emptiness test on it is language-dependent. The contenteditable
        # is "" once X clears it after a successful send, in every locale.
        textarea = page.locator('[data-testid="tweetTextarea_0"]').first
        # Persistent page already parked on this post with an empty
        # composer (previous reply went to the same target)? Skip the
        # navigation entirely. Anything else (different target, user
        # navigated, X bounced us) goes through _open_status_page.
        on_target = False
        if f"/status/{target_tweet_id}" in page.url:
            try:
                on_target = (
                    await textarea.is_visible(timeout=500)
                    and not (await textarea.inner_text(timeout=500)).strip()
                )
            except Exception:  # noqa: BLE001
                on_target = False
        if not on_target:
            nav_err = await _open_status_page(page, target_tweet_id)
            if nav_err is not None:
                return nav_err

        # Anything left over from the previous reply (the "want more
        # people to see your reply?" Premium upsell, etc.) would sit on
        # top of the composer and swallow the click.
        await _dismiss_boost_popup(page)

        # Simulate reading the tweet before replying (human behavior)
        await pause(0.2, 1.2)
        if pause_scale > 0.0:
            # Slight scroll — looks like reading the thread
            await page.mouse.wheel(0, random.randint(40, 150))
            await pause(0.3, 0.8)
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
        await pause(0.6, 1.4)  # pause before typing
        if typing_mode == "paste":
            await _paste_content(page, content)
        else:
            await _type_with_hashtag_parsing(page, content)
        await pause(0.6, 1.5)  # review before send

        if media_paths:
            upload_err = await _attach_media(page, media_paths)
            if upload_err:
                return PostResult(ok=False, error=upload_err)

        button = page.locator(
            '[data-testid="tweetButtonInline"]:not([aria-disabled="true"]), '
            '[data-testid="tweetButton"]:not([aria-disabled="true"])'
        ).first
        button_timeout = 120_000 if media_paths else 5_000
        await button.wait_for(timeout=button_timeout)

        url_before_reply = page.url

        await page.keyboard.press(_POST_HOTKEY)

        for _ in range(100):
            await asyncio.sleep(0.2)
            if await _dismiss_boost_popup(page):
                return await _reply_ok(page)
            err = await _check_for_error(page)
            if err:
                return PostResult(ok=False, error=err)
            if page.url != url_before_reply:
                return await _reply_ok(page)
            try:
                if not await editor.is_visible(timeout=100):
                    return await _reply_ok(page)
            except Exception:  # noqa: BLE001
                return await _reply_ok(page)
            try:
                text = (
                    await textarea.inner_text(timeout=100)
                ) or ""
                if text.strip() == "":
                    return await _reply_ok(page)
            except Exception:  # noqa: BLE001
                pass

        final_err = await _check_for_error(page)
        if final_err:
            return PostResult(ok=False, error=final_err)
        if page.url != url_before_reply:
            return await _reply_ok(page)
        try:
            final_visible = await editor.is_visible(timeout=200)
        except Exception:  # noqa: BLE001
            return await _reply_ok(page)
        if not final_visible:
            return await _reply_ok(page)
        try:
            final_text = (
                await textarea.inner_text(timeout=200)
            ) or ""
        except Exception:  # noqa: BLE001
            return await _reply_ok(page)
        if final_text.strip():
            return PostResult(
                ok=False,
                error=(
                    "X ไม่ได้รับ reply (กล่องเขียนยังมีเนื้อหาเดิม) · "
                    "อาจเป็นเนื้อหาซ้ำ, ติด rate limit, หรือบัญชีถูกจำกัด"
                ),
            )
        return await _reply_ok(page)
    except Exception as e:  # noqa: BLE001
        log.exception("_do_reply failed")
        # Unknown Playwright state — drop the browser so the next reply
        # starts from a clean launch instead of a wedged page.
        discard = True
        return PostResult(ok=False, error=str(e))
    finally:
        await _release_reply_session(account_id, session, discard=discard)



async def _is_target_gone(page) -> bool:  # type: ignore[no-untyped-def]
    """X renders a "this page doesn't exist" / "post unavailable" stub when
    the target tweet was deleted. Cheap probe — 1.5s ceiling — because we
    don't want to delay the common success path."""
    # 'empty_state' is X's testid for the deleted/unavailable stub.
    try:
        loc = page.locator('[data-testid="empty_state_header_text"]').first
        if await loc.is_visible(timeout=100):
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
            "hmm... this page doesn",
            "post unavailable",
            "this post was deleted",
            "this post is unavailable",
            "โพสต์นี้ไม่สามารถใช้งานได้",
            "โพสต์นี้มาจากบัญชีที่ไม่มีอยู่",
            "ไม่มีหน้าเว็บนี้",
            "ไม่พบหน้าที่คุณต้องการ",
        ):
            if phrase in lowered:
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


_STATUS_EDITOR_SEL = (
    '[data-testid="tweetTextarea_0"], '
    '[data-testid="tweetTextarea_0RichTextInputContainer"]'
)
# X's "this post is unavailable" stub (empty_state_header_text) and the
# generic "Hmm... this page doesn't exist" route error (error-detail).
_GONE_SEL = '[data-testid="empty_state_header_text"], [data-testid="error-detail"]'
_GONE_RESULT = PostResult(
    ok=False,
    error="โพสต์ต้นทางหายไปแล้ว — อาจถูกลบ, ถูกซ่อน, หรือเข้าถึงไม่ได้",
)
_NO_EDITOR_RESULT = PostResult(
    ok=False,
    error="หา reply editor ไม่เจอ — อาจไม่มีสิทธิ์ reply โพสต์นี้",
)


def _focal_sel(tweet_id: str) -> str:
    """The focal tweet on a status page is the one article X marks
    tabindex=-1 (parents above it and replies below are tabindex=0). Its
    timestamp link carries the tweet id, so this only matches once the
    *target* post is rendered — not a stale article from the previous
    page."""
    return (
        f'article[data-testid="tweet"][tabindex="-1"] '
        f'a[href*="/status/{tweet_id}"] time'
    )


async def _open_status_page(page: Any, tweet_id: str) -> PostResult | None:
    """Bring the persistent page to /status/{tweet_id} with the reply
    editor mounted. Returns None on success or the PostResult to bail
    with.

    Fast path: when the page is already on x.com, push the new route
    into history and fire popstate — X's client router picks it up and
    swaps the status view in place (~0.8s cold, ~0.05s when X has the
    tweet cached) instead of a full reload that re-boots the whole app
    (~2-5s). Falls back to page.goto when the route change doesn't
    render the target within a few seconds."""
    target_or_gone = page.locator(f"{_focal_sel(tweet_id)}, {_GONE_SEL}").first
    swapped = False
    if "://x.com/" in page.url or "://twitter.com/" in page.url:
        try:
            await page.evaluate(
                "(u) => { history.pushState({}, '', u);"
                " dispatchEvent(new PopStateEvent('popstate', {state: {}})); }",
                f"/i/web/status/{tweet_id}",
            )
            await target_or_gone.wait_for(timeout=5_000)
            swapped = True
        except Exception:  # noqa: BLE001
            swapped = False
    if not swapped:
        await page.goto(
            f"https://x.com/i/web/status/{tweet_id}", wait_until="commit"
        )
        try:
            await target_or_gone.wait_for(timeout=20_000)
        except Exception:  # noqa: BLE001
            if await _is_target_gone(page):
                return _GONE_RESULT
            return _NO_EDITOR_RESULT
    try:
        stub = page.locator(_GONE_SEL).first
        if await stub.is_visible(timeout=100):
            if await _is_target_gone(page):
                return _GONE_RESULT
            # error-detail that isn't a "doesn't exist" copy — e.g. X's
            # "something went wrong, try reloading". Surface it verbatim
            # rather than misreporting the post as deleted.
            text = ((await stub.inner_text(timeout=200)) or "").strip()
            return PostResult(
                ok=False, error=f"X แสดงข้อผิดพลาด: {text[:120]}"
            )
    except Exception:  # noqa: BLE001
        pass
    try:
        await page.locator(_STATUS_EDITOR_SEL).first.wait_for(timeout=5_000)
    except Exception:  # noqa: BLE001
        if await _is_target_gone(page):
            return _GONE_RESULT
        return _NO_EDITOR_RESULT
    return None


async def _reply_ok(page: Any) -> PostResult:
    """Success wrap-up for a persistent reply page. X pops the "want more
    people to see your reply?" Premium sheet a beat after the send goes
    through; with a fresh browser per reply it died with the window, but
    a parked page would keep it on screen and it would swallow the next
    composer click. Sweep for it briefly, then hand back success."""
    deadline = asyncio.get_running_loop().time() + 1.0
    while asyncio.get_running_loop().time() < deadline:
        if await _dismiss_boost_popup(page):
            break
        await asyncio.sleep(0.1)
    return PostResult(ok=True)


# "Maybe later" / "Not now" in the locales X ships. Substring match, so
# "ทีหลัง" also covers "ไว้ทีหลัง", "later" covers "Maybe later", etc.
_LATER_BUTTON_RE = re.compile(
    r"maybe later|not now|later|"
    r"ไว้คราวหลัง|ไว้ทีหลัง|ทีหลัง|ภายหลัง|ไม่ใช่ตอนนี้|ไว้ก่อน|"
    r"後で|あとで|Talvez mais tarde|Später|Más tarde|Plus tard",
    re.IGNORECASE,
)
# Copy that identifies the Premium reply-boost sheet even when its
# dismiss button uses wording we don't know yet.
_BOOST_DIALOG_RE = re.compile(
    r"see your repl|boost|premium|เห็นการตอบกลับ|พรีเมียม",
    re.IGNORECASE,
)


async def _dismiss_boost_popup(page: Any) -> bool:
    """Dismiss the 'Want more people to see your reply? Subscribe to
    Premium' sheet. Returns True if a sheet was found and dismissed
    (which also means the reply went through — X only shows it after a
    successful send). Order: the sheet's own "Maybe later" button (any
    known locale) → its close button → Escape."""
    try:
        dialog = page.locator('[role="dialog"], [data-testid="sheetDialog"]').first
        if not await dialog.is_visible(timeout=100):
            return False
        later = dialog.locator('button, [role="button"]').filter(
            has_text=_LATER_BUTTON_RE
        ).first
        if await later.is_visible(timeout=100):
            await later.click(timeout=1_000)
            return True
        text = (await dialog.inner_text(timeout=200)) or ""
        if not _BOOST_DIALOG_RE.search(text):
            return False
        close = dialog.locator(
            '[data-testid="app-bar-close"], [aria-label="Close"], [aria-label="ปิด"]'
        ).first
        if await close.is_visible(timeout=100):
            await close.click(timeout=1_000)
            return True
        await page.keyboard.press("Escape")
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

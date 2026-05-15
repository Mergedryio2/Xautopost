"""Playwright scraper that walks an X account's profile timeline and indexes
the user's own tweets into TweetIndex. The reply-mode prompts pick targets
out of this index, so accuracy + freshness matters more than completeness —
X caps profile timeline at ~3,200 tweets anyway, so deep history is a lost
cause and we don't try to work around it.

The scan runs headless and is fire-and-forget from the API's perspective:
POST /accounts/{id}/scan-tweets spawns a background task tracked by
ScanManager, and the UI polls GET /accounts/{id}/scan-status for progress.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from playwright.async_api import Page, async_playwright
from sqlalchemy import select

from app.core.crypto import get_crypto
from app.db.database import SessionLocal
from app.db.models import Proxy, TweetIndex, XAccount
from app.db.utils import utcnow

log = logging.getLogger(__name__)

# Max consecutive scrolls that surface no new tweet ids before we conclude
# the timeline is exhausted. X loads incrementally; sometimes a single scroll
# pulls nothing because the network request is in flight, so 1-2 isn't a
# reliable signal but 4 in a row is.
_END_OF_TIMELINE_THRESHOLD = 4

# Hard cap on scroll iterations. With X's ~3,200 visible tweet cap and
# roughly 5-10 tweets per scroll, ~400 scrolls is more than enough. The
# cap is a safety net against infinite loops if the page never settles.
_MAX_SCROLL_ITERATIONS = 400

# Hard wallclock timeout for the whole scan. Above the loop iteration cap
# so a slow network can use the time, but bounded enough that a hung scan
# doesn't pile up forever.
_SCAN_TIMEOUT_SEC = 600

# How long to wait after each scroll for new tweets to render. Shorter is
# faster but skips tweets when the network is slow; longer is wasteful when
# the network is quick. 800ms is the sweet spot in testing.
_SCROLL_SETTLE_MS = 800

_TWEET_ID_RE = re.compile(r"/status/(\d+)")


@dataclass
class ScanTask:
    """In-memory handle for a running scan. ScanManager exposes status to
    the API; the actual progress is also persisted on XAccount so the UI
    can survive a sidecar restart mid-scan."""

    account_id: int
    status: str = "running"  # 'running' | 'success' | 'error'
    tweets_collected: int = 0
    error: str | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    bg_task: asyncio.Task[Any] | None = None


class ScanManager:
    """One scan per account at most. Starting a second scan while one is
    running returns the existing task — re-scanning during a scan is
    pointless and the duplicate Chromium would just compete for the same
    storage_state file lock."""

    def __init__(self) -> None:
        self._tasks: dict[int, ScanTask] = {}

    def get(self, account_id: int) -> ScanTask | None:
        return self._tasks.get(account_id)

    def start(self, account_id: int) -> ScanTask:
        # Don't return an existing task unless its bg_task actually exists —
        # a previous start() that failed mid-flight (e.g. create_task raised
        # because the endpoint was sync and ran without a loop) leaves a
        # phantom ScanTask in status='running' with bg_task=None. Treating
        # that as "still running" would lock the user out of retrying.
        existing = self._tasks.get(account_id)
        if (
            existing is not None
            and existing.status == "running"
            and existing.bg_task is not None
            and not existing.bg_task.done()
        ):
            return existing

        task = ScanTask(account_id=account_id)
        self._tasks[account_id] = task
        try:
            task.bg_task = asyncio.create_task(self._run(task))
        except RuntimeError:
            # No running event loop (e.g. caller is a sync FastAPI endpoint
            # invoked in a threadpool worker). Drop the half-built entry so
            # the caller's next attempt can start fresh, and surface the
            # underlying error rather than silently leaving a ghost task.
            self._tasks.pop(account_id, None)
            raise
        return task

    def cancel(self, account_id: int) -> bool:
        task = self._tasks.get(account_id)
        if task is None or task.status != "running":
            return False
        task.cancel_event.set()
        return True

    async def _run(self, task: ScanTask) -> None:
        _set_account_scan_status(task.account_id, "running", error=None)
        try:
            count = await asyncio.wait_for(
                _scan_account(task), timeout=_SCAN_TIMEOUT_SEC
            )
            task.tweets_collected = count
            task.status = "success"
            _set_account_scan_status(
                task.account_id, "idle", count=count, completed=True
            )
        except asyncio.TimeoutError:
            task.status = "error"
            task.error = f"scan timeout after {_SCAN_TIMEOUT_SEC}s"
            _set_account_scan_status(
                task.account_id, "error", error=task.error
            )
        except Exception as e:  # noqa: BLE001
            log.exception("tweet scan failed for account %s", task.account_id)
            task.status = "error"
            task.error = str(e)
            _set_account_scan_status(
                task.account_id, "error", error=str(e)[:500]
            )


scan_manager = ScanManager()


def _load_account(
    account_id: int,
) -> tuple[dict[str, Any] | None, dict[str, str] | None, str | None]:
    """Decrypt and return (storage_state, proxy_kwargs, handle) for the
    account, or (None, None, None) if the account/session is missing.
    Mirrors poster._load_account_state but also surfaces the handle so the
    scraper can navigate to the right profile URL."""
    crypto = get_crypto()
    with SessionLocal() as db:
        acc = db.get(XAccount, account_id)
        if acc is None or acc.storage_state_enc is None or not acc.handle:
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


def _set_account_scan_status(
    account_id: int,
    status: str,
    *,
    count: int | None = None,
    error: str | None = None,
    completed: bool = False,
) -> None:
    with SessionLocal() as db:
        acc = db.get(XAccount, account_id)
        if acc is None:
            return
        acc.scan_status = status
        if error is not None:
            acc.scan_error = error
        elif status != "error":
            # Clear stale error when we start a new run or finish cleanly.
            acc.scan_error = None
        if count is not None:
            acc.scanned_tweet_count = count
        if completed:
            acc.last_scan_at = utcnow()
        db.commit()


async def _scan_account(task: ScanTask) -> int:
    state, proxy_kwargs, handle = _load_account(task.account_id)
    if state is None or not handle:
        raise RuntimeError("ยังไม่มี session ของบัญชี — login ก่อนแล้วค่อย scan")

    handle_lower = handle.lstrip("@").lower()

    async with async_playwright() as pw:
        launch_kwargs: dict[str, Any] = {
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if proxy_kwargs:
            launch_kwargs["proxy"] = proxy_kwargs

        try:
            browser = await pw.chromium.launch(channel="chrome", **launch_kwargs)
        except Exception:  # noqa: BLE001
            browser = await pw.chromium.launch(**launch_kwargs)

        try:
            context = await browser.new_context(storage_state=state)
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', "
                "{ get: () => undefined })"
            )
            page = await context.new_page()

            await page.goto(
                f"https://x.com/{handle_lower}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            # Bail loudly if the session expired — re-scan would just shadow
            # all tweets as 'deleted' since we'd index zero rows.
            try:
                await page.locator(
                    'article[data-testid="tweet"]'
                ).first.wait_for(timeout=20_000)
            except Exception:  # noqa: BLE001
                # Could be login wall, empty profile, or layout change. The
                # SideNav button distinguishes login state from empty profile.
                nav = page.locator('[data-testid="SideNav_NewTweet_Button"]')
                if not await nav.count():
                    raise RuntimeError(
                        "session หมดอายุหรือ X เปลี่ยน layout — "
                        "ลอง login บัญชีนี้ใหม่อีกครั้ง"
                    ) from None
                # Profile is logged-in but empty/no tweets — that's a valid
                # zero-tweet result, not an error.
                return _commit_scan_result(task.account_id, {}, handle_lower)

            seen_ids: dict[str, dict[str, Any]] = {}
            stagnant_scrolls = 0

            for _ in range(_MAX_SCROLL_ITERATIONS):
                if task.cancel_event.is_set():
                    break

                new_count = await _collect_visible_tweets(
                    page, seen_ids, handle_lower
                )
                task.tweets_collected = len(seen_ids)
                # Periodic checkpoint so a crash mid-scan still leaves a
                # partial index rather than rolling back everything.
                if len(seen_ids) and len(seen_ids) % 100 == 0:
                    _commit_scan_result(
                        task.account_id, seen_ids, handle_lower, partial=True
                    )

                if new_count == 0:
                    stagnant_scrolls += 1
                    if stagnant_scrolls >= _END_OF_TIMELINE_THRESHOLD:
                        break
                else:
                    stagnant_scrolls = 0

                # Scroll by 80% of viewport so the next batch overlaps the
                # previous — guards against missing tweets that straddle the
                # fold when X's virtualizer recycles DOM nodes.
                await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
                await page.wait_for_timeout(_SCROLL_SETTLE_MS)

            return _commit_scan_result(task.account_id, seen_ids, handle_lower)
        finally:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass


async def _collect_visible_tweets(
    page: Page,
    seen_ids: dict[str, dict[str, Any]],
    expected_handle: str,
) -> int:
    """Parse currently-rendered articles and add any unseen ids to seen_ids.
    Returns the number of newly added ids. Tweets authored by other users
    (retweets) are kept but flagged is_retweet=True so reply mode can skip
    them — replying to a retweeted post replies to the *original* author,
    which is not what 'reply to my own posts' means."""
    articles = page.locator('article[data-testid="tweet"]')
    count = await articles.count()
    added = 0

    for i in range(count):
        art = articles.nth(i)
        try:
            data = await _extract_tweet_data(art, expected_handle)
        except Exception:  # noqa: BLE001
            continue
        if data is None:
            continue
        tid = data["tweet_id"]
        if tid in seen_ids:
            # Keep the earlier sighting's pinned flag — pinned is only
            # detected on the first occurrence at the top of the timeline.
            if seen_ids[tid].get("is_pinned"):
                data["is_pinned"] = True
            # But update the rest in case scroll surfaced more info.
            seen_ids[tid].update(data)
            continue
        seen_ids[tid] = data
        added += 1

    return added


async def _extract_tweet_data(
    article, expected_handle: str  # noqa: ANN001
) -> dict[str, Any] | None:
    # The first /status/<id> link inside the article is the tweet permalink.
    # Quote tweets nest a second article — we only read the outer one.
    link = article.locator('a[href*="/status/"]').first
    href = await link.get_attribute("href", timeout=500)
    if not href:
        return None
    m = _TWEET_ID_RE.search(href)
    if not m:
        return None
    tweet_id = m.group(1)
    # Author handle sits in the link's path before /status/.
    author = href.lstrip("/").split("/status/")[0].lower()

    # Promoted tweets show in profile timeline too; skip them — they're not
    # ours and replying loops back to the advertiser's tweet.
    is_promoted = False
    try:
        is_promoted = await article.locator(
            'div[data-testid="placementTracking"]'
        ).count() > 0
    except Exception:  # noqa: BLE001
        pass
    if is_promoted:
        return None

    # X marks reposts with a "reposted" indicator at the top of the tweet
    # block ("You reposted" / "{handle} reposted").
    is_retweet = False
    try:
        is_retweet = await article.locator(
            '[data-testid="socialContext"]'
        ).count() > 0
    except Exception:  # noqa: BLE001
        pass

    # Authored by us? When is_retweet is True the author handle in the link
    # is the *original* poster, not us — so we can't infer ownership from
    # the link alone; we need a more direct check. The default Posts tab
    # only shows our own posts + our reposts, so falling through to "not
    # ours" is rare unless X added a new layout case.
    is_own = (author == expected_handle) and not is_retweet

    # Pinned banner sits above the tweet, only on the first occurrence at
    # the top of the timeline. We capture it at index time.
    is_pinned = False
    try:
        # X labels the pinned banner via a "Pinned" text node inside the
        # socialContext slot on the pinned tweet specifically.
        ctx_text = await article.locator(
            '[data-testid="socialContext"]'
        ).first.text_content(timeout=200)
        if ctx_text and "pin" in ctx_text.lower():
            is_pinned = True
            is_retweet = False  # pinned and retweet share the slot
    except Exception:  # noqa: BLE001
        pass

    # is_reply: the Posts tab generally hides replies to others, but it
    # does show our self-replies (threads). We detect "Replying to" via the
    # tweetText link's preceding sibling. Cheap heuristic — false negatives
    # are tolerable since reply mode targets non-reply tweets anyway.
    is_reply = False
    try:
        is_reply = await article.locator(
            'div:has-text("Replying to")'
        ).count() > 0
    except Exception:  # noqa: BLE001
        pass

    text_preview: str | None = None
    try:
        text_preview = (
            await article.locator('[data-testid="tweetText"]')
            .first.inner_text(timeout=500)
        )[:500]
    except Exception:  # noqa: BLE001
        text_preview = None

    has_media = False
    try:
        # Image / video / GIF / card all attach to the tweet through one of
        # these testids; presence of any of them is enough.
        for sel in (
            '[data-testid="tweetPhoto"]',
            'video',
            '[data-testid="card.wrapper"]',
        ):
            if await article.locator(sel).count() > 0:
                has_media = True
                break
    except Exception:  # noqa: BLE001
        pass

    posted_at: datetime | None = None
    try:
        dt = await article.locator("time").first.get_attribute(
            "datetime", timeout=500
        )
        if dt:
            posted_at = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        pass

    # We index retweets and replies too, but flag them so the UI can hide
    # them by default in the reply-target picker. Promoted / non-own tweets
    # are filtered out upstream.
    return {
        "tweet_id": tweet_id,
        "url": f"https://x.com/{expected_handle}/status/{tweet_id}",
        "text_preview": text_preview,
        "has_media": has_media,
        "is_reply": is_reply,
        "is_retweet": is_retweet,
        "is_pinned": is_pinned,
        "is_own": is_own,
        "posted_at": posted_at,
    }


def _commit_scan_result(
    account_id: int,
    seen: dict[str, dict[str, Any]],
    expected_handle: str,
    *,
    partial: bool = False,
) -> int:
    """Upsert all seen tweets into TweetIndex and mark vanished ones deleted.
    Returns the count of tweets currently belonging to the account.
    Skipping non-own tweets here keeps the index small and avoids the case
    where the user picks a retweet as a reply target (which would reply to
    the *original* author's tweet on X). Partial mode skips the
    deleted-detection step because the scan isn't done — we'd false-mark
    everything below the current scroll position."""
    now = utcnow()
    fresh_ids: set[str] = set()

    with SessionLocal() as db:
        existing_rows = list(
            db.scalars(
                select(TweetIndex).where(TweetIndex.x_account_id == account_id)
            ).all()
        )
        by_id = {r.tweet_id: r for r in existing_rows}

        for tid, data in seen.items():
            if not data.get("is_own"):
                # Skip non-own; we still need fresh_ids to cover restored
                # own-tweets that come back after a delete-then-restore, so
                # only add own-tweet ids here.
                continue
            fresh_ids.add(tid)
            row = by_id.get(tid)
            if row is None:
                row = TweetIndex(
                    x_account_id=account_id,
                    tweet_id=tid,
                    url=data["url"],
                    text_preview=data.get("text_preview"),
                    has_media=bool(data.get("has_media")),
                    is_reply=bool(data.get("is_reply")),
                    is_retweet=bool(data.get("is_retweet")),
                    is_pinned=bool(data.get("is_pinned")),
                    posted_at=data.get("posted_at"),
                    scraped_at=now,
                    deleted_at=None,
                )
                db.add(row)
            else:
                # Refresh in case the user edited the tweet (X allows
                # short-window edits) or pin state changed.
                row.url = data["url"]
                if data.get("text_preview"):
                    row.text_preview = data["text_preview"]
                row.has_media = bool(data.get("has_media"))
                row.is_reply = bool(data.get("is_reply"))
                row.is_retweet = bool(data.get("is_retweet"))
                row.is_pinned = bool(data.get("is_pinned"))
                if data.get("posted_at"):
                    row.posted_at = data["posted_at"]
                row.scraped_at = now
                row.deleted_at = None

        if not partial:
            for tid, row in by_id.items():
                if tid not in fresh_ids and row.deleted_at is None:
                    row.deleted_at = now

        db.commit()

        # Return count of currently-live tweets for this account.
        from sqlalchemy import func

        count = (
            db.scalar(
                select(func.count())
                .select_from(TweetIndex)
                .where(
                    TweetIndex.x_account_id == account_id,
                    TweetIndex.deleted_at.is_(None),
                )
            )
            or 0
        )
        return int(count)

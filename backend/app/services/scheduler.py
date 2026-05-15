from __future__ import annotations

import asyncio
import logging
import platform
import random
import subprocess
from datetime import datetime
from pathlib import Path

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from app.core.crypto import get_crypto
from app.db.database import SessionLocal
from app.db.models import ApiKey, Operator, PostLog, Prompt, TweetIndex, XAccount
from app.db.utils import now_local, utcnow
from app.services.ai import generate_content
from app.services.manual import apply_decoration, split_manual
from app.services.media import extract_media_tokens, resolve_media_ids
from app.services.poster import post_reply, post_tweet
from app.services.tweet_scanner import scan_manager

log = logging.getLogger(__name__)

# (account_id, slot_kind) pairs currently mid-post. slot_kind is 'post' or
# 'reply' — each account has up to two independent jobs running at once
# (one new-tweet, one reply). The UI polls this via is_posting(account_id)
# which collapses across both slots. Also doubles as the tick-time
# exclusion set so concurrent ticks don't double-book the same slot.
# In-memory single-process state — resets on sidecar restart, which is
# correct because in-flight posts also abort on restart.
_currently_posting: set[tuple[int, str]] = set()

# Per-operator in-flight counter. Tick uses (parallel_posts - count) to
# decide how many new accounts to spawn this round. Updated alongside
# _currently_posting; the dict key is removed when count hits 0 so the
# state is self-cleaning across operator deletes.
_in_flight_by_operator: dict[int, int] = {}

# Proxy IDs currently driving a post. Tick skips accounts whose proxy is
# busy so two parallel posts don't fire through the same proxy at once —
# both because most proxies cap concurrent connections and because two
# simultaneous X requests through one IP is exactly the fingerprint X's
# anti-spam looks for.
_proxy_in_use: set[int] = set()

# Per-operator window slot tracker for the parallel tile layout. Slot
# index i (0-based) maps to a fixed (x, y, w, h) on screen via
# _slot_position(i, cap), so concurrent Chromium windows land in a
# deterministic grid instead of stacking at the OS default.
_busy_slots_by_operator: dict[int, set[int]] = {}

def _detect_screen_size() -> tuple[int, int]:
    """Best-effort detection of the main display's usable size. macOS:
    AppleScript via Finder returns the desktop bounds (already excludes
    the menubar); we subtract ~50px more for the Dock. Windows: ctypes
    GetSystemMetrics, minus ~40px for the taskbar. Falls back to
    1920×1040 on detection failure (headless server, sandboxed bundle
    where osascript is unavailable, etc.). Cached at module import —
    operators don't migrate displays mid-session."""
    try:
        if platform.system() == "Darwin":
            r = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "Finder" to get bounds of window of desktop',
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if r.returncode == 0:
                parts = [int(p.strip()) for p in r.stdout.strip().split(",")]
                if len(parts) == 4:
                    return parts[2], max(600, parts[3] - 50)
        elif platform.system() == "Windows":
            import ctypes

            user32 = ctypes.windll.user32
            try:
                user32.SetProcessDPIAware()
            except Exception:  # noqa: BLE001
                pass
            return (
                user32.GetSystemMetrics(0),
                max(600, user32.GetSystemMetrics(1) - 40),
            )
    except Exception:  # noqa: BLE001
        pass
    return 1920, 1040


_SCREEN_W, _SCREEN_H_USABLE = _detect_screen_size()
_TILE_MARGIN = 16


def _slot_position(slot_idx: int, total_slots: int) -> tuple[int, int, int, int]:
    """Return (x, y, w, h) for a window in a deterministic tile grid sized
    against the detected screen so concurrent windows always tile without
    overlap regardless of how many accounts are running. Single-window
    layout caps the size so it never dominates the screen — the operator
    is supervising automation, not editing in the window themselves."""
    if total_slots <= 1:
        # Cap at a compact size; on small displays shrink to fit.
        w = min(720, _SCREEN_W - 2 * _TILE_MARGIN)
        h = min(560, _SCREEN_H_USABLE - 2 * _TILE_MARGIN)
        x = (_SCREEN_W - w) // 2
        y = (_SCREEN_H_USABLE - h) // 2
        return (x, y, w, h)

    if total_slots == 2:
        cols, rows = 2, 1
    elif total_slots == 3:
        cols, rows = 3, 1
    elif total_slots == 4:
        cols, rows = 2, 2
    else:  # 5 or 6 — both use a 3x2 grid; cap=5 just leaves slot index 5 unused
        cols, rows = 3, 2

    cell_w = (_SCREEN_W - _TILE_MARGIN * (cols + 1)) // cols
    cell_h = (_SCREEN_H_USABLE - _TILE_MARGIN * (rows + 1)) // rows

    col = slot_idx % cols
    row = slot_idx // cols
    x = _TILE_MARGIN + col * (cell_w + _TILE_MARGIN)
    y = _TILE_MARGIN + row * (cell_h + _TILE_MARGIN)
    return (x, y, cell_w, cell_h)


def _acquire_slot(operator_id: int, cap: int) -> int:
    """Reserve and return the lowest-index free slot in [0, cap) for this
    operator. Caller must release with _release_slot when the post ends."""
    busy = _busy_slots_by_operator.setdefault(operator_id, set())
    for i in range(cap):
        if i not in busy:
            busy.add(i)
            return i
    # Defensive: shouldn't happen because the tick only spawns up to (cap
    # - in_flight) jobs, but if the count drifts somehow, fall back to
    # slot 0 so the post still fires (it just won't tile uniquely).
    return 0


def _release_slot(operator_id: int, slot_idx: int) -> None:
    busy = _busy_slots_by_operator.get(operator_id)
    if busy is None:
        return
    busy.discard(slot_idx)
    if not busy:
        _busy_slots_by_operator.pop(operator_id, None)


def is_posting(account_id: int) -> bool:
    """True while the scheduler has Playwright actively driving X for this
    account on EITHER slot (post or reply). Used by the UI to surface the
    posting state in real time."""
    return any(aid == account_id for aid, _slot in _currently_posting)


class RotationScheduler:
    """Per-operator rotation: every N seconds, post to the enabled account that
    was posted to least recently. Round-robin emerges naturally from sorting by
    `last_post_at`.

    One APScheduler interval job per operator. `posting_enabled` on the account
    is the on/off "checkbox"; accounts that aren't enabled are excluded from
    the rotation entirely.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._scheduler.start()
        self._started = True
        with SessionLocal() as db:
            ops = list(db.scalars(select(Operator)).all())
        for op in ops:
            self._schedule_operator(op.id)
        # Periodic tweet re-scan. Reply-mode prompts depend on a fresh
        # index, but we don't want to spawn a Chromium per account per
        # tick — running every 6 hours catches new tweets in a window
        # the user will tolerate without burning resources. max_instances=1
        # prevents a long-running scan round from overlapping with itself.
        self._scheduler.add_job(
            self._periodic_rescan,
            trigger="interval",
            seconds=6 * 3600,
            id="periodic_rescan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        log.info("scheduler started: %d operator(s)", len(ops))

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    def refresh_operator(self, operator_id: int) -> None:
        if not self._started:
            return
        try:
            self._scheduler.remove_job(self._job_id(operator_id))
        except JobLookupError:
            pass
        self._schedule_operator(operator_id)

    def refresh_account(self, account_id: int) -> None:
        """Account-level changes (toggle, prompt, etc.) -> reschedule its operator."""
        with SessionLocal() as db:
            acc = db.get(XAccount, account_id)
            if acc is not None:
                self.refresh_operator(acc.operator_id)

    @staticmethod
    def _job_id(operator_id: int) -> str:
        return f"op_{operator_id}"

    def _schedule_operator(self, operator_id: int) -> None:
        with SessionLocal() as db:
            op = db.get(Operator, operator_id)
            if op is None:
                return
            enabled_count = (
                db.scalar(
                    select(func.count())
                    .select_from(XAccount)
                    .where(
                        XAccount.operator_id == operator_id,
                        XAccount.posting_enabled.is_(True),
                    )
                )
                or 0
            )
            interval = max(1, op.rotation_interval_seconds)
        if enabled_count == 0:
            log.info(
                "operator %d: no enabled accounts, rotation idle", operator_id
            )
            return
        # max_instances=1 + coalesce=True is fine even with parallel posting:
        # the tick body now fires-and-forgets the actual posts, so it returns
        # in milliseconds. The next tick (rotation_interval_seconds later)
        # checks for free slots and tops up.
        self._scheduler.add_job(
            self._tick,
            trigger="interval",
            seconds=interval,
            args=[operator_id],
            id=self._job_id(operator_id),
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        log.info(
            "operator %d: rotation every %ds across %d account(s)",
            operator_id,
            interval,
            enabled_count,
        )

    async def _tick(self, operator_id: int) -> None:
        try:
            await self._do_tick(operator_id)
        except Exception:  # noqa: BLE001
            log.exception("rotation tick failed for operator %s", operator_id)

    async def _periodic_rescan(self) -> None:
        """Walk every account with a saved session and refresh its tweet
        index. Runs sequentially so we never have more than one scrape
        Chromium up at once — scans are headless and the 6-hour cadence
        gives plenty of headroom even for operators with many accounts."""
        try:
            with SessionLocal() as db:
                ids = list(
                    db.scalars(
                        select(XAccount.id).where(
                            XAccount.storage_state_enc.is_not(None)
                        )
                    ).all()
                )
        except Exception:  # noqa: BLE001
            log.exception("periodic rescan: failed to enumerate accounts")
            return

        for account_id in ids:
            task = scan_manager.start(account_id)
            if task.bg_task is None:
                continue
            try:
                await task.bg_task
            except Exception:  # noqa: BLE001
                log.exception(
                    "periodic rescan: scan failed for account %s",
                    account_id,
                )

    async def _do_tick(self, operator_id: int) -> None:
        """Pick up to (parallel_posts - in_flight) eligible (account, slot)
        jobs and spawn each as an independent task. Each account exposes
        two independent slots:
          - 'post' uses default_prompt_id, gated by last_post_at
          - 'reply' uses reply_prompt_id, gated by reply_last_run_at
        Both can be eligible in the same tick — the operator's
        parallel_posts cap and the per-proxy serial guard naturally bound
        actual concurrency. The tick body itself is fast (DB queries +
        bookkeeping); content build and Playwright drive happen inside the
        spawned tasks so a slow AI call for one slot doesn't block the
        rest of the rotation."""
        with SessionLocal() as db:
            op = db.get(Operator, operator_id)
            if op is None:
                return
            cap = max(1, op.parallel_posts)

        in_flight = _in_flight_by_operator.get(operator_id, 0)
        free_slots = cap - in_flight
        if free_slots <= 0:
            return

        # (account_id, op_id, proxy_id, prompt_id, slot_kind)
        chosen_jobs: list[tuple[int, int, int | None, int, str]] = []

        with SessionLocal() as db:
            # Sort by least-recently-active (across either slot). NULLs first
            # so never-run accounts win the first slot. Tie-break by id.
            accounts = list(
                db.scalars(
                    select(XAccount)
                    .where(
                        XAccount.operator_id == operator_id,
                        XAccount.posting_enabled.is_(True),
                    )
                    .order_by(
                        XAccount.last_post_at.asc().nulls_first(),
                        XAccount.id,
                    )
                ).all()
            )
            if not accounts:
                return

            now = now_local()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            # Track per-tick proxy reservations so a single tick doesn't pick
            # post+reply for the same account through the same proxy — two
            # parallel Chromiums on one IP is exactly the X anti-spam
            # fingerprint we're trying to avoid. Across ticks the global
            # _proxy_in_use guard does the same job.
            proxy_picked_this_tick: set[int] = set()

            loud_skipped: list[tuple[int, str]] = []

            for acc in accounts:
                if len(chosen_jobs) >= free_slots:
                    break

                # --- Account-level gates (apply to every slot) ---
                # Proxy busy from a prior tick or earlier in this tick?
                if acc.proxy_id is not None and (
                    acc.proxy_id in _proxy_in_use
                    or acc.proxy_id in proxy_picked_this_tick
                ):
                    continue
                if not _in_active_window(
                    now, acc.active_hours_start, acc.active_hours_end
                ):
                    continue
                if acc.daily_limit > 0:
                    count = (
                        db.scalar(
                            select(func.count())
                            .select_from(PostLog)
                            .where(
                                PostLog.x_account_id == acc.id,
                                PostLog.status == "success",
                                PostLog.timestamp >= today_start,
                            )
                        )
                        or 0
                    )
                    if count >= acc.daily_limit:
                        continue

                # --- Per-slot eligibility ---
                slot_configs: list[tuple[str, int | None, datetime | None]] = [
                    ("post", acc.default_prompt_id, acc.last_post_at),
                    ("reply", acc.reply_prompt_id, acc.reply_last_run_at),
                ]
                if all(pid is None for _, pid, _ in slot_configs):
                    loud_skipped.append(
                        (acc.id, "ยังไม่ตั้งสไตล์การเขียน")
                    )
                    continue

                # At most one slot per account per tick. Both slots can be
                # eligible (post + reply ready), but firing them in the same
                # instant would mean two Chromiums driving the same X account
                # at once — X's anti-spam flags that pattern. With a typical
                # rotation_interval_seconds of 1-5s, the other slot fires in
                # the very next tick anyway, so "parallel" from the user's
                # perspective just means "both modes active in the rotation",
                # not literally racing the same browser session.
                for slot_kind, prompt_id, last_run_at in slot_configs:
                    if len(chosen_jobs) >= free_slots:
                        break
                    if prompt_id is None:
                        continue
                    if (acc.id, slot_kind) in _currently_posting:
                        continue
                    if last_run_at is not None:
                        target_seconds = random.uniform(
                            acc.min_interval_seconds, acc.max_interval_seconds
                        )
                        elapsed_seconds = (now - last_run_at).total_seconds()
                        if elapsed_seconds < target_seconds:
                            continue
                    chosen_jobs.append(
                        (
                            acc.id,
                            acc.operator_id,
                            acc.proxy_id,
                            prompt_id,
                            slot_kind,
                        )
                    )
                    if acc.proxy_id is not None:
                        proxy_picked_this_tick.add(acc.proxy_id)
                    break

            if not chosen_jobs:
                if loud_skipped:
                    _log_skip(loud_skipped[0][0], loud_skipped[0][1])
                return

            # Reserve slots SYNCHRONOUSLY so a fast subsequent tick can't
            # double-pick or exceed the cap.
            jobs_with_slots: list[
                tuple[int, int, int | None, int, str, int, int]
            ] = []
            for account_id, op_id, proxy_id, prompt_id, slot_kind in chosen_jobs:
                _currently_posting.add((account_id, slot_kind))
                _in_flight_by_operator[op_id] = (
                    _in_flight_by_operator.get(op_id, 0) + 1
                )
                if proxy_id is not None:
                    _proxy_in_use.add(proxy_id)
                tile_idx = _acquire_slot(op_id, cap)
                jobs_with_slots.append(
                    (
                        account_id,
                        op_id,
                        proxy_id,
                        prompt_id,
                        slot_kind,
                        tile_idx,
                        cap,
                    )
                )

        for (
            account_id,
            op_id,
            proxy_id,
            prompt_id,
            slot_kind,
            tile_idx,
            total,
        ) in jobs_with_slots:
            asyncio.create_task(
                self._do_post(
                    account_id,
                    op_id,
                    proxy_id,
                    prompt_id,
                    slot_kind,
                    tile_idx,
                    total,
                )
            )

    async def _do_post(
        self,
        account_id: int,
        operator_id: int,
        proxy_id: int | None,
        prompt_id: int,
        slot_kind: str,
        slot_idx: int,
        total_slots: int,
    ) -> None:
        """Build content for one chosen (account, slot) job and drive the
        Playwright post/reply. Wrapped in try/finally so the in-flight
        bookkeeping is always released, even on AI / network / Playwright
        failures."""
        target_tweet_id: str | None = None
        try:
            with SessionLocal() as db:
                prompt = db.get(Prompt, prompt_id)
                if prompt is None:
                    _log_skip(account_id, "สไตล์ถูกลบไปแล้ว")
                    return

                mode = prompt.mode
                body = prompt.body
                fallback = prompt.fallback_text
                decorate_emoji = prompt.decorate_emoji
                decorate_letters = prompt.decorate_letters
                reply_source = prompt.reply_source

                # For the reply slot we expect a reply-mode prompt. If the
                # user accidentally assigned an ai/manual prompt to the
                # reply slot, bail loudly rather than silently posting it
                # as a new tweet (which would surprise the user).
                if slot_kind == "reply" and mode != "reply":
                    _log_skip(
                        account_id,
                        "สไตล์ที่กำหนดให้ช่อง reply ไม่ใช่โหมด reply — "
                        "เปลี่ยนสไตล์ในช่องนั้น",
                    )
                    return
                if slot_kind == "post" and mode == "reply":
                    _log_skip(
                        account_id,
                        "สไตล์โหมด reply ถูกกำหนดในช่องโพสต์ใหม่ — "
                        "ย้ายไปช่อง reply",
                    )
                    return

                # Multi-target picker for reply mode. Returns the tweet_id
                # to reply to (one per tick, chosen round-robin) or a
                # human-readable skip reason.
                if mode == "reply":
                    picked, skip_reason = _pick_reply_target(
                        db, account_id, prompt
                    )
                    if picked is None:
                        _log_skip(
                            account_id, skip_reason or "ไม่มีโพสต์ที่ reply ได้"
                        )
                        return
                    target_tweet_id = picked

                # Decide which content path runs. For non-reply modes the
                # outer `mode` is the source; for reply mode the inner
                # `reply_source` field steers between ai/manual.
                effective_source = (
                    reply_source if mode == "reply" else mode
                )

                if effective_source == "manual":
                    provider = "manual"
                    model = "-"
                    api_key_plain = None
                else:
                    key_row = db.scalar(
                        select(ApiKey)
                        .where(
                            ApiKey.operator_id == operator_id,
                            ApiKey.provider == prompt.provider,
                        )
                        .order_by(ApiKey.created_at.desc())
                    )
                    if key_row is None:
                        _log_skip(
                            account_id,
                            f"ไม่มี API key ของ {prompt.provider}",
                        )
                        return
                    provider = prompt.provider
                    model = prompt.model
                    api_key_plain = get_crypto().decrypt_str(key_row.key_enc)

            media_paths: list[Path] = []
            if effective_source == "manual":
                candidates = split_manual(body)
                if not candidates:
                    _log_skip(
                        account_id,
                        "สไตล์เขียนเองยังไม่มีข้อความ · แก้ไขสไตล์แล้วใส่ข้อความก่อน",
                    )
                    return
                picked = random.choice(candidates)
                content, media_ids = extract_media_tokens(picked)
                content = apply_decoration(
                    content,
                    with_emoji=decorate_emoji,
                    with_letters=decorate_letters,
                    account_id=account_id,
                )
                if media_ids:
                    with SessionLocal() as media_db:
                        media_paths = resolve_media_ids(
                            media_db, operator_id, media_ids
                        )
            else:
                try:
                    content = await generate_content(
                        provider=provider,  # type: ignore[arg-type]
                        model=model,
                        system_prompt=body,
                        api_key=api_key_plain or "",
                    )
                except Exception:  # noqa: BLE001
                    log.exception(
                        "AI generation failed for account %s", account_id
                    )
                    if fallback:
                        content = fallback
                    else:
                        _log_skip(
                            account_id,
                            "AI generate ล้มเหลว และไม่มี fallback",
                        )
                        return

            # Playwright opens its own visible Chromium per task. Multiple
            # tasks run concurrently up to the operator's parallel_posts
            # cap (enforced at tick time). Per-proxy serial posting is
            # enforced via the _proxy_in_use guard at tick time too. The
            # tile slot pins the window to a fixed (x, y, w, h) so the
            # parallel windows land in a deterministic grid. Each task
            # posts independently the moment its own prep is ready.
            x, y, w, h = _slot_position(slot_idx, total_slots)
            if mode == "reply":
                await post_reply(
                    account_id=account_id,
                    content=content,
                    target_tweet_id=target_tweet_id,  # type: ignore[arg-type]
                    media_paths=media_paths or None,
                    window_position=(x, y),
                    window_size=(w, h),
                    headless=False,
                )
            else:
                await post_tweet(
                    account_id=account_id,
                    content=content,
                    media_paths=media_paths or None,
                    window_position=(x, y),
                    window_size=(w, h),
                    headless=False,
                )
        except Exception:  # noqa: BLE001
            log.exception(
                "%s task failed for account %s", slot_kind, account_id
            )
        finally:
            _currently_posting.discard((account_id, slot_kind))
            remaining = _in_flight_by_operator.get(operator_id, 0) - 1
            if remaining <= 0:
                _in_flight_by_operator.pop(operator_id, None)
            else:
                _in_flight_by_operator[operator_id] = remaining
            if proxy_id is not None:
                _proxy_in_use.discard(proxy_id)
            _release_slot(operator_id, slot_idx)


def _in_active_window(now: datetime, start: int, end: int) -> bool:
    if start == end:
        return True  # treated as 24/7
    h = now.hour
    if start < end:
        return start <= h < end
    return h >= start or h < end  # overnight window


def _pick_reply_target(
    db,  # type: ignore[no-untyped-def]
    account_id: int,
    prompt: Prompt,
) -> tuple[str | None, str | None]:
    """Pick which tweet a reply-mode prompt targets this tick. Returns
    (tweet_id, skip_reason). When tweet_id is None the caller should log
    the skip_reason and bail.

    Selection rules:
      'single'    → prompt.target_tweet_id, validated against the index.
      'latest_n'  → N most recently indexed live tweets, round-robin by
                    fewest past replies (ties: oldest last-reply, then
                    oldest posted_at).
      'all'       → every live tweet in the index, same round-robin.

    reply_repeat_limit (when > 0) drops targets that already hit the cap.
    Retweets are excluded — replying to a retweet would land on the
    original author's post, not ours."""
    mode = prompt.reply_target_mode or "single"
    limit = prompt.reply_repeat_limit

    if mode == "single":
        tid = prompt.target_tweet_id
        if not tid:
            return None, "Reply mode ยังไม่ได้เลือกโพสต์ต้นทาง"
        row = db.scalar(
            select(TweetIndex).where(
                TweetIndex.x_account_id == account_id,
                TweetIndex.tweet_id == tid,
            )
        )
        if row is None:
            return None, (
                f"โพสต์ต้นทาง {tid} ไม่อยู่ใน index ของบัญชีนี้ — "
                "สแกนใหม่หรือเลือกอันอื่น"
            )
        if row.deleted_at is not None:
            return None, "โพสต์ต้นทางถูกลบไปแล้ว — แก้ไขสไตล์ก่อน"
        if limit > 0:
            count = (
                db.scalar(
                    select(func.count())
                    .select_from(PostLog)
                    .where(
                        PostLog.x_account_id == account_id,
                        PostLog.reply_to_tweet_id == tid,
                        PostLog.status == "success",
                    )
                )
                or 0
            )
            if count >= limit:
                return None, (
                    f"reply ครบ {limit} ครั้งแล้วสำหรับโพสต์ {tid}"
                )
        return tid, None

    # latest_n or all — query candidates from the index.
    candidates_stmt = (
        select(TweetIndex)
        .where(
            TweetIndex.x_account_id == account_id,
            TweetIndex.deleted_at.is_(None),
            TweetIndex.is_retweet.is_(False),
        )
        .order_by(TweetIndex.posted_at.desc().nulls_last())
    )
    if mode == "latest_n":
        n = max(1, prompt.reply_target_count or 5)
        candidates_stmt = candidates_stmt.limit(n)
    candidates = list(db.scalars(candidates_stmt).all())
    if not candidates:
        return None, (
            "ยังไม่มีโพสต์ใน index ของบัญชีนี้ — กดสแกนก่อน"
        )

    target_ids = [c.tweet_id for c in candidates]
    # One pass to fetch (count, last_timestamp) per target. SQLite handles
    # group_by + count + max in a single statement; for the typical N≤50
    # the IN clause is well within limits.
    rows = list(
        db.execute(
            select(
                PostLog.reply_to_tweet_id,
                func.count(),
                func.max(PostLog.timestamp),
            )
            .where(
                PostLog.x_account_id == account_id,
                PostLog.status == "success",
                PostLog.reply_to_tweet_id.in_(target_ids),
            )
            .group_by(PostLog.reply_to_tweet_id)
        ).all()
    )
    count_map: dict[str, int] = {r[0]: r[1] for r in rows}
    last_map: dict[str, datetime | None] = {r[0]: r[2] for r in rows}

    eligible = []
    for c in candidates:
        if limit > 0 and count_map.get(c.tweet_id, 0) >= limit:
            continue
        eligible.append(c)

    if not eligible:
        return None, (
            f"reply ครบ {limit} ครั้งต่อโพสต์แล้วทุกตัว · "
            "ขยายตัวเลือก target หรือเพิ่ม limit"
        )

    # Earliest sentinel for datetime comparison when the candidate has no
    # past reply. Using utcnow-style epoch keeps sort stable across runs.
    sentinel = datetime.min.replace(tzinfo=None)
    eligible.sort(
        key=lambda c: (
            count_map.get(c.tweet_id, 0),
            _coerce_naive(last_map.get(c.tweet_id)) or sentinel,
            _coerce_naive(c.posted_at) or sentinel,
        )
    )
    return eligible[0].tweet_id, None


def _coerce_naive(dt: datetime | None) -> datetime | None:
    """Sort keys can't mix tz-aware and tz-naive datetimes. SQLite stores
    timestamps either way depending on how they were inserted, so strip
    tzinfo for ordering purposes only."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _log_skip(account_id: int, reason: str) -> None:
    with SessionLocal() as db:
        row = PostLog(
            x_account_id=account_id,
            status="skipped",
            detail=reason,
            timestamp=utcnow(),
        )
        db.add(row)
        db.commit()


scheduler = RotationScheduler()

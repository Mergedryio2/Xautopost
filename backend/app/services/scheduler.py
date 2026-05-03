from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from pathlib import Path

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from app.core.crypto import get_crypto
from app.db.database import SessionLocal
from app.db.models import ApiKey, Operator, PostLog, Prompt, XAccount
from app.db.utils import now_local, utcnow
from app.services.ai import generate_content
from app.services.manual import apply_decoration, split_manual
from app.services.media import extract_media_tokens, resolve_media_ids
from app.services.poster import post_tweet

log = logging.getLogger(__name__)

# Account IDs currently mid-post. The UI polls this (via the is_posting
# field on XAccountOut) to show a live "📮 กำลังโพสต์อยู่" indicator.
# Also doubles as the tick-time exclusion set so concurrent ticks don't
# double-pick the same account.
# In-memory single-process state — resets on sidecar restart, which is
# correct because in-flight posts also abort on restart.
_currently_posting: set[int] = set()

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


def is_posting(account_id: int) -> bool:
    """True while the scheduler has Playwright actively driving X for this
    account. Used by the UI to surface the posting state in real time."""
    return account_id in _currently_posting


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

    async def _do_tick(self, operator_id: int) -> None:
        """Pick up to (parallel_posts - in_flight) eligible accounts and
        spawn each as an independent task. The tick body itself is fast
        (DB queries + bookkeeping); the actual content build and Playwright
        drive happen inside the spawned tasks so a slow AI call for one
        account doesn't block the rest of the rotation."""
        with SessionLocal() as db:
            op = db.get(Operator, operator_id)
            if op is None:
                return
            cap = max(1, op.parallel_posts)

        in_flight = _in_flight_by_operator.get(operator_id, 0)
        free_slots = cap - in_flight
        if free_slots <= 0:
            return

        chosen_jobs: list[tuple[int, int, int | None, int]] = []

        with SessionLocal() as db:
            # Sort by least-recently-posted (NULLs first => never-posted accounts
            # get the slot first), tie-break by id for stable order.
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

            # Loud skips = configuration problems the user needs to know about
            # (no prompt, manual style empty, etc). Operational throttling
            # (active window, per-account interval, daily limit) is silent —
            # logging every tick of "ยังไม่ถึงเวลา" would drown the actual log.
            loud_skipped: list[tuple[int, str]] = []

            for acc in accounts:
                if len(chosen_jobs) >= free_slots:
                    break

                # Concurrency exclusion 1: account already mid-post (from an
                # earlier tick that hasn't completed yet).
                if acc.id in _currently_posting:
                    continue

                # Concurrency exclusion 2: another in-flight post is using
                # this account's proxy. Two parallel X requests through one
                # IP is the fingerprint we're trying to avoid.
                if acc.proxy_id is not None and acc.proxy_id in _proxy_in_use:
                    continue

                # Operational gate 1: active hours window — silent skip
                if not _in_active_window(
                    now, acc.active_hours_start, acc.active_hours_end
                ):
                    continue

                # Operational gate 2: per-account min/max interval — silent skip.
                # Pick a random target in [min, max] seconds; the same account
                # cannot post again until that much time has passed since
                # last_post_at. This is the human-like cadence guarantee.
                if acc.last_post_at is not None:
                    target_seconds = random.uniform(
                        acc.min_interval_seconds, acc.max_interval_seconds
                    )
                    elapsed_seconds = (now - acc.last_post_at).total_seconds()
                    if elapsed_seconds < target_seconds:
                        continue

                # Operational gate 3: daily limit — silent skip.
                # daily_limit == 0 means unlimited; skip the count query entirely.
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

                # Configuration gate: missing prompt — loud skip
                if not acc.default_prompt_id:
                    loud_skipped.append(
                        (acc.id, "ยังไม่ตั้งสไตล์การเขียน")
                    )
                    continue

                chosen_jobs.append(
                    (acc.id, acc.operator_id, acc.proxy_id, acc.default_prompt_id)
                )

            if not chosen_jobs:
                # Only surface configuration issues; operational throttling is
                # part of normal operation and shouldn't pollute the log.
                if loud_skipped:
                    _log_skip(loud_skipped[0][0], loud_skipped[0][1])
                return

            # Reserve slots SYNCHRONOUSLY (no await between mark and spawn)
            # so a fast subsequent tick can't double-pick or exceed the cap.
            # asyncio is single-threaded, so this block of mutations is
            # atomic w.r.t. the next coroutine point.
            for account_id, op_id, proxy_id, _ in chosen_jobs:
                _currently_posting.add(account_id)
                _in_flight_by_operator[op_id] = (
                    _in_flight_by_operator.get(op_id, 0) + 1
                )
                if proxy_id is not None:
                    _proxy_in_use.add(proxy_id)

        # Spawn each post as an independent task. The tick returns
        # immediately; the next interval tops up free slots.
        for account_id, op_id, proxy_id, prompt_id in chosen_jobs:
            asyncio.create_task(
                self._do_post(account_id, op_id, proxy_id, prompt_id)
            )

    async def _do_post(
        self,
        account_id: int,
        operator_id: int,
        proxy_id: int | None,
        prompt_id: int,
    ) -> None:
        """Build content for one chosen account and drive the Playwright
        post. Wrapped in try/finally so the in-flight bookkeeping is
        always released, even on AI / network / Playwright failures."""
        try:
            with SessionLocal() as db:
                prompt = db.get(Prompt, prompt_id)
                if prompt is None:
                    _log_skip(account_id, "default prompt ถูกลบไปแล้ว")
                    return

                mode = prompt.mode
                body = prompt.body
                fallback = prompt.fallback_text
                decorate_emoji = prompt.decorate_emoji
                decorate_letters = prompt.decorate_letters

                if mode == "manual":
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
            if mode == "manual":
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
            # enforced via the _proxy_in_use guard at tick time too.
            await post_tweet(
                account_id=account_id,
                content=content,
                media_paths=media_paths or None,
                headless=False,
            )
        except Exception:  # noqa: BLE001
            log.exception("post task failed for account %s", account_id)
        finally:
            _currently_posting.discard(account_id)
            remaining = _in_flight_by_operator.get(operator_id, 0) - 1
            if remaining <= 0:
                _in_flight_by_operator.pop(operator_id, None)
            else:
                _in_flight_by_operator[operator_id] = remaining
            if proxy_id is not None:
                _proxy_in_use.discard(proxy_id)


def _in_active_window(now: datetime, start: int, end: int) -> bool:
    if start == end:
        return True  # treated as 24/7
    h = now.hour
    if start < end:
        return start <= h < end
    return h >= start or h < end  # overnight window


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

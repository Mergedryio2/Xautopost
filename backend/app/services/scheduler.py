from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func, select

from app.core.crypto import get_crypto
from app.db.database import SessionLocal
from app.db.models import ApiKey, Operator, PostLog, Prompt, XAccount
from app.db.utils import now_local, utcnow
from app.services.ai import generate_content
from app.services.manual import decorate, split_manual
from app.services.poster import post_tweet

log = logging.getLogger(__name__)

# Serializes posts so multiple operators don't open concurrent Chromium.
_post_lock = asyncio.Lock()


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

            chosen: XAccount | None = None
            # Loud skips = configuration problems the user needs to know about
            # (no prompt, manual style empty, etc). Operational throttling
            # (active window, per-account interval, daily limit) is silent —
            # logging every tick of "ยังไม่ถึงเวลา" would drown the actual log.
            loud_skipped: list[tuple[int, str]] = []

            for acc in accounts:
                # Operational gate 1: active hours window — silent skip
                if not _in_active_window(
                    now, acc.active_hours_start, acc.active_hours_end
                ):
                    continue

                # Operational gate 2: per-account min/max interval — silent skip.
                # Pick a random target in [min, max] minutes; the same account
                # cannot post again until that much time has passed since
                # last_post_at. This is the human-like cadence guarantee.
                if acc.last_post_at is not None:
                    target_minutes = random.uniform(
                        acc.min_interval_minutes, acc.max_interval_minutes
                    )
                    elapsed_minutes = (
                        now - acc.last_post_at
                    ).total_seconds() / 60.0
                    if elapsed_minutes < target_minutes:
                        continue

                # Operational gate 3: daily limit — silent skip
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

                chosen = acc
                break

            if chosen is None:
                # Only surface configuration issues; operational throttling is
                # part of normal operation and shouldn't pollute the log.
                if loud_skipped:
                    _log_skip(loud_skipped[0][0], loud_skipped[0][1])
                return

            prompt = db.get(Prompt, chosen.default_prompt_id)
            if prompt is None:
                _log_skip(chosen.id, "default prompt ถูกลบไปแล้ว")
                return

            account_id = chosen.id
            mode = prompt.mode
            body = prompt.body
            fallback = prompt.fallback_text
            vary_decoration = prompt.vary_decoration

            if mode == "manual":
                provider = "manual"
                model = "-"
                api_key_plain = None
            else:
                key_row = db.scalar(
                    select(ApiKey)
                    .where(
                        ApiKey.operator_id == chosen.operator_id,
                        ApiKey.provider == prompt.provider,
                    )
                    .order_by(ApiKey.created_at.desc())
                )
                if key_row is None:
                    _log_skip(chosen.id, f"ไม่มี API key ของ {prompt.provider}")
                    return
                provider = prompt.provider
                model = prompt.model
                api_key_plain = get_crypto().decrypt_str(key_row.key_enc)

        # Build content
        if mode == "manual":
            candidates = split_manual(body)
            if not candidates:
                _log_skip(
                    account_id,
                    "สไตล์เขียนเองยังไม่มีข้อความ · แก้ไขสไตล์แล้วใส่ข้อความก่อน",
                )
                return
            content = random.choice(candidates)
            if vary_decoration:
                content = decorate(content, account_id=account_id)
        else:
            try:
                content = await generate_content(
                    provider=provider,  # type: ignore[arg-type]
                    model=model,
                    system_prompt=body,
                    api_key=api_key_plain or "",
                )
            except Exception:  # noqa: BLE001
                log.exception("AI generation failed for account %s", account_id)
                if fallback:
                    content = fallback
                else:
                    _log_skip(
                        account_id, "AI generate ล้มเหลว และไม่มี fallback"
                    )
                    return

        # Post (serialized across operators)
        async with _post_lock:
            await post_tweet(
                account_id=account_id, content=content, headless=True
            )


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

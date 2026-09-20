"""Tweet index API: trigger a fresh scrape of an account's profile,
report scan progress, list the cached results for the reply-target picker
in the prompt editor, and add/remove individual posts by link (own or
someone else's)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_serializer
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.db.database import get_db
from app.db.models import Operator, TweetIndex, XAccount
from app.db.utils import utcnow
from app.services.tweet_ref import (
    fetch_tweet_meta,
    parse_tweet_ref,
    snowflake_time,
)
from app.services.tweet_scanner import scan_manager

router = APIRouter(prefix="/accounts/{account_id}/tweets", tags=["tweets"])


class TweetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tweet_id: str
    url: str
    text_preview: str | None
    has_media: bool
    is_reply: bool
    is_retweet: bool
    is_pinned: bool
    posted_at: datetime | None
    scraped_at: datetime
    added_at: datetime | None = None
    deleted_at: datetime | None
    source: str = "scan"
    is_own: bool = True

    # posted_at comes from X's ISO timestamps (UTC) but SQLite drops the
    # offset on the way in, so it reads back naive. Every other datetime
    # here is naive Bangkok-local and the UI assumes +07:00 for anything
    # without an offset — so put the UTC offset back on this one field.
    @field_serializer("posted_at")
    def _posted_at_utc(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=UTC)
        return v.isoformat()


class AddByLinkIn(BaseModel):
    link: str = Field(min_length=1, max_length=512)
    # None = decide from the post's author (oEmbed) or the handle in the
    # link; the UI sends an explicit value from its dropdown.
    is_own: bool | None = None


class ScanStatusOut(BaseModel):
    # Persisted on the account so the UI survives sidecar restarts.
    scan_status: str
    last_scan_at: datetime | None
    scanned_tweet_count: int
    scan_error: str | None
    # In-flight state from the in-memory ScanManager — only populated when
    # a scan is currently running for this account.
    running: bool
    tweets_collected_so_far: int = 0


def _owned_account(
    account_id: int, op: Operator, db: Session
) -> XAccount:
    acc = db.get(XAccount, account_id)
    if acc is None or acc.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    return acc


@router.post(
    "/scan", response_model=ScanStatusOut, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_scan(
    account_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> ScanStatusOut:
    """Start a background scan. Returns 202 with the current status. If a
    scan is already running for this account, returns the existing one
    instead of starting a duplicate."""
    acc = _owned_account(account_id, op, db)
    if acc.storage_state_enc is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "บัญชีนี้ยังไม่ login — login ก่อนแล้วค่อยสแกน",
        )
    task = scan_manager.start(account_id)
    return ScanStatusOut(
        scan_status="running",
        last_scan_at=acc.last_scan_at,
        scanned_tweet_count=acc.scanned_tweet_count,
        scan_error=acc.scan_error,
        running=task.status == "running",
        tweets_collected_so_far=task.tweets_collected,
    )


@router.get("/scan", response_model=ScanStatusOut)
def scan_status(
    account_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> ScanStatusOut:
    acc = _owned_account(account_id, op, db)
    task = scan_manager.get(account_id)
    return ScanStatusOut(
        scan_status=acc.scan_status,
        last_scan_at=acc.last_scan_at,
        scanned_tweet_count=acc.scanned_tweet_count,
        scan_error=acc.scan_error,
        running=task is not None and task.status == "running",
        tweets_collected_so_far=task.tweets_collected if task else 0,
    )


@router.post("/scan/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_scan(
    account_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    _owned_account(account_id, op, db)
    scan_manager.cancel(account_id)


@router.get("", response_model=list[TweetOut])
def list_tweets(
    account_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[str | None, Query(description="text search")] = None,
    has_media: Annotated[bool | None, Query()] = None,
    is_own: Annotated[bool | None, Query()] = None,
    source: Annotated[Literal["scan", "manual"] | None, Query()] = None,
    # 'posted' = newest post first (pinned on top); 'added' = most recently
    # added to the index first — what "links I just pasted" means.
    sort: Annotated[Literal["posted", "added"], Query()] = "posted",
    include_deleted: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TweetIndex]:
    """List indexed tweets for the account. Defaults to live (non-deleted)
    tweets ordered newest-first. Search is a substring match on the cached
    preview text — cheap for SQLite without a FTS index."""
    _owned_account(account_id, op, db)
    stmt = select(TweetIndex).where(TweetIndex.x_account_id == account_id)
    if not include_deleted:
        stmt = stmt.where(TweetIndex.deleted_at.is_(None))
    if has_media is True:
        stmt = stmt.where(TweetIndex.has_media.is_(True))
    elif has_media is False:
        stmt = stmt.where(TweetIndex.has_media.is_(False))
    if is_own is True:
        stmt = stmt.where(TweetIndex.is_own.is_(True))
    elif is_own is False:
        stmt = stmt.where(TweetIndex.is_own.is_(False))
    if source is not None:
        stmt = stmt.where(TweetIndex.source == source)
    if q:
        # Always-true clause for tweets whose preview wasn't captured so
        # they're not silently dropped from the search results.
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                TweetIndex.text_preview.ilike(pattern),
                TweetIndex.tweet_id == q,
            )
        )
    if sort == "added":
        stmt = stmt.order_by(
            TweetIndex.added_at.desc().nulls_last(),
            TweetIndex.id.desc(),
        )
    else:
        stmt = stmt.order_by(
            TweetIndex.is_pinned.desc(),
            TweetIndex.posted_at.desc().nulls_last(),
            TweetIndex.id.desc(),
        )
    return list(db.scalars(stmt.limit(limit).offset(offset)).all())


@router.post("/by-link", response_model=TweetOut)
async def add_by_link(
    account_id: int,
    payload: AddByLinkIn,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> TweetIndex:
    """Add one post to the index from a pasted link. Works for posts the
    scraper can't reach: other people's posts, or own posts not scanned
    yet. Author/text come from X's public oEmbed when reachable; the row
    is still created without them so the reply target works regardless."""
    acc = _owned_account(account_id, op, db)
    ref = parse_tweet_ref(payload.link)
    if ref is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ยังไม่ใช่ลิงก์โพสต์ X ค่ะ ลองวางแบบ https://x.com/<ชื่อ>/status/<เลข>",
        )

    meta = await fetch_tweet_meta(ref.tweet_id)
    my_handle = (acc.handle or "").lstrip("@").lower()
    author = meta.author_handle if meta else ref.handle
    if payload.is_own is not None:
        is_own = payload.is_own
    elif author is not None and my_handle:
        is_own = author == my_handle
    else:
        is_own = False
    url = meta.url if meta else ref.url

    now = utcnow()
    row = db.scalar(
        select(TweetIndex).where(
            TweetIndex.x_account_id == account_id,
            TweetIndex.tweet_id == ref.tweet_id,
        )
    )
    if row is None:
        row = TweetIndex(
            x_account_id=account_id,
            tweet_id=ref.tweet_id,
            url=url,
            text_preview=meta.text if meta else None,
            posted_at=snowflake_time(ref.tweet_id),
            scraped_at=now,
            added_at=now,
            source="manual",
            is_own=is_own,
        )
        db.add(row)
    else:
        # Re-adding an existing row un-deletes it and refreshes what we
        # learned; a scraped row keeps source='scan' so the sweep still
        # governs it.
        row.url = url
        if meta and meta.text:
            row.text_preview = meta.text
        if row.posted_at is None:
            row.posted_at = snowflake_time(ref.tweet_id)
        row.is_own = is_own
        row.scraped_at = now
        row.deleted_at = None
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{tweet_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_tweet(
    account_id: int,
    tweet_id: str,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Remove a link-added row. Scraped rows are owned by the scanner
    (they'd just come back on the next scan), so only source='manual'
    rows can be removed here. post_logs reference tweets by id string,
    not FK, so a hard delete is safe."""
    _owned_account(account_id, op, db)
    row = db.scalar(
        select(TweetIndex).where(
            TweetIndex.x_account_id == account_id,
            TweetIndex.tweet_id == tweet_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tweet not in index")
    if row.source != "manual":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ลบได้เฉพาะโพสต์ที่เพิ่มจาก link — โพสต์จากการสแกนจะหายเองเมื่อสแกนใหม่",
        )
    db.delete(row)
    db.commit()


class TweetCountOut(BaseModel):
    total: int
    live: int
    with_media: int


@router.get("/count", response_model=TweetCountOut)
def tweet_counts(
    account_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> TweetCountOut:
    _owned_account(account_id, op, db)
    base = select(func.count()).select_from(TweetIndex).where(
        TweetIndex.x_account_id == account_id
    )
    total = int(db.scalar(base) or 0)
    live = int(
        db.scalar(base.where(TweetIndex.deleted_at.is_(None))) or 0
    )
    with_media = int(
        db.scalar(
            base.where(
                TweetIndex.deleted_at.is_(None),
                TweetIndex.has_media.is_(True),
            )
        )
        or 0
    )
    return TweetCountOut(total=total, live=live, with_media=with_media)

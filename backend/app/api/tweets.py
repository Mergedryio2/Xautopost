"""Tweet index API: trigger a fresh scrape of an account's profile,
report scan progress, and list the cached results for the reply-target
picker in the prompt editor."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.db.database import get_db
from app.db.models import Operator, TweetIndex, XAccount
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
    deleted_at: datetime | None


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
    stmt = (
        stmt.order_by(
            TweetIndex.is_pinned.desc(),
            TweetIndex.posted_at.desc().nulls_last(),
            TweetIndex.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


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

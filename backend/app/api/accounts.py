from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.core.crypto import get_crypto
from app.db.database import get_db
from app.db.models import Operator, Prompt, Proxy, XAccount
from app.services.media import resolve_media_ids
from app.services.playwright_login import login_manager
from app.services.poster import post_tweet
from app.services.scheduler import is_posting, scheduler

router = APIRouter(prefix="/accounts", tags=["accounts"])


class XAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    handle: str
    display_name: str | None
    status: str
    daily_limit: int
    proxy_id: int | None
    default_prompt_id: int | None
    posting_enabled: bool
    min_interval_seconds: int
    max_interval_seconds: int
    active_hours_start: int
    active_hours_end: int
    last_post_at: datetime | None
    created_at: datetime
    # Live state — populated from in-memory scheduler tracker, not the DB.
    is_posting: bool = False


def _enrich(acc: XAccount) -> XAccountOut:
    out = XAccountOut.model_validate(acc)
    out.is_posting = is_posting(acc.id)
    return out


class XAccountUpdate(BaseModel):
    default_prompt_id: int | None = None
    posting_enabled: bool | None = None
    # 0 = unlimited; otherwise a daily ceiling.
    daily_limit: int | None = Field(default=None, ge=0, le=100000)
    # Per-account spacing in seconds. 1s floor matches the UI; 86400s = 24h cap.
    min_interval_seconds: int | None = Field(default=None, ge=1, le=86400)
    max_interval_seconds: int | None = Field(default=None, ge=1, le=86400)
    active_hours_start: int | None = Field(default=None, ge=0, le=23)
    active_hours_end: int | None = Field(default=None, ge=0, le=23)
    proxy_id: int | None = None


@router.get("", response_model=list[XAccountOut])
def list_accounts(
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> list[XAccountOut]:
    accounts = list(
        db.scalars(
            select(XAccount)
            .where(XAccount.operator_id == op.id)
            .order_by(XAccount.created_at.desc())
        ).all()
    )
    return [_enrich(a) for a in accounts]


@router.patch("/{account_id}", response_model=XAccountOut)
def update_account(
    account_id: int,
    payload: XAccountUpdate,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> XAccountOut:
    acc = db.get(XAccount, account_id)
    if acc is None or acc.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")

    data = payload.model_dump(exclude_unset=True)

    if data.get("default_prompt_id") is not None:
        p = db.get(Prompt, data["default_prompt_id"])
        if p is None or p.operator_id != op.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt not found")

    if data.get("proxy_id") is not None:
        proxy = db.get(Proxy, data["proxy_id"])
        if proxy is None or proxy.operator_id != op.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "proxy not found")

    new_min = data.get("min_interval_seconds", acc.min_interval_seconds)
    new_max = data.get("max_interval_seconds", acc.max_interval_seconds)
    if new_min > new_max:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "min interval ต้อง ≤ max interval"
        )

    for k, v in data.items():
        setattr(acc, k, v)
    db.commit()
    db.refresh(acc)

    scheduler.refresh_account(acc.id)
    return _enrich(acc)


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    acc = db.get(XAccount, account_id)
    if acc is None or acc.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    db.delete(acc)
    db.commit()
    scheduler.refresh_account(account_id)
    return {"ok": True}


class StartLoginIn(BaseModel):
    proxy_id: int | None = None


class StartLoginOut(BaseModel):
    task_id: str


@router.post("/login", response_model=StartLoginOut)
async def start_login(
    payload: StartLoginIn,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> StartLoginOut:
    proxy_server: str | None = None
    proxy_user: str | None = None
    proxy_pass: str | None = None

    if payload.proxy_id is not None:
        proxy = db.get(Proxy, payload.proxy_id)
        if proxy is None or proxy.operator_id != op.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "proxy not found")
        proxy_server = proxy.server
        crypto = get_crypto()
        if proxy.username_enc:
            proxy_user = crypto.decrypt_str(proxy.username_enc)
        if proxy.password_enc:
            proxy_pass = crypto.decrypt_str(proxy.password_enc)

    task = login_manager.start(
        operator_id=op.id,
        proxy_id=payload.proxy_id,
        proxy_server=proxy_server,
        proxy_username=proxy_user,
        proxy_password=proxy_pass,
    )
    return StartLoginOut(task_id=task.task_id)


class LoginStatusOut(BaseModel):
    status: Literal["waiting", "success", "failed", "canceled"]
    handle: str | None = None
    account_id: int | None = None
    error: str | None = None


@router.get("/login/{task_id}", response_model=LoginStatusOut)
def login_status(
    task_id: str,
    op: Annotated[Operator, Depends(get_current_operator)],
) -> LoginStatusOut:
    task = login_manager.get(task_id)
    if task is None or task.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return LoginStatusOut(
        status=task.status,
        handle=task.handle,
        account_id=task.account_id,
        error=task.error,
    )


@router.delete("/login/{task_id}")
async def cancel_login(
    task_id: str,
    op: Annotated[Operator, Depends(get_current_operator)],
) -> dict[str, bool]:
    task = login_manager.get(task_id)
    if task is None or task.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    login_manager.cancel(task_id)
    return {"ok": True}


class TestPostIn(BaseModel):
    # Allow blank text when media is attached — X accepts media-only posts.
    content: str = Field(default="", max_length=4000)
    media_ids: list[int] = Field(default_factory=list)


class TestPostOut(BaseModel):
    ok: bool
    error: str | None = None


@router.post("/{account_id}/test-post", response_model=TestPostOut)
async def test_post_account(
    account_id: int,
    payload: TestPostIn,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> TestPostOut:
    acc = db.get(XAccount, account_id)
    if acc is None or acc.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")

    if not payload.content.strip() and not payload.media_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ต้องมีข้อความหรือไฟล์แนบอย่างน้อยหนึ่งอย่าง",
        )

    media_paths = resolve_media_ids(db, op.id, payload.media_ids) or None

    result = await post_tweet(
        account_id=account_id,
        content=payload.content,
        media_paths=media_paths,
    )
    return TestPostOut(ok=result.ok, error=result.error)

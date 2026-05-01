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
from app.services.playwright_login import login_manager
from app.services.poster import post_tweet
from app.services.scheduler import scheduler

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
    min_interval_minutes: int
    max_interval_minutes: int
    active_hours_start: int
    active_hours_end: int
    last_post_at: datetime | None
    created_at: datetime


class XAccountUpdate(BaseModel):
    default_prompt_id: int | None = None
    posting_enabled: bool | None = None
    daily_limit: int | None = Field(default=None, ge=1, le=100)
    min_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    max_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    active_hours_start: int | None = Field(default=None, ge=0, le=23)
    active_hours_end: int | None = Field(default=None, ge=0, le=23)
    proxy_id: int | None = None


@router.get("", response_model=list[XAccountOut])
def list_accounts(
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> list[XAccount]:
    return list(
        db.scalars(
            select(XAccount)
            .where(XAccount.operator_id == op.id)
            .order_by(XAccount.created_at.desc())
        ).all()
    )


@router.patch("/{account_id}", response_model=XAccountOut)
def update_account(
    account_id: int,
    payload: XAccountUpdate,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> XAccount:
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

    new_min = data.get("min_interval_minutes", acc.min_interval_minutes)
    new_max = data.get("max_interval_minutes", acc.max_interval_minutes)
    if new_min > new_max:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "min interval ต้อง ≤ max interval"
        )

    for k, v in data.items():
        setattr(acc, k, v)
    db.commit()
    db.refresh(acc)

    scheduler.refresh_account(acc.id)
    return acc


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
    content: str = Field(min_length=1, max_length=4000)


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

    result = await post_tweet(account_id=account_id, content=payload.content)
    return TestPostOut(ok=result.ok, error=result.error)

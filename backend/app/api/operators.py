from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.core.passwords import hash_password, verify_password
from app.db.database import get_db
from app.db.models import Operator
from app.db.utils import utcnow
from app.services.scheduler import scheduler

router = APIRouter(prefix="/operators", tags=["operators"])


class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    avatar_color: str
    rotation_interval_seconds: int
    parallel_posts: int
    created_at: datetime
    last_login_at: datetime | None


class OperatorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    passphrase: str = Field(min_length=4, max_length=128)
    avatar_color: str = Field(default="#F4A6CD", pattern=r"^#[0-9A-Fa-f]{6}$")


class OperatorLogin(BaseModel):
    name: str
    passphrase: str


class OperatorUpdate(BaseModel):
    rotation_interval_seconds: int | None = Field(default=None, ge=1, le=3600)
    # 1 = original sequential behavior. 4 cap matches the analysis in the
    # design discussion — beyond that, RAM (4× Chromium) and X anti-spam
    # detection start dominating the gains.
    parallel_posts: int | None = Field(default=None, ge=1, le=6)
    avatar_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


@router.get("", response_model=list[OperatorOut])
def list_operators(db: Annotated[Session, Depends(get_db)]) -> list[Operator]:
    return list(db.scalars(select(Operator).order_by(Operator.created_at)).all())


@router.post("", response_model=OperatorOut, status_code=status.HTTP_201_CREATED)
def create_operator(
    payload: OperatorCreate,
    db: Annotated[Session, Depends(get_db)],
) -> Operator:
    existing = db.scalar(select(Operator).where(Operator.name == payload.name))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "ชื่อโปรไฟล์นี้ถูกใช้แล้ว")
    op = Operator(
        name=payload.name,
        passphrase_hash=hash_password(payload.passphrase),
        avatar_color=payload.avatar_color,
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return op


@router.post("/login", response_model=OperatorOut)
def login_operator(
    payload: OperatorLogin,
    db: Annotated[Session, Depends(get_db)],
) -> Operator:
    op = db.scalar(select(Operator).where(Operator.name == payload.name))
    if op is None or not verify_password(op.passphrase_hash, payload.passphrase):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "ชื่อหรือรหัสผ่านไม่ถูกต้อง"
        )
    op.last_login_at = utcnow()
    db.commit()
    db.refresh(op)
    return op


@router.patch("/{operator_id}", response_model=OperatorOut)
def update_operator(
    operator_id: int,
    payload: OperatorUpdate,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> Operator:
    if op.id != operator_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "ไม่สามารถแก้ไขโปรไฟล์ของคนอื่น"
        )
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(op, k, v)
    db.commit()
    db.refresh(op)
    if "rotation_interval_seconds" in data or "parallel_posts" in data:
        scheduler.refresh_operator(op.id)
    return op

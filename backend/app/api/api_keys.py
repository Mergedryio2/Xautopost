from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.core.crypto import get_crypto
from app.db.database import get_db
from app.db.models import ApiKey, Operator

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: str
    label: str | None
    created_at: datetime


class ApiKeyCreate(BaseModel):
    provider: str = Field(pattern=r"^(openai|gemini)$")
    label: str | None = Field(default=None, max_length=64)
    key: str = Field(min_length=8, max_length=512)


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ApiKey]:
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.operator_id == op.id)
            .order_by(ApiKey.created_at.desc())
        ).all()
    )


@router.post("", response_model=ApiKeyOut, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: ApiKeyCreate,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> ApiKey:
    crypto = get_crypto()
    k = ApiKey(
        operator_id=op.id,
        provider=payload.provider,
        label=payload.label,
        key_enc=crypto.encrypt_str(payload.key),
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


@router.delete("/{key_id}")
def delete_api_key(
    key_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    k = db.get(ApiKey, key_id)
    if k is None or k.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "api key not found")
    db.delete(k)
    db.commit()
    return {"ok": True}

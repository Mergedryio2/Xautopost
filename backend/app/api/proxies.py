from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.core.crypto import get_crypto
from app.db.database import get_db
from app.db.models import Operator, Proxy

router = APIRouter(prefix="/proxies", tags=["proxies"])


class ProxyOut(BaseModel):
    id: int
    label: str
    server: str
    has_credentials: bool


def _to_out(p: Proxy) -> ProxyOut:
    return ProxyOut(
        id=p.id,
        label=p.label,
        server=p.server,
        has_credentials=p.username_enc is not None or p.password_enc is not None,
    )


class ProxyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    server: str = Field(min_length=4, max_length=255)
    username: str | None = None
    password: str | None = None


@router.get("", response_model=list[ProxyOut])
def list_proxies(
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ProxyOut]:
    items = list(
        db.scalars(
            select(Proxy)
            .where(Proxy.operator_id == op.id)
            .order_by(Proxy.created_at.desc())
        ).all()
    )
    return [_to_out(p) for p in items]


@router.post("", response_model=ProxyOut, status_code=status.HTTP_201_CREATED)
def create_proxy(
    payload: ProxyCreate,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> ProxyOut:
    crypto = get_crypto()
    p = Proxy(
        operator_id=op.id,
        label=payload.label,
        server=payload.server,
        username_enc=crypto.encrypt_str(payload.username) if payload.username else None,
        password_enc=crypto.encrypt_str(payload.password) if payload.password else None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/{proxy_id}")
def delete_proxy(
    proxy_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    p = db.get(Proxy, proxy_id)
    if p is None or p.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proxy not found")
    db.delete(p)
    db.commit()
    return {"ok": True}

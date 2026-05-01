from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.db.database import get_db
from app.db.models import Operator, PostLog, XAccount

router = APIRouter(prefix="/logs", tags=["logs"])


class PostLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    x_account_id: int | None
    timestamp: datetime
    content: str | None
    status: str
    detail: str | None
    tweet_url: str | None


@router.get("", response_model=list[PostLogOut])
def list_logs(
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
    account_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[PostLog]:
    operator_account_ids = list(
        db.scalars(
            select(XAccount.id).where(XAccount.operator_id == op.id)
        ).all()
    )
    if not operator_account_ids:
        return []

    q = select(PostLog).where(PostLog.x_account_id.in_(operator_account_ids))
    if account_id is not None:
        if account_id not in operator_account_ids:
            return []
        q = q.where(PostLog.x_account_id == account_id)
    if status_filter:
        q = q.where(PostLog.status == status_filter)
    q = q.order_by(PostLog.timestamp.desc()).limit(limit)

    return list(db.scalars(q).all())

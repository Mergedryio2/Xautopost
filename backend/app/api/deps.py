from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Operator


def get_current_operator(
    db: Annotated[Session, Depends(get_db)],
    x_operator_id: Annotated[int | None, Header(alias="X-Operator-Id")] = None,
) -> Operator:
    if x_operator_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing X-Operator-Id header"
        )
    op = db.get(Operator, x_operator_id)
    if op is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "operator not found")
    return op

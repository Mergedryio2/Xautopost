from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.db.database import get_db
from app.db.models import MediaAsset, Operator, Prompt
from app.services.media import (
    MediaError,
    delete_file,
    extract_media_tokens,
    media_path,
    save_upload_stream,
)

router = APIRouter(prefix="/media", tags=["media"])


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    original_name: str | None
    mime_type: str
    kind: str
    size_bytes: int
    created_at: datetime


@router.get("", response_model=list[MediaAssetOut])
def list_media(
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> list[MediaAsset]:
    return list(
        db.scalars(
            select(MediaAsset)
            .where(MediaAsset.operator_id == op.id)
            .order_by(MediaAsset.created_at.desc())
        ).all()
    )


@router.post(
    "", response_model=MediaAssetOut, status_code=status.HTTP_201_CREATED
)
def upload_media(
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File(...)],
) -> MediaAsset:
    if not file.content_type:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ไม่พบชนิดไฟล์ (Content-Type) ของไฟล์ที่อัปโหลด",
        )
    try:
        stored = save_upload_stream(
            operator_id=op.id, mime_type=file.content_type, src=file.file
        )
    except MediaError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    row = MediaAsset(
        operator_id=op.id,
        filename=stored.filename,
        original_name=file.filename,
        mime_type=stored.mime_type,
        kind=stored.kind,
        size_bytes=stored.size_bytes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/{media_id}/file")
def serve_media(
    media_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    row = db.get(MediaAsset, media_id)
    if row is None or row.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media not found")
    p = media_path(op.id, row.filename)
    if p is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "ไฟล์หาย — น่าจะถูกลบจากดิสก์"
        )
    # Default content_disposition_type is "attachment" which forces a download
    # in some browsers; we want inline so <img>/<video> can render the blob.
    return FileResponse(
        path=str(p),
        media_type=row.mime_type,
        content_disposition_type="inline",
    )


@router.delete("/{media_id}")
def delete_media(
    media_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    row = db.get(MediaAsset, media_id)
    if row is None or row.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media not found")

    # Refuse to delete media that's still referenced by a prompt — otherwise
    # the next manual tick that picks that candidate posts text without the
    # media, and the user has no way to know why their image disappeared.
    in_use = _prompt_using_media(db, op.id, media_id)
    if in_use:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f'สไตล์ "{in_use}" ยังใช้ไฟล์นี้อยู่ · ลบ token [media:{media_id}] '
            "ออกจากสไตล์นั้นก่อน",
        )

    db.delete(row)
    db.commit()
    delete_file(op.id, row.filename)
    return {"ok": True}


def _prompt_using_media(db: Session, operator_id: int, media_id: int) -> str | None:
    """Return the name of the first prompt that still references this media,
    or None if it's safe to delete."""
    prompts = db.scalars(
        select(Prompt).where(Prompt.operator_id == operator_id)
    ).all()
    for p in prompts:
        if p.mode != "manual":
            continue
        # Cheap pre-filter so we don't tokenize every body unnecessarily.
        marker = f"[media:{media_id}]"
        if marker in (p.body or ""):
            for part in (p.body or "").split("\n---\n"):
                _, ids = extract_media_tokens(part)
                if media_id in ids:
                    return p.name
    return None

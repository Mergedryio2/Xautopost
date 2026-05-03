from __future__ import annotations

import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

log = logging.getLogger(__name__)

# Storage layout: <data_dir>/media/<operator_id>/<uuid>.<ext>. UUID filenames
# guarantee no collisions and no path-traversal surface from user-supplied names.
MEDIA_DIR: Path = settings.data_dir / "media"

# Cap matches the design decision in the analysis (rough X limits + practical
# disk usage). X actually accepts up to ~5MB images / ~512MB videos, but we
# keep videos modest to bound the local data dir.
IMAGE_MAX_BYTES = 5 * 1024 * 1024
VIDEO_MAX_BYTES = 50 * 1024 * 1024

# X-supported formats. Anything outside this list rejects with a clear error
# so the user doesn't waste an upload only to have the post fail later.
IMAGE_MIMES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
VIDEO_MIMES: dict[str, str] = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}


class MediaError(Exception):
    """Raised for user-fixable upload problems (size, type, IO). Caller turns
    this into an HTTP 400 with the message visible to the user."""


@dataclass
class StoredMedia:
    filename: str
    mime_type: str
    kind: str  # 'image' or 'video'
    size_bytes: int


def _operator_dir(operator_id: int) -> Path:
    p = MEDIA_DIR / str(operator_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def classify(mime_type: str) -> tuple[str, str]:
    """Return (kind, extension) or raise MediaError if the type isn't allowed."""
    if mime_type in IMAGE_MIMES:
        return "image", IMAGE_MIMES[mime_type]
    if mime_type in VIDEO_MIMES:
        return "video", VIDEO_MIMES[mime_type]
    raise MediaError(
        f"ไม่รองรับชนิดไฟล์ {mime_type} · รับเฉพาะ JPG/PNG/GIF/WebP/MP4/MOV"
    )


def save_upload_stream(
    *,
    operator_id: int,
    mime_type: str,
    src,  # file-like with .read() (UploadFile.file)
) -> StoredMedia:
    """Stream an uploaded file to disk while enforcing the per-kind size cap.
    Cleans up the partial file on error so we don't leak bytes when the user
    blows past the limit."""
    kind, ext = classify(mime_type)
    cap = IMAGE_MAX_BYTES if kind == "image" else VIDEO_MAX_BYTES

    name = f"{uuid.uuid4().hex}{ext}"
    dest = _operator_dir(operator_id) / name

    written = 0
    chunk_size = 1 << 20  # 1MB
    try:
        with dest.open("wb") as out:
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > cap:
                    raise MediaError(
                        f"ไฟล์ใหญ่เกิน {cap // (1024 * 1024)} MB"
                    )
                out.write(chunk)
    except MediaError:
        dest.unlink(missing_ok=True)
        raise
    except OSError as e:
        dest.unlink(missing_ok=True)
        raise MediaError(f"บันทึกไฟล์ไม่สำเร็จ: {e}") from e

    return StoredMedia(
        filename=name, mime_type=mime_type, kind=kind, size_bytes=written
    )


def media_path(operator_id: int, filename: str) -> Path | None:
    """Resolve a stored media filename to its on-disk path. Returns None if
    the file is missing (e.g., disk was wiped while the DB row survived)."""
    p = _operator_dir(operator_id) / filename
    return p if p.is_file() else None


def resolve_media_ids(
    db: Session, operator_id: int, ids: list[int]
) -> list[Path]:
    """Look up MediaAsset rows for the given ids belonging to the operator
    and return their on-disk paths in the *same order* as `ids`. Silently
    drops missing rows / missing files so the caller can post text-only
    rather than fail outright when a referenced asset was deleted."""
    # Local import: media.py is imported from main.py at boot via
    # `from app.api import media`, and api/media.py also imports models —
    # importing models here at module level would force the chain to load
    # in the wrong order during cold start.
    from app.db.models import MediaAsset

    if not ids:
        return []
    rows = list(
        db.scalars(
            select(MediaAsset).where(
                MediaAsset.id.in_(ids),
                MediaAsset.operator_id == operator_id,
            )
        ).all()
    )
    by_id = {r.id: r for r in rows}
    paths: list[Path] = []
    for mid in ids:
        row = by_id.get(mid)
        if row is None:
            continue
        p = media_path(operator_id, row.filename)
        if p is not None:
            paths.append(p)
    return paths


def delete_file(operator_id: int, filename: str) -> None:
    """Best-effort delete. Missing file is fine (DB-only rows can exist after
    a crash); we just want the disk reclaimed when present."""
    p = _operator_dir(operator_id) / filename
    try:
        p.unlink(missing_ok=True)
    except OSError:
        log.exception("failed to delete media file %s", p)


def remove_operator_dir(operator_id: int) -> None:
    """Wipe an operator's media folder when the operator is deleted."""
    p = MEDIA_DIR / str(operator_id)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


# `[media:N]` token, where N is the asset id. Tokens can sit anywhere in the
# candidate; we strip them out of the post text and return the ids in order.
_MEDIA_TOKEN = re.compile(r"\[media:(\d+)\]")


def extract_media_tokens(text: str) -> tuple[str, list[int]]:
    """Pull `[media:N]` tokens out of a candidate. Returns the cleaned text
    (token markers removed, surrounding whitespace tidied) and the ordered
    list of media ids referenced — duplicates preserved so the user can post
    the same asset twice if they really want to."""
    if not text:
        return text, []

    ids: list[int] = []

    def _take(match: re.Match[str]) -> str:
        ids.append(int(match.group(1)))
        return ""

    cleaned = _MEDIA_TOKEN.sub(_take, text)
    # Collapse the blank line(s) the removed tokens leave behind so the
    # resulting post text doesn't have an awkward gap at the top.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, ids

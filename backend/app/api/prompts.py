from __future__ import annotations

import random
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_operator
from app.core.crypto import get_crypto
from app.db.database import get_db
from app.db.models import ApiKey, Operator, Prompt
from app.services.ai import generate_content
from app.services.manual import apply_decoration, split_manual
from app.services.media import extract_media_tokens

router = APIRouter(prefix="/prompts", tags=["prompts"])


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    body: str
    mode: str
    decorate_emoji: bool
    decorate_letters: bool
    provider: str
    model: str
    fallback_text: str | None
    created_at: datetime


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1)
    mode: str = Field(default="ai", pattern=r"^(ai|manual)$")
    decorate_emoji: bool = True
    decorate_letters: bool = False
    provider: str = Field(default="openai", pattern=r"^(openai|gemini)$")
    model: str = Field(default="gpt-4o-mini", min_length=1, max_length=64)
    fallback_text: str | None = None


class PromptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    body: str | None = Field(default=None, min_length=1)
    mode: str | None = Field(default=None, pattern=r"^(ai|manual)$")
    decorate_emoji: bool | None = None
    decorate_letters: bool | None = None
    provider: str | None = Field(default=None, pattern=r"^(openai|gemini)$")
    model: str | None = Field(default=None, min_length=1, max_length=64)
    fallback_text: str | None = None


class GenerateOut(BaseModel):
    text: str
    provider: str
    model: str
    # For manual prompts: any [media:N] tokens in the picked candidate are
    # surfaced here so the test-post UI can show what would be attached.
    # AI prompts always return [].
    media_ids: list[int] = []


@router.get("", response_model=list[PromptOut])
def list_prompts(
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Prompt]:
    return list(
        db.scalars(
            select(Prompt)
            .where(Prompt.operator_id == op.id)
            .order_by(Prompt.created_at.desc())
        ).all()
    )


@router.post("", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
def create_prompt(
    payload: PromptCreate,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> Prompt:
    p = Prompt(
        operator_id=op.id,
        name=payload.name,
        body=payload.body,
        mode=payload.mode,
        decorate_emoji=payload.decorate_emoji,
        decorate_letters=payload.decorate_letters,
        provider=payload.provider,
        model=payload.model,
        fallback_text=payload.fallback_text,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/{prompt_id}", response_model=PromptOut)
def update_prompt(
    prompt_id: int,
    payload: PromptUpdate,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> Prompt:
    p = db.get(Prompt, prompt_id)
    if p is None or p.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{prompt_id}")
def delete_prompt(
    prompt_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, bool]:
    p = db.get(Prompt, prompt_id)
    if p is None or p.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt not found")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/{prompt_id}/generate", response_model=GenerateOut)
async def generate_from_prompt(
    prompt_id: int,
    op: Annotated[Operator, Depends(get_current_operator)],
    db: Annotated[Session, Depends(get_db)],
) -> GenerateOut:
    p = db.get(Prompt, prompt_id)
    if p is None or p.operator_id != op.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt not found")

    if p.mode == "manual":
        candidates = split_manual(p.body)
        if not candidates:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "ยังไม่มีข้อความให้สุ่มเลือก · เปิดแก้ไขสไตล์แล้วใส่ข้อความก่อนนะคะ",
            )
        picked = random.choice(candidates)
        text, media_ids = extract_media_tokens(picked)
        text = apply_decoration(
            text,
            with_emoji=p.decorate_emoji,
            with_letters=p.decorate_letters,
        )
        return GenerateOut(
            text=text, provider="manual", model="-", media_ids=media_ids
        )

    key_row = db.scalar(
        select(ApiKey)
        .where(ApiKey.operator_id == op.id, ApiKey.provider == p.provider)
        .order_by(ApiKey.created_at.desc())
    )
    if key_row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"ยังไม่มี API key ของ {p.provider} ค่ะ — เพิ่มที่แท็บ API Key ก่อนนะคะ",
        )

    api_key = get_crypto().decrypt_str(key_row.key_enc)
    try:
        text = await generate_content(
            provider=p.provider,  # type: ignore[arg-type]
            model=p.model,
            system_prompt=p.body,
            api_key=api_key,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"AI provider error: {e}"
        ) from e

    return GenerateOut(text=text, provider=p.provider, model=p.model)

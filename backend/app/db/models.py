from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utcnow


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    passphrase_hash: Mapped[str] = mapped_column(String(255))
    avatar_color: Mapped[str] = mapped_column(String(16), default="#F4A6CD")
    rotation_interval_seconds: Mapped[int] = mapped_column(default=5)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)


class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(64))
    server: Mapped[str] = mapped_column(String(255))  # http://host:port
    username_enc: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    password_enc: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class XAccount(Base):
    __tablename__ = "x_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), index=True
    )
    handle: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(128), default=None)
    storage_state_enc: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    proxy_id: Mapped[int | None] = mapped_column(
        ForeignKey("proxies.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(String(32), default="unverified")
    daily_limit: Mapped[int] = mapped_column(default=10)
    default_prompt_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL"), default=None
    )
    posting_enabled: Mapped[bool] = mapped_column(default=False)
    min_interval_minutes: Mapped[int] = mapped_column(default=60)
    max_interval_minutes: Mapped[int] = mapped_column(default=240)
    active_hours_start: Mapped[int] = mapped_column(default=9)
    active_hours_end: Mapped[int] = mapped_column(default=22)
    last_post_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))  # openai / gemini
    label: Mapped[str | None] = mapped_column(String(64), default=None)
    key_enc: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    body: Mapped[str] = mapped_column(Text)
    # 'ai' = body is the system prompt, AI generates each post.
    # 'manual' = body is the literal post text(s); split by `\n---\n` and the
    # scheduler picks one at random per tick. No AI / API key needed.
    mode: Mapped[str] = mapped_column(String(16), default="ai")
    # Append a random decorative emoji to each manual post so X doesn't see
    # the same text twice and reject as duplicate. AI prompts ignore this
    # (their output is naturally varied).
    vary_decoration: Mapped[bool] = mapped_column(default=True)
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    model: Mapped[str] = mapped_column(String(64), default="gpt-4o-mini")
    fallback_text: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PostQueue(Base):
    __tablename__ = "posts_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    x_account_id: Mapped[int] = mapped_column(
        ForeignKey("x_accounts.id", ondelete="CASCADE"), index=True
    )
    prompt_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL"), default=None
    )
    content: Mapped[str | None] = mapped_column(Text, default=None)
    scheduled_at: Mapped[datetime] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)


class PostLog(Base):
    __tablename__ = "post_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    x_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("x_accounts.id", ondelete="SET NULL"), default=None, index=True
    )
    queue_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts_queue.id", ondelete="SET NULL"), default=None
    )
    timestamp: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    content: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[str] = mapped_column(String(16))  # success / failed / skipped
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    tweet_url: Mapped[str | None] = mapped_column(String(255), default=None)

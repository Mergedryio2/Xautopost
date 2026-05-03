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
    # Concurrency cap for the rotation: how many of this operator's accounts
    # can be mid-post at once. 1 keeps the original sequential behavior;
    # raising it spawns up to N concurrent Playwright browsers. Bounded at
    # the API layer (1-4) — beyond that hits diminishing returns vs. memory
    # and X anti-spam pattern detection.
    parallel_posts: Mapped[int] = mapped_column(default=1)
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
    # 0 = unlimited (no daily ceiling). Otherwise the scheduler stops posting
    # for the rest of the day once `count >= daily_limit`.
    daily_limit: Mapped[int] = mapped_column(default=0)
    default_prompt_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL"), default=None
    )
    posting_enabled: Mapped[bool] = mapped_column(default=False)
    # Per-account spacing in *seconds*. Scheduler picks a uniform random
    # target in [min, max] and refuses to post the same account again until
    # that much time has passed since `last_post_at`.
    min_interval_seconds: Mapped[int] = mapped_column(default=3600)
    max_interval_seconds: Mapped[int] = mapped_column(default=14400)
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
    # Append decorations to each manual post so X doesn't see the same text
    # twice and reject as duplicate. AI prompts ignore these (their output is
    # naturally varied). Both flags can be on at once — letters are appended
    # first, then the emoji, so the emoji stays at the visual tail.
    decorate_emoji: Mapped[bool] = mapped_column(default=True)
    decorate_letters: Mapped[bool] = mapped_column(default=False)
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    model: Mapped[str] = mapped_column(String(64), default="gpt-4o-mini")
    fallback_text: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(
        ForeignKey("operators.id", ondelete="CASCADE"), index=True
    )
    # Stored on disk under <data_dir>/media/<operator_id>/<filename>. The
    # filename is a server-generated UUID + extension, so it never reflects
    # untrusted user input and there's no path-traversal surface.
    filename: Mapped[str] = mapped_column(String(128))
    original_name: Mapped[str | None] = mapped_column(String(255), default=None)
    mime_type: Mapped[str] = mapped_column(String(64))
    # 'image' or 'video' — used to enforce X's "no mixing" rule and pick the
    # right wait strategy in the poster (videos take far longer to process).
    kind: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(default=0)
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

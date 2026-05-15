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
    # Tweet index bookkeeping. last_scan_at is the wall-clock time the last
    # successful scrape finished; scan_status is one of 'idle' | 'running' |
    # 'error' (loud failure for the UI). scanned_tweet_count is the count
    # observed at end of last scan — surfaced in the UI so the user can tell
    # whether the scan completed or bailed early.
    last_scan_at: Mapped[datetime | None] = mapped_column(default=None)
    scan_status: Mapped[str] = mapped_column(String(16), default="idle")
    scanned_tweet_count: Mapped[int] = mapped_column(default=0)
    scan_error: Mapped[str | None] = mapped_column(Text, default=None)
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
    # 'reply' = body works like 'ai' or 'manual' depending on reply_source,
    # but the scheduler routes through poster.post_reply instead of post_tweet
    # using target_tweet_id as the parent tweet.
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
    # Reply-mode fields. target_tweet_id is the X tweet id (string because
    # X ids are 64-bit unsigned, beyond JS number safety). reply_repeat_limit
    # caps how many times the scheduler will reply to the same target — 0
    # means unlimited. reply_source picks where the reply text comes from:
    # 'ai' regenerates via the AI prompt body, 'manual' uses body as literal
    # text (same `\n---\n` split as manual mode).
    target_tweet_id: Mapped[str | None] = mapped_column(String(32), default=None)
    reply_repeat_limit: Mapped[int] = mapped_column(default=0)
    reply_source: Mapped[str] = mapped_column(String(16), default="ai")
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
    # When status='success' for a reply, this is the X tweet id of the parent
    # tweet we replied to. The scheduler uses this column to count how many
    # replies we've already sent against reply_repeat_limit on the prompt.
    reply_to_tweet_id: Mapped[str | None] = mapped_column(
        String(32), default=None, index=True
    )


class TweetIndex(Base):
    """Cached snapshot of an X account's own timeline. Populated by the
    Playwright scraper and refreshed periodically. The scheduler reads this
    when running reply-mode prompts so we don't have to re-scrape on every
    tick. tweet_id is X's snowflake id (string — 64-bit unsigned exceeds JS
    safe int range); paired with x_account_id it's unique."""

    __tablename__ = "tweet_index"

    id: Mapped[int] = mapped_column(primary_key=True)
    x_account_id: Mapped[int] = mapped_column(
        ForeignKey("x_accounts.id", ondelete="CASCADE"), index=True
    )
    tweet_id: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str] = mapped_column(String(255))
    # Preview text — full body is on X; we just need enough to render a list
    # row. Truncated to ~500 chars at scrape time.
    text_preview: Mapped[str | None] = mapped_column(Text, default=None)
    has_media: Mapped[bool] = mapped_column(default=False)
    is_reply: Mapped[bool] = mapped_column(default=False)
    is_retweet: Mapped[bool] = mapped_column(default=False)
    is_pinned: Mapped[bool] = mapped_column(default=False)
    posted_at: Mapped[datetime | None] = mapped_column(default=None, index=True)
    scraped_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Set when a subsequent scan no longer sees a tweet that was indexed
    # before. We don't hard-delete the row because there may still be
    # post_logs pointing at it via reply_to_tweet_id.
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)

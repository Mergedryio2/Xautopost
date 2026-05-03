from __future__ import annotations

import random
import re
import string
from collections import deque

# Posts in a manual prompt are separated by a line that contains only "---"
# (3+ dashes), surrounded by optional whitespace. Empty parts are dropped.
_SEPARATOR = re.compile(r"\n\s*-{3,}\s*\n")


def split_manual(body: str) -> list[str]:
    """Split a manual prompt body into individual post candidates."""
    parts = _SEPARATOR.split(body or "")
    return [p.strip() for p in parts if p and p.strip()]


# Curated pool of decorative emojis to append to manual posts. All chosen to be
# tone-neutral so they fit posts about food, mood, weather, daily life, etc.
# without changing the meaning. Wider pool = lower duplicate risk.
EMOJI_POOL: tuple[str, ...] = (
    # botanical / nature
    "🌸", "🌷", "🌹", "🌺", "🌻", "🌼", "🌿", "🍀", "🍃", "🌱", "☘️", "🪷", "🪻",
    # sparkle / sky
    "✨", "⭐", "💫", "🌟", "☀️", "🌙", "☁️", "🌤️", "🌈",
    # hearts (light, won't change tone too much)
    "🤍", "🩷", "💛", "💚", "🩵", "💜",
    # cozy / drinks
    "☕", "🍵", "🧋",
    # bubbles / waves / butterflies
    "🫧", "🌊", "🦋",
    # fruit (light, common)
    "🍓", "🍑", "🍒",
)

# Per-account recency window — refuse to reuse the last N emojis for the same
# account. Single-process in-memory cache; resets on sidecar restart, which is
# fine because X's duplicate detection window is ~24h and a restart that
# infrequent doesn't compound the risk meaningfully.
_RECENT_HISTORY = 12
_RECENT_EMOJIS: dict[int, deque[str]] = {}


def _pick_emoji(account_id: int | None) -> str:
    excluded: set[str] = set()
    if account_id is not None:
        recent = _RECENT_EMOJIS.get(account_id)
        if recent:
            excluded = set(recent)

    pool = [e for e in EMOJI_POOL if e not in excluded]
    if not pool:
        pool = list(EMOJI_POOL)

    emoji = random.choice(pool)

    if account_id is not None:
        ring = _RECENT_EMOJIS.setdefault(
            account_id, deque(maxlen=_RECENT_HISTORY)
        )
        ring.append(emoji)

    return emoji


# 26**4 ≈ 457k combinations — collision probability is negligible at any
# realistic post rate, so no recency window is needed.
_LETTER_LEN = 4


def _pick_letters() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=_LETTER_LEN))


def apply_decoration(
    text: str,
    *,
    with_emoji: bool,
    with_letters: bool,
    account_id: int | None = None,
) -> str:
    """Append decorations so the post isn't an exact duplicate of previous
    identical text. Letters are appended first, then the emoji, so the
    emoji stays at the visual tail when both are enabled."""
    if not text:
        return text
    if not with_emoji and not with_letters:
        return text

    parts: list[str] = [text.rstrip()]
    if with_letters:
        parts.append(_pick_letters())
    if with_emoji:
        parts.append(_pick_emoji(account_id))
    return " ".join(parts)

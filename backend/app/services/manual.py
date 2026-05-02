from __future__ import annotations

import random
import re
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


def decorate(text: str, account_id: int | None = None) -> str:
    """Append a random decorative emoji so the post isn't an exact duplicate
    of a previous identical text. When account_id is given, the emoji is
    drawn from the pool minus the last 12 emojis used on that account, so
    repeats are spread across at least 13 picks before recycling — well
    outside X's duplicate-content detection window for typical post rates."""
    if not text:
        return text

    excluded: set[str] = set()
    if account_id is not None:
        recent = _RECENT_EMOJIS.get(account_id)
        if recent:
            excluded = set(recent)

    pool = [e for e in EMOJI_POOL if e not in excluded]
    if not pool:
        # Defensive: if the exclusion set somehow covered the whole pool
        # (won't happen with 38 emojis vs 12 history slots, but cheap to
        # guard). Fall back to the full pool.
        pool = list(EMOJI_POOL)

    emoji = random.choice(pool)

    if account_id is not None:
        ring = _RECENT_EMOJIS.setdefault(
            account_id, deque(maxlen=_RECENT_HISTORY)
        )
        ring.append(emoji)

    return f"{text.rstrip()} {emoji}"

from __future__ import annotations

import random
import re

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


def decorate(text: str) -> str:
    """Append a random decorative emoji so the post isn't an exact duplicate
    of any previous identical text. Adds a leading space so it sits clean
    after the message regardless of the user's punctuation."""
    if not text:
        return text
    emoji = random.choice(EMOJI_POOL)
    # Trailing-whitespace-aware: avoid double-spacing if user already left a space.
    return f"{text.rstrip()} {emoji}"

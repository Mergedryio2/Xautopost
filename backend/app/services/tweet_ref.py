"""Resolve a user-supplied reference to an X post.

``parse_tweet_ref`` turns a pasted link (or bare numeric id) into a tweet
id. Accepted shapes, current and historical:

    https://x.com/<handle>/status/<id>
    https://x.com/<handle>/status/<id>?s=20&t=...
    https://x.com/i/web/status/<id>
    https://twitter.com/<handle>/status/<id>
    https://mobile.twitter.com/<handle>/statuses/<id>
    https://x.com/<handle>/status/<id>/photo/1
    <id>                        (bare numeric id)

Anything else returns None. The scheduler and poster only need the id —
``/i/web/status/<id>`` resolves to the right post regardless of author —
so the link is kept only for display.

``fetch_tweet_meta`` asks X's public oEmbed endpoint for the author and
text of a post. It needs no login and works for any public post, which
is what makes "add someone else's post by link" possible without a
browser round-trip. Best effort: a failure just means no preview.

``snowflake_time`` recovers the post time from the id itself — X ids are
snowflakes (ms since 2010-11-04 in the top bits), so a link-added row can
sort by posted_at next to scraped rows without asking X for anything.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

log = logging.getLogger(__name__)

_URL_RE = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)*(?:x|twitter)\.com/"
    r"(?:#!/)?(?P<handle>i/web|[A-Za-z0-9_]{1,15})/status(?:es)?/(?P<id>\d{1,25})",
    re.IGNORECASE,
)
_BARE_ID_RE = re.compile(r"^\d{5,25}$")

_OEMBED_URL = "https://publish.x.com/oembed"
_OEMBED_TIMEOUT = 8.0
# Twitter's snowflake epoch, ms. Ids below the first snowflake (Nov 2010)
# are sequential and carry no timestamp.
_SNOWFLAKE_EPOCH_MS = 1_288_834_974_657
_FIRST_SNOWFLAKE_ID = 29_700_859_247

_OEMBED_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


@dataclass(frozen=True)
class TweetRef:
    tweet_id: str
    # Canonical link: keeps the author's handle when the input had one,
    # otherwise falls back to the author-agnostic /i/web/ form.
    url: str
    # Lower-case handle from the link, or None for /i/web/ and bare ids.
    handle: str | None = None


@dataclass(frozen=True)
class TweetMeta:
    tweet_id: str
    author_handle: str  # lower-case, no '@'
    url: str
    text: str | None


def parse_tweet_ref(raw: str | None) -> TweetRef | None:
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if _BARE_ID_RE.match(s):
        return TweetRef(tweet_id=s, url=f"https://x.com/i/web/status/{s}")
    m = _URL_RE.search(s)
    if m is None:
        return None
    tid = m.group("id")
    handle = m.group("handle")
    if handle.lower() == "i/web":
        return TweetRef(tweet_id=tid, url=f"https://x.com/i/web/status/{tid}")
    return TweetRef(
        tweet_id=tid,
        url=f"https://x.com/{handle}/status/{tid}",
        handle=handle.lower(),
    )


def snowflake_time(tweet_id: str) -> datetime | None:
    try:
        n = int(tweet_id)
    except ValueError:
        return None
    if n < _FIRST_SNOWFLAKE_ID:
        return None
    ms = (n >> 22) + _SNOWFLAKE_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _oembed_text(html_blob: str) -> str | None:
    m = _OEMBED_P_RE.search(html_blob)
    if m is None:
        return None
    body = _BR_RE.sub("\n", m.group(1))
    body = _TAG_RE.sub("", body)
    text = html.unescape(body).strip()
    return text[:500] or None


async def fetch_tweet_meta(tweet_id: str) -> TweetMeta | None:
    """Author + text via oEmbed. Returns None for deleted, protected or
    otherwise unreachable posts, and on any network problem."""
    # /i/status/<id> lets X fill in the real author; oEmbed rejects the
    # /i/web/ form but accepts this one.
    params = {
        "url": f"https://x.com/i/status/{tweet_id}",
        "omit_script": "1",
        "dnt": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=_OEMBED_TIMEOUT) as client:
            resp = await client.get(_OEMBED_URL, params=params)
        if resp.status_code != 200:
            log.info("oembed %s -> HTTP %s", tweet_id, resp.status_code)
            return None
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        log.info("oembed %s failed: %s", tweet_id, e)
        return None

    author_url = str(data.get("author_url") or "")
    handle = author_url.rstrip("/").rsplit("/", 1)[-1].lower()
    if not handle:
        return None
    url = str(data.get("url") or f"https://x.com/{handle}/status/{tweet_id}")
    return TweetMeta(
        tweet_id=tweet_id,
        author_handle=handle,
        url=url,
        text=_oembed_text(str(data.get("html") or "")),
    )

// Parse a pasted X post link (or bare numeric id) into a tweet id.
// Mirrors backend/app/services/tweet_ref.py — keep the two in sync so the
// UI never accepts something the API will reject.
//
// Accepted:
//   https://x.com/<handle>/status/<id>[?query][/photo/1]
//   https://x.com/i/web/status/<id>
//   https://twitter.com/<handle>/status(es)/<id>   (incl. mobile./www.)
//   <id>

// handle is lower-case and null for /i/web/ links and bare ids.
export type TweetRef = { tweetId: string; url: string; handle: string | null }

const URL_RE =
  /(?:https?:\/\/)?(?:[\w-]+\.)*(?:x|twitter)\.com\/(?:#!\/)?(i\/web|[A-Za-z0-9_]{1,15})\/status(?:es)?\/(\d{1,25})/i
const BARE_ID_RE = /^\d{5,25}$/

export function parseTweetRef(raw: string): TweetRef | null {
  const s = raw.trim()
  if (!s) return null
  if (BARE_ID_RE.test(s)) {
    return { tweetId: s, url: `https://x.com/i/web/status/${s}`, handle: null }
  }
  const m = URL_RE.exec(s)
  const handle = m?.[1]
  const tweetId = m?.[2]
  if (!handle || !tweetId) return null
  if (handle.toLowerCase() === 'i/web') {
    return { tweetId, url: `https://x.com/i/web/status/${tweetId}`, handle: null }
  }
  return {
    tweetId,
    url: `https://x.com/${handle}/status/${tweetId}`,
    handle: handle.toLowerCase(),
  }
}

// Short, readable form for cards: "x.com/handle/status/123…".
export function shortTweetUrl(url: string): string {
  return url.replace(/^https?:\/\//, '')
}

// "@handle" out of a canonical post URL, or null for the /i/web/ form.
export function handleFromUrl(url: string): string | null {
  const ref = parseTweetRef(url)
  return ref?.handle ? `@${ref.handle}` : null
}

import { useEffect, useMemo, useRef, useState } from 'react'
import { Modal } from './Modal'
import {
  api,
  type ScanStatusOut,
  type TweetOut,
  type XAccountOut,
} from '../lib/api'
import { formatRelative } from '../lib/time'

type Props = {
  open: boolean
  account: XAccountOut | null
  // When provided, switches the modal into "picker" mode: clicking a tweet
  // calls onPick instead of opening the X URL. When undefined the modal is
  // a read-only browser (used from the Accounts page).
  onPick?: (tweet: TweetOut) => void
  // Tweet id currently selected as the reply target — highlighted in the
  // list so the user can tell which one is wired up. Display-only.
  selectedTweetId?: string | null
  onClose: () => void
}

const PAGE_SIZE = 50

export function TweetPickerModal({
  open,
  account,
  onPick,
  selectedTweetId,
  onClose,
}: Props) {
  const [tweets, setTweets] = useState<TweetOut[]>([])
  const [scanStatus, setScanStatus] = useState<ScanStatusOut | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [filterMedia, setFilterMedia] = useState<'any' | 'with' | 'without'>(
    'any',
  )
  const [hasMore, setHasMore] = useState(false)
  const [offset, setOffset] = useState(0)
  const pollRef = useRef<number | null>(null)
  const accountId = account?.id ?? null

  // Debounce the search so we don't fire a request per keystroke. 250ms is
  // short enough to feel reactive while still cutting requests by ~5x for
  // a typical typing speed.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query.trim()), 250)
    return () => clearTimeout(t)
  }, [query])

  async function loadPage(reset: boolean) {
    if (accountId === null) return
    if (loading) return
    setLoading(true)
    setError(null)
    try {
      const nextOffset = reset ? 0 : offset
      const has_media =
        filterMedia === 'with'
          ? true
          : filterMedia === 'without'
            ? false
            : undefined
      const rows = await api.listTweets(accountId, {
        q: debouncedQuery || undefined,
        has_media,
        limit: PAGE_SIZE,
        offset: nextOffset,
      })
      setTweets((prev) => (reset ? rows : [...prev, ...rows]))
      setOffset(nextOffset + rows.length)
      setHasMore(rows.length === PAGE_SIZE)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  // Reset and reload whenever the search or filter changes. The account id
  // is in the dep array so opening a different account also re-fetches.
  useEffect(() => {
    if (!open || accountId === null) return
    setTweets([])
    setOffset(0)
    setHasMore(false)
    void loadPage(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, accountId, debouncedQuery, filterMedia])

  // Initial scan status on open + poll while a scan is running. The poll is
  // cheap (single GET) and the user sees progress live without manual
  // refresh.
  useEffect(() => {
    if (!open || accountId === null) {
      if (pollRef.current !== null) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }
    let cancelled = false

    async function tick() {
      if (accountId === null) return
      try {
        const s = await api.scanStatus(accountId)
        if (cancelled) return
        setScanStatus(s)
        if (!s.running && pollRef.current !== null) {
          clearInterval(pollRef.current)
          pollRef.current = null
          // Re-fetch list when scan finishes so newly-indexed tweets appear.
          void loadPage(true)
        }
      } catch {
        // ignore — transient sidecar hiccup; the next tick will retry
      }
    }

    void tick()
    pollRef.current = window.setInterval(tick, 2000) as unknown as number

    return () => {
      cancelled = true
      if (pollRef.current !== null) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, accountId])

  async function onScan() {
    if (accountId === null) return
    try {
      const s = await api.scanTweets(accountId)
      setScanStatus(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function onCancelScan() {
    if (accountId === null) return
    try {
      await api.cancelScan(accountId)
      // Don't optimistically clear scanStatus — the poll picks up the
      // transition once the background task notices the cancel event.
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const titleSuffix = account?.handle ? ` · ${account.handle}` : ''
  const isPicker = typeof onPick === 'function'
  const scanning = scanStatus?.running ?? false

  const idleLabel = useMemo(() => {
    if (!scanStatus) return 'ยังไม่เคยสแกน'
    if (scanStatus.scan_status === 'error')
      return `สแกนล้มเหลว · ${scanStatus.scan_error ?? 'ไม่ทราบสาเหตุ'}`
    if (scanStatus.last_scan_at)
      return `สแกนล่าสุด ${formatRelative(scanStatus.last_scan_at)} · ${scanStatus.scanned_tweet_count} โพสต์`
    return 'ยังไม่เคยสแกน'
  }, [scanStatus])

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`${isPicker ? 'เลือกโพสต์ที่จะ reply' : 'จัดการโพสต์'}${titleSuffix}`}
      size="lg"
    >
      <div className="tweet-picker">
        <div className="tweet-picker-toolbar">
          <input
            className="tweet-picker-search"
            placeholder="ค้นหาในโพสต์…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="tweet-picker-filter"
            value={filterMedia}
            onChange={(e) =>
              setFilterMedia(e.target.value as 'any' | 'with' | 'without')
            }
          >
            <option value="any">ทุกชนิด</option>
            <option value="with">มีรูป/วิดีโอ</option>
            <option value="without">ข้อความล้วน</option>
          </select>
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={onScan}
            disabled={scanning}
          >
            {scanning ? 'กำลังสแกน…' : 'สแกนใหม่'}
          </button>
        </div>

        {scanning ? (
          <div className="scan-banner">
            <span className="scan-banner-dots">
              <span /><span /><span />
            </span>
            <div className="scan-banner-text">
              <div className="scan-banner-title">
                กำลังสแกนโพสต์ของบัญชีนี้…
              </div>
              <div className="scan-banner-count">
                {scanStatus?.tweets_collected_so_far ?? 0} โพสต์
              </div>
              <div className="scan-banner-sub">
                ไม่ต้องรอ · ปิดหน้าต่างนี้ได้ ระบบจะสแกนต่อในเบื้องหลัง
              </div>
            </div>
            <button
              type="button"
              className="btn-ghost btn-sm"
              onClick={onCancelScan}
            >
              หยุดสแกน
            </button>
          </div>
        ) : (
          <div className="tweet-picker-status">{idleLabel}</div>
        )}

        {error && <div className="form-error">{error}</div>}

        {tweets.length === 0 && !loading ? (
          <div className="tweet-picker-empty">
            {scanStatus?.scanned_tweet_count === 0 && !scanning ? (
              <>
                ยังไม่เคยสแกนบัญชีนี้ — กด "สแกนใหม่" ด้านบนเพื่อให้ระบบไล่ดูโพสต์ทั้งหมด
                <br />
                (ใช้เวลา 1–10 นาทีขึ้นกับจำนวนโพสต์)
              </>
            ) : debouncedQuery ? (
              `ไม่พบโพสต์ที่ตรงกับ "${debouncedQuery}"`
            ) : (
              'ไม่มีโพสต์ตรงกับตัวกรองที่เลือก'
            )}
          </div>
        ) : (
          <ul className="tweet-picker-list">
            {tweets.map((t) => {
              const isSelected =
                selectedTweetId !== null &&
                selectedTweetId !== undefined &&
                t.tweet_id === selectedTweetId
              const isDeleted = t.deleted_at !== null
              return (
                <li
                  key={t.id}
                  className={[
                    'tweet-picker-item',
                    isSelected ? 'is-selected' : '',
                    isDeleted ? 'is-deleted' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  <div className="tweet-picker-item-body">
                    <div className="tweet-picker-item-text">
                      {t.is_pinned && (
                        <span className="tweet-badge tweet-badge-pin">
                          📌 Pinned
                        </span>
                      )}
                      {t.has_media && (
                        <span className="tweet-badge">🖼 มีสื่อ</span>
                      )}
                      {isDeleted && (
                        <span className="tweet-badge tweet-badge-del">
                          ลบแล้ว
                        </span>
                      )}
                      <span className="tweet-picker-item-preview">
                        {t.text_preview || (
                          <em style={{ opacity: 0.6 }}>
                            (ไม่มีข้อความ — โพสต์รูป/วิดีโอเท่านั้น)
                          </em>
                        )}
                      </span>
                    </div>
                    <div className="tweet-picker-item-meta">
                      {t.posted_at ? formatRelative(t.posted_at) : '—'}
                      {' · '}
                      <a
                        href={t.url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        เปิดใน X ↗
                      </a>
                    </div>
                  </div>
                  {isPicker && (
                    <button
                      type="button"
                      className={
                        isSelected ? 'btn-primary btn-sm' : 'btn-ghost btn-sm'
                      }
                      onClick={() => onPick?.(t)}
                      disabled={isDeleted}
                    >
                      {isSelected ? 'เลือกแล้ว' : 'เลือก'}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}

        {hasMore && (
          <div className="tweet-picker-more">
            <button
              type="button"
              className="btn-ghost btn-sm"
              onClick={() => loadPage(false)}
              disabled={loading}
            >
              {loading ? 'กำลังโหลด…' : 'แสดงเพิ่ม'}
            </button>
          </div>
        )}
      </div>
    </Modal>
  )
}

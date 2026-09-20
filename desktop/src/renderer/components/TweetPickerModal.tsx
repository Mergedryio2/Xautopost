import { useEffect, useMemo, useRef, useState } from 'react'
import { Modal } from './Modal'
import {
  api,
  type ScanStatusOut,
  type TweetOut,
  type XAccountOut,
} from '../lib/api'
import { formatRelative } from '../lib/time'
import { handleFromUrl, parseTweetRef } from '../lib/tweetRef'

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

type OwnerFilter = 'any' | 'own' | 'other'
type SourceFilter = 'any' | 'manual' | 'scan'
type SortMode = 'posted' | 'added'
type LinkOwner = 'own' | 'other'

export function TweetPickerModal({
  open,
  account,
  onPick,
  selectedTweetId,
  onClose,
}: Props) {
  const [tweets, setTweets] = useState<TweetOut[]>([])
  const [linkInput, setLinkInput] = useState('')
  const [linkOwner, setLinkOwner] = useState<LinkOwner>('own')
  const [linkBusy, setLinkBusy] = useState(false)
  const [linkError, setLinkError] = useState<string | null>(null)
  const [ownerFilter, setOwnerFilter] = useState<OwnerFilter>('any')
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('any')
  const [sortMode, setSortMode] = useState<SortMode>('posted')
  const [removingId, setRemovingId] = useState<string | null>(null)
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
      const is_own =
        ownerFilter === 'own' ? true : ownerFilter === 'other' ? false : undefined
      const rows = await api.listTweets(accountId, {
        q: debouncedQuery || undefined,
        has_media,
        is_own,
        source: sourceFilter === 'any' ? undefined : sourceFilter,
        sort: sortMode,
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
  }, [
    open,
    accountId,
    debouncedQuery,
    filterMedia,
    ownerFilter,
    sourceFilter,
    sortMode,
  ])

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

  // Reset the link row each time the modal opens so a stale error from the
  // previous session doesn't greet the user.
  useEffect(() => {
    if (open) {
      setLinkInput('')
      setLinkOwner('own')
      setLinkError(null)
      setLinkBusy(false)
    }
  }, [open])

  const titleSuffix = account?.handle ? ` · ${account.handle}` : ''
  const isPicker = typeof onPick === 'function'
  const scanning = scanStatus?.running ?? false
  const myHandle = (account?.handle ?? '').replace(/^@/, '').toLowerCase()

  // Pre-select the owner dropdown from the handle in the pasted link. The
  // user can still override — e.g. a /i/web/ link carries no handle.
  function onLinkInputChange(value: string) {
    setLinkInput(value)
    if (linkError) setLinkError(null)
    const ref = parseTweetRef(value)
    if (ref?.handle && myHandle) {
      setLinkOwner(ref.handle === myHandle ? 'own' : 'other')
    }
  }

  // Save the link into the index (so it shows in the list with its
  // owner tag and survives re-scans), then hand the row to the picker.
  async function onUseLink() {
    if (accountId === null || linkBusy) return
    const ref = parseTweetRef(linkInput)
    if (!ref) {
      setLinkError(
        'ยังไม่ใช่ลิงก์โพสต์ X ค่ะ ลองวางแบบ https://x.com/ชื่อ/status/เลขโพสต์',
      )
      return
    }
    setLinkError(null)
    setLinkBusy(true)
    try {
      const row = await api.addTweetByLink(accountId, {
        link: ref.url,
        is_own: linkOwner === 'own',
      })
      setLinkInput('')
      if (isPicker) {
        onPick?.(row)
        return
      }
      setOwnerFilter('any')
      void loadPage(true)
    } catch (e) {
      setLinkError(e instanceof Error ? e.message : String(e))
    } finally {
      setLinkBusy(false)
    }
  }

  const recentLinksActive = sourceFilter === 'manual' && sortMode === 'added'

  // One-click preset for "the links I just pasted": link-added rows,
  // newest addition first. Clicking again returns to the default view.
  function toggleRecentLinks() {
    if (recentLinksActive) {
      setSourceFilter('any')
      setSortMode('posted')
    } else {
      setSourceFilter('manual')
      setSortMode('added')
    }
  }

  const filtersActive =
    filterMedia !== 'any' ||
    ownerFilter !== 'any' ||
    sourceFilter !== 'any' ||
    sortMode !== 'posted'

  function resetFilters() {
    setFilterMedia('any')
    setOwnerFilter('any')
    setSourceFilter('any')
    setSortMode('posted')
  }

  async function onRemove(t: TweetOut) {
    if (accountId === null || removingId !== null) return
    setRemovingId(t.tweet_id)
    try {
      await api.deleteTweet(accountId, t.tweet_id)
      setTweets((prev) => prev.filter((x) => x.tweet_id !== t.tweet_id))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRemovingId(null)
    }
  }

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
            aria-label="ค้นหาในโพสต์"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="tweet-picker-filter"
            aria-label="ชนิดสื่อ"
            value={filterMedia}
            onChange={(e) =>
              setFilterMedia(e.target.value as 'any' | 'with' | 'without')
            }
          >
            <option value="any">ทุกชนิด</option>
            <option value="with">มีรูป/วิดีโอ</option>
            <option value="without">ข้อความล้วน</option>
          </select>
          <select
            className="tweet-picker-filter"
            aria-label="เจ้าของโพสต์"
            value={ownerFilter}
            onChange={(e) => setOwnerFilter(e.target.value as OwnerFilter)}
          >
            <option value="any">ทั้งเราและคนอื่น</option>
            <option value="own">โพสต์เรา</option>
            <option value="other">โพสต์คนอื่น</option>
          </select>
          <select
            className="tweet-picker-filter"
            aria-label="ที่มาของโพสต์"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as SourceFilter)}
          >
            <option value="any">ทุกที่มา</option>
            <option value="manual">จาก link</option>
            <option value="scan">จากการสแกน</option>
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

        <div className="tweet-picker-toolbar tweet-picker-toolbar-secondary">
          <button
            type="button"
            className={
              'tweet-picker-preset' + (recentLinksActive ? ' is-active' : '')
            }
            aria-pressed={recentLinksActive}
            onClick={toggleRecentLinks}
            title="เฉพาะโพสต์ที่เพิ่มจาก link เรียงตามที่เพิ่งเพิ่ม"
          >
            🔗 link ที่เพิ่มล่าสุด
          </button>
          <select
            className="tweet-picker-filter"
            aria-label="การเรียงลำดับ"
            value={sortMode}
            onChange={(e) => setSortMode(e.target.value as SortMode)}
          >
            <option value="posted">เรียง: โพสต์ล่าสุดก่อน</option>
            <option value="added">เรียง: เพิ่มล่าสุดก่อน</option>
          </select>
        </div>

        <div className="tweet-picker-link">
          <div className="tweet-picker-link-head">
            <label
              className="tweet-picker-link-label"
              htmlFor="tweet-picker-link-input"
            >
              {isPicker ? 'Link ที่ต้องการตอบกลับ' : 'เพิ่มโพสต์จาก link'}
            </label>
            <span className="muted-note is-inline">
              ใช้ได้ทั้งโพสต์เราและของคนอื่น ไม่ต้องสแกนก่อน และไม่หายตอนสแกนใหม่
            </span>
          </div>
          <div className="tweet-picker-link-row">
            <input
              id="tweet-picker-link-input"
              className="tweet-picker-search"
              placeholder="https://x.com/ชื่อ/status/1234567890"
              value={linkInput}
              onChange={(e) => onLinkInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void onUseLink()
                }
              }}
              disabled={linkBusy}
              aria-invalid={linkError !== null}
              aria-describedby={linkError ? 'tweet-picker-link-error' : undefined}
            />
            <select
              className="tweet-picker-filter"
              aria-label="โพสต์นี้เป็นของใคร"
              value={linkOwner}
              onChange={(e) => setLinkOwner(e.target.value as LinkOwner)}
              disabled={linkBusy}
            >
              <option value="own">โพสต์เรา</option>
              <option value="other">โพสต์คนอื่น</option>
            </select>
            <button
              type="button"
              className="btn-primary btn-sm"
              onClick={() => void onUseLink()}
              disabled={!linkInput.trim() || linkBusy || accountId === null}
            >
              {linkBusy ? 'กำลังเพิ่ม…' : isPicker ? 'ใช้ link นี้' : 'เพิ่มเข้า index'}
            </button>
          </div>
          {linkError && (
            <div className="form-error" id="tweet-picker-link-error" role="alert">
              {linkError}
            </div>
          )}
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

        {error && <div className="form-error" role="alert">{error}</div>}

        {loading && tweets.length === 0 ? (
          <ul className="tweet-picker-list" aria-busy="true" aria-label="กำลังโหลด">
            {[0, 1, 2].map((i) => (
              <li key={i} className="tweet-picker-skeleton" aria-hidden="true">
                <span style={{ width: `${72 - i * 14}%` }} />
                <span style={{ width: '38%' }} />
              </li>
            ))}
          </ul>
        ) : tweets.length === 0 ? (
          <div className="tweet-picker-empty">
            {scanStatus?.scanned_tweet_count === 0 && !scanning && !filtersActive ? (
              <>
                ยังไม่เคยสแกนบัญชีนี้ · กด "สแกนใหม่" ด้านบนเพื่อให้ระบบไล่ดูโพสต์ทั้งหมด
                <br />
                (ใช้เวลา 1–10 นาทีขึ้นกับจำนวนโพสต์) หรือวาง link โพสต์ด้านบนเพื่อเพิ่มทีละโพสต์
              </>
            ) : debouncedQuery ? (
              <>ไม่พบโพสต์ที่ตรงกับ "{debouncedQuery}"</>
            ) : recentLinksActive ? (
              <>ยังไม่มีโพสต์ที่เพิ่มจาก link · วาง link ด้านบนเพื่อเพิ่ม</>
            ) : (
              <>ไม่มีโพสต์ตรงกับตัวกรองที่เลือก</>
            )}
            {filtersActive && (
              <div className="tweet-picker-empty-actions">
                <button
                  type="button"
                  className="btn-ghost btn-sm"
                  onClick={resetFilters}
                >
                  ล้างตัวกรองทั้งหมด
                </button>
              </div>
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
                          📌 ปักหมุด
                        </span>
                      )}
                      {t.has_media && (
                        <span className="tweet-badge">🖼 มีสื่อ</span>
                      )}
                      {!t.is_own && (
                        <span className="tweet-badge tweet-badge-other">
                          👤 คนอื่น{handleFromUrl(t.url) ? ` · ${handleFromUrl(t.url)}` : ''}
                        </span>
                      )}
                      {t.source === 'manual' && (
                        <span className="tweet-badge tweet-badge-manual">
                          🔗 จาก link
                        </span>
                      )}
                      {isDeleted && (
                        <span className="tweet-badge tweet-badge-del">
                          ลบแล้ว
                        </span>
                      )}
                      <span className="tweet-picker-item-preview">
                        {t.text_preview || (
                          <em style={{ opacity: 0.6 }}>
                            (ไม่มีข้อความ · โพสต์รูป/วิดีโอเท่านั้น)
                          </em>
                        )}
                      </span>
                    </div>
                    <div className="tweet-picker-item-meta">
                      {[
                        t.posted_at ? formatRelative(t.posted_at) : null,
                        (sortMode === 'added' || t.source === 'manual') &&
                        t.added_at
                          ? `เพิ่มเมื่อ ${formatRelative(t.added_at)}`
                          : null,
                      ]
                        .filter(Boolean)
                        .map((part) => (
                          <span key={part as string}>{part} · </span>
                        ))}
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
                  <div className="tweet-picker-item-actions">
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
                    {t.source === 'manual' && (
                      <button
                        type="button"
                        className="btn-ghost btn-sm btn-danger"
                        onClick={() => void onRemove(t)}
                        disabled={removingId !== null || isSelected}
                        title={
                          isSelected
                            ? 'เลือกเป็น target อยู่ — เปลี่ยน target ก่อนลบ'
                            : 'เอาออกจาก index'
                        }
                      >
                        {removingId === t.tweet_id ? 'กำลังลบ…' : 'ลบออก'}
                      </button>
                    )}
                  </div>
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

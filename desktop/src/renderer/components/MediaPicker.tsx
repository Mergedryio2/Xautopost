import { useEffect, useRef, useState } from 'react'
import { Modal } from './Modal'
import { api, type MediaAssetOut } from '../lib/api'

export function MediaPicker({
  open,
  multi = false,
  onClose,
  onPick,
}: {
  open: boolean
  // When true the user can pick several files in one go (e.g. building a
  // 4-image post). Single-pick mode closes the modal on the first selection.
  multi?: boolean
  onClose: () => void
  onPick: (mediaIds: number[]) => void
}) {
  const [items, setItems] = useState<MediaAssetOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const list = await api.listMedia()
      setItems(list)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    setSelectedIds(new Set())
    setConfirmDeleteId(null)
    refresh()
  }, [open])

  async function onUploadFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setUploading(true)
    setError(null)
    const errors: string[] = []
    for (const f of Array.from(files)) {
      try {
        await api.uploadMedia(f)
      } catch (e) {
        errors.push(`${f.name}: ${e instanceof Error ? e.message : String(e)}`)
      }
    }
    if (errors.length > 0) setError(errors.join(' · '))
    setUploading(false)
    await refresh()
  }

  function toggle(id: number) {
    if (!multi) {
      onPick([id])
      onClose()
      return
    }
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function onConfirmPick() {
    onPick(Array.from(selectedIds))
    onClose()
  }

  async function onDelete(id: number) {
    setError(null)
    try {
      await api.deleteMedia(id)
      setConfirmDeleteId(null)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="คลังไฟล์" size="lg">
      <div className="modal-form">
        <div className="form-actions" style={{ justifyContent: 'flex-start' }}>
          <button
            type="button"
            className="btn-primary"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'กำลังอัปโหลด…' : '📤 อัปโหลดไฟล์ใหม่'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/jpeg,image/png,image/gif,image/webp,video/mp4,video/quicktime"
            style={{ display: 'none' }}
            onChange={(e) => {
              onUploadFiles(e.target.files)
              e.target.value = ''
            }}
          />
          <span className="muted-note">
            รูป ≤ 5 MB · วิดิโอ ≤ 50 MB · JPG/PNG/GIF/WebP/MP4/MOV
          </span>
        </div>

        {error && <div className="form-error">{error}</div>}

        {loading ? (
          <div className="empty-state empty-small">
            <span className="dots">
              <span />
              <span />
              <span />
            </span>
          </div>
        ) : items.length === 0 ? (
          <div className="empty-state">
            <p>ยังไม่มีไฟล์ในคลัง · กดปุ่มด้านบนเพื่ออัปโหลด</p>
          </div>
        ) : (
          <div className="media-grid">
            {items.map((m) => (
              <MediaCard
                key={m.id}
                media={m}
                selected={selectedIds.has(m.id)}
                pendingDelete={confirmDeleteId === m.id}
                onToggle={() => toggle(m.id)}
                onAskDelete={() => setConfirmDeleteId(m.id)}
                onCancelDelete={() => setConfirmDeleteId(null)}
                onConfirmDelete={() => onDelete(m.id)}
              />
            ))}
          </div>
        )}

        <div className="form-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>
            ปิด
          </button>
          {multi && (
            <button
              type="button"
              className="btn-primary"
              onClick={onConfirmPick}
              disabled={selectedIds.size === 0}
            >
              เลือก {selectedIds.size} ไฟล์
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}

function MediaCard({
  media,
  selected,
  pendingDelete,
  onToggle,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  media: MediaAssetOut
  selected: boolean
  pendingDelete: boolean
  onToggle: () => void
  onAskDelete: () => void
  onCancelDelete: () => void
  onConfirmDelete: () => void
}) {
  const [thumbUrl, setThumbUrl] = useState<string | null>(null)
  const [thumbError, setThumbError] = useState<string | null>(null)

  useEffect(() => {
    let revoked = false
    let url: string | null = null
    setThumbError(null)
    api
      .mediaObjectUrl(media.id)
      .then((u) => {
        if (revoked) {
          URL.revokeObjectURL(u)
        } else {
          url = u
          setThumbUrl(u)
        }
      })
      .catch((e: unknown) => {
        // Surface fetch errors so we can debug auth / 404 issues instead of
        // staring at a blank placeholder. Render errors (CSP, decode) are
        // caught by onError on the <img>/<video> below.
        setThumbError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      revoked = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [media.id])

  return (
    <article className={`media-card${selected ? ' is-selected' : ''}`}>
      <button
        type="button"
        className="media-card-thumb"
        onClick={onToggle}
        aria-pressed={selected}
        aria-label={`เลือก ${media.original_name ?? media.filename}`}
      >
        {thumbUrl ? (
          media.kind === 'image' ? (
            <img
              src={thumbUrl}
              alt=""
              onError={() => setThumbError('decode failed')}
            />
          ) : (
            // preload="metadata" makes the browser fetch enough of the file
            // to render the first frame. Without it the <video> stays black.
            <video
              src={thumbUrl}
              muted
              preload="metadata"
              onError={() => setThumbError('video decode failed')}
            />
          )
        ) : (
          <span className="media-card-placeholder">
            {media.kind === 'video' ? '🎬' : '🖼️'}
          </span>
        )}
        <span className="media-card-kind">
          {media.kind === 'video' ? '🎬 วิดิโอ' : '🖼️ รูป'}
        </span>
      </button>
      <div className="media-card-meta">
        <span className="media-card-name" title={media.original_name ?? ''}>
          {media.original_name ?? media.filename}
        </span>
        <span className="muted-note">
          {(media.size_bytes / 1024 / 1024).toFixed(2)} MB
        </span>
        {thumbError && (
          <span className="muted-note" style={{ color: 'var(--error-fg)' }}>
            {thumbError}
          </span>
        )}
      </div>
      {pendingDelete ? (
        <div className="confirm-inline-row">
          <span style={{ flex: 1, color: 'var(--error-fg)' }}>ลบเลย?</span>
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={onCancelDelete}
          >
            ไม่
          </button>
          <button
            type="button"
            className="btn-primary btn-danger-solid btn-sm"
            onClick={onConfirmDelete}
          >
            ลบ
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="btn-ghost btn-sm btn-danger"
          onClick={onAskDelete}
        >
          ลบ
        </button>
      )}
    </article>
  )
}

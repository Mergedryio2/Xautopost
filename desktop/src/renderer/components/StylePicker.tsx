import { useEffect, useRef, useState, type FormEvent } from 'react'
import { MediaPicker } from './MediaPicker'
import { Modal } from './Modal'
import { TweetPickerModal } from './TweetPickerModal'
import {
  api,
  type AiProvider,
  type ApiKeyOut,
  type PromptMode,
  type PromptOut,
  type ReplySource,
  type ReplyTargetMode,
  type TweetOut,
  type XAccountOut,
} from '../lib/api'

export type StyleTemplate = {
  emoji: string
  name: string
  sub: string
  body: string
  mode: PromptMode
}

const TEMPLATES: StyleTemplate[] = [
  {
    emoji: '✨',
    name: 'คำคมให้กำลังใจ',
    sub: 'โพสต์เชิงบวกสั้น กระชับ',
    body: 'คุณเป็น content creator ที่เขียนคำคมให้กำลังใจให้คนไทยอ่านบน X เขียนเป็นภาษาไทย ความยาวไม่เกิน 240 ตัวอักษร น้ำเสียงอบอุ่น จริงใจ ไม่ใช้ภาษาตลาด ไม่ต้องใส่ # หรือ emoji เยอะ ทุกครั้งให้สร้างคำคมที่แตกต่างกัน หลีกเลี่ยงการซ้ำเดิม',
    mode: 'ai',
  },
  {
    emoji: '☕',
    name: 'ชวนกินอะไร',
    sub: 'แนะนำของกินไทยในแต่ละช่วงวัน',
    body: 'คุณเป็น food blogger คนไทยที่โพสต์บน X แนะนำของกินไทยในช่วงเช้า กลางวัน หรือเย็น เขียนเหมือนเพื่อนชวนกินด้วย ภาษาไทย ความยาวไม่เกิน 200 ตัวอักษร ห้ามใส่ราคา',
    mode: 'ai',
  },
  {
    emoji: '📰',
    name: 'ข่าวเทคย่อย',
    sub: 'สรุปเทรนด์ AI / เทคล่าสุดสั้นๆ',
    body: 'คุณเป็น tech journalist เขียนสรุปเทรนด์เทคโนโลยีหรือ AI เป็นภาษาไทย โทนเป็นกลาง ไม่เชียร์ ไม่ดิส ความยาวไม่เกิน 240 ตัวอักษร ใส่ context พอให้คนทั่วไปเข้าใจ',
    mode: 'ai',
  },
  {
    emoji: '😆',
    name: 'มุกเบาๆ',
    sub: 'มุกตลก relatable ของคนเมือง',
    body: 'คุณเขียนมุกตลกเบาๆ บน X เกี่ยวกับชีวิตประจำวันของคนเมือง ภาษาไทย ความยาวไม่เกิน 180 ตัวอักษร เน้นมุกแบบ relatable ไม่ดราม่า ไม่หยาบ',
    mode: 'ai',
  },
  {
    emoji: '🌙',
    name: 'ก่อนนอน',
    sub: 'ความคิดสั้นๆ โทนสงบ',
    body: 'คุณเขียนความคิดสั้นๆ ก่อนนอนบน X โทนใคร่ครวญ สงบ ภาษาไทย ความยาวไม่เกิน 200 ตัวอักษร อย่าลงท้ายว่า "ฝันดี"',
    mode: 'ai',
  },
  {
    emoji: '🎨',
    name: 'AI ตามใจ',
    sub: 'เขียน prompt ให้ AI เอง',
    body: '',
    mode: 'ai',
  },
  {
    emoji: '📝',
    name: 'เขียนเอง',
    sub: 'พิมพ์ทวีตเอง ไม่ใช้ AI',
    body: '',
    mode: 'manual',
  },
  {
    emoji: '💬',
    name: 'Reply โพสต์เก่า',
    sub: 'ตอบกลับโพสต์เดิมของบัญชีตัวเอง',
    body: 'คุณเป็นเจ้าของโพสต์ต้นทาง · เขียน reply ต่อยอดจากโพสต์ของตัวเอง ภาษาไทย ความยาวไม่เกิน 200 ตัวอักษร น้ำเสียงเป็นกันเอง ไม่ทัก hi ไม่ทักทาย ให้เหมือนคุยต่อจากที่เคยพูด',
    mode: 'reply',
  },
]

type Mode = 'pick' | 'edit-or-create'

const DEFAULT_OPENAI_MODEL = 'gpt-4o-mini'
const DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash'

export function StylePicker({
  open,
  slot = 'post',
  currentPromptId,
  onClose,
  onSelected,
}: {
  open: boolean
  // 'post' = main rotation (ai/manual prompts), 'reply' = reply slot
  // (reply prompts only). When picking from "ตั้ง reply" the picker
  // filters existing prompts AND the templates to mode='reply' so the
  // user can't accidentally land a post-style in the reply slot.
  slot?: 'post' | 'reply'
  currentPromptId: number | null
  onClose: () => void
  onSelected: (promptId: number) => void
}) {
  const [prompts, setPrompts] = useState<PromptOut[]>([])
  const [keys, setKeys] = useState<ApiKeyOut[]>([])
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState<Mode>('pick')
  const [editing, setEditing] = useState<PromptOut | null>(null)
  const [seedTemplate, setSeedTemplate] = useState<StyleTemplate | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const [ps, ks] = await Promise.all([api.listPrompts(), api.listApiKeys()])
      setPrompts(ps)
      setKeys(ks)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    setMode('pick')
    setEditing(null)
    setSeedTemplate(null)
    setError(null)
    refresh()
  }, [open])

  function startCreateFromTemplate(t: StyleTemplate) {
    setSeedTemplate(t)
    setEditing(null)
    setMode('edit-or-create')
  }

  function startEdit(p: PromptOut) {
    setEditing(p)
    setSeedTemplate(null)
    setMode('edit-or-create')
  }

  function onPickExisting(p: PromptOut) {
    onSelected(p.id)
    onClose()
  }

  async function onSavedPrompt(saved: PromptOut, picked: boolean) {
    if (picked) {
      onSelected(saved.id)
      onClose()
    } else {
      await refresh()
      setMode('pick')
    }
  }

  async function onDeletedPrompt() {
    await refresh()
    setMode('pick')
  }

  // Slot-aware filters. The "post" slot rotates new tweets, so only
  // ai/manual prompts belong here. The "reply" slot only takes reply-mode
  // prompts — assigning a post-style there would just sit dormant forever.
  const visiblePrompts = prompts.filter((p) =>
    slot === 'reply' ? p.mode === 'reply' : p.mode !== 'reply',
  )
  const visibleTemplates = TEMPLATES.filter((t) =>
    slot === 'reply' ? t.mode === 'reply' : t.mode !== 'reply',
  )

  const title =
    mode === 'pick'
      ? slot === 'reply'
        ? 'เลือกสไตล์ Reply'
        : 'เลือกสไตล์การเขียน'
      : editing
        ? 'แก้ไขสไตล์'
        : 'ตั้งสไตล์ใหม่'

  const hasManualOnly =
    visiblePrompts.some((p) => p.mode === 'manual') && keys.length === 0

  return (
    <Modal open={open} onClose={onClose} title={title}>
      {loading ? (
        <div className="empty-state empty-small">
          <span className="dots"><span /><span /><span /></span>
        </div>
      ) : mode === 'pick' ? (
        <div className="modal-form">
          {keys.length === 0 && !hasManualOnly && (
            <div className="helper-callout">
              <span style={{ fontSize: 22, lineHeight: 1 }}>💡</span>
              <span>
                ถ้าจะใช้ AI ช่วยเขียน ต้อง <strong>เชื่อม OpenAI หรือ Gemini</strong>{' '}
                ที่หน้า "ตั้งค่า" ก่อน · หรือเลือกสไตล์ <strong>"เขียนเอง"</strong> ที่ด้านล่างก็ได้
              </span>
            </div>
          )}

          {visiblePrompts.length > 0 && (
            <div className="field">
              <span className="field-label-plain">สไตล์ที่มีอยู่แล้ว</span>
              <div className="card-list">
                {visiblePrompts.map((p) => (
                  <article
                    key={p.id}
                    className="row-card row-card-pick"
                    role="button"
                    tabIndex={0}
                    aria-pressed={p.id === currentPromptId}
                    style={{
                      cursor: 'pointer',
                      borderColor:
                        p.id === currentPromptId ? 'var(--primary-strong)' : undefined,
                      background:
                        p.id === currentPromptId ? 'var(--primary-soft)' : undefined,
                    }}
                    onClick={() => onPickExisting(p)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onPickExisting(p)
                      }
                    }}
                  >
                    <div
                      className="row-avatar"
                      style={{
                        background:
                          p.mode === 'reply'
                            ? 'var(--primary-soft)'
                            : p.mode === 'manual'
                              ? 'var(--lavender)'
                              : 'var(--peach)',
                      }}
                    >
                      {p.mode === 'reply' ? '💬' : p.mode === 'manual' ? '📝' : '✦'}
                    </div>
                    <div className="row-info">
                      <div className="row-title">{p.name}</div>
                      <div className="row-meta">
                        {p.mode === 'reply' ? (
                          <span
                            className="provider-badge"
                            style={{
                              background: 'var(--primary-soft)',
                              color: 'var(--text)',
                            }}
                          >
                            Reply โพสต์เก่า · {p.reply_source === 'manual' ? 'เขียนเอง' : p.provider === 'openai' ? 'OpenAI' : 'Gemini'}
                          </span>
                        ) : p.mode === 'manual' ? (
                          <span
                            className="provider-badge"
                            style={{
                              background: 'var(--lavender-soft)',
                              color: 'var(--text-on-lavender)',
                            }}
                          >
                            เขียนเอง · ไม่ใช้ AI
                          </span>
                        ) : (
                          <span className={`provider-badge ${p.provider}`}>
                            {p.provider === 'openai' ? 'OpenAI' : 'Gemini'}
                          </span>
                        )}
                        {p.id === currentPromptId && (
                          <span className="pill ok" style={{ fontSize: 10 }}>
                            กำลังใช้
                          </span>
                        )}
                      </div>
                    </div>
                    <div
                      className="row-actions"
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      <button
                        type="button"
                        className="btn-ghost"
                        onClick={() => startEdit(p)}
                      >
                        แก้ไข
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}

          <div className="field">
            <span className="field-label-plain">หรือสร้างสไตล์ใหม่</span>
            <div className="style-template-grid">
              {visibleTemplates.map((t) => (
                <button
                  type="button"
                  key={t.name}
                  className="style-template"
                  onClick={() => startCreateFromTemplate(t)}
                  style={
                    t.mode === 'manual'
                      ? {
                        background: 'var(--lavender-soft)',
                        borderColor: 'var(--lavender)',
                      }
                      : undefined
                  }
                >
                  <span className="style-template-emoji">{t.emoji}</span>
                  <span className="style-template-name">{t.name}</span>
                  <span className="style-template-sub">{t.sub}</span>
                </button>
              ))}
            </div>
          </div>

          {error && <div className="form-error">{error}</div>}

          <div className="form-actions">
            <button type="button" className="btn-ghost" onClick={onClose}>
              ปิด
            </button>
          </div>
        </div>
      ) : (
        <PromptForm
          seed={seedTemplate}
          existing={editing}
          keys={keys}
          onCancel={() => setMode('pick')}
          onSaved={onSavedPrompt}
          onDeleted={onDeletedPrompt}
        />
      )}
    </Modal>
  )
}

function PromptForm({
  seed,
  existing,
  keys,
  onCancel,
  onSaved,
  onDeleted,
}: {
  seed: StyleTemplate | null
  existing: PromptOut | null
  keys: ApiKeyOut[]
  onCancel: () => void
  onSaved: (p: PromptOut, pickAfterSave: boolean) => void
  onDeleted: () => void
}) {
  const startMode: PromptMode = existing?.mode ?? seed?.mode ?? 'ai'
  const initialProvider: AiProvider =
    existing?.provider ?? keys[0]?.provider ?? 'openai'

  const [promptMode] = useState<PromptMode>(startMode)
  const [name, setName] = useState(existing?.name ?? seed?.name ?? '')
  const [body, setBody] = useState(existing?.body ?? seed?.body ?? '')
  const [manualForms, setManualForms] = useState<{ text: string, enabled: boolean }[]>(() => {
    const raw = existing?.body ?? seed?.body ?? ''
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    } catch { }
    if (!raw) return [{ text: '', enabled: true }]
    return raw.split(/\n\s*-{3,}\s*\n/).filter(s => s.trim()).map(s => ({ text: s.trim(), enabled: true }))
  })
  const [focusedFormIndex, setFocusedFormIndex] = useState(0)
  const [provider, setProvider] = useState<AiProvider>(initialProvider)
  const [model, setModel] = useState(
    existing?.model ??
    (initialProvider === 'openai'
      ? DEFAULT_OPENAI_MODEL
      : DEFAULT_GEMINI_MODEL),
  )
  const [fallback, setFallback] = useState(existing?.fallback_text ?? '')
  const [decorateEmoji, setDecorateEmoji] = useState(
    existing?.decorate_emoji ?? true,
  )
  const [decorateLetters, setDecorateLetters] = useState(
    existing?.decorate_letters ?? false,
  )
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [mediaPickerOpen, setMediaPickerOpen] = useState(false)
  const bodyRef = useRef<HTMLTextAreaElement>(null)

  // Reply-mode state. Only meaningful when promptMode === 'reply', but
  // declared unconditionally so the hook order stays stable on mode switch.
  const [replySource, setReplySource] = useState<ReplySource>(
    existing?.reply_source ?? 'ai',
  )
  const [replyRepeatLimit, setReplyRepeatLimit] = useState<number>(
    existing?.reply_repeat_limit ?? 0,
  )
  const [targetTweetId, setTargetTweetId] = useState<string | null>(
    existing?.target_tweet_id ?? null,
  )
  // Default to latest_n for NEW reply prompts. The previous 'single' default
  // forced users to pick a specific tweet before save would succeed; if they
  // skipped that step the validation blocked save with an error that was
  // easy to miss. latest_n + count 5 is a sensible "just works" default —
  // the user can switch modes after the fact if they want a fixed target.
  const [replyTargetMode, setReplyTargetMode] = useState<ReplyTargetMode>(
    existing?.reply_target_mode ?? 'latest_n',
  )
  const [replyTargetCount, setReplyTargetCount] = useState<number>(
    existing?.reply_target_count ?? 5,
  )
  // The tweet picker browses one account at a time. Default to the first
  // account; reset whenever the modal opens for an existing prompt by
  // scanning its target back to its owning account in an effect below.
  const [replyAccounts, setReplyAccounts] = useState<XAccountOut[]>([])
  const [replyAccountId, setReplyAccountId] = useState<number | null>(null)
  const [targetPreview, setTargetPreview] = useState<TweetOut | null>(null)
  const [tweetPickerOpen, setTweetPickerOpen] = useState(false)

  // Load accounts on mount (reply mode needs them; cheap call for other
  // modes too, so we just always do it — guarded by promptMode === 'reply'
  // in the JSX).
  useEffect(() => {
    let cancelled = false
    if (promptMode !== 'reply') return
    api.listAccounts().then(
      (rows) => {
        if (cancelled) return
        setReplyAccounts(rows)
        const first = rows[0]
        if (replyAccountId === null && first) {
          setReplyAccountId(first.id)
        }
      },
      () => {
        /* surfaced inline via the disabled picker if list is empty */
      },
    )
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [promptMode])

  // Resolve the preview for an existing target_tweet_id. We don't know
  // which account owns it offhand, so try each account until one returns
  // a hit. Bounded by the number of accounts (small).
  useEffect(() => {
    if (!targetTweetId) {
      setTargetPreview(null)
      return
    }
    if (replyAccounts.length === 0) return
    let cancelled = false
      ; (async () => {
        for (const acc of replyAccounts) {
          try {
            const rows = await api.listTweets(acc.id, {
              q: targetTweetId,
              limit: 1,
            })
            if (cancelled) return
            const hit = rows.find((t) => t.tweet_id === targetTweetId)
            if (hit) {
              setTargetPreview(hit)
              setReplyAccountId(acc.id)
              return
            }
          } catch {
            // ignore — try next account
          }
        }
        if (!cancelled) setTargetPreview(null)
      })()
    return () => {
      cancelled = true
    }
  }, [targetTweetId, replyAccounts])

  function insertMediaTokens(ids: number[]) {
    if (ids.length === 0) return
    const tokens = ids.map((id) => `[media:${id}]`).join(' ')

    if (promptMode === 'manual' || (promptMode === 'reply' && replySource === 'manual')) {
      const next = [...manualForms]
      const form = next[focusedFormIndex] || next[0]
      if (form) {
        form.text = form.text ? `${form.text}\n${tokens}\n` : `${tokens}\n`
        setManualForms(next)
      }
      return
    }

    const ta = bodyRef.current
    if (!ta) {
      // Fallback: append at the end with a leading newline so the token sits
      // at the top of a new candidate block instead of mid-sentence.
      setBody((prev) => (prev ? `${prev}\n${tokens}\n` : `${tokens}\n`))
      return
    }
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const before = body.slice(0, start)
    const after = body.slice(end)
    // Tokens read most cleanly on their own line. Pad with newlines if the
    // surrounding text isn't already at a line boundary.
    const padBefore = before && !before.endsWith('\n') ? '\n' : ''
    const padAfter = after && !after.startsWith('\n') ? '\n' : ''
    const next = `${before}${padBefore}${tokens}${padAfter}${after}`
    setBody(next)
    requestAnimationFrame(() => {
      ta.focus()
      const cursor = (before + padBefore + tokens).length
      ta.setSelectionRange(cursor, cursor)
    })
  }

  async function handleDelete() {
    if (!existing) return
    setDeleting(true)
    setError(null)
    try {
      await api.deletePrompt(existing.id)
      onDeleted()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setDeleting(false)
    }
  }

  function onProviderChange(p: AiProvider) {
    setProvider(p)
    if (model === DEFAULT_OPENAI_MODEL || model === DEFAULT_GEMINI_MODEL || !model) {
      setModel(p === 'openai' ? DEFAULT_OPENAI_MODEL : DEFAULT_GEMINI_MODEL)
    }
  }

  async function handleSave(picksAfter: boolean) {
    setError(null)
    if (!name.trim()) {
      setError('ใส่ชื่อสไตล์ก่อนนะคะ')
      return
    }
    let finalBody = body.trim()
    if (promptMode === 'manual' || (promptMode === 'reply' && replySource === 'manual')) {
      const cleaned = manualForms.filter(f => f.text.trim())
      if (cleaned.length === 0) {
        setError('ใส่ข้อความที่จะโพสต์อย่างน้อย 1 ฟอร์มนะคะ')
        return
      }
      finalBody = JSON.stringify(cleaned)
    } else {
      if (!finalBody) {
        setError('ใส่คำสั่งให้ AI ก่อนนะคะ')
        return
      }
    }
    if (
      promptMode === 'reply' &&
      replyTargetMode === 'single' &&
      !targetTweetId
    ) {
      setError('เลือกโพสต์ที่จะ reply ก่อนนะคะ')
      return
    }
    if (
      promptMode === 'reply' &&
      replyTargetMode === 'latest_n' &&
      replyTargetCount < 1
    ) {
      setError('จำนวนโพสต์ต้องอย่างน้อย 1')
      return
    }
    setSubmitting(true)
    try {
      const useManualText =
        promptMode === 'manual' || (promptMode === 'reply' && replySource === 'manual')
      const data = {
        name: name.trim(),
        body: finalBody,
        mode: promptMode,
        decorate_emoji: decorateEmoji,
        decorate_letters: decorateLetters,
        provider,
        model,
        fallback_text: useManualText ? undefined : fallback.trim() || undefined,
        target_tweet_id:
          promptMode === 'reply' && replyTargetMode === 'single'
            ? targetTweetId
            : null,
        reply_repeat_limit: promptMode === 'reply' ? replyRepeatLimit : 0,
        reply_source: promptMode === 'reply' ? replySource : 'ai',
        reply_target_mode: promptMode === 'reply' ? replyTargetMode : 'single',
        reply_target_count:
          promptMode === 'reply' ? Math.max(1, replyTargetCount) : 5,
      }
      const saved = existing
        ? await api.updatePrompt(existing.id, data)
        : await api.createPrompt(data)
      onSaved(saved, picksAfter)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSubmitting(false)
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    handleSave(true)
  }

  const renderActions = () => {
    if (confirmDelete && existing) {
      return (
        <div className="confirm-inline-row">
          <span style={{ flex: 1, color: 'var(--error-fg)' }}>
            ลบสไตล์ "<strong>{existing.name}</strong>" ? · ลบแล้วกู้คืนไม่ได้
          </span>
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => setConfirmDelete(false)}
            disabled={deleting}
          >
            ไม่ลบ
          </button>
          <button
            type="button"
            className="btn-primary btn-danger-solid btn-sm"
            onClick={handleDelete}
            disabled={deleting}
          >
            {deleting ? 'กำลังลบ…' : 'ลบเลย'}
          </button>
        </div>
      )
    }
    return (
      <div
        className="form-actions"
        style={{ justifyContent: 'space-between' }}
      >
        {existing ? (
          <button
            type="button"
            className="btn-ghost btn-danger"
            onClick={() => setConfirmDelete(true)}
          >
            ลบสไตล์
          </button>
        ) : (
          <span />
        )}
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn-ghost" onClick={onCancel}>
            กลับ
          </button>
          {!existing && (
            <button
              type="button"
              className="btn-ghost"
              onClick={() => handleSave(false)}
              disabled={submitting}
            >
              บันทึกแล้วกลับ
            </button>
          )}
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting
              ? 'กำลังบันทึก…'
              : existing
                ? 'บันทึก'
                : 'บันทึกและใช้สไตล์นี้'}
          </button>
        </div>
      </div>
    )
  }

  if (promptMode === 'reply') {
    const activeAccount = replyAccounts.find((a) => a.id === replyAccountId) ?? null
    return (
      <form className="modal-form" onSubmit={onSubmit}>
        <div className="helper-callout">
          <span style={{ fontSize: 22, lineHeight: 1 }}>💬</span>
          <span>
            สไตล์นี้จะ <strong>reply</strong> ไปยังโพสต์เก่าของบัญชีตัวเอง · เลือกบัญชีและโพสต์ต้นทางด้านล่าง
          </span>
        </div>

        <label className="field">
          <span className="field-label-plain">ชื่อสไตล์</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="เช่น Reply ข่าวประจำสัปดาห์"
            autoFocus
            maxLength={128}
          />
        </label>

        <label className="field">
          <span className="field-label-plain">เลือกบัญชีที่จะ reply</span>
          <select
            value={replyAccountId ?? ''}
            onChange={(e) => {
              const id = Number(e.target.value)
              setReplyAccountId(Number.isFinite(id) ? id : null)
              // Switching account invalidates the previously-picked tweet —
              // it belongs to the old account's timeline.
              setTargetTweetId(null)
              setTargetPreview(null)
            }}
          >
            {replyAccounts.length === 0 && (
              <option value="">- ยังไม่มีบัญชี -</option>
            )}
            {replyAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.handle}
              </option>
            ))}
          </select>
        </label>

        <div className="field">
          <span className="field-label-plain">จะ reply โพสต์ไหน</span>
          <div className="target-mode-row">
            <label
              className={
                'target-mode-card' +
                (replyTargetMode === 'single' ? ' is-active' : '')
              }
            >
              <input
                type="radio"
                name="reply-target-mode"
                checked={replyTargetMode === 'single'}
                onChange={() => setReplyTargetMode('single')}
              />
              <div>
                <div className="target-mode-title">เลือกโพสต์เดียว</div>
                <div className="target-mode-sub">
                  รีพลายโพสต์ที่กำหนดซ้ำๆ
                </div>
              </div>
            </label>
            <label
              className={
                'target-mode-card' +
                (replyTargetMode === 'latest_n' ? ' is-active' : '')
              }
            >
              <input
                type="radio"
                name="reply-target-mode"
                checked={replyTargetMode === 'latest_n'}
                onChange={() => setReplyTargetMode('latest_n')}
              />
              <div>
                <div className="target-mode-title">N โพสต์ล่าสุด</div>
                <div className="target-mode-sub">
                  หมุนเวียน N ตัวที่เพิ่งโพสต์
                </div>
              </div>
            </label>
            <label
              className={
                'target-mode-card' +
                (replyTargetMode === 'all' ? ' is-active' : '')
              }
            >
              <input
                type="radio"
                name="reply-target-mode"
                checked={replyTargetMode === 'all'}
                onChange={() => setReplyTargetMode('all')}
              />
              <div>
                <div className="target-mode-title">ทุกโพสต์</div>
                <div className="target-mode-sub">
                  หมุนเวียนทุกโพสต์ใน index
                </div>
              </div>
            </label>
          </div>
          <span className="muted-note" style={{ marginTop: 6, display: 'block' }}>
            ทุก mode: ระบบจะหมุนเวียน reply ตัวที่ <strong>โดน reply น้อยที่สุด</strong>{' '}
            ก่อน (กระจายให้สมดุล)
          </span>
        </div>

        {replyTargetMode === 'latest_n' && (
          <label className="field">
            <span className="field-label-plain">
              จำนวนโพสต์ล่าสุดที่จะหมุนเวียน
            </span>
            <input
              type="number"
              min={1}
              max={3200}
              value={replyTargetCount}
              onChange={(e) =>
                setReplyTargetCount(Math.max(1, Number(e.target.value) || 1))
              }
            />
            <span className="muted-note" style={{ marginTop: 4 }}>
              เช่น 10 = เอา 10 โพสต์ล่าสุด แล้วหมุน reply วนไปเรื่อยๆ
            </span>
          </label>
        )}

        {replyTargetMode === 'single' && (
          <div className="field">
            <span className="field-label-plain">โพสต์ต้นทาง</span>
            {targetPreview ? (
              <div className="tweet-target-card">
                <div className="tweet-target-text">
                  {targetPreview.is_pinned && (
                    <span className="tweet-badge tweet-badge-pin">📌</span>
                  )}
                  {targetPreview.text_preview || (
                    <em style={{ opacity: 0.6 }}>(โพสต์ไม่มีข้อความ)</em>
                  )}
                </div>
                <div className="form-actions" style={{ marginTop: 6 }}>
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={() => setTweetPickerOpen(true)}
                    disabled={replyAccountId === null}
                  >
                    เปลี่ยน
                  </button>
                  <a
                    href={targetPreview.url}
                    target="_blank"
                    rel="noreferrer"
                    className="btn-ghost btn-sm"
                    style={{ textDecoration: 'none' }}
                  >
                    เปิดใน X ↗
                  </a>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setTweetPickerOpen(true)}
                disabled={replyAccountId === null}
              >
                เลือกโพสต์ที่จะ reply
              </button>
            )}
          </div>
        )}

        {replyTargetMode === 'all' && (
          <div className="helper-callout">
            <span style={{ fontSize: 22, lineHeight: 1 }}>♾️</span>
            <span>
              ระบบจะ reply <strong>ทุกโพสต์</strong> ของบัญชีที่อยู่ใน index ·{' '}
              สแกนใหม่ก่อนจะดีที่สุดเพื่อให้ครอบคลุม
            </span>
          </div>
        )}

        <label className="field">
          <span className="field-label-plain">
            จำกัดจำนวนครั้งที่จะ reply <strong>ต่อ 1 โพสต์</strong>
          </span>
          <input
            type="number"
            min={0}
            max={10000}
            value={replyRepeatLimit}
            onChange={(e) =>
              setReplyRepeatLimit(Math.max(0, Number(e.target.value) || 0))
            }
          />
          <span className="muted-note" style={{ marginTop: 4 }}>
            0 = ไม่จำกัด · เช่น 3 = reply โพสต์เดิมไม่เกิน 3 ครั้ง แล้วข้ามไปโพสต์ถัดไป
          </span>
        </label>

        <div className="field">
          <span className="field-label-plain">เนื้อหา reply มาจาก</span>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <label
              style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}
            >
              <input
                type="radio"
                name="reply-source"
                checked={replySource === 'ai'}
                onChange={() => setReplySource('ai')}
              />
              <span>AI สร้างให้</span>
            </label>
            <label
              style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}
            >
              <input
                type="radio"
                name="reply-source"
                checked={replySource === 'manual'}
                onChange={() => setReplySource('manual')}
              />
              <span>เขียนเอง</span>
            </label>
          </div>
        </div>

        {replySource === 'manual' ? (
          <div className="field">
            <span className="field-label-plain">
              ข้อความ reply ({manualForms.filter(f => f.enabled && f.text.trim()).length} ฟอร์มที่เปิดใช้งาน)
            </span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {manualForms.map((form, idx) => (
                <div key={idx} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={e => {
                      const next = [...manualForms]
                      next[idx].enabled = e.target.checked
                      setManualForms(next)
                    }}
                    style={{ marginTop: 8 }}
                  />
                  <textarea
                    value={form.text}
                    onChange={e => {
                      const next = [...manualForms]
                      next[idx].text = e.target.value
                      setManualForms(next)
                    }}
                    onFocus={() => setFocusedFormIndex(idx)}
                    rows={3}
                    placeholder={`ฟอร์มที่ ${idx + 1}`}
                    style={{ fontFamily: 'var(--font)', lineHeight: 1.6, flex: 1 }}
                  />
                  <button type="button" className="btn-ghost btn-sm btn-danger" onClick={() => {
                    const next = [...manualForms]
                    next.splice(idx, 1)
                    setManualForms(next)
                  }} style={{ marginTop: 4 }}>ลบ</button>
                </div>
              ))}
              <button type="button" className="btn-ghost" onClick={() => {
                setManualForms([...manualForms, { text: '', enabled: true }])
              }} style={{ alignSelf: 'flex-start' }}>+ เพิ่มฟอร์ม</button>
            </div>

            <div
              className="form-actions"
              style={{ marginTop: 6, justifyContent: 'flex-start' }}
            >
              <button
                type="button"
                className="btn-ghost btn-sm"
                onClick={() => setMediaPickerOpen(true)}
              >
                📎 เลือกรูป
              </button>
              <button
                type="button"
                className="btn-ghost btn-sm"
                onClick={() => {
                  const next = [...manualForms]
                  const form = next[focusedFormIndex] || next[0]
                  if (form) {
                    form.text = form.text ? `${form.text}\n[media:random]\n` : '[media:random]\n'
                    setManualForms(next)
                  }
                }}
              >
                🎲 สุ่มรูปทั้งหมด
              </button>
              <span className="muted-note">
                คลิกสุ่มรูปเพื่อสุ่มจากรูปที่เคยอัปโหลด
              </span>
            </div>
            <div className="field" style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
              <span className="field-label-plain">ตกแต่งท้ายโพสต์อัตโนมัติ (กัน X มองว่าซ้ำ)</span>
              <label className="toggle-row">
                <span>
                  <strong>🎲 อิโมจิสุ่ม</strong>
                </span>
                <input
                  type="checkbox"
                  checked={decorateEmoji}
                  onChange={(e) => setDecorateEmoji(e.target.checked)}
                />
              </label>
              <label className="toggle-row" style={{ marginTop: 8 }}>
                <span>
                  <strong>🔤 อักขระสุ่ม 6–7 ตัว (ตัวเล็ก ตัวใหญ่ ตัวเลข)</strong>
                </span>
                <input
                  type="checkbox"
                  checked={decorateLetters}
                  onChange={(e) => setDecorateLetters(e.target.checked)}
                />
              </label>
            </div>
          </div>
        ) : (
          <>
            <label className="field">
              <span className="field-label-plain">คำสั่งให้ AI</span>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={5}
                placeholder="เช่น 'เขียน reply ขยายความโพสต์ต้นทาง ภาษาไทย ความยาวไม่เกิน 200 ตัวอักษร'"
              />
            </label>

            <label className="field">
              <span className="field-label-plain">ใช้ AI ตัวไหน</span>
              <select
                value={provider}
                onChange={(e) => onProviderChange(e.target.value as AiProvider)}
              >
                <option value="openai">OpenAI (GPT)</option>
                <option value="gemini">Google Gemini</option>
              </select>
            </label>
          </>
        )}

        {error && <div className="form-error">{error}</div>}

        <TweetPickerModal
          open={tweetPickerOpen}
          account={activeAccount}
          selectedTweetId={targetTweetId}
          onPick={(t) => {
            setTargetTweetId(t.tweet_id)
            setTargetPreview(t)
            setTweetPickerOpen(false)
          }}
          onClose={() => setTweetPickerOpen(false)}
        />

        <MediaPicker
          open={mediaPickerOpen}
          multi
          onClose={() => setMediaPickerOpen(false)}
          onPick={insertMediaTokens}
        />

        {renderActions()}
      </form>
    )
  }

  if (promptMode === 'manual') {
    const candidates = manualForms.filter(f => f.enabled && f.text.trim())
    const previewBase = candidates[0]?.text || 'สวัสดีตอนเช้าค่ะ'

    return (
      <form className="modal-form" onSubmit={onSubmit}>
        <div className="helper-callout">
          <span style={{ fontSize: 22, lineHeight: 1 }}>📝</span>
          <span>
            สไตล์นี้ <strong>ไม่ใช้ AI</strong> · พิมพ์ข้อความที่เตรียมไว้ · สามารถติ๊กเลือกฟอร์มที่จะใช้หมุนเวียนได้ · ระบบจะ <strong>สลับไปเรื่อยๆ</strong> ตามลำดับ
          </span>
        </div>

        <label className="field">
          <span className="field-label-plain">ชื่อสไตล์</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="เช่น ทักทายตอนเช้า"
            autoFocus
            maxLength={128}
          />
        </label>

        <div className="field">
          <span className="field-label-plain">
            ฟอร์มข้อความ ({candidates.length} ฟอร์มที่เปิดใช้งาน)
          </span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {manualForms.map((form, idx) => (
              <div key={idx} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={e => {
                    const next = [...manualForms]
                    next[idx].enabled = e.target.checked
                    setManualForms(next)
                  }}
                  style={{ marginTop: 8 }}
                />
                <textarea
                  value={form.text}
                  onChange={e => {
                    const next = [...manualForms]
                    next[idx].text = e.target.value
                    setManualForms(next)
                  }}
                  onFocus={() => setFocusedFormIndex(idx)}
                  rows={3}
                  placeholder={`ฟอร์มที่ ${idx + 1}`}
                  style={{ fontFamily: 'var(--font)', lineHeight: 1.6, flex: 1 }}
                />
                <button type="button" className="btn-ghost btn-sm btn-danger" onClick={() => {
                  const next = [...manualForms]
                  next.splice(idx, 1)
                  setManualForms(next)
                }} style={{ marginTop: 4 }}>ลบ</button>
              </div>
            ))}
            <button type="button" className="btn-ghost" onClick={() => {
              setManualForms([...manualForms, { text: '', enabled: true }])
            }} style={{ alignSelf: 'flex-start' }}>+ เพิ่มฟอร์ม</button>
          </div>

          <div
            className="form-actions"
            style={{ marginTop: 6, justifyContent: 'flex-start' }}
          >
            <button
              type="button"
              className="btn-ghost btn-sm"
              onClick={() => setMediaPickerOpen(true)}
            >
              📎 เลือกรูป
            </button>
            <button
              type="button"
              className="btn-ghost btn-sm"
              onClick={() => {
                const next = [...manualForms]
                const form = next[focusedFormIndex] || next[0]
                if (form) {
                  form.text = form.text ? `${form.text}\n[media:random]\n` : '[media:random]\n'
                  setManualForms(next)
                }
              }}
            >
              🎲 สุ่มรูปทั้งหมด
            </button>
            <span className="muted-note">
              คลิกสุ่มรูปเพื่อสุ่มจากรูปที่เคยอัปโหลด
            </span>
          </div>
        </div>

        <MediaPicker
          open={mediaPickerOpen}
          multi
          onClose={() => setMediaPickerOpen(false)}
          onPick={insertMediaTokens}
        />

        <div className="field">
          <span className="field-label-plain">ตกแต่งท้ายโพสต์อัตโนมัติ (กัน X มองว่าซ้ำ)</span>
          <label className="toggle-row">
            <span>
              <strong>🎲 อิโมจิสุ่ม</strong>
              <span className="muted-note" style={{ display: 'block', margin: '4px 0 0' }}>
                หยิบจาก pool {38} ตัว · ตัวอย่าง: "<span style={{ color: 'var(--text)' }}>{previewBase} ✨</span>"
              </span>
            </span>
            <input
              type="checkbox"
              checked={decorateEmoji}
              onChange={(e) => setDecorateEmoji(e.target.checked)}
            />
          </label>
          <label className="toggle-row" style={{ marginTop: 8 }}>
            <span>
              <strong>🔤 อักขระสุ่ม 6–7 ตัว (ตัวเล็ก ตัวใหญ่ ตัวเลข)</strong>
              <span className="muted-note" style={{ display: 'block', margin: '4px 0 0' }}>
                ลดโอกาสซ้ำซ้อน · ตัวอย่าง: "<span style={{ color: 'var(--text)' }}>{previewBase} aB3xFg✨</span>"
              </span>
            </span>
            <input
              type="checkbox"
              checked={decorateLetters}
              onChange={(e) => setDecorateLetters(e.target.checked)}
            />
          </label>
          {decorateEmoji && decorateLetters && (
            <p className="muted-note" style={{ margin: '6px 0 0' }}>
              เปิดทั้งสองอย่าง · ตัวอย่าง: "<span style={{ color: 'var(--text)' }}>{previewBase} aBc1Xy ✨</span>"
            </p>
          )}
        </div>

        {!decorateEmoji && !decorateLetters && (
          <div
            className="helper-callout"
            style={{
              background: 'var(--warn-bg)',
              color: 'var(--warn-fg)',
              borderColor: '#f0d18a',
            }}
          >
            <span style={{ fontSize: 22, lineHeight: 1 }}>⚠️</span>
            <span>
              ปิดทั้งอิโมจิและตัวอักษรสุ่มแล้ว · ถ้าข้อความน้อยจะถูกหยิบซ้ำและ X จะ reject
              ข้อความเดิมในรอบ 24 ชม. แนะนำใส่อย่างน้อย{' '}
              <strong>{Math.max(10, manualForms.length + 1)} ข้อความ</strong> ที่ต่างกัน
            </span>
          </div>
        )}

        {error && <div className="form-error">{error}</div>}

        {renderActions()}
      </form>
    )
  }

  return (
    <form className="modal-form" onSubmit={onSubmit}>
      <label className="field">
        <span className="field-label-plain">ชื่อสไตล์</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="เช่น คำคมให้กำลังใจ"
          autoFocus
          maxLength={128}
        />
      </label>

      <label className="field">
        <span className="field-label-plain">คำสั่งให้ AI</span>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={6}
          placeholder="บรรยายว่าอยากให้ AI เขียนสไตล์ไหน เช่น 'เขียนคำคมเชิงบวก ภาษาไทย ความยาวไม่เกิน 240 ตัวอักษร...'"
        />
      </label>

      <label className="field">
        <span className="field-label-plain">ใช้ AI ตัวไหน</span>
        <select
          value={provider}
          onChange={(e) => onProviderChange(e.target.value as AiProvider)}
        >
          <option value="openai">OpenAI (GPT)</option>
          <option value="gemini">Google Gemini</option>
        </select>
      </label>

      <button
        type="button"
        className={`accordion ${showAdvanced ? 'is-open' : ''}`}
        onClick={() => setShowAdvanced((v) => !v)}
        style={{
          background: 'transparent',
          padding: '8px 0',
          border: 'none',
          color: 'var(--muted)',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          textAlign: 'left',
          letterSpacing: '0.04em',
        }}
      >
        {showAdvanced ? '▾ ขั้นสูง' : '▸ ขั้นสูง (ไม่บังคับ)'}
      </button>

      {showAdvanced && (
        <>
          <label className="field">
            <span className="field-label-plain">รุ่นโมเดล (ถ้าจำชื่อ)</span>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={
                provider === 'openai' ? DEFAULT_OPENAI_MODEL : DEFAULT_GEMINI_MODEL
              }
            />
          </label>
          <label className="field">
            <span className="field-label-plain">ข้อความสำรอง (ใช้ตอน AI ใช้งานไม่ได้)</span>
            <textarea
              value={fallback}
              onChange={(e) => setFallback(e.target.value)}
              rows={2}
              placeholder="ข้อความนี้จะถูกโพสต์แทนถ้า AI ขัดข้อง"
            />
          </label>
        </>
      )}

      {error && <div className="form-error">{error}</div>}

      {renderActions()}
    </form>
  )
}

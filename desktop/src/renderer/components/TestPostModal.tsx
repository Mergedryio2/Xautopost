import { useEffect, useRef, useState } from 'react'
import { Modal } from './Modal'
import { api, type PromptOut, type XAccountOut } from '../lib/api'

type Phase = 'compose' | 'posting' | 'done'

type AccountResult =
  | { kind: 'pending' }
  | { kind: 'posting' }
  | { kind: 'success' }
  | { kind: 'failed'; error: string }

const TWEET_LIMIT = 280

export function TestPostModal({
  account,
  onClose,
}: {
  account: XAccountOut | null
  onClose: () => void
}) {
  const [allAccounts, setAllAccounts] = useState<XAccountOut[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<number>>(
    () => new Set(account ? [account.id] : []),
  )
  const [prompts, setPrompts] = useState<PromptOut[]>([])
  const [promptId, setPromptId] = useState<number | null>(null)
  const [content, setContent] = useState('')
  const [phase, setPhase] = useState<Phase>('compose')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<Record<number, AccountResult>>({})
  const stopRef = useRef(false)

  useEffect(() => {
    Promise.all([api.listAccounts(), api.listPrompts()])
      .then(([accs, ps]) => {
        setAllAccounts(accs)
        setPrompts(ps)
        const [first] = ps
        if (first) setPromptId(first.id)
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  function toggleAccount(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAll() {
    setSelectedIds(new Set(allAccounts.map((a) => a.id)))
  }

  function clearSelection() {
    setSelectedIds(new Set())
  }

  async function onGenerate() {
    if (!promptId) return
    setGenerating(true)
    setError(null)
    try {
      const r = await api.generatePrompt(promptId)
      setContent(r.text)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setGenerating(false)
    }
  }

  async function onPost() {
    if (!content.trim()) {
      setError('กรุณากรอกข้อความก่อน')
      return
    }
    if (selectedIds.size === 0) {
      setError('เลือกบัญชีอย่างน้อย 1 บัญชี')
      return
    }

    setError(null)
    setPhase('posting')
    stopRef.current = false

    const targets = allAccounts.filter((a) => selectedIds.has(a.id))
    const initial: Record<number, AccountResult> = {}
    for (const acc of targets) initial[acc.id] = { kind: 'pending' }
    setResults(initial)

    for (const acc of targets) {
      if (stopRef.current) break
      setResults((prev) => ({ ...prev, [acc.id]: { kind: 'posting' } }))
      try {
        const r = await api.testPost(acc.id, content)
        setResults((prev) => ({
          ...prev,
          [acc.id]: r.ok
            ? { kind: 'success' }
            : { kind: 'failed', error: r.error || 'ไม่ทราบสาเหตุ' },
        }))
      } catch (e) {
        setResults((prev) => ({
          ...prev,
          [acc.id]: {
            kind: 'failed',
            error: e instanceof Error ? e.message : String(e),
          },
        }))
      }
    }
    setPhase('done')
  }

  function requestStop() {
    stopRef.current = true
  }

  const selectedPrompt = prompts.find((p) => p.id === promptId) ?? null
  const len = content.length
  const overLimit = len > TWEET_LIMIT
  const isPosting = phase === 'posting'

  const totalResults = Object.keys(results).length
  const finishedResults = Object.values(results).filter(
    (r) => r.kind === 'success' || r.kind === 'failed',
  ).length
  const successCount = Object.values(results).filter(
    (r) => r.kind === 'success',
  ).length
  const failedCount = Object.values(results).filter(
    (r) => r.kind === 'failed',
  ).length

  return (
    <Modal
      open
      onClose={isPosting ? () => {} : onClose}
      title="ทดลองโพสต์"
      closeOnBackdrop={!isPosting}
    >
      {phase === 'compose' && (
        <div className="modal-form">
          <div className="field">
            <span className="field-label-plain">
              บัญชีที่จะโพสต์ · เลือก {selectedIds.size}/{allAccounts.length}
            </span>
            {allAccounts.length === 0 ? (
              <p className="muted-note">ยังไม่มีบัญชี X</p>
            ) : (
              <>
                <div className="bulk-account-list">
                  {allAccounts.map((a) => (
                    <label key={a.id} className="bulk-account-item">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(a.id)}
                        onChange={() => toggleAccount(a.id)}
                      />
                      <span className="bulk-account-handle">{a.handle}</span>
                      {a.posting_enabled && (
                        <span className="pill ok bulk-pill">auto</span>
                      )}
                    </label>
                  ))}
                </div>
                <div className="bulk-account-actions">
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={selectAll}
                  >
                    เลือกทั้งหมด
                  </button>
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={clearSelection}
                  >
                    ล้าง
                  </button>
                </div>
              </>
            )}
          </div>

          <div className="field-row">
            <label className="field">
              <span className="field-label-plain">สไตล์การเขียน (ไม่บังคับ)</span>
              <select
                value={promptId ?? ''}
                onChange={(e) =>
                  setPromptId(e.target.value ? Number(e.target.value) : null)
                }
                disabled={prompts.length === 0}
              >
                {prompts.length === 0 && (
                  <option value="">(ยังไม่มีสไตล์)</option>
                )}
                {prompts.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}{' '}
                    {p.mode === 'manual'
                      ? '· เขียนเอง'
                      : `· ${p.provider === 'openai' ? 'OpenAI' : 'Gemini'}`}
                  </option>
                ))}
              </select>
            </label>
            <div className="field" style={{ justifyContent: 'flex-end' }}>
              <span style={{ visibility: 'hidden' }}>·</span>
              <button
                type="button"
                className="btn-ghost"
                onClick={onGenerate}
                disabled={!promptId || generating}
              >
                {generating
                  ? selectedPrompt?.mode === 'manual'
                    ? 'กำลังหยิบ…'
                    : 'AI กำลังคิด…'
                  : selectedPrompt?.mode === 'manual'
                    ? '🎲 หยิบข้อความสุ่ม'
                    : '✨ ให้ AI ลองเขียน'}
              </button>
            </div>
          </div>

          <label className="field">
            <span className="field-label-plain">
              {selectedPrompt?.mode === 'manual'
                ? 'เนื้อหาทวีต (พิมพ์เอง หรือกดสุ่มจากสไตล์ที่ตั้งไว้)'
                : 'เนื้อหาทวีต (พิมพ์เอง หรือกดให้ AI ช่วย)'}
            </span>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={6}
              placeholder="พิมพ์ข้อความที่อยากโพสต์ที่นี่"
              autoFocus
            />
            <div className="char-count">
              <span
                style={{ color: overLimit ? 'var(--error-fg)' : 'var(--muted)' }}
              >
                {len}/{TWEET_LIMIT}
              </span>
            </div>
          </label>

          {error && <div className="form-error">{error}</div>}

          <div className="form-actions">
            <button type="button" className="btn-ghost" onClick={onClose}>
              ยกเลิก
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={onPost}
              disabled={
                !content.trim() || overLimit || selectedIds.size === 0
              }
            >
              โพสต์เลย ({selectedIds.size} บัญชี)
            </button>
          </div>
        </div>
      )}

      {(phase === 'posting' || phase === 'done') && (
        <div className="modal-form">
          <div className="modal-status">
            {phase === 'posting' ? (
              <>
                <span className="dots">
                  <span />
                  <span />
                  <span />
                </span>
                <span>
                  กำลังโพสต์ {finishedResults}/{totalResults} บัญชี
                </span>
              </>
            ) : (
              <span>
                เสร็จแล้วค่ะ · สำเร็จ {successCount}/{totalResults}
                {failedCount > 0 && ` · ไม่สำเร็จ ${failedCount}`}
              </span>
            )}
          </div>

          <div className="bulk-result-list">
            {allAccounts
              .filter((a) => results[a.id])
              .map((a) => {
                const r = results[a.id]
                if (!r) return null
                return (
                  <div key={a.id} className="bulk-result-item">
                    <span className="bulk-account-handle">{a.handle}</span>
                    {r.kind === 'pending' && (
                      <span className="pill idle">รอคิว</span>
                    )}
                    {r.kind === 'posting' && (
                      <span className="pill warn">กำลังโพสต์…</span>
                    )}
                    {r.kind === 'success' && (
                      <span className="pill ok">สำเร็จ</span>
                    )}
                    {r.kind === 'failed' && (
                      <>
                        <span className="pill err">ไม่สำเร็จ</span>
                        <span className="bulk-error">{r.error}</span>
                      </>
                    )}
                  </div>
                )
              })}
          </div>

          <div className="form-actions">
            {phase === 'posting' && (
              <button
                type="button"
                className="btn-ghost"
                onClick={requestStop}
              >
                หยุดหลังจบบัญชีนี้
              </button>
            )}
            {phase === 'done' && (
              <button
                type="button"
                className="btn-primary"
                onClick={onClose}
              >
                ปิด
              </button>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

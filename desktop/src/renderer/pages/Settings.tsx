import { useEffect, useState, type FormEvent } from 'react'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { IntervalPicker, formatInterval } from '../components/IntervalPicker'
import { Modal } from '../components/Modal'
import { formatTime } from '../lib/time'
import {
  api,
  type AiProvider,
  type ApiKeyOut,
  type Operator,
  type PostLogOut,
  type XAccountOut,
} from '../lib/api'

export function Settings({
  operator,
  onOperatorChange,
}: {
  operator: Operator
  onOperatorChange: (op: Operator) => void
}) {
  return (
    <>
      <div className="section-head">
        <div>
          <h2 className="section-title">ตั้งค่า</h2>
          <p className="section-sub">เชื่อม AI · โปรไฟล์ · ประวัติ</p>
        </div>
      </div>

      <div className="settings-section">
        <ApiKeysSection />
      </div>

      <div className="settings-section">
        <ProfileSection
          operator={operator}
          onOperatorChange={onOperatorChange}
        />
      </div>

      <div className="settings-section">
        <HistorySection />
      </div>
    </>
  )
}

/* ─── AI keys ──────────────────────────────────────────────── */

function ApiKeysSection() {
  const [keys, setKeys] = useState<ApiKeyOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<ApiKeyOut | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      setKeys(await api.listApiKeys())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  async function onConfirmDelete() {
    if (!pendingDelete) return
    const id = pendingDelete.id
    setPendingDelete(null)
    try {
      await api.deleteApiKey(id)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="card">
      <div className="settings-section-head">
        <div>
          <h3>เชื่อม AI ที่จะช่วยเขียน</h3>
          <p className="settings-section-sub">
            ใส่ API key ของ OpenAI หรือ Gemini · เก็บแบบเข้ารหัสในเครื่องคุณ
          </p>
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={() => setShowAdd(true)}
        >
          + เพิ่ม AI
        </button>
      </div>

      {error && <div className="form-error">{error}</div>}

      {loading ? (
        <div className="empty-state empty-small">
          <span className="dots"><span /><span /><span /></span>
        </div>
      ) : keys.length === 0 ? (
        <EmptyState
          mood="hi"
          title="ยังไม่ได้เชื่อม AI"
          description="ต้องเชื่อม OpenAI หรือ Gemini ก่อน AI ถึงจะช่วยเขียนทวีตได้ค่ะ"
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => setShowAdd(true)}
            >
              + เชื่อม AI ตัวแรก
            </button>
          }
        />
      ) : (
        <div className="card-list">
          {keys.map((k) => (
            <article key={k.id} className="row-card">
              <ProviderAvatar provider={k.provider} />
              <div className="row-info">
                <div className="row-title">
                  {k.label || (k.provider === 'openai' ? 'OpenAI' : 'Gemini')}
                </div>
                <div className="row-meta">
                  <span className={`provider-badge ${k.provider}`}>
                    {k.provider === 'openai' ? 'OpenAI · GPT' : 'Google Gemini'}
                  </span>
                </div>
              </div>
              <button
                type="button"
                className="btn-ghost btn-danger"
                onClick={() => setPendingDelete(k)}
              >
                ลบ
              </button>
            </article>
          ))}
        </div>
      )}

      <AddKeyModal
        open={showAdd}
        onClose={() => {
          setShowAdd(false)
          refresh()
        }}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="ลบกุญแจ AI นี้?"
        message={`สไตล์การเขียนที่ใช้ ${pendingDelete?.provider === 'openai' ? 'OpenAI' : 'Gemini'} ตัวนี้จะใช้งานไม่ได้จนกว่าจะเชื่อม AI ตัวใหม่`}
        tone="danger"
        confirmLabel="ลบ"
        onConfirm={onConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  )
}

function ProviderAvatar({ provider }: { provider: AiProvider }) {
  if (provider === 'openai') {
    return (
      <div
        className="row-avatar"
        style={{ background: 'var(--peach)', color: 'var(--text-on-peach)' }}
        aria-label="OpenAI"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <path
            d="M21.6 9.5a5.5 5.5 0 0 0-.5-4.5 5.5 5.5 0 0 0-6-2.6 5.5 5.5 0 0 0-9.3 2 5.5 5.5 0 0 0-3.6 2.6 5.5 5.5 0 0 0 .7 6.5 5.5 5.5 0 0 0 .5 4.5 5.5 5.5 0 0 0 6 2.6 5.5 5.5 0 0 0 9.3-2 5.5 5.5 0 0 0 3.6-2.6 5.5 5.5 0 0 0-.7-6.5z"
            stroke="currentColor"
            strokeWidth="1.6"
          />
        </svg>
      </div>
    )
  }
  return (
    <div
      className="row-avatar"
      style={{ background: 'var(--mint)', color: 'var(--text-on-mint)' }}
      aria-label="Gemini"
    >
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 2 13.4 8.6 20 10 13.4 11.4 12 18 10.6 11.4 4 10 10.6 8.6 12 2z" />
      </svg>
    </div>
  )
}

function AddKeyModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [provider, setProvider] = useState<AiProvider>('openai')
  const [label, setLabel] = useState('')
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) {
      setProvider('openai')
      setLabel('')
      setKey('')
      setError(null)
      setSubmitting(false)
    }
  }, [open])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await api.createApiKey({ provider, label: label || undefined, key })
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSubmitting(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="เชื่อม AI ตัวใหม่">
      <form className="modal-form" onSubmit={onSubmit}>
        <div className="field">
          <span className="field-label-plain">เลือก AI ที่จะเชื่อม</span>
          <div className="style-template-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <button
              type="button"
              className={`style-template ${provider === 'openai' ? 'is-active' : ''}`}
              onClick={() => setProvider('openai')}
            >
              <span className="style-template-emoji">🟠</span>
              <span className="style-template-name">OpenAI</span>
              <span className="style-template-sub">GPT · ChatGPT</span>
            </button>
            <button
              type="button"
              className={`style-template ${provider === 'gemini' ? 'is-active' : ''}`}
              onClick={() => setProvider('gemini')}
            >
              <span className="style-template-emoji">💎</span>
              <span className="style-template-name">Gemini</span>
              <span className="style-template-sub">Google AI</span>
            </button>
          </div>
        </div>

        <label className="field">
          <span className="field-label-plain">ชื่อเรียก (ไม่บังคับ)</span>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="เช่น ส่วนตัว, ทำงาน"
            maxLength={64}
          />
        </label>

        <label className="field">
          <span className="field-label-plain">API Key</span>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            required
            minLength={8}
            placeholder={
              provider === 'openai' ? 'sk-...' : 'AIza...'
            }
            autoFocus
          />
        </label>

        <div className="helper-callout">
          <span style={{ fontSize: 22, lineHeight: 1 }}>🔒</span>
          <span>
            กุญแจจะถูกเข้ารหัสก่อนเก็บลงเครื่อง คนอื่นเปิดไฟล์ก็อ่านไม่ได้
            กุญแจหลักอยู่ใน Keychain ของระบบ
          </span>
        </div>

        {error && <div className="form-error">{error}</div>}

        <div className="form-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>
            ยกเลิก
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'กำลังเชื่อม…' : 'เชื่อม AI'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/* ─── Profile + advanced rotation ──────────────────────────── */

function ProfileSection({
  operator,
  onOperatorChange,
}: {
  operator: Operator
  onOperatorChange: (op: Operator) => void
}) {
  const [interval, setIntervalSec] = useState(operator.rotation_interval_seconds)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty = interval !== operator.rotation_interval_seconds

  async function onSave() {
    setSaving(true)
    setError(null)
    try {
      const updated = await api.updateOperator(operator.id, {
        rotation_interval_seconds: interval,
      })
      onOperatorChange(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card">
      <div className="settings-section-head">
        <div>
          <h3>โปรไฟล์ของคุณ</h3>
          <p className="settings-section-sub">
            ข้อมูลโปรไฟล์ที่คุณ login เข้ามา
          </p>
        </div>
      </div>

      <div className="row-card" style={{ marginBottom: 8 }}>
        <div
          className="op-avatar"
          style={{ background: operator.avatar_color }}
        >
          {operator.name.slice(0, 1).toUpperCase()}
        </div>
        <div className="row-info">
          <div className="row-title">{operator.name}</div>
          <div className="row-meta">
            <span className="muted-note is-inline">
              เริ่มใช้งาน {formatTime(operator.created_at)}
            </span>
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setShowAdvanced((v) => !v)}
        style={{
          background: 'transparent',
          border: 'none',
          padding: '8px 0',
          color: 'var(--muted)',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          letterSpacing: '0.04em',
          textAlign: 'left',
        }}
      >
        {showAdvanced ? '▾ ขั้นสูง' : '▸ ขั้นสูง · จังหวะหมุนเวียน'}
      </button>

      {showAdvanced && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <p className="muted-note is-inline">
            ระบบจะตรวจดูบัญชีต่างๆ ทุก {formatInterval(interval)} เพื่อเลือกบัญชีถัดไปที่จะโพสต์ ถ้าตั้งถี่เกินอาจถูก rate limit ค่ะ
          </p>
          <IntervalPicker
            value={interval}
            onChange={setIntervalSec}
            min={5}
            max={3600}
          />
          {error && <div className="form-error">{error}</div>}
          <div className="form-actions">
            <button
              type="button"
              className="btn-primary btn-sm"
              onClick={onSave}
              disabled={!dirty || saving}
            >
              {saving ? 'บันทึก…' : 'บันทึก'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ─── History (Logs) ───────────────────────────────────────── */

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: '', label: 'ทั้งหมด' },
  { value: 'success', label: 'สำเร็จ' },
  { value: 'failed', label: 'ล้มเหลว' },
  { value: 'skipped', label: 'ข้าม' },
]

const PAGE_SIZE = 20

function HistorySection() {
  const [open, setOpen] = useState(false)
  const [logs, setLogs] = useState<PostLogOut[]>([])
  const [accounts, setAccounts] = useState<XAccountOut[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [accountFilter, setAccountFilter] = useState<number | null>(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [limit, setLimit] = useState(PAGE_SIZE)

  async function refresh(nextLimit = limit) {
    setLoading(true)
    setError(null)
    try {
      const [ls, accs] = await Promise.all([
        api.listLogs({
          account_id: accountFilter ?? undefined,
          status: statusFilter || undefined,
          limit: nextLimit,
        }),
        accounts.length === 0 ? api.listAccounts() : Promise.resolve(accounts),
      ])
      setLogs(ls)
      if (accounts.length === 0) setAccounts(accs)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  // Reset paging when filters change
  useEffect(() => {
    setLimit(PAGE_SIZE)
  }, [accountFilter, statusFilter])

  useEffect(() => {
    if (open) refresh(limit)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, accountFilter, statusFilter, limit])

  function loadMore() {
    setLimit((n) => n + PAGE_SIZE)
  }

  // hasMore: server returned exactly `limit` items, so probably more exist.
  // Soft cap at 500 so we don't accidentally fetch unbounded sets.
  const hasMore = logs.length === limit && limit < 500

  function pillClass(s: string) {
    if (s === 'success') return 'pill ok'
    if (s === 'failed') return 'pill err'
    return 'pill idle'
  }

  function pillText(s: string) {
    if (s === 'success') return 'สำเร็จ'
    if (s === 'failed') return 'ล้มเหลว'
    if (s === 'skipped') return 'ข้าม'
    return s
  }

  function handleName(accountId: number | null): string {
    if (accountId == null) return '·'
    const acc = accounts.find((a) => a.id === accountId)
    return acc ? acc.handle : `#${accountId}`
  }

  return (
    <div className={`accordion ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        className="accordion-head"
        onClick={() => setOpen((v) => !v)}
      >
        <span style={{ fontSize: 16, lineHeight: 1 }}>📜</span>
        <span style={{ color: 'var(--text)', fontSize: 14 }}>
          ประวัติการโพสต์ทั้งหมด
        </span>
        <span className="muted-note is-inline">
          ดู log ทุกการโพสต์ พร้อมเหตุผลถ้าล้มเหลว
        </span>
        <span className="accordion-arrow">▸</span>
      </button>

      {open && (
        <div className="accordion-body">
          <div className="filter-row">
            <select
              value={accountFilter ?? ''}
              onChange={(e) =>
                setAccountFilter(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">ทุกบัญชี</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.handle}
                </option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              {STATUS_FILTERS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-ghost btn-sm"
              onClick={() => {
                setLimit(PAGE_SIZE)
                refresh(PAGE_SIZE)
              }}
            >
              รีเฟรช
            </button>
          </div>

          {error && <div className="form-error">{error}</div>}

          {loading && logs.length === 0 ? (
            <div className="empty-state empty-small">
              <span className="dots"><span /><span /><span /></span>
            </div>
          ) : logs.length === 0 ? (
            <p className="muted-note" style={{ margin: '8px 0 0' }}>
              ยังไม่มีบันทึกในตัวเลือกนี้
            </p>
          ) : (
            <>
              <div className="log-list">
                {logs.map((l) => (
                  <article key={l.id} className="log-row">
                    <div className="log-meta">
                      <span className={pillClass(l.status)}>
                        {pillText(l.status)}
                      </span>
                      <span className="log-time">{formatTime(l.timestamp)}</span>
                      <span className="log-account">
                        {handleName(l.x_account_id)}
                      </span>
                    </div>
                    {l.content && <div className="log-content">{l.content}</div>}
                    {l.detail && <div className="log-detail">{l.detail}</div>}
                    {l.tweet_url && (
                      <a
                        className="log-link"
                        href={l.tweet_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        เปิดดูทวีต ↗
                      </a>
                    )}
                  </article>
                ))}
              </div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'center',
                  marginTop: 12,
                }}
              >
                {hasMore ? (
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={loadMore}
                    disabled={loading}
                  >
                    {loading ? 'กำลังโหลด…' : `ดูเพิ่ม (+${PAGE_SIZE})`}
                  </button>
                ) : (
                  <span className="muted-note is-inline">
                    แสดงครบทุกรายการแล้ว · {logs.length} รายการ
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

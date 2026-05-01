import { useEffect, useState } from 'react'
import { AccountSettingsModal } from '../components/AccountSettingsModal'
import { AutoSwitch } from '../components/AutoSwitch'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { Modal } from '../components/Modal'
import { StylePicker } from '../components/StylePicker'
import { TestPostModal } from '../components/TestPostModal'
import { formatHour, formatRelative } from '../lib/time'
import {
  api,
  type LoginTaskStatus,
  type PromptOut,
  type XAccountOut,
} from '../lib/api'

export function Accounts() {
  const [accounts, setAccounts] = useState<XAccountOut[]>([])
  const [prompts, setPrompts] = useState<PromptOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [showTest, setShowTest] = useState(false)
  const [settingsOf, setSettingsOf] = useState<XAccountOut | null>(null)
  const [styleOf, setStyleOf] = useState<XAccountOut | null>(null)
  const [pendingDelete, setPendingDelete] = useState<XAccountOut | null>(null)
  const [alert, setAlert] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      const [accs, ps] = await Promise.all([
        api.listAccounts(),
        api.listPrompts(),
      ])
      setAccounts(accs)
      setPrompts(ps)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  function promptFor(acc: XAccountOut): PromptOut | undefined {
    if (acc.default_prompt_id == null) return undefined
    return prompts.find((p) => p.id === acc.default_prompt_id)
  }

  async function onTogglePosting(acc: XAccountOut, checked: boolean) {
    if (checked && acc.default_prompt_id === null) {
      setAlert('ตั้งสไตล์การเขียนให้บัญชีนี้ก่อนเปิดใช้งานนะคะ')
      return
    }
    try {
      const updated = await api.updateAccount(acc.id, {
        posting_enabled: checked,
      })
      setAccounts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
    } catch (e) {
      setAlert(e instanceof Error ? e.message : String(e))
    }
  }

  async function onConfirmDelete() {
    if (!pendingDelete) return
    const target = pendingDelete
    setPendingDelete(null)
    try {
      await api.deleteAccount(target.id)
      await refresh()
    } catch (e) {
      setAlert(e instanceof Error ? e.message : String(e))
    }
  }

  async function onAssignStyle(promptId: number) {
    if (!styleOf) return
    try {
      const updated = await api.updateAccount(styleOf.id, {
        default_prompt_id: promptId,
      })
      setAccounts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
      // refresh prompts in case a new one was just created
      const ps = await api.listPrompts()
      setPrompts(ps)
    } catch (e) {
      setAlert(e instanceof Error ? e.message : String(e))
    }
  }

  const enabledCount = accounts.filter((a) => a.posting_enabled).length

  return (
    <>
      <div className="section-head">
        <div>
          <h2 className="section-title">บัญชี X ของคุณ</h2>
          <p className="section-sub">
            {accounts.length === 0
              ? 'ยังไม่มีบัญชี'
              : `${accounts.length} บัญชี · เปิดอยู่ ${enabledCount}`}
          </p>
        </div>
        <div className="section-actions">
          <button
            type="button"
            className="btn-ghost"
            onClick={() => setShowTest(true)}
            disabled={accounts.length === 0}
          >
            โพสต์
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => setShowAdd(true)}
          >
            + เพิ่มบัญชี X
          </button>
        </div>
      </div>

      {error && <div className="form-error">{error}</div>}

      {loading ? (
        <div className="empty-state empty-small">
          <span className="dots"><span /><span /><span /></span>
        </div>
      ) : accounts.length === 0 ? (
        <EmptyState
          mood="hi"
          size="large"
          title="มาเพิ่มบัญชี X แรกของคุณกันค่ะ"
          description={
            <>
              เมื่อกด "เพิ่มบัญชี X" จะมีหน้าต่าง browser เปิดขึ้นให้ login
              <br />
              ระบบจะเก็บ session ไว้ในเครื่องคุณแบบเข้ารหัส
            </>
          }
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => setShowAdd(true)}
            >
              + เพิ่มบัญชีแรก
            </button>
          }
        />
      ) : (
        <div className="card-list">
          {accounts.map((acc) => {
            const prompt = promptFor(acc)
            const lastAt = acc.last_post_at
            return (
              <article key={acc.id} className="account-block">
                <div className="account-block-head">
                  <div
                    className="row-avatar"
                    style={{
                      width: 44,
                      height: 44,
                      background: 'var(--lavender)',
                      fontSize: 16,
                    }}
                  >
                    {acc.handle.replace('@', '').slice(0, 1).toUpperCase()}
                  </div>
                  <div className="account-block-info">
                    <h3 className="account-block-handle">{acc.handle}</h3>
                    <div className="account-block-meta">
                      {lastAt ? (
                        <span>โพสต์ล่าสุด {formatRelative(lastAt)}</span>
                      ) : (
                        <span>ยังไม่เคยโพสต์</span>
                      )}
                    </div>
                  </div>
                  <AutoSwitch
                    checked={acc.posting_enabled}
                    onChange={(next) => onTogglePosting(acc, next)}
                  />
                </div>

                <div
                  className={`auto-status ${acc.posting_enabled ? 'is-on' : 'is-off'}`}
                >
                  <span className="auto-status-icon">
                    {acc.posting_enabled ? '✓' : '⏸'}
                  </span>
                  {acc.posting_enabled ? (
                    <span>
                      <strong>กำลังโพสต์อัตโนมัติ</strong> · ระหว่าง{' '}
                      {formatHour(acc.active_hours_start)}–
                      {formatHour(acc.active_hours_end)} ทุก{' '}
                      {acc.min_interval_minutes}–{acc.max_interval_minutes} นาที
                      ไม่เกิน {acc.daily_limit} ครั้งต่อวัน
                    </span>
                  ) : acc.default_prompt_id === null ? (
                    <span>
                      <strong>ยังเริ่มไม่ได้</strong> · ตั้งสไตล์การเขียนด้านล่างก่อน แล้วเปิดสวิตช์เพื่อให้ระบบโพสต์อัตโนมัติ
                    </span>
                  ) : (
                    <span>
                      <strong>พร้อมเปิดใช้งาน</strong> · กดสวิตช์ด้านบนเพื่อให้ระบบโพสต์อัตโนมัติ ระหว่าง{' '}
                      {formatHour(acc.active_hours_start)}–
                      {formatHour(acc.active_hours_end)}
                    </span>
                  )}
                </div>

                <div className="account-block-style">
                  <span style={{ fontSize: 22, lineHeight: 1 }}>
                    {prompt?.mode === 'manual' ? '📝' : '✦'}
                  </span>
                  {prompt ? (
                    <div className="account-block-style-info">
                      <div className="account-block-style-name">
                        {prompt.name}{' '}
                        <span
                          className="provider-badge"
                          style={
                            prompt.mode === 'manual'
                              ? {
                                  background: 'var(--lavender-soft)',
                                  color: 'var(--text-on-lavender)',
                                  fontSize: 10,
                                  padding: '2px 8px',
                                  marginLeft: 4,
                                }
                              : {
                                  fontSize: 10,
                                  padding: '2px 8px',
                                  marginLeft: 4,
                                }
                          }
                        >
                          {prompt.mode === 'manual'
                            ? 'เขียนเอง · ไม่ใช้ AI'
                            : prompt.provider === 'openai'
                              ? 'OpenAI'
                              : 'Gemini'}
                        </span>
                      </div>
                      <div className="account-block-style-preview">
                        {prompt.body.slice(0, 80)}
                        {prompt.body.length > 80 ? '…' : ''}
                      </div>
                    </div>
                  ) : (
                    <span className="account-block-style-empty">
                      ยังไม่ได้ตั้งสไตล์การเขียน · กดปุ่มขวาเพื่อเลือก
                    </span>
                  )}
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={() => setStyleOf(acc)}
                  >
                    {prompt ? 'เปลี่ยนสไตล์' : 'ตั้งสไตล์'}
                  </button>
                </div>

                <div
                  className="row-actions"
                  style={{ alignSelf: 'flex-end' }}
                >
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => setSettingsOf(acc)}
                  >
                    ตั้งค่าเวลา
                  </button>
                  <button
                    type="button"
                    className="btn-ghost btn-danger"
                    onClick={() => setPendingDelete(acc)}
                  >
                    ลบบัญชี
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}

      <AddAccountModal
        open={showAdd}
        onClose={() => {
          setShowAdd(false)
          refresh()
        }}
      />

      {showTest && (
        <TestPostModal
          account={null}
          onClose={() => {
            setShowTest(false)
            refresh()
          }}
        />
      )}

      {settingsOf && (
        <AccountSettingsModal
          account={settingsOf}
          onClose={() => {
            setSettingsOf(null)
            refresh()
          }}
        />
      )}

      <StylePicker
        open={styleOf !== null}
        currentPromptId={styleOf?.default_prompt_id ?? null}
        onClose={() => setStyleOf(null)}
        onSelected={onAssignStyle}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="ลบบัญชีนี้?"
        message={`บัญชี ${pendingDelete?.handle ?? ''} และข้อมูล session จะถูกลบออกจากเครื่องนี้ ไม่สามารถกู้คืนได้`}
        tone="danger"
        confirmLabel="ลบบัญชี"
        cancelLabel="ยกเลิก"
        onConfirm={onConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      <ConfirmDialog
        open={alert !== null}
        title="แจ้งให้ทราบ"
        message={alert ?? ''}
        confirmLabel="เข้าใจแล้ว"
        cancelLabel=""
        onConfirm={() => setAlert(null)}
        onCancel={() => setAlert(null)}
      />
    </>
  )
}

function AddAccountModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [taskId, setTaskId] = useState<string | null>(null)
  const [status, setStatus] = useState<LoginTaskStatus | 'idle' | 'starting'>(
    'idle',
  )
  const [handle, setHandle] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setTaskId(null)
      setStatus('idle')
      setHandle(null)
      setError(null)
    }
  }, [open])

  useEffect(() => {
    if (!taskId) return
    if (status !== 'waiting' && status !== 'starting') return
    const iv = setInterval(async () => {
      try {
        const s = await api.loginStatus(taskId)
        setStatus(s.status)
        setHandle(s.handle)
        if (s.error) setError(s.error)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        clearInterval(iv)
      }
    }, 1500)
    return () => clearInterval(iv)
  }, [taskId, status])

  async function onStart() {
    setStatus('starting')
    setError(null)
    try {
      const r = await api.startLogin()
      setTaskId(r.task_id)
      setStatus('waiting')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('idle')
    }
  }

  async function onCancel() {
    if (taskId && status === 'waiting') {
      try {
        await api.cancelLogin(taskId)
      } catch {
        // ignore
      }
    }
    onClose()
  }

  const isWorking = status === 'starting' || status === 'waiting'

  return (
    <Modal
      open={open}
      onClose={isWorking ? onCancel : onClose}
      title="เพิ่มบัญชี X"
      closeOnBackdrop={!isWorking}
    >
      {status === 'idle' && (
        <div className="modal-form">
          <div className="helper-callout">
            <span style={{ fontSize: 22, lineHeight: 1 }}>🌐</span>
            <span>
              จะมีหน้าต่าง browser เปิดขึ้นมา <strong>กรุณา login ด้วย email และรหัสผ่านของ X โดยตรง</strong> อย่ากด "Sign in with Google" เพราะ Google จะบล็อก browser อัตโนมัติค่ะ
            </span>
          </div>

          {error && <div className="form-error">{error}</div>}
          <div className="form-actions">
            <button type="button" className="btn-ghost" onClick={onClose}>
              ยกเลิก
            </button>
            <button type="button" className="btn-primary" onClick={onStart}>
              เปิด browser เลย
            </button>
          </div>
        </div>
      )}

      {isWorking && (
        <div className="modal-form">
          <div className="login-progress">
            <span className="dots"><span /><span /><span /></span>
            <p>
              {status === 'starting'
                ? 'กำลังเปิด browser ให้คุณ…'
                : 'กรุณา login ในหน้าต่างที่เพิ่งเปิดขึ้นมาค่ะ'}
            </p>
            <p className="muted-note">รอได้สูงสุด 5 นาที</p>
          </div>
          <div className="form-actions">
            <button type="button" className="btn-ghost" onClick={onCancel}>
              ยกเลิก
            </button>
          </div>
        </div>
      )}

      {status === 'success' && (
        <div className="modal-form">
          <div className="success-block">
            <span className="pill ok">login สำเร็จ</span>
            {handle && <p>บันทึก {handle} เรียบร้อยแล้วค่ะ</p>}
          </div>
          <div className="form-actions">
            <button type="button" className="btn-primary" onClick={onClose}>
              เสร็จสิ้น
            </button>
          </div>
        </div>
      )}

      {(status === 'failed' || status === 'canceled') && (
        <div className="modal-form">
          <div className="form-error">
            {error || (status === 'canceled' ? 'ยกเลิกแล้ว' : 'ไม่สำเร็จ')}
          </div>
          <div className="form-actions">
            <button type="button" className="btn-primary" onClick={onClose}>
              ปิด
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

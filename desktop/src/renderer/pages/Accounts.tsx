import { useEffect, useState } from 'react'
import { AccountSettingsModal } from '../components/AccountSettingsModal'
import { AutoSwitch } from '../components/AutoSwitch'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { EmptyState } from '../components/EmptyState'
import { Modal } from '../components/Modal'
import { StylePicker } from '../components/StylePicker'
import { TestPostModal } from '../components/TestPostModal'
import { TweetPickerModal } from '../components/TweetPickerModal'
import { formatHour, formatRelative, formatSeconds } from '../lib/time'
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
  // When a row's style picker opens, remember which slot the click targets
  // so the picker can route saves to the right column.
  const [styleOf, setStyleOf] = useState<
    { acc: XAccountOut; slot: 'post' | 'reply' } | null
  >(null)
  const [tweetsOf, setTweetsOf] = useState<XAccountOut | null>(null)
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

  // Light poll while any account has a scan running so the badge counter
  // ticks up live. Stops polling when no scans are active to avoid burning
  // network on an idle page. 2s matches the modal's internal poll cadence.
  const anyScanning = accounts.some((a) => a.is_scanning)
  useEffect(() => {
    if (!anyScanning) return
    const iv = setInterval(() => {
      api
        .listAccounts()
        .then((rows) => setAccounts(rows))
        .catch(() => {
          /* transient — next tick retries */
        })
    }, 2000)
    return () => clearInterval(iv)
  }, [anyScanning])

  function postPromptFor(acc: XAccountOut): PromptOut | undefined {
    if (acc.default_prompt_id == null) return undefined
    return prompts.find((p) => p.id === acc.default_prompt_id)
  }
  function replyPromptFor(acc: XAccountOut): PromptOut | undefined {
    if (acc.reply_prompt_id == null) return undefined
    return prompts.find((p) => p.id === acc.reply_prompt_id)
  }

  async function onTogglePosting(acc: XAccountOut, checked: boolean) {
    if (
      checked &&
      acc.default_prompt_id === null &&
      acc.reply_prompt_id === null
    ) {
      setAlert(
        'ตั้งสไตล์การเขียน (โพสต์ใหม่หรือ reply อย่างน้อยอย่างหนึ่ง) ก่อนเปิดใช้งานนะคะ',
      )
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

  async function onRunModeChange(acc: XAccountOut, newMode: 'post_only' | 'reply_only' | 'both') {
    try {
      const updated = await api.updateAccount(acc.id, {
        run_mode: newMode,
      })
      setAccounts((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
    } catch (e) {
      setAlert(e instanceof Error ? e.message : String(e))
    }
  }

  async function onAssignStyle(promptId: number) {
    // Capture styleOf into a local so the closure can't see a null value
    // after a downstream setStyleOf(null) batches in. Route by the slot the
    // user explicitly opened — the picker already pre-filters prompts by
    // slot, so trusting the click intent is both correct and cheaper than
    // re-fetching prompts to inspect the picked one's mode.
    const target = styleOf
    if (!target) return
    const patch: { default_prompt_id?: number; reply_prompt_id?: number } = {}
    if (target.slot === 'reply') {
      patch.reply_prompt_id = promptId
    } else {
      patch.default_prompt_id = promptId
    }
    try {
      const updated = await api.updateAccount(target.acc.id, patch)
      setAccounts((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a)),
      )
      // Refresh prompts so a freshly-created prompt shows up in the row
      // preview ("body slice", provider badge, etc) on the next render.
      const ps = await api.listPrompts()
      setPrompts(ps)
    } catch (e) {
      setAlert(e instanceof Error ? e.message : String(e))
    }
  }

  async function onClearReplySlot(acc: XAccountOut) {
    try {
      const updated = await api.updateAccount(acc.id, {
        reply_prompt_id: null,
      })
      setAccounts((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a)),
      )
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
            const postPrompt = postPromptFor(acc)
            const replyPrompt = replyPromptFor(acc)
            // "Last activity" = whichever slot ran more recently.
            const lastTs = [acc.last_post_at, acc.reply_last_run_at]
              .filter((s): s is string => !!s)
              .sort()
              .pop()
            const lastAt = lastTs ?? null
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
                      {acc.is_scanning && (
                        <span className="scan-badge">
                          <span className="scan-badge-dots">
                            <span /><span /><span />
                          </span>
                          กำลังสแกน {acc.scan_progress} โพสต์
                        </span>
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
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="auto-status-icon">
                        {acc.posting_enabled ? '✓' : '⏸'}
                      </span>
                      {acc.posting_enabled ? (
                        <span>
                          <strong>กำลังโพสต์อัตโนมัติ</strong> · ระหว่าง{' '}
                          {formatHour(acc.active_hours_start)}–
                          {formatHour(acc.active_hours_end)} ทุก{' '}
                          {formatSeconds(acc.min_interval_seconds)}–
                          {formatSeconds(acc.max_interval_seconds)}
                          {acc.daily_limit === 0
                            ? ' · ไม่จำกัดจำนวนต่อวัน'
                            : ` · ไม่เกิน ${acc.daily_limit} ครั้งต่อวัน`}
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
                    
                    <div style={{ paddingLeft: 24, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="field-label-plain" style={{ margin: 0, fontSize: 13 }}>โหมดการทำงาน:</span>
                      <select 
                        className="run-mode-select"
                        value={acc.run_mode || 'both'}
                        onChange={(e) => onRunModeChange(acc, e.target.value as 'post_only' | 'reply_only' | 'both')}
                      >
                        <option value="both">โพสต์ใหม่ + ตอบกลับ (ถ้าตั้งไว้)</option>
                        <option value="post_only">โพสต์ใหม่อย่างเดียว</option>
                        <option value="reply_only">ตอบกลับอย่างเดียว</option>
                      </select>
                    </div>
                  </div>
                </div>

                <div className="account-block-style">
                  <span style={{ fontSize: 22, lineHeight: 1 }}>
                    {postPrompt?.mode === 'manual' ? '📝' : '✦'}
                  </span>
                  {postPrompt ? (
                    <div className="account-block-style-info">
                      <div className="account-block-style-name">
                        <span className="slot-label">โพสต์ใหม่</span>{' '}
                        {postPrompt.name}{' '}
                        <span
                          className="provider-badge"
                          style={
                            postPrompt.mode === 'manual'
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
                          {postPrompt.mode === 'manual'
                            ? 'เขียนเอง · ไม่ใช้ AI'
                            : postPrompt.provider === 'openai'
                              ? 'OpenAI'
                              : 'Gemini'}
                        </span>
                      </div>
                      <div className="account-block-style-preview">
                        {postPrompt.body.slice(0, 80)}
                        {postPrompt.body.length > 80 ? '…' : ''}
                      </div>
                    </div>
                  ) : (
                    <span className="account-block-style-empty">
                      <span className="slot-label">โพสต์ใหม่</span> ยังไม่ได้ตั้งสไตล์
                    </span>
                  )}
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    onClick={() => setStyleOf({ acc, slot: 'post' })}
                  >
                    {postPrompt ? 'เปลี่ยนสไตล์' : 'ตั้งสไตล์'}
                  </button>
                </div>

                <div className="account-block-style account-block-style-reply">
                  <span style={{ fontSize: 22, lineHeight: 1 }}>💬</span>
                  {replyPrompt ? (
                    <div className="account-block-style-info">
                      <div className="account-block-style-name">
                        <span className="slot-label slot-label-reply">
                          Reply
                        </span>{' '}
                        {replyPrompt.name}{' '}
                        <span
                          className="provider-badge"
                          style={{
                            background: 'var(--primary-soft)',
                            color: 'var(--text)',
                            fontSize: 10,
                            padding: '2px 8px',
                            marginLeft: 4,
                          }}
                        >
                          {replyPrompt.reply_target_mode === 'all'
                            ? 'ทุกโพสต์'
                            : replyPrompt.reply_target_mode === 'latest_n'
                              ? `${replyPrompt.reply_target_count} ล่าสุด`
                              : '1 โพสต์'}
                        </span>
                      </div>
                      <div className="account-block-style-preview">
                        {replyPrompt.body.slice(0, 80)}
                        {replyPrompt.body.length > 80 ? '…' : ''}
                      </div>
                    </div>
                  ) : (
                    <span className="account-block-style-empty">
                      <span className="slot-label slot-label-reply">
                        Reply
                      </span>{' '}
                      ยังไม่ได้ตั้ง (เลือกได้ ถ้าอยากให้รัน reply ควบคู่ไปด้วย)
                    </span>
                  )}
                  <div style={{ display: 'flex', gap: 6 }}>
                    {replyPrompt && (
                      <button
                        type="button"
                        className="btn-ghost btn-sm"
                        onClick={() => onClearReplySlot(acc)}
                      >
                        เอาออก
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn-ghost btn-sm"
                      onClick={() => setStyleOf({ acc, slot: 'reply' })}
                    >
                      {replyPrompt ? 'เปลี่ยน' : 'ตั้ง reply'}
                    </button>
                  </div>
                </div>

                <div
                  className="row-actions"
                  style={{ alignSelf: 'flex-end' }}
                >
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => setTweetsOf(acc)}
                  >
                    จัดการโพสต์
                  </button>
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
        slot={styleOf?.slot ?? 'post'}
        currentPromptId={
          styleOf
            ? styleOf.slot === 'reply'
              ? (styleOf.acc.reply_prompt_id ?? null)
              : (styleOf.acc.default_prompt_id ?? null)
            : null
        }
        onClose={() => setStyleOf(null)}
        onSelected={onAssignStyle}
      />

      <TweetPickerModal
        open={tweetsOf !== null}
        account={tweetsOf}
        onClose={() => {
          setTweetsOf(null)
          // Refresh in case the scan completed while the modal was open —
          // last_scan_at / scanned_tweet_count get freshened in the list.
          refresh()
        }}
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

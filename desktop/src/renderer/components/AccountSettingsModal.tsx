import { useEffect, useState, type FormEvent } from 'react'
import { Modal } from './Modal'
import { api, type PromptOut, type XAccountOut } from '../lib/api'
import { formatHour } from '../lib/time'

const HOURS: number[] = Array.from({ length: 24 }, (_, i) => i)

type TimePreset = { label: string; sub: string; start: number; end: number }
const TIME_PRESETS: TimePreset[] = [
  { label: 'ตลอดวัน', sub: '00:00–23:00', start: 0, end: 23 },
  { label: 'เช้า-ค่ำ', sub: '07:00–22:00', start: 7, end: 22 },
  { label: 'กลางวัน', sub: '09:00–18:00', start: 9, end: 18 },
  { label: 'เย็น-ดึก', sub: '17:00–23:00', start: 17, end: 23 },
]

export function AccountSettingsModal({
  account,
  onClose,
}: {
  account: XAccountOut
  onClose: () => void
}) {
  const [prompts, setPrompts] = useState<PromptOut[]>([])
  const [dailyLimit, setDailyLimit] = useState(account.daily_limit)
  const [hourStart, setHourStart] = useState(account.active_hours_start)
  const [hourEnd, setHourEnd] = useState(account.active_hours_end)
  const [minInterval, setMinInterval] = useState(account.min_interval_minutes)
  const [maxInterval, setMaxInterval] = useState(account.max_interval_minutes)
  const matchedTime = TIME_PRESETS.find(
    (p) => p.start === hourStart && p.end === hourEnd,
  )
  const [customTime, setCustomTime] = useState(!matchedTime)
  const isCustomTime = customTime || !matchedTime
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api
      .listPrompts()
      .then(setPrompts)
      .catch(() => {})
  }, [])

  const linkedPrompt =
    account.default_prompt_id !== null
      ? prompts.find((p) => p.id === account.default_prompt_id)
      : null

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (minInterval < 5 || maxInterval < 5) {
      setError('ช่วงห่างต่ำสุดและสูงสุดต้องไม่น้อยกว่า 5 นาที')
      return
    }
    if (minInterval > maxInterval) {
      setError('ช่วงห่างต่ำสุดต้องน้อยกว่าหรือเท่ากับสูงสุด')
      return
    }
    setSubmitting(true)
    try {
      await api.updateAccount(account.id, {
        daily_limit: dailyLimit,
        active_hours_start: hourStart,
        active_hours_end: hourEnd,
        min_interval_minutes: minInterval,
        max_interval_minutes: maxInterval,
      })
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={`ตั้งค่า ${account.handle}`}>
      <form className="modal-form" onSubmit={onSubmit}>
        <div
          className="account-block-style"
          style={{ background: 'var(--cream)', borderStyle: 'solid' }}
        >
          <span style={{ fontSize: 22, lineHeight: 1 }}>
            {linkedPrompt?.mode === 'manual' ? '📝' : '✦'}
          </span>
          {linkedPrompt ? (
            <div className="account-block-style-info">
              <div className="account-block-style-name">
                สไตล์: {linkedPrompt.name}{' '}
                {linkedPrompt.mode === 'manual' && (
                  <span
                    className="provider-badge"
                    style={{
                      background: 'var(--lavender-soft)',
                      color: 'var(--text-on-lavender)',
                      fontSize: 10,
                      padding: '2px 8px',
                      marginLeft: 4,
                    }}
                  >
                    เขียนเอง · ไม่ใช้ AI
                  </span>
                )}
              </div>
              <div className="account-block-style-preview">
                เปลี่ยนสไตล์ได้จากการ์ดบัญชีหน้า "บัญชี"
              </div>
            </div>
          ) : (
            <span className="account-block-style-empty">
              ยังไม่ตั้งสไตล์ · ตั้งจากการ์ดบัญชีหน้า "บัญชี"
            </span>
          )}
        </div>

        <div className="field">
          <span className="field-label-plain">ช่วงเวลาที่จะโพสต์</span>
          <div className="interval-chips">
            {TIME_PRESETS.map((p) => (
              <button
                type="button"
                key={p.label}
                className={`interval-chip ${
                  !isCustomTime && matchedTime?.start === p.start
                    ? 'is-active'
                    : ''
                }`}
                onClick={() => {
                  setCustomTime(false)
                  setHourStart(p.start)
                  setHourEnd(p.end)
                }}
              >
                <span className="interval-chip-label">{p.label}</span>
                <span className="interval-chip-sub">{p.sub}</span>
              </button>
            ))}
            <button
              type="button"
              className={`interval-chip ${isCustomTime ? 'is-active' : ''}`}
              onClick={() => setCustomTime(true)}
            >
              <span className="interval-chip-label">กำหนดเอง</span>
              <span className="interval-chip-sub">
                {isCustomTime
                  ? `${formatHour(hourStart)}–${formatHour(hourEnd)}`
                  : '…'}
              </span>
            </button>
          </div>
          {isCustomTime && (
            <div className="field-row" style={{ marginTop: 8 }}>
              <label className="field">
                <span style={{ textTransform: 'none', letterSpacing: 0 }}>
                  เริ่ม
                </span>
                <select
                  value={hourStart}
                  onChange={(e) => setHourStart(Number(e.target.value))}
                >
                  {HOURS.map((h) => (
                    <option key={h} value={h}>
                      {String(h).padStart(2, '0')}:00
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span style={{ textTransform: 'none', letterSpacing: 0 }}>
                  หยุด
                </span>
                <select
                  value={hourEnd}
                  onChange={(e) => setHourEnd(Number(e.target.value))}
                >
                  {HOURS.map((h) => (
                    <option key={h} value={h}>
                      {String(h).padStart(2, '0')}:00
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </div>

        <label className="field">
          <span className="field-label-plain">โพสต์ได้สูงสุดต่อวัน</span>
          <input
            type="number"
            min={1}
            max={100}
            value={dailyLimit}
            onChange={(e) => setDailyLimit(Number(e.target.value))}
          />
        </label>

        <div className="field">
          <span className="field-label-plain">เว้นช่วงระหว่างโพสต์ของบัญชีนี้</span>
          <div className="field-row">
            <label className="field">
              <span style={{ textTransform: 'none', letterSpacing: 0 }}>
                ต่ำสุด (นาที)
              </span>
              <input
                type="number"
                min={5}
                max={1440}
                value={minInterval}
                onChange={(e) => setMinInterval(Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span style={{ textTransform: 'none', letterSpacing: 0 }}>
                สูงสุด (นาที)
              </span>
              <input
                type="number"
                min={5}
                max={1440}
                value={maxInterval}
                onChange={(e) => setMaxInterval(Number(e.target.value))}
              />
            </label>
          </div>
          <p className="muted-note" style={{ margin: '4px 0 0' }}>
            ระบบจะสุ่มเวลาในช่วงนี้ทุกครั้ง เพื่อให้ดูเป็นธรรมชาติ · ต่ำสุด 5 นาที (กันโดน X ตรวจจับว่าเป็น bot)
          </p>
        </div>

        {error && <div className="form-error">{error}</div>}
        <div className="form-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>
            ยกเลิก
          </button>
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'กำลังบันทึก…' : 'บันทึก'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

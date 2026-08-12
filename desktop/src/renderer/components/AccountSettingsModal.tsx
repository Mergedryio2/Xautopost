import { useCallback, useEffect, useState, type FormEvent, type WheelEvent } from 'react'
import { Modal } from './Modal'
import { api, type PromptOut, type XAccountOut } from '../lib/api'
import { formatSeconds } from '../lib/time'

// Snap a raw minute value to the nearest 30-minute step (0–1410)
function snapToStep(m: number, step = 30): number {
  return Math.round(m / step) * step
}

function fmtMin(m: number): string {
  const h = Math.floor(m / 60)
  const min = m % 60
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`
}

/** Drum-roll time stepper — H and M spinners with ▲▼ + scroll. */
function TimeStepper({
  value,
  onChange,
  label,
}: {
  value: number
  onChange: (m: number) => void
  label: string
}) {
  const hour   = Math.floor(value / 60)
  const minute = value % 60

  const setHour   = useCallback(
    (h: number) => onChange(((h + 24) % 24) * 60 + minute),
    [minute, onChange],
  )
  const setMinute = useCallback(
    (m: number) => onChange(hour * 60 + ((m + 60) % 60)),
    [hour, onChange],
  )

  function onWheelH(e: WheelEvent<HTMLDivElement>) {
    e.preventDefault()
    setHour(hour + (e.deltaY > 0 ? -1 : 1))
  }
  function onWheelM(e: WheelEvent<HTMLDivElement>) {
    e.preventDefault()
    setMinute(minute + (e.deltaY > 0 ? -1 : 1))
  }

  return (
    <div className="stepper-wrap">
      <span className="stepper-label">{label}</span>
      <div className="stepper-row">
        {/* Hour */}
        <div className="stepper-col" onWheel={onWheelH}>
          <button type="button" className="stepper-btn" onClick={() => setHour(hour + 1)} aria-label="hour up">▲</button>
          <div className="stepper-drum">{String(hour).padStart(2, '0')}</div>
          <button type="button" className="stepper-btn" onClick={() => setHour(hour - 1)} aria-label="hour down">▼</button>
        </div>
        <span className="stepper-colon">:</span>
        {/* Minute — step 1 */}
        <div className="stepper-col" onWheel={onWheelM}>
          <button type="button" className="stepper-btn" onClick={() => setMinute(minute + 1)} aria-label="minute up">▲</button>
          <div className="stepper-drum">{String(minute).padStart(2, '0')}</div>
          <button type="button" className="stepper-btn" onClick={() => setMinute(minute - 1)} aria-label="minute down">▼</button>
        </div>
      </div>
    </div>
  )
}

type TimePreset = { label: string; sub: string; start: number; end: number }
const TIME_PRESETS: TimePreset[] = [
  { label: 'ตลอดวัน', sub: '00:00–23:00', start: 0,    end: 23 * 60 },
  { label: 'เช้า-ค่ำ', sub: '07:00–22:00', start: 7 * 60, end: 22 * 60 },
  { label: 'กลางวัน', sub: '09:00–18:00', start: 9 * 60, end: 18 * 60 },
  { label: 'เย็น-ดึก', sub: '17:00–23:00', start: 17 * 60, end: 23 * 60 },
]

export function AccountSettingsModal({
  account,
  onClose,
}: {
  account: XAccountOut
  onClose: () => void
}) {
  const [prompts, setPrompts] = useState<PromptOut[]>([])
  // 0 in DB = unlimited. Track the checkbox state separately so the user can
  // toggle back to a number without losing the value they had typed.
  const [dailyLimit, setDailyLimit] = useState(
    account.daily_limit === 0 ? 10 : account.daily_limit,
  )
  const [unlimitedDaily, setUnlimitedDaily] = useState(account.daily_limit === 0)
  // Backward-compat: old DB values stored as hours (0–23); convert to minutes.
  const rawStart = account.active_hours_start
  const rawEnd = account.active_hours_end
  const initStart = rawStart <= 23 ? rawStart * 60 : rawStart
  const initEnd   = rawEnd   <= 23 ? rawEnd   * 60 : rawEnd

  const [minStart, setMinStart] = useState(initStart)
  const [minEnd,   setMinEnd]   = useState(initEnd)
  const [minInterval, setMinInterval] = useState(account.min_interval_seconds)
  const [maxInterval, setMaxInterval] = useState(account.max_interval_seconds)
  const matchedTime = TIME_PRESETS.find(
    (p) => p.start === minStart && p.end === minEnd,
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
    if (minInterval < 1 || maxInterval < 1) {
      setError('ช่วงห่างต่ำสุดและสูงสุดต้องไม่น้อยกว่า 1 วินาที')
      return
    }
    if (minInterval > maxInterval) {
      setError('ช่วงห่างต่ำสุดต้องน้อยกว่าหรือเท่ากับสูงสุด')
      return
    }
    if (!unlimitedDaily && dailyLimit < 1) {
      setError('โพสต์ต่อวันต้องอย่างน้อย 1 ครั้ง หรือเลือก "ไม่จำกัด"')
      return
    }
    setSubmitting(true)
    try {
      await api.updateAccount(account.id, {
        daily_limit: unlimitedDaily ? 0 : dailyLimit,
        active_hours_start: minStart,
        active_hours_end: minEnd,
        min_interval_seconds: minInterval,
        max_interval_seconds: maxInterval,
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
                  setMinStart(p.start)
                  setMinEnd(p.end)
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
                  ? `${fmtMin(minStart)}–${fmtMin(minEnd)}`
                  : '…'}
              </span>
            </button>
          </div>
          {isCustomTime && (
            <div className="stepper-time-row">
              <TimeStepper
                label="เริ่ม"
                value={minStart}
                onChange={(m) => { setMinStart(m); setCustomTime(true) }}
              />
              <div className="stepper-time-sep">→</div>
              <TimeStepper
                label="หยุด"
                value={minEnd}
                onChange={(m) => { setMinEnd(m); setCustomTime(true) }}
              />
            </div>
          )}
        </div>

        <div className="field">
          <span className="field-label-plain">โพสต์ได้สูงสุดต่อวัน</span>
          <label
            className="toggle-row"
            style={{ marginBottom: 8, padding: '8px 12px' }}
          >
            <span>
              <strong>ไม่จำกัด</strong>
              <span
                className="muted-note"
                style={{ display: 'block', margin: '4px 0 0' }}
              >
                โพสต์ได้เรื่อยๆ จนกว่าจะถึงเวลานอกช่วง
              </span>
            </span>
            <input
              type="checkbox"
              checked={unlimitedDaily}
              onChange={(e) => setUnlimitedDaily(e.target.checked)}
            />
          </label>
          {!unlimitedDaily && (
            <input
              type="number"
              min={1}
              max={100000}
              value={dailyLimit}
              onChange={(e) => setDailyLimit(Number(e.target.value))}
            />
          )}
        </div>

        <div className="field">
          <span className="field-label-plain">เว้นช่วงระหว่างโพสต์ของบัญชีนี้</span>
          <div className="field-row">
            <label className="field">
              <span style={{ textTransform: 'none', letterSpacing: 0 }}>
                ต่ำสุด (วินาที)
              </span>
              <input
                type="number"
                min={1}
                max={86400}
                value={minInterval}
                onChange={(e) => setMinInterval(Number(e.target.value))}
              />
              <span className="muted-note" style={{ marginTop: 4 }}>
                = {formatSeconds(minInterval)}
              </span>
            </label>
            <label className="field">
              <span style={{ textTransform: 'none', letterSpacing: 0 }}>
                สูงสุด (วินาที)
              </span>
              <input
                type="number"
                min={1}
                max={86400}
                value={maxInterval}
                onChange={(e) => setMaxInterval(Number(e.target.value))}
              />
              <span className="muted-note" style={{ marginTop: 4 }}>
                = {formatSeconds(maxInterval)}
              </span>
            </label>
          </div>
          <p className="muted-note" style={{ margin: '4px 0 0' }}>
            ระบบจะสุ่มเวลาในช่วงนี้ทุกครั้ง เพื่อให้ดูเป็นธรรมชาติ · ต่ำสุด 1 วินาที
          </p>
          {minInterval < 60 && (
            <p
              className="muted-note"
              style={{ margin: '4px 0 0', color: 'var(--warn-fg)' }}
            >
              ⚠️ ต่ำกว่า 1 นาทีอาจเสี่ยงโดน X ตรวจจับว่าเป็น bot
            </p>
          )}
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

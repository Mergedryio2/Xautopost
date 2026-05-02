import { useState } from 'react'

type Preset = { label: string; sub: string; seconds: number }
type Unit = 's' | 'm' | 'h'

const PRESETS: Preset[] = [
  { label: 'เร็ว', sub: '30 วินาที', seconds: 30 },
  { label: 'ถี่', sub: '5 นาที', seconds: 5 * 60 },
  { label: 'ปกติ', sub: '30 นาที', seconds: 30 * 60 },
  { label: 'ช้า', sub: '2 ชม.', seconds: 2 * 60 * 60 },
]

const UNIT_FACTOR: Record<Unit, number> = { s: 1, m: 60, h: 3600 }
const UNIT_LABEL: Record<Unit, string> = {
  s: 'วินาที',
  m: 'นาที',
  h: 'ชั่วโมง',
}

export function formatInterval(seconds: number): string {
  if (seconds < 60) return `${seconds} วินาที`
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return s === 0 ? `${m} นาที` : `${m} นาที ${s} วิ`
  }
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds - h * 3600) / 60)
  if (m === 0) return `${h} ชั่วโมง`
  return `${h} ชม. ${m} น.`
}

function bestUnitFor(seconds: number): Unit {
  if (seconds % 3600 === 0) return 'h'
  if (seconds % 60 === 0) return 'm'
  return 's'
}

export function IntervalPicker({
  value,
  onChange,
  min = 1,
  max = 6 * 60 * 60,
}: {
  value: number
  onChange: (seconds: number) => void
  min?: number
  max?: number
}) {
  const matched = PRESETS.find((p) => p.seconds === value)
  const [customMode, setCustomMode] = useState(!matched)
  const isCustom = customMode || !matched
  const [unit, setUnit] = useState<Unit>(() => bestUnitFor(value))

  function pickPreset(seconds: number) {
    setCustomMode(false)
    onChange(seconds)
    setUnit(bestUnitFor(seconds))
  }

  function pickCustom() {
    setCustomMode(true)
  }

  function changeUnit(u: Unit) {
    setUnit(u)
  }

  function changeAmount(amount: number) {
    if (Number.isNaN(amount) || amount < 1) amount = 1
    const seconds = Math.min(max, Math.max(min, amount * UNIT_FACTOR[unit]))
    onChange(seconds)
  }

  const displayAmount = Math.max(1, Math.round(value / UNIT_FACTOR[unit]))
  const minForUnit = Math.max(1, Math.ceil(min / UNIT_FACTOR[unit]))
  const maxForUnit = Math.floor(max / UNIT_FACTOR[unit])

  return (
    <div className="interval-picker">
      <div className="interval-chips">
        {PRESETS.map((p) => (
          <button
            type="button"
            key={p.seconds}
            className={`interval-chip ${
              !isCustom && matched?.seconds === p.seconds ? 'is-active' : ''
            }`}
            onClick={() => pickPreset(p.seconds)}
          >
            <span className="interval-chip-label">{p.label}</span>
            <span className="interval-chip-sub">{p.sub}</span>
          </button>
        ))}
        <button
          type="button"
          className={`interval-chip ${isCustom ? 'is-active' : ''}`}
          onClick={pickCustom}
        >
          <span className="interval-chip-label">กำหนดเอง</span>
          <span className="interval-chip-sub">
            {isCustom ? formatInterval(value) : '…'}
          </span>
        </button>
      </div>
      {isCustom && (
        <div className="interval-custom">
          <span className="muted-note is-inline">
            ทุก
          </span>
          <input
            type="number"
            className="rotation-input"
            min={minForUnit}
            max={maxForUnit}
            value={displayAmount}
            onChange={(e) => changeAmount(Number(e.target.value))}
          />
          <select
            className="interval-unit"
            value={unit}
            onChange={(e) => changeUnit(e.target.value as Unit)}
          >
            {(['s', 'm', 'h'] as Unit[]).map((u) => (
              <option key={u} value={u}>
                {UNIT_LABEL[u]}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  )
}

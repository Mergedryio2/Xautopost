import type { PostLogOut, XAccountOut } from './api'
import { activeMinutes } from './time'

// Backend stores naive Bangkok-local datetime; same pattern as time.ts.
function parseBkk(iso: string): Date {
  const hasOffset = /[+-]\d{2}:?\d{2}$|Z$/.test(iso)
  return new Date(hasOffset ? iso : `${iso}+07:00`)
}

export type AccountStateKind =
  | 'disabled'
  | 'no_style'
  | 'posting'
  | 'limit_reached'
  | 'waiting_window'
  | 'waiting_interval'
  | 'ready'

export type AccountStateTone = 'idle' | 'warn' | 'live' | 'wait' | 'ok'

export type AccountState = {
  kind: AccountStateKind
  label: string
  tone: AccountStateTone
  // Lower = more urgent / closer to posting; used to sort the Home grid so
  // the most actionable accounts appear in the first 4 slots and quieter
  // states (off-hours / limit-reached / no-style) sink to the modal.
  priority: number
}

// start / end are minutes since midnight, matching the backend's
// _in_active_hours. activeMinutes() upgrades legacy hour values.
function inActiveWindow(now: Date, start: number, end: number): boolean {
  const s = activeMinutes(start)
  const e = activeMinutes(end)
  if (s === e) return true // 24h
  const m = now.getHours() * 60 + now.getMinutes()
  if (s < e) return m >= s && m < e
  // Overnight window e.g. 22:00 → 06:00
  return m >= s || m < e
}

function nextWindowOpen(now: Date, start: number, end: number): Date {
  const s = activeMinutes(start)
  const next = new Date(now)
  next.setSeconds(0, 0)
  // If we're already past today's start, jump to tomorrow's
  if (now.getHours() * 60 + now.getMinutes() >= s) {
    next.setDate(next.getDate() + 1)
  }
  next.setHours(Math.floor(s / 60), s % 60)
  return next
}

function formatHHMM(d: Date): string {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatRelMinutes(minutes: number): string {
  if (minutes < 1) return 'อีกแป๊บ'
  if (minutes < 60) return `${Math.ceil(minutes)} นาที`
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  if (m === 0) return `${h} ชม.`
  return `${h} ชม. ${m} น.`
}

function formatRelSeconds(seconds: number): string {
  if (seconds < 1) return 'อีกแป๊บ'
  if (seconds < 60) return `${Math.ceil(seconds)} วินาที`
  return formatRelMinutes(seconds / 60)
}

export function todayPostCount(
  acc: XAccountOut,
  logs: PostLogOut[],
  now: Date = new Date(),
): number {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Bangkok',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  const today = fmt.format(now)
  return logs.filter(
    (l) =>
      l.x_account_id === acc.id &&
      l.status === 'success' &&
      fmt.format(parseBkk(l.timestamp)) === today,
  ).length
}

export function deriveAccountState(
  acc: XAccountOut,
  logs: PostLogOut[],
  now: Date = new Date(),
): AccountState {
  if (!acc.posting_enabled) {
    return {
      kind: 'disabled',
      label: 'ปิดอยู่',
      tone: 'idle',
      priority: 9_000,
    }
  }
  if (acc.default_prompt_id === null) {
    return {
      kind: 'no_style',
      label: 'ยังไม่ได้ตั้งสไตล์การเขียน',
      tone: 'warn',
      // Configuration issue — surface high so the user fixes it
      priority: 50,
    }
  }
  if (acc.is_posting) {
    return {
      kind: 'posting',
      label: 'กำลังโพสต์อยู่ตอนนี้',
      tone: 'live',
      priority: 0,
    }
  }

  const todayCount = todayPostCount(acc, logs, now)
  // daily_limit === 0 means unlimited; never trip the limit-reached state.
  if (acc.daily_limit > 0 && todayCount >= acc.daily_limit) {
    return {
      kind: 'limit_reached',
      label: `ครบโควต้าวันนี้แล้ว (${todayCount}/${acc.daily_limit}) · เริ่มใหม่พรุ่งนี้`,
      tone: 'idle',
      priority: 5_000,
    }
  }

  if (!inActiveWindow(now, acc.active_hours_start, acc.active_hours_end)) {
    const next = nextWindowOpen(now, acc.active_hours_start, acc.active_hours_end)
    return {
      kind: 'waiting_window',
      label: `พักนอกช่วงเวลา · เริ่มอีกครั้ง ${formatHHMM(next)}`,
      tone: 'idle',
      priority: 4_000,
    }
  }

  if (acc.last_post_at) {
    const lastMs = parseBkk(acc.last_post_at).getTime()
    const elapsedSec = (now.getTime() - lastMs) / 1_000
    if (elapsedSec < acc.min_interval_seconds) {
      const minRemainingSec = acc.min_interval_seconds - elapsedSec
      const maxRemainingSec = acc.max_interval_seconds - elapsedSec
      return {
        kind: 'waiting_interval',
        label:
          maxRemainingSec > minRemainingSec + 30
            ? `รออีก ${formatRelSeconds(minRemainingSec)} – ${formatRelSeconds(maxRemainingSec)}`
            : `รออีก ~${formatRelSeconds(minRemainingSec)}`,
        tone: 'wait',
        // Closer to ready = lower priority value = appears earlier.
        // 200 base + remaining-minutes keeps the spread bounded.
        priority: 200 + minRemainingSec / 60,
      }
    }
  }

  return {
    kind: 'ready',
    label:
      acc.daily_limit === 0
        ? `พร้อมโพสต์ทุกเมื่อ · วันนี้ ${todayCount} โพสต์`
        : `พร้อมโพสต์ทุกเมื่อ · ${todayCount}/${acc.daily_limit} วันนี้`,
    tone: 'ok',
    priority: 100,
  }
}

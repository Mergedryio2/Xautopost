import type { PostLogOut, XAccountOut } from './api'

// Backend stores naive Bangkok-local datetime; same pattern as time.ts.
function parseBkk(iso: string): Date {
  const hasOffset = /[+-]\d{2}:?\d{2}$|Z$/.test(iso)
  return new Date(hasOffset ? iso : `${iso}+07:00`)
}

export type AccountState =
  | { kind: 'disabled'; label: string; tone: 'idle' }
  | { kind: 'no_style'; label: string; tone: 'warn' }
  | { kind: 'posting'; label: string; tone: 'live' }
  | { kind: 'limit_reached'; label: string; tone: 'idle' }
  | { kind: 'waiting_window'; label: string; tone: 'idle' }
  | { kind: 'waiting_interval'; label: string; tone: 'wait' }
  | { kind: 'ready'; label: string; tone: 'ok' }

function inActiveWindow(now: Date, start: number, end: number): boolean {
  if (start === end) return true // 24h
  const h = now.getHours()
  if (start < end) return h >= start && h < end
  // Overnight window e.g. 22 → 6
  return h >= start || h < end
}

function nextWindowOpen(now: Date, start: number, end: number): Date {
  const next = new Date(now)
  next.setMinutes(0, 0, 0)
  // If we're already past today's start hour, jump to tomorrow's
  if (now.getHours() >= start) {
    next.setDate(next.getDate() + 1)
  }
  next.setHours(start)
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
    return { kind: 'disabled', label: 'ปิดอยู่', tone: 'idle' }
  }
  if (acc.default_prompt_id === null) {
    return {
      kind: 'no_style',
      label: 'ยังไม่ได้ตั้งสไตล์การเขียน',
      tone: 'warn',
    }
  }
  if (acc.is_posting) {
    return {
      kind: 'posting',
      label: 'กำลังโพสต์อยู่ตอนนี้',
      tone: 'live',
    }
  }

  const todayCount = todayPostCount(acc, logs, now)
  if (todayCount >= acc.daily_limit) {
    return {
      kind: 'limit_reached',
      label: `ครบโควต้าวันนี้แล้ว (${todayCount}/${acc.daily_limit}) · เริ่มใหม่พรุ่งนี้`,
      tone: 'idle',
    }
  }

  if (!inActiveWindow(now, acc.active_hours_start, acc.active_hours_end)) {
    const next = nextWindowOpen(now, acc.active_hours_start, acc.active_hours_end)
    return {
      kind: 'waiting_window',
      label: `พักนอกช่วงเวลา · เริ่มอีกครั้ง ${formatHHMM(next)}`,
      tone: 'idle',
    }
  }

  if (acc.last_post_at) {
    const lastMs = parseBkk(acc.last_post_at).getTime()
    const elapsedMin = (now.getTime() - lastMs) / 60_000
    if (elapsedMin < acc.min_interval_minutes) {
      const minRemaining = acc.min_interval_minutes - elapsedMin
      const maxRemaining = acc.max_interval_minutes - elapsedMin
      return {
        kind: 'waiting_interval',
        label:
          maxRemaining > minRemaining + 0.5
            ? `รออีก ${formatRelMinutes(minRemaining)} – ${formatRelMinutes(maxRemaining)}`
            : `รออีก ~${formatRelMinutes(minRemaining)}`,
        tone: 'wait',
      }
    }
  }

  return {
    kind: 'ready',
    label: `พร้อมโพสต์ทุกเมื่อ · ${todayCount}/${acc.daily_limit} วันนี้`,
    tone: 'ok',
  }
}

// Backend stores naive Bangkok-local datetime. Append +07:00 if no offset.
function parseBkk(iso: string): Date {
  const hasOffset = /[+-]\d{2}:?\d{2}$|Z$/.test(iso)
  return new Date(hasOffset ? iso : `${iso}+07:00`)
}

export function formatTime(iso: string): string {
  return parseBkk(iso).toLocaleString('th-TH', {
    timeZone: 'Asia/Bangkok',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function formatTimeShort(iso: string): string {
  return parseBkk(iso).toLocaleString('th-TH', {
    timeZone: 'Asia/Bangkok',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatRelative(iso: string): string {
  const then = parseBkk(iso).getTime()
  const now = Date.now()
  const sec = Math.round((now - then) / 1000)
  if (sec < 0) return 'อีกสักครู่'
  if (sec < 30) return 'เมื่อสักครู่'
  if (sec < 60) return `${sec} วินาทีที่แล้ว`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} นาทีที่แล้ว`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr} ชั่วโมงที่แล้ว`
  const day = Math.round(hr / 24)
  if (day < 7) return `${day} วันที่แล้ว`
  return formatTime(iso)
}

export function isToday(iso: string): boolean {
  const d = parseBkk(iso)
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Bangkok',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  return fmt.format(d) === fmt.format(new Date())
}

export function formatHour(h: number): string {
  return `${String(h).padStart(2, '0')}:00`
}

// Render a duration in seconds as a Thai short form ("45 วินาที", "5 นาที",
// "2 ชม. 30 น.") so the user can sanity-check what they typed in the seconds
// field of the per-account interval setting.
export function formatSeconds(s: number): string {
  if (!Number.isFinite(s) || s <= 0) return '0 วินาที'
  if (s < 60) return `${Math.round(s)} วินาที`
  const totalMin = Math.round(s / 60)
  if (totalMin < 60) return `${totalMin} นาที`
  const hr = Math.floor(totalMin / 60)
  const min = totalMin % 60
  if (min === 0) return `${hr} ชม.`
  return `${hr} ชม. ${min} น.`
}

import { useEffect, useMemo, useState } from 'react'
import { EmptyState } from '../components/EmptyState'
import { Mascot } from '../components/Mascot'
import {
  deriveAccountState,
  type AccountState,
} from '../lib/account-state'
import { formatHour, formatRelative, formatTimeShort, isToday } from '../lib/time'
import {
  api,
  type Operator,
  type PostLogOut,
  type XAccountOut,
} from '../lib/api'

export function Home({
  operator,
  onGoToAccounts,
}: {
  operator: Operator
  onGoToAccounts: () => void
}) {
  const [accounts, setAccounts] = useState<XAccountOut[]>([])
  const [logs, setLogs] = useState<PostLogOut[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [, forceTick] = useState(0)

  async function refresh() {
    try {
      setError(null)
      const [accs, ls] = await Promise.all([
        api.listAccounts(),
        api.listLogs({ limit: 30 }),
      ])
      setAccounts(accs)
      setLogs(ls)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // 8s server poll: catches `is_posting=true` while a browser is open
    // (a single post takes ~30-60s) so the live indicator shows up
    // promptly when the scheduler kicks off a post.
    const id = setInterval(refresh, 8_000)
    return () => clearInterval(id)
  }, [])

  // 5s client tick to refresh "ago" labels and per-account countdowns
  // without paying server round-trips.
  useEffect(() => {
    const id = setInterval(() => forceTick((n) => n + 1), 5_000)
    return () => clearInterval(id)
  }, [])

  const active = useMemo(
    () => accounts.filter((a) => a.posting_enabled),
    [accounts],
  )
  const todayLogs = useMemo(
    () => logs.filter((l) => isToday(l.timestamp)),
    [logs],
  )
  const successToday = todayLogs.filter((l) => l.status === 'success').length
  const successPct =
    todayLogs.length > 0
      ? Math.round((successToday / todayLogs.length) * 100)
      : null

  const accountById = useMemo(
    () => new Map(accounts.map((a) => [a.id, a])),
    [accounts],
  )

  if (loading) {
    return (
      <div className="empty-state empty-large">
        <Mascot mood="sleep" size={96} />
        <p className="empty-title">กำลังเตรียมข้อมูล</p>
      </div>
    )
  }

  return (
    <>
      <section className="home-hero">
        <div className="home-hero-mascot">
          <Mascot mood={active.length > 0 ? 'working' : 'sleep'} size={72} />
        </div>
        <div className="home-hero-info">
          {accounts.length === 0 ? (
            <>
              <h2 className="home-hero-title">ยินดีต้อนรับ {operator.name}</h2>
              <p className="home-hero-sub">
                เพิ่มบัญชี X แรกของคุณ แล้วให้ AI ช่วยโพสต์ตามสไตล์ที่คุณตั้งไว้ค่ะ
              </p>
            </>
          ) : active.length > 0 ? (
            <>
              <h2 className="home-hero-title">
                กำลังดูแล {active.length} จาก {accounts.length} บัญชีให้คุณอยู่
              </h2>
              <p className="home-hero-sub">
                ระบบจะสุ่มเวลาโพสต์ให้แต่ละบัญชี เคารพช่วงเวลาและจำนวนต่อวันที่ตั้งไว้
              </p>
            </>
          ) : (
            <>
              <h2 className="home-hero-title">ตอนนี้พักอยู่</h2>
              <p className="home-hero-sub">
                ทุกบัญชีถูกปิดอยู่ · เปิดที่แท็บ "บัญชี" เมื่อพร้อมจะให้ระบบโพสต์ค่ะ
              </p>
            </>
          )}
        </div>
        {accounts.length === 0 && (
          <button
            type="button"
            className="btn-primary home-hero-cta"
            onClick={onGoToAccounts}
          >
            + เพิ่มบัญชีแรก
          </button>
        )}
      </section>

      {error && <div className="form-error">{error}</div>}

      {active.length > 0 && (
        <section className="card">
          <h3 className="card-title">บัญชีที่กำลังหมุนเวียน</h3>
          <div className="home-account-grid">
            {active.map((acc) => {
              const lastLog = logs.find(
                (l) => l.x_account_id === acc.id && l.status === 'success',
              )
              const state = deriveAccountState(acc, logs)
              return (
                <article
                  key={acc.id}
                  className={`home-account-card${state.kind === 'posting' ? ' is-posting' : ''}`}
                >
                  <div className="home-account-head">
                    <div
                      className="row-avatar"
                      style={{ background: 'var(--lavender)' }}
                    >
                      {acc.handle.replace('@', '').slice(0, 1).toUpperCase()}
                    </div>
                    <span className="home-account-handle">{acc.handle}</span>
                    <StatePill state={state} />
                  </div>
                  <div className="row-meta">
                    <span className="muted-note" style={{ margin: 0 }}>
                      ⏱ ทุก {acc.min_interval_minutes}–{acc.max_interval_minutes} นาที
                    </span>
                    <span className="muted-note" style={{ margin: 0 }}>
                      ☀️ {formatHour(acc.active_hours_start)}–
                      {formatHour(acc.active_hours_end)}
                    </span>
                  </div>
                  {lastLog ? (
                    <div className="home-account-recent">
                      <strong style={{ color: 'var(--text)' }}>
                        {formatRelative(lastLog.timestamp)}:
                      </strong>{' '}
                      {lastLog.content || '(ไม่มีเนื้อหา)'}
                    </div>
                  ) : (
                    <div className="home-account-recent">
                      <em>ยังไม่เคยโพสต์ตั้งแต่เปิดใช้งาน</em>
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        </section>
      )}

      <section className="card">
        <div
          className="section-head"
          style={{ marginBottom: 12 }}
        >
          <div>
            <h3 className="section-title" style={{ fontSize: 16 }}>
              โพสต์ล่าสุด
            </h3>
            <p className="section-sub">
              {todayLogs.length === 0
                ? 'รวมทุกบัญชี · ยังไม่มีโพสต์วันนี้'
                : `วันนี้ ${todayLogs.length} ครั้ง · สำเร็จ ${successToday}${
                    successPct !== null ? ` (${successPct}%)` : ''
                  }`}
            </p>
          </div>
        </div>
        {logs.length === 0 ? (
          <EmptyState
            mood="sleep"
            title="ยังไม่มีโพสต์เลยค่ะ"
            description={
              accounts.length === 0
                ? 'เริ่มจากเพิ่มบัญชี X แรกของคุณ'
                : active.length === 0
                  ? 'เปิดบัญชีในแท็บ "บัญชี" แล้วระบบจะเริ่มทำงานให้'
                  : 'รอสักครู่ ระบบกำลังเตรียมรอบโพสต์แรก'
            }
          />
        ) : (
          <div className="home-recent">
            {logs.slice(0, 8).map((l) => {
              const acc = l.x_account_id ? accountById.get(l.x_account_id) : null
              return (
                <div key={l.id} className="home-recent-item">
                  <span className="home-recent-when">
                    {formatTimeShort(l.timestamp)}
                  </span>
                  <span
                    className={
                      l.status === 'success'
                        ? 'pill ok'
                        : l.status === 'failed'
                          ? 'pill err'
                          : 'pill idle'
                    }
                    style={{ fontSize: 10, padding: '2px 8px' }}
                  >
                    {l.status === 'success'
                      ? 'สำเร็จ'
                      : l.status === 'failed'
                        ? 'ล้มเหลว'
                        : 'ข้าม'}
                  </span>
                  <span className="home-recent-handle">
                    {acc?.handle ?? '(ไม่ทราบ)'}
                  </span>
                  <span className="home-recent-text">{l.content || l.detail || ''}</span>
                </div>
              )
            })}
          </div>
        )}
      </section>
    </>
  )
}

function StatePill({ state }: { state: AccountState }) {
  const icon =
    state.kind === 'posting'
      ? '📮'
      : state.kind === 'ready'
        ? '🟢'
        : state.kind === 'waiting_interval'
          ? '⏱'
          : state.kind === 'waiting_window'
            ? '🌙'
            : state.kind === 'limit_reached'
              ? '🛑'
              : state.kind === 'no_style'
                ? '⚠️'
                : '·'
  return (
    <span className={`state-pill tone-${state.tone}`}>
      <span aria-hidden>{icon}</span>
      {state.label}
    </span>
  )
}

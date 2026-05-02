import { useEffect, useMemo, useState } from 'react'
import { EmptyState } from '../components/EmptyState'
import { Mascot } from '../components/Mascot'
import { Modal } from '../components/Modal'
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

const INLINE_LIMIT = 4

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

  const [showAllAccounts, setShowAllAccounts] = useState(false)

  // Sort active accounts by state priority so the user sees the most
  // actionable ones first: posting now → about to post → ready → waiting →
  // off-hours → limit-reached. Quieter states sink into the "ดูทั้งหมด"
  // modal when there are more than INLINE_LIMIT accounts.
  const activeSorted = useMemo(() => {
    const enabled = accounts.filter((a) => a.posting_enabled)
    return enabled
      .map((acc) => ({ acc, state: deriveAccountState(acc, logs) }))
      .sort((a, b) => a.state.priority - b.state.priority)
  }, [accounts, logs])

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
          <Mascot mood={activeSorted.length > 0 ? 'working' : 'sleep'} size={72} />
        </div>
        <div className="home-hero-info">
          {accounts.length === 0 ? (
            <>
              <h2 className="home-hero-title">ยินดีต้อนรับ {operator.name}</h2>
              <p className="home-hero-sub">
                เพิ่มบัญชี X แรกของคุณ แล้วให้ AI ช่วยโพสต์ตามสไตล์ที่คุณตั้งไว้ค่ะ
              </p>
            </>
          ) : activeSorted.length > 0 ? (
            <>
              <h2 className="home-hero-title">
                กำลังดูแล {activeSorted.length} จาก {accounts.length} บัญชีให้คุณอยู่
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

      {activeSorted.length > 0 && (
        <section className="card">
          <div className="section-head" style={{ marginBottom: 12 }}>
            <h3 className="card-title" style={{ margin: 0 }}>
              บัญชีที่กำลังหมุนเวียน
            </h3>
            {activeSorted.length > INLINE_LIMIT && (
              <button
                type="button"
                className="btn-ghost btn-sm"
                onClick={() => setShowAllAccounts(true)}
              >
                ดูทั้งหมด ({activeSorted.length})
              </button>
            )}
          </div>
          <div className="home-account-grid">
            {activeSorted.slice(0, INLINE_LIMIT).map(({ acc, state }) => (
              <AccountCard
                key={acc.id}
                acc={acc}
                state={state}
                logs={logs}
              />
            ))}
          </div>
          {activeSorted.length > INLINE_LIMIT && (
            <p
              className="muted-note"
              style={{ margin: '12px 0 0', textAlign: 'center' }}
            >
              อีก {activeSorted.length - INLINE_LIMIT} บัญชีอยู่ในรายการเต็ม
            </p>
          )}
        </section>
      )}

      <Modal
        open={showAllAccounts}
        onClose={() => setShowAllAccounts(false)}
        title={`บัญชีที่กำลังหมุนเวียนทั้งหมด (${activeSorted.length})`}
      >
        <div
          className="home-account-grid"
          style={{ gridTemplateColumns: '1fr', maxHeight: '60vh', overflowY: 'auto' }}
        >
          {activeSorted.map(({ acc, state }) => (
            <AccountCard key={acc.id} acc={acc} state={state} logs={logs} />
          ))}
        </div>
        <div className="form-actions" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="btn-primary"
            onClick={() => setShowAllAccounts(false)}
          >
            ปิด
          </button>
        </div>
      </Modal>

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
                : activeSorted.length === 0
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

function AccountCard({
  acc,
  state,
  logs,
}: {
  acc: XAccountOut
  state: AccountState
  logs: PostLogOut[]
}) {
  const lastLog = logs.find(
    (l) => l.x_account_id === acc.id && l.status === 'success',
  )
  return (
    <article
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

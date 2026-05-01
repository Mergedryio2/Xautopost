import { useEffect, useState, type FormEvent } from 'react'
import { Mascot } from '../components/Mascot'
import { api, type Operator } from '../lib/api'

const DEFAULT_COLOR = '#F4A6CD'
const PALETTE: readonly string[] = [
  DEFAULT_COLOR,
  '#FFD6A5',
  '#B8E6D9',
  '#E0D4F9',
  '#FFB4C6',
  '#FFC8A2',
]

type Mode = 'pick' | 'login' | 'signup'

export function Login({ onLogin }: { onLogin: (op: Operator) => void }) {
  const [operators, setOperators] = useState<Operator[]>([])
  const [loading, setLoading] = useState(true)
  const [mode, setMode] = useState<Mode>('pick')
  const [selected, setSelected] = useState<Operator | null>(null)
  const [name, setName] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [color, setColor] = useState(DEFAULT_COLOR)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    api
      .listOperators()
      .then((ops) => {
        setOperators(ops)
        if (ops.length === 0) setMode('signup')
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [])

  function pickOp(op: Operator) {
    setSelected(op)
    setName(op.name)
    setPassphrase('')
    setError(null)
    setMode('login')
  }

  function backToPick() {
    setMode('pick')
    setError(null)
    setPassphrase('')
  }

  function startSignup() {
    setMode('signup')
    setName('')
    setPassphrase('')
    setColor(DEFAULT_COLOR)
    setError(null)
  }

  async function submitLogin(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const op = await api.loginOperator({ name, passphrase })
      onLogin(op)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function submitSignup(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const op = await api.createOperator({
        name,
        passphrase,
        avatar_color: color,
      })
      onLogin(op)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const subtitle =
    mode === 'signup' && operators.length === 0
      ? 'มาสร้างโปรไฟล์แรกกันค่ะ'
      : mode === 'signup'
        ? 'สร้างโปรไฟล์ใหม่'
        : mode === 'login'
          ? 'ยินดีต้อนรับกลับมา'
          : 'เลือกโปรไฟล์เพื่อเข้าใช้งาน'

  return (
    <div className="login-shell">
      <div className="login-card">
        <header className="login-header">
          <Mascot mood={mode === 'login' ? 'hi' : 'hi'} size={56} />
          <div>
            <h1 className="app-title">Xautopost</h1>
            <p className="app-subtitle">{subtitle}</p>
          </div>
        </header>

        {loading ? (
          <div className="login-loading">
            <Mascot mood="sleep" size={72} />
          </div>
        ) : mode === 'pick' ? (
          <>
            <div className="op-grid">
              {operators.map((op) => (
                <button
                  type="button"
                  key={op.id}
                  className="op-card"
                  onClick={() => pickOp(op)}
                >
                  <div
                    className="op-avatar"
                    style={{ background: op.avatar_color }}
                  >
                    {op.name.slice(0, 1).toUpperCase()}
                  </div>
                  <span className="op-name">{op.name}</span>
                </button>
              ))}
            </div>
            <button
              type="button"
              className="btn-ghost btn-block"
              onClick={startSignup}
            >
              + เพิ่มโปรไฟล์ใหม่
            </button>
          </>
        ) : mode === 'login' && selected ? (
          <form onSubmit={submitLogin} className="login-form">
            <div className="op-card op-card-selected">
              <div
                className="op-avatar"
                style={{ background: selected.avatar_color }}
              >
                {selected.name.slice(0, 1).toUpperCase()}
              </div>
              <span className="op-name">{selected.name}</span>
            </div>
            <label className="field">
              <span className="field-label-plain">รหัสผ่าน</span>
              <input
                type="password"
                autoFocus
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                required
                minLength={4}
              />
            </label>
            {error && <div className="form-error">{error}</div>}
            <div className="form-actions">
              <button type="button" className="btn-ghost" onClick={backToPick}>
                กลับ
              </button>
              <button
                type="submit"
                className="btn-primary"
                disabled={submitting}
              >
                {submitting ? 'กำลังเข้า…' : 'เข้าใช้งาน'}
              </button>
            </div>
          </form>
        ) : (
          <form onSubmit={submitSignup} className="login-form">
            <label className="field">
              <span className="field-label-plain">ชื่อโปรไฟล์</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                minLength={2}
                maxLength={64}
                autoFocus
                placeholder="เช่น Mint, Workspace 1"
              />
            </label>
            <label className="field">
              <span className="field-label-plain">รหัสผ่าน</span>
              <input
                type="password"
                value={passphrase}
                onChange={(e) => setPassphrase(e.target.value)}
                required
                minLength={4}
                placeholder="อย่างน้อย 4 ตัวอักษร"
              />
            </label>
            <div className="field">
              <span className="field-label-plain">สีโปรไฟล์</span>
              <div className="color-picker">
                {PALETTE.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={`color-swatch ${color === c ? 'selected' : ''}`}
                    style={{ background: c }}
                    onClick={() => setColor(c)}
                    aria-label={c}
                  />
                ))}
              </div>
            </div>
            {error && <div className="form-error">{error}</div>}
            <div className="form-actions">
              {operators.length > 0 && (
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={backToPick}
                >
                  กลับ
                </button>
              )}
              <button
                type="submit"
                className="btn-primary"
                disabled={submitting}
              >
                {submitting ? 'กำลังสร้าง…' : 'สร้างโปรไฟล์'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { Mascot } from './components/Mascot'
import {
  api,
  getCurrentOperatorId,
  setCurrentOperator,
  type Operator,
} from './lib/api'
import { Accounts } from './pages/Accounts'
import { Home } from './pages/Home'
import { Login } from './pages/Login'
import { Settings } from './pages/Settings'
import { SetupWizard } from './pages/SetupWizard'

type Section = 'home' | 'accounts' | 'settings'

const SECTIONS: { value: Section; label: string; icon: string }[] = [
  { value: 'home', label: 'หน้าหลัก', icon: '🏠' },
  { value: 'accounts', label: 'บัญชี', icon: '🎭' },
  { value: 'settings', label: 'ตั้งค่า', icon: '⚙️' },
]

function wizardKey(opId: number) {
  return `xautopost.wizardSeen.${opId}`
}

export function App() {
  const [operator, setOperator] = useState<Operator | null>(null)
  const [section, setSection] = useState<Section>('home')
  const [showWizard, setShowWizard] = useState(false)
  const [bootstrapping, setBootstrapping] = useState(true)

  function activate(op: Operator) {
    setCurrentOperator(op.id)
    setOperator(op)
    setSection('home')
    const seen = localStorage.getItem(wizardKey(op.id)) === '1'
    setShowWizard(!seen)
  }

  // On first mount, try to resume a previous session from storage.
  useEffect(() => {
    const stored = getCurrentOperatorId()
    if (stored === null) {
      setBootstrapping(false)
      return
    }
    let cancelled = false
    api
      .listOperators()
      .then((ops) => {
        if (cancelled) return
        const found = ops.find((o) => o.id === stored)
        if (found) {
          activate(found)
        } else {
          setCurrentOperator(null)
        }
      })
      .catch(() => {
        if (!cancelled) setCurrentOperator(null)
      })
      .finally(() => {
        if (!cancelled) setBootstrapping(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function handleLogin(op: Operator) {
    activate(op)
  }

  function handleLogout() {
    setCurrentOperator(null)
    setOperator(null)
  }

  function dismissWizard() {
    if (operator) localStorage.setItem(wizardKey(operator.id), '1')
    setShowWizard(false)
  }

  if (bootstrapping) {
    return (
      <div className="login-shell">
        <div className="login-loading">
          <Mascot mood="sleep" size={96} />
        </div>
      </div>
    )
  }

  if (!operator) return <Login onLogin={handleLogin} />

  if (showWizard) {
    return (
      <SetupWizard
        operator={operator}
        onDone={dismissWizard}
        onSkip={dismissWizard}
      />
    )
  }

  return (
    <Shell
      operator={operator}
      section={section}
      onSection={setSection}
      onLogout={handleLogout}
      onOperatorChange={setOperator}
      onReopenWizard={() => setShowWizard(true)}
    />
  )
}

function Shell({
  operator,
  section,
  onSection,
  onLogout,
  onOperatorChange,
  onReopenWizard,
}: {
  operator: Operator
  section: Section
  onSection: (s: Section) => void
  onLogout: () => void
  onOperatorChange: (op: Operator) => void
  onReopenWizard: () => void
}) {
  const greeting = useMemo(() => {
    const h = new Date().getHours()
    if (h < 11) return 'อรุณสวัสดิ์'
    if (h < 17) return 'สวัสดี'
    if (h < 20) return 'สวัสดีตอนเย็น'
    return 'ราตรีสวัสดิ์'
  }, [])

  useEffect(() => {
    document.title = `Xautopost · ${operator.name}`
  }, [operator.name])

  return (
    <main className="container container-wide">
      <header className="app-header">
        <Mascot mood="hi" size={48} />
        <div className="header-text">
          <h1 className="app-title">Xautopost</h1>
          <p className="app-subtitle">
            {greeting}{' '}
            <span
              className="op-tag"
              style={{
                background: `${operator.avatar_color}33`,
                color: '#5b3a5e',
              }}
            >
              {operator.name}
            </span>
          </p>
        </div>
        <button
          type="button"
          className="btn-ghost btn-sm"
          onClick={onReopenWizard}
          title="เปิด Setup Wizard อีกครั้ง"
        >
          ดูคู่มือเริ่มต้น
        </button>
        <button type="button" className="btn-ghost btn-sm" onClick={onLogout}>
          ออกจากระบบ
        </button>
      </header>

      <nav className="nav-shell" role="tablist">
        {SECTIONS.map((s) => (
          <button
            key={s.value}
            type="button"
            className={`nav-section ${section === s.value ? 'is-active' : ''}`}
            onClick={() => onSection(s.value)}
            role="tab"
            aria-selected={section === s.value}
          >
            <span className="nav-icon">{s.icon}</span>
            {s.label}
          </button>
        ))}
      </nav>

      <section>
        {section === 'home' && (
          <Home
            operator={operator}
            onGoToAccounts={() => onSection('accounts')}
          />
        )}
        {section === 'accounts' && <Accounts />}
        {section === 'settings' && (
          <Settings operator={operator} onOperatorChange={onOperatorChange} />
        )}
      </section>
    </main>
  )
}

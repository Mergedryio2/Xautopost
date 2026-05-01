import { useEffect, useState, type FormEvent } from 'react'
import { Mascot } from '../components/Mascot'
import {
  api,
  type AiProvider,
  type LoginTaskStatus,
  type Operator,
  type PromptOut,
} from '../lib/api'

const TEMPLATES: { emoji: string; name: string; sub: string; body: string }[] = [
  {
    emoji: '✨',
    name: 'คำคมให้กำลังใจ',
    sub: 'โพสต์เชิงบวกสั้น กระชับ',
    body: 'คุณเป็น content creator ที่เขียนคำคมให้กำลังใจให้คนไทยอ่านบน X เขียนเป็นภาษาไทย ความยาวไม่เกิน 240 ตัวอักษร น้ำเสียงอบอุ่น จริงใจ ทุกครั้งให้สร้างคำคมที่แตกต่างกัน',
  },
  {
    emoji: '☕',
    name: 'ชวนกินอะไร',
    sub: 'แนะนำของกินไทย',
    body: 'คุณเป็น food blogger คนไทยที่โพสต์บน X แนะนำของกินไทยในช่วงเช้า กลางวัน หรือเย็น เขียนเหมือนเพื่อนชวนกินด้วย ภาษาไทย ความยาวไม่เกิน 200 ตัวอักษร',
  },
  {
    emoji: '📰',
    name: 'ข่าวเทคย่อย',
    sub: 'สรุปเทรนด์ AI / เทค',
    body: 'คุณเป็น tech journalist เขียนสรุปเทรนด์เทคโนโลยีหรือ AI เป็นภาษาไทย โทนเป็นกลาง ความยาวไม่เกิน 240 ตัวอักษร',
  },
  {
    emoji: '😆',
    name: 'มุกเบาๆ',
    sub: 'มุกตลก relatable',
    body: 'คุณเขียนมุกตลกเบาๆ บน X เกี่ยวกับชีวิตประจำวันของคนเมือง ภาษาไทย ความยาวไม่เกิน 180 ตัวอักษร เน้นมุกแบบ relatable ไม่ดราม่า',
  },
  {
    emoji: '🌙',
    name: 'ก่อนนอน',
    sub: 'ความคิดสั้นๆ โทนสงบ',
    body: 'คุณเขียนความคิดสั้นๆ ก่อนนอนบน X โทนใคร่ครวญ สงบ ภาษาไทย ความยาวไม่เกิน 200 ตัวอักษร',
  },
]

const DEFAULT_OPENAI_MODEL = 'gpt-4o-mini'
const DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash'

type Step = 'welcome' | 'ai' | 'style' | 'account' | 'ready'

export function SetupWizard({
  operator,
  onDone,
  onSkip,
}: {
  operator: Operator
  onDone: () => void
  onSkip: () => void
}) {
  const [step, setStep] = useState<Step>('welcome')
  const [provider, setProvider] = useState<AiProvider>('openai')
  const [savedPrompt, setSavedPrompt] = useState<PromptOut | null>(null)
  const [hasKey, setHasKey] = useState(false)
  const [hasAccount, setHasAccount] = useState(false)

  // pre-flight checks
  useEffect(() => {
    api
      .listApiKeys()
      .then((ks) => setHasKey(ks.length > 0))
      .catch(() => {})
    api
      .listAccounts()
      .then((as) => setHasAccount(as.length > 0))
      .catch(() => {})
    api
      .listPrompts()
      .then((ps) => {
        if (ps.length > 0) setSavedPrompt(ps[0]!)
      })
      .catch(() => {})
  }, [])

  const stepIndex = ['welcome', 'ai', 'style', 'account', 'ready'].indexOf(step)

  return (
    <div className="wizard-shell">
      <div className="wizard-card">
        <div className="wizard-progress">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className={`wizard-progress-dot ${
                stepIndex - 1 === i
                  ? 'is-active'
                  : stepIndex - 1 > i
                    ? 'is-done'
                    : ''
              }`}
            />
          ))}
        </div>

        {step === 'welcome' && (
          <WelcomeStep
            operator={operator}
            onNext={() => setStep('ai')}
            onSkip={onSkip}
          />
        )}
        {step === 'ai' && (
          <AiStep
            initialProvider={provider}
            hasExisting={hasKey}
            onChangeProvider={setProvider}
            onNext={() => {
              setHasKey(true)
              setStep('style')
            }}
            onBack={() => setStep('welcome')}
            onSkip={() => setStep('style')}
          />
        )}
        {step === 'style' && (
          <StyleStep
            provider={provider}
            existing={savedPrompt}
            disabled={!hasKey}
            onNext={(p) => {
              setSavedPrompt(p)
              setStep('account')
            }}
            onBack={() => setStep('ai')}
            onSkip={() => setStep('account')}
          />
        )}
        {step === 'account' && (
          <AccountStep
            hasExisting={hasAccount}
            onNext={() => {
              setHasAccount(true)
              setStep('ready')
            }}
            onBack={() => setStep('style')}
            onSkip={() => setStep('ready')}
          />
        )}
        {step === 'ready' && (
          <ReadyStep
            hasKey={hasKey}
            hasAccount={hasAccount}
            hasStyle={savedPrompt !== null}
            onDone={onDone}
          />
        )}
      </div>
    </div>
  )
}

function WelcomeStep({
  operator,
  onNext,
  onSkip,
}: {
  operator: Operator
  onNext: () => void
  onSkip: () => void
}) {
  return (
    <>
      <div className="wizard-hero">
        <Mascot mood="hi" size={120} />
        <h2 className="wizard-title">สวัสดีค่ะ {operator.name}</h2>
        <p className="wizard-desc">
          มาตั้งค่าให้ Xautopost ช่วยโพสต์ X ของคุณกันค่ะ ใช้เวลาไม่ถึง 3 นาที
          ขอให้คุณเตรียม API key ของ OpenAI หรือ Gemini ไว้ให้พร้อม
        </p>
      </div>
      <div className="wizard-cta-row">
        <button type="button" className="wizard-skip" onClick={onSkip}>
          ข้ามไปก่อน ทำเอง
        </button>
        <button type="button" className="btn-primary" onClick={onNext}>
          เริ่มกันเลย →
        </button>
      </div>
    </>
  )
}

function AiStep({
  initialProvider,
  hasExisting,
  onChangeProvider,
  onNext,
  onBack,
  onSkip,
}: {
  initialProvider: AiProvider
  hasExisting: boolean
  onChangeProvider: (p: AiProvider) => void
  onNext: () => void
  onBack: () => void
  onSkip: () => void
}) {
  const [provider, setProvider] = useState<AiProvider>(initialProvider)
  const [key, setKey] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function pick(p: AiProvider) {
    setProvider(p)
    onChangeProvider(p)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await api.createApiKey({ provider, key })
      onNext()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSubmitting(false)
    }
  }

  return (
    <>
      <div className="wizard-hero">
        <Mascot mood="working" size={88} />
        <h2 className="wizard-title">เชื่อม AI ที่จะช่วยเขียน</h2>
        <p className="wizard-desc">
          เลือก AI สักตัวแล้ววาง API key ลงไป กุญแจจะถูกเข้ารหัสก่อนเก็บลงเครื่องค่ะ
        </p>
      </div>

      {hasExisting && (
        <div className="helper-callout">
          <span style={{ fontSize: 22, lineHeight: 1 }}>✓</span>
          <span>
            คุณ<strong>มี AI เชื่อมไว้แล้ว</strong> จะข้ามขั้นนี้หรือเพิ่มอีกตัวก็ได้
          </span>
        </div>
      )}

      <form className="wizard-content" onSubmit={onSubmit}>
        <div className="field">
          <span className="field-label-plain">เลือก AI</span>
          <div
            className="style-template-grid"
            style={{ gridTemplateColumns: '1fr 1fr' }}
          >
            <button
              type="button"
              className={`style-template ${provider === 'openai' ? 'is-active' : ''}`}
              onClick={() => pick('openai')}
            >
              <span className="style-template-emoji">🟠</span>
              <span className="style-template-name">OpenAI</span>
              <span className="style-template-sub">GPT · ChatGPT</span>
            </button>
            <button
              type="button"
              className={`style-template ${provider === 'gemini' ? 'is-active' : ''}`}
              onClick={() => pick('gemini')}
            >
              <span className="style-template-emoji">💎</span>
              <span className="style-template-name">Gemini</span>
              <span className="style-template-sub">Google AI</span>
            </button>
          </div>
        </div>

        <label className="field">
          <span className="field-label-plain">API Key</span>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={provider === 'openai' ? 'sk-...' : 'AIza...'}
            minLength={8}
            autoFocus
          />
        </label>

        {error && <div className="form-error">{error}</div>}

        <div className="wizard-cta-row">
          <button type="button" className="wizard-skip" onClick={onSkip}>
            {hasExisting ? 'ใช้ AI เดิมไปก่อน →' : 'ข้ามขั้นนี้'}
          </button>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="btn-ghost" onClick={onBack}>
              ← ย้อน
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={submitting || key.length < 8}
            >
              {submitting ? 'เชื่อม…' : 'เชื่อม AI →'}
            </button>
          </div>
        </div>
      </form>
    </>
  )
}

function StyleStep({
  provider,
  existing,
  disabled,
  onNext,
  onBack,
  onSkip,
}: {
  provider: AiProvider
  existing: PromptOut | null
  disabled: boolean
  onNext: (p: PromptOut) => void
  onBack: () => void
  onSkip: () => void
}) {
  const [picked, setPicked] = useState<number>(0)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const t = TEMPLATES[picked]

  async function onContinue() {
    if (!t) return
    setSubmitting(true)
    setError(null)
    try {
      const saved = await api.createPrompt({
        name: t.name,
        body: t.body,
        provider,
        model:
          provider === 'openai' ? DEFAULT_OPENAI_MODEL : DEFAULT_GEMINI_MODEL,
      })
      onNext(saved)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSubmitting(false)
    }
  }

  return (
    <>
      <div className="wizard-hero">
        <Mascot mood="hi" size={88} />
        <h2 className="wizard-title">เลือกสไตล์การเขียน</h2>
        <p className="wizard-desc">
          AI จะเขียนทวีตตามสไตล์ที่คุณเลือก แก้ไขทีหลังได้ตลอด หรือสร้างเองในแอปก็ได้
        </p>
      </div>

      {existing && (
        <div className="helper-callout">
          <span style={{ fontSize: 22, lineHeight: 1 }}>✓</span>
          <span>
            คุณมีสไตล์ <strong>{existing.name}</strong> อยู่แล้ว · กด "ข้าม" ก็ได้
          </span>
        </div>
      )}

      <div className="wizard-content">
        <div className="style-template-grid">
          {TEMPLATES.map((tt, i) => (
            <button
              key={tt.name}
              type="button"
              className={`style-template ${picked === i ? 'is-active' : ''}`}
              onClick={() => setPicked(i)}
            >
              <span className="style-template-emoji">{tt.emoji}</span>
              <span className="style-template-name">{tt.name}</span>
              <span className="style-template-sub">{tt.sub}</span>
            </button>
          ))}
        </div>

        {error && <div className="form-error">{error}</div>}

        <div className="wizard-cta-row">
          <button type="button" className="wizard-skip" onClick={onSkip}>
            ข้ามขั้นนี้
          </button>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" className="btn-ghost" onClick={onBack}>
              ← ย้อน
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={onContinue}
              disabled={submitting || disabled}
              title={disabled ? 'เชื่อม AI ก่อนนะคะ' : undefined}
            >
              {submitting ? 'บันทึก…' : 'ใช้สไตล์นี้ →'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function AccountStep({
  hasExisting,
  onNext,
  onBack,
  onSkip,
}: {
  hasExisting: boolean
  onNext: () => void
  onBack: () => void
  onSkip: () => void
}) {
  const [taskId, setTaskId] = useState<string | null>(null)
  const [status, setStatus] = useState<LoginTaskStatus | 'idle' | 'starting'>(
    'idle',
  )
  const [handle, setHandle] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!taskId) return
    if (status !== 'waiting' && status !== 'starting') return
    const iv = setInterval(async () => {
      try {
        const s = await api.loginStatus(taskId)
        setStatus(s.status)
        setHandle(s.handle)
        if (s.error) setError(s.error)
        if (s.status === 'success') {
          setTimeout(() => onNext(), 800)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        clearInterval(iv)
      }
    }, 1500)
    return () => clearInterval(iv)
  }, [taskId, status, onNext])

  async function onStart() {
    setStatus('starting')
    setError(null)
    try {
      const r = await api.startLogin()
      setTaskId(r.task_id)
      setStatus('waiting')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setStatus('idle')
    }
  }

  const isWorking = status === 'starting' || status === 'waiting'

  return (
    <>
      <div className="wizard-hero">
        <Mascot
          mood={isWorking ? 'working' : status === 'success' ? 'hi' : 'hi'}
          size={88}
        />
        <h2 className="wizard-title">เพิ่มบัญชี X แรก</h2>
        <p className="wizard-desc">
          จะเปิดหน้าต่าง browser ให้ login เข้า X ระบบเก็บ session ไว้ในเครื่องคุณเท่านั้น
        </p>
      </div>

      {hasExisting && status === 'idle' && (
        <div className="helper-callout">
          <span style={{ fontSize: 22, lineHeight: 1 }}>✓</span>
          <span>
            คุณ<strong>มีบัญชี X อยู่แล้ว</strong> จะข้ามขั้นนี้ก็ได้
          </span>
        </div>
      )}

      <div className="wizard-content">
        {status === 'idle' && (
          <div className="helper-callout">
            <span style={{ fontSize: 22, lineHeight: 1 }}>💡</span>
            <span>
              <strong>กรุณา login ด้วย email/รหัสผ่านโดยตรง</strong> · อย่ากด "Sign in with Google" เพราะ Google จะ block browser อัตโนมัติค่ะ
            </span>
          </div>
        )}

        {isWorking && (
          <div className="login-progress">
            <span className="dots"><span /><span /><span /></span>
            <p>
              {status === 'starting'
                ? 'กำลังเปิด browser ให้คุณ…'
                : 'กรุณา login ในหน้าต่างที่เพิ่งเปิดขึ้น'}
            </p>
            <p className="muted-note">รอได้สูงสุด 5 นาที</p>
          </div>
        )}

        {status === 'success' && (
          <div className="success-block">
            <span className="pill ok">login สำเร็จ</span>
            {handle && <p>บันทึก {handle} แล้ว</p>}
          </div>
        )}

        {(status === 'failed' || status === 'canceled') && (
          <div className="form-error">
            {error || (status === 'canceled' ? 'ยกเลิกแล้ว' : 'ไม่สำเร็จ')}
          </div>
        )}

        {error && status === 'idle' && (
          <div className="form-error">{error}</div>
        )}

        <div className="wizard-cta-row">
          <button
            type="button"
            className="wizard-skip"
            onClick={onSkip}
            disabled={isWorking}
          >
            ข้าม - เพิ่มทีหลัง
          </button>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="btn-ghost"
              onClick={onBack}
              disabled={isWorking}
            >
              ← ย้อน
            </button>
            {status === 'idle' && (
              <button type="button" className="btn-primary" onClick={onStart}>
                เปิด browser เลย →
              </button>
            )}
            {(status === 'failed' || status === 'canceled') && (
              <button type="button" className="btn-primary" onClick={onStart}>
                ลองอีกครั้ง
              </button>
            )}
            {status === 'success' && (
              <button type="button" className="btn-primary" onClick={onNext}>
                ต่อไป →
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

function ReadyStep({
  hasKey,
  hasAccount,
  hasStyle,
  onDone,
}: {
  hasKey: boolean
  hasAccount: boolean
  hasStyle: boolean
  onDone: () => void
}) {
  const allReady = hasKey && hasAccount && hasStyle

  return (
    <>
      <div className="wizard-hero">
        <Mascot mood={allReady ? 'working' : 'hi'} size={120} />
        <h2 className="wizard-title">
          {allReady ? 'เรียบร้อย พร้อมใช้งานค่ะ' : 'ติดตั้งเบื้องต้นเสร็จแล้ว'}
        </h2>
        <p className="wizard-desc">
          {allReady
            ? 'ระบบจะเริ่มหมุนเวียนโพสต์ตามสไตล์ที่ตั้งไว้ คุณจะดูสถานะได้ที่หน้าหลัก'
            : 'คุณยังไม่ได้ตั้งค่าครบทุกอย่าง · ทำให้เสร็จทีหลังก็ได้ค่ะ'}
        </p>
      </div>

      <div className="wizard-content">
        <div className="card-list">
          <ChecklistRow done={hasKey} label="เชื่อม AI" />
          <ChecklistRow done={hasStyle} label="ตั้งสไตล์การเขียน" />
          <ChecklistRow done={hasAccount} label="เพิ่มบัญชี X" />
        </div>

        <div className="wizard-cta-row" style={{ justifyContent: 'flex-end' }}>
          <button
            type="button"
            className="btn-primary btn-block"
            onClick={onDone}
          >
            ไปยังหน้าหลัก
          </button>
        </div>
      </div>
    </>
  )
}

function ChecklistRow({ done, label }: { done: boolean; label: string }) {
  return (
    <div
      className="row-card"
      style={{
        background: done ? 'var(--mint-soft)' : 'var(--surface-soft)',
        borderColor: done ? 'var(--mint)' : 'var(--border)',
      }}
    >
      <div
        className="row-avatar"
        style={{
          background: done ? 'var(--mint)' : 'var(--idle-bg)',
          color: done ? 'var(--success-fg)' : 'var(--muted)',
        }}
      >
        {done ? '✓' : '·'}
      </div>
      <div className="row-info">
        <div className="row-title" style={{ color: done ? 'var(--success-fg)' : 'var(--muted)' }}>
          {label}
        </div>
      </div>
    </div>
  )
}

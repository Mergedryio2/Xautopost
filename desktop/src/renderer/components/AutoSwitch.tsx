type Size = 'sm' | 'md'

export function AutoSwitch({
  checked,
  onChange,
  disabled = false,
  disabledTitle,
  size = 'md',
  onLabel = 'อัตโนมัติ',
  offLabel = 'หยุดอยู่',
}: {
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
  disabledTitle?: string
  size?: Size
  onLabel?: string
  offLabel?: string
}) {
  return (
    <label
      className={`auto-switch auto-switch-${size} ${
        checked ? 'is-on' : 'is-off'
      } ${disabled ? 'is-disabled' : ''}`}
      title={disabled ? disabledTitle : undefined}
    >
      <input
        type="checkbox"
        role="switch"
        aria-checked={checked}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="auto-switch-track">
        <span className="auto-switch-thumb" />
      </span>
      <span className="auto-switch-label">
        {checked ? onLabel : offLabel}
      </span>
    </label>
  )
}

import type { CSSProperties } from 'react'

export function Logo({
  size = 48,
  style,
  ariaHidden = false,
}: {
  size?: number
  style?: CSSProperties
  ariaHidden?: boolean
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={ariaHidden ? undefined : 'img'}
      aria-hidden={ariaHidden || undefined}
      aria-label={ariaHidden ? undefined : 'Xautopost'}
      style={style}
    >
      <defs>
        <linearGradient
          id="xa-logo-bg"
          x1="6"
          y1="6"
          x2="58"
          y2="58"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#f4a6cd" />
          <stop offset="50%" stopColor="#e879a8" />
          <stop offset="100%" stopColor="#c39bdb" />
        </linearGradient>
        <linearGradient
          id="xa-logo-x"
          x1="20"
          y1="20"
          x2="44"
          y2="44"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#fff0f6" />
        </linearGradient>
      </defs>

      <rect width="64" height="64" rx="16" fill="url(#xa-logo-bg)" />
      <rect width="64" height="32" rx="16" fill="#ffffff" opacity="0.12" />

      <g
        stroke="url(#xa-logo-x)"
        strokeWidth="6.5"
        strokeLinecap="round"
        fill="none"
      >
        <line x1="22" y1="22" x2="42" y2="42" />
        <line x1="42" y1="22" x2="22" y2="42" />
      </g>

      <path
        d="M48 12 L48.9 9.4 L49.8 12 L52.4 12.9 L49.8 13.8 L48.9 16.4 L48 13.8 L45.4 12.9 Z"
        fill="#ffffff"
      />
      <circle cx="14" cy="50" r="1.6" fill="#ffffff" opacity="0.65" />
    </svg>
  )
}

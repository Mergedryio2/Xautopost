import type { CSSProperties } from 'react'

export type MascotMood = 'hi' | 'sleep' | 'working' | 'oops'

const BODY = '#ffe5d3'
const EAR_INNER = '#ffc8dc'
const CHEEK = '#ffc8dc'
const INK = '#4a3f4b'
const NOSE = '#e879a8'
const WHISKER = '#d4b9a6'

export function Mascot({
  mood = 'hi',
  size = 96,
  style,
  animated = true,
}: {
  mood?: MascotMood
  size?: number
  style?: CSSProperties
  animated?: boolean
}) {
  const cls = `mascot mascot-${mood}${animated ? '' : ' mascot-still'}`
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      role="img"
      aria-label="แมวกลม"
      style={style}
      className={cls}
    >
      <path d="M28 38 L36 18 L54 36 Z" fill={BODY} />
      <path d="M92 38 L84 18 L66 36 Z" fill={BODY} />
      <path d="M34 32 L38 24 L46 33 Z" fill={EAR_INNER} />
      <path d="M86 32 L82 24 L74 33 Z" fill={EAR_INNER} />

      <circle cx="60" cy="66" r="38" fill={BODY} />

      <ellipse cx="36" cy="76" rx="6" ry="4" fill={CHEEK} opacity="0.65" />
      <ellipse cx="84" cy="76" rx="6" ry="4" fill={CHEEK} opacity="0.65" />

      {mood === 'hi' && (
        <g>
          <ellipse cx="46" cy="62" rx="4" ry="5" fill={INK} />
          <ellipse cx="74" cy="62" rx="4" ry="5" fill={INK} />
          <circle cx="47.5" cy="60" r="1.3" fill="white" />
          <circle cx="75.5" cy="60" r="1.3" fill="white" />
        </g>
      )}
      {mood === 'sleep' && (
        <g>
          <path
            d="M40 62 Q46 66 52 62"
            stroke={INK}
            strokeWidth="2.6"
            fill="none"
            strokeLinecap="round"
          />
          <path
            d="M68 62 Q74 66 80 62"
            stroke={INK}
            strokeWidth="2.6"
            fill="none"
            strokeLinecap="round"
          />
        </g>
      )}
      {mood === 'working' && (
        <g>
          <path
            d="M40 64 L46 58 L52 64"
            stroke={INK}
            strokeWidth="2.6"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M68 64 L74 58 L80 64"
            stroke={INK}
            strokeWidth="2.6"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </g>
      )}
      {mood === 'oops' && (
        <g>
          <ellipse
            cx="46"
            cy="62"
            rx="5"
            ry="6"
            fill="white"
            stroke={INK}
            strokeWidth="1.6"
          />
          <ellipse
            cx="74"
            cy="62"
            rx="5"
            ry="6"
            fill="white"
            stroke={INK}
            strokeWidth="1.6"
          />
          <circle cx="46" cy="63" r="1.8" fill={INK} />
          <circle cx="74" cy="63" r="1.8" fill={INK} />
        </g>
      )}

      <path d="M58 72 L62 72 L60 75 Z" fill={NOSE} />

      {mood === 'hi' && (
        <path
          d="M55 77 Q60 81 65 77"
          stroke={INK}
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
        />
      )}
      {mood === 'sleep' && (
        <path
          d="M57 78 Q60 80 63 78"
          stroke={INK}
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
        />
      )}
      {mood === 'working' && (
        <path
          d="M55 78 Q60 82 65 78"
          stroke={INK}
          strokeWidth="1.8"
          fill="none"
          strokeLinecap="round"
        />
      )}
      {mood === 'oops' && (
        <ellipse cx="60" cy="80" rx="2.4" ry="2.8" fill={INK} />
      )}

      <line
        x1="22"
        y1="70"
        x2="32"
        y2="70"
        stroke={WHISKER}
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <line
        x1="22"
        y1="76"
        x2="32"
        y2="74"
        stroke={WHISKER}
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <line
        x1="88"
        y1="70"
        x2="98"
        y2="70"
        stroke={WHISKER}
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <line
        x1="88"
        y1="74"
        x2="98"
        y2="76"
        stroke={WHISKER}
        strokeWidth="1.2"
        strokeLinecap="round"
      />

      {mood === 'sleep' && animated && (
        <g className="mascot-zzz">
          <text
            x="92"
            y="24"
            fontFamily="Quicksand, sans-serif"
            fontSize="13"
            fontWeight="700"
            fill="#c8b8d6"
          >
            z
          </text>
          <text
            x="100"
            y="14"
            fontFamily="Quicksand, sans-serif"
            fontSize="10"
            fontWeight="700"
            fill="#d4c4e2"
          >
            z
          </text>
        </g>
      )}
      {mood === 'oops' && (
        <path
          d="M22 46 Q19 52 22 56 Q25 52 22 46 Z"
          fill="#9bd6e4"
          opacity="0.85"
        />
      )}
    </svg>
  )
}

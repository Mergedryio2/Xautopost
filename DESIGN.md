# Xautopost · Design Language

## Color

OKLCH-anchored, expressed in hex for legacy CSS where needed. Strategy is **Restrained**: tinted neutrals + pink/peach accent ≤ ~15% of any screen.

| Token | Hex | Role |
|---|---|---|
| `--bg-from` | `#ffeef3` | Background gradient anchor (warm pink-cream) |
| `--bg-to` | `#fff8f3` | Background gradient anchor (peach-cream) |
| `--surface` | `#ffffff` | Cards, modal body |
| `--surface-soft` | `#fffbfd` | Row cards, secondary surfaces (slight pink tint) |
| `--cream` | `#fff5ec` | Warm secondary surface (status bands) |
| `--border` | `#fce4ec` | Card borders, dividers (low-contrast pink) |
| `--primary` | `#f4a6cd` | Primary accent (rose pink) |
| `--primary-strong` | `#e879a8` | Primary on press / strong text |
| `--primary-soft` | `#ffe0ec` | Primary tint backgrounds |
| `--peach` | `#ffd6a5` | Accent #2 (warm) — provider badge, friendly tag |
| `--mint` | `#b8e6d9` | Accent #3 (cool) — success-adjacent, secondary tag |
| `--lavender` | `#e0d4f9` | Accent #4 — gradient counterpart, account avatar |
| `--text` | `#4a3f4b` | Body text — warm purple-gray, never `#000` |
| `--muted` | `#9b8b9e` | Secondary / hint text |
| `--success-bg` / `--success-fg` | `#dff5e8` / `#2e7d5b` | OK pill |
| `--warn-bg` / `--warn-fg` | `#fff1d6` / `#b07823` | Warning pill |
| `--error-bg` / `--error-fg` | `#ffe0e5` / `#c0395a` | Error pill, danger button |
| `--idle-bg` / `--idle-fg` | `#f0ebf4` / `#9b8b9e` | Neutral pill |
| `--text-on-peach` | `#7d4d1e` | Body text on `--peach`/`--peach-soft` surface |
| `--text-on-mint` | `#1f5046` | Body text on `--mint`/`--mint-soft` surface |
| `--text-on-lavender` | `#5b3a8a` | Body text on `--lavender`/`--lavender-soft` surface |

**Rules**:
- Never `#000` or `#fff` for text. Body text is `--text` (warm gray-purple).
- Tint every neutral toward pink (`--bg-to`, `--surface-soft`).
- Pink primary appears in: primary buttons, active tab, focus ring, accent dots, row hover border. That's the budget.
- Peach / mint / lavender are *accent-2/3/4* — used for category differentiation (avatar tints, provider badges), never as primary.

## Theme

**Light only.** Scene sentence: *"Thai content creator at their kitchen table mid-morning, planning tomorrow's posts on a 13-inch laptop."* Warm afternoon light → cream/pink palette. Dark mode is explicitly out of scope; the surface IS daylight.

## Typography

- **Display**: `Quicksand` 500–700 — for app titles, section headers, large numbers, mascot speech
- **Body**: `Plus Jakarta Sans` 400–700, paired with `IBM Plex Sans Thai Looped` for Thai glyphs
- **Mono**: `ui-monospace, SF Mono, JetBrains Mono` — only for: API key previews, IP/proxy server strings, timestamps, code

**Scale** (relative to `14px` body):
- Body: 14px / line 1.55
- Small / hint: 12–13px
- Card title (eyebrow): 12px uppercase letter-spaced 0.12em
- Section title: 18px Quicksand 700
- Page title (header): 24px Quicksand 700, letter-spacing -0.01em
- Hero number (countdown, master toggle): 32–40px Quicksand 700
- Login / setup hero: 28–32px Quicksand 700

Cap body line length at ~70ch for paragraphs.

## Layout

- **Container**: max-width 880px (wide pages) / 680px (single-column) / 480px (modal).
- **Radius**: 22px (cards, modals), 16px (rows, inputs), 12px (small chips), 999px (pills, swatches).
- **Spacing**: 4 / 8 / 12 / 16 / 22 / 32 / 48 — vary it deliberately. Same padding everywhere = monotony.
- **Shadows**: `--shadow-sm` for resting cards, `--shadow-md` for hover/popups, `--shadow-lg` for modals + login card. Shadow tint is pink (`rgba(244, 166, 205, 0.x)`) — never neutral gray.

## Motion

- **Easing**: `cubic-bezier(0.22, 1, 0.36, 1)` (ease-out-quart) for everything user-triggered. No bounce, no elastic.
- **Duration**: 120ms (hover), 180ms (modal pop), 240ms (page transition). Long durations feel slow — keep most under 200ms.
- **Live tickers** (countdown, posting indicator): 1s tick, no easing, just data update. Add a subtle 0.6s pulse on the mascot for "alive" feedback.
- **Never animate layout** (`width`, `top`, `padding`). Use `transform`, `opacity`, `clip-path`.

## Components

### Mascot — round cat (`Mascot.tsx`)
Inline SVG. A flat-color round face with two triangle ears, oval eyes, small mouth. Moods:
- `hi` — eyes open, tiny smile, optional waving paw
- `sleep` — eyes as `~ ~`, "Z" particles for loading
- `working` — eyes as `^ ^`, slight 0.6s breathing pulse
- `oops` — eyes wide, mouth small `o`, sweat drop for errors

Sizes: 56px (inline), 96px (empty state), 140px (login / setup hero). Color via `currentColor` so it adapts to context.

### Pills
`.pill.ok | .warn | .err | .idle` — 12px text, 4px 12px padding, dot prefix, 999px radius. Never use raw color words in copy; use the pill.

### Buttons
- `.btn-primary` — pink gradient, white text, 14px radius, soft shadow that grows on hover
- `.btn-ghost` — transparent + border, hover tints pink-soft
- `.btn-danger` — ghost variant with error fg color, hover tints error-bg
- `.btn-block` — full width
- `.btn-sm` — 6px 14px / 12px font

### Cards
- `.card` — elevated white, 22px radius, soft pink shadow, used for major page sections
- `.row-card` — pinkish-white rest, hover lifts border to `--primary` + small shadow. Used for repeat-list rows (accounts, keys, proxies)
- `.prompt-card` — for style/prompt previews, has a soft pink "code block" body inside

### Empty state
Mascot (sleep mood) + 16px gap + Quicksand title 18px + muted note 14px + optional CTA. Never bare text.

### Confirm dialog
`<ConfirmDialog />` replaces all `window.confirm`. Title + message + Cancel/Confirm with optional `tone="danger"`. No browser alerts in the app — period.

### Interval picker
Preset chips (`.interval-chip`): ⏱ ถี่ · 5 นาที / ปกติ · 30 นาที / ช้า · 2 ชม. / กำหนดเอง. Active chip uses pink gradient. Custom mode reveals a small numeric input with min/max guards.

### Countdown
Large Quicksand digits + label. When < 60s, transitions to `กำลังเตรียมโพสต์…` with mascot in `working` mood.

## Bans

- No `#000` / `#fff`
- No side-stripe borders (`border-left: 3px solid X` decorative)
- No gradient text
- No glassmorphism as default (one allowed exception: tab nav uses subtle `backdrop-filter` because it floats over the gradient bg — purposeful)
- No browser `alert()` / `confirm()`
- No em dashes (—) or `--` in user-facing copy. Use commas, colons, `·`, parentheses.
- No identical card grids (icon + title + text repeated 4x). If you need 4 cards, give them different sizes, different content shapes, or use a list.
- No SaaS hero-metric template (giant number + tiny label + gradient stripe).

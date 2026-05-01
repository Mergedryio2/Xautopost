# Xautopost · Product Context

## Register

`product` — desktop app UI that serves a workflow. Design choices favor everyday usability and warmth over "look at me" aesthetic. Marketing/landing pages live in `web/` and follow the same pastel language.

## Users

The primary user is **a non-technical Thai operator** who wants to run several X (Twitter) accounts on autopilot — content creators, small social-media agencies, hobbyists curating themed accounts. They don't think in CRUD inventories ("API key", "prompt", "proxy"); they think in goals ("ฉันอยากให้บัญชีนี้โพสต์คำคมตอนเช้าทุกวัน").

Implications:
- Avoid English jargon at the user-facing layer. "Provider", "model", "rotation interval", "fallback text" must read as plain Thai phrases.
- Mental model is *"each X account has a personality and a schedule"* — not *"each account links to a prompt id which references an API key"*. The UI surfaces the first model and hides the second.
- Tech-savvy operators do exist (multi-account agencies). They get an "ขั้นสูง" expandable section, not a separate power-user mode.

## Product purpose

A locally-installed desktop app (Electron + Python sidecar) that:
1. Manages multiple X account sessions (cookies stored encrypted, optional per-account proxy)
2. Generates tweets via OpenAI / Gemini using a writing-style prompt assigned per account
3. Posts on a randomized human-like schedule, with daily limits and active-hours windows
4. Logs every attempt with status (success / failed / skipped) and error detail

Not a SaaS; not a Twitter client. The vibe is "เครื่องมือเล็กๆ ในบ้าน ที่ช่วยดูแลบัญชี X ให้คุณ" — a kitchen tool, not a control room.

## Brand & tone

- **Voice**: warm, friendly Thai with female-leaning ending particles ("ค่ะ", "นะคะ" — sparingly, not every sentence). Reassuring, never alarming. Errors phrase the *next step*, not the failure noun.
- **Anti-references**: 
  - SaaS dashboards (cold, dense, navy + gradient) — opposite of what we want
  - "Power-user terminal" automation tools (dark mode, monospace, danger red) — opposite
  - Childish kawaii (rainbow, every emoji, Comic Sans) — too far, undermines trust for an account-management tool
- **Reference vibe**: Things Apple's older "iLife" tools, Notion's friendlier surfaces, the way Linear *isn't* — but in a softer pastel skin and Thai typography that breathes.

## Strategic principles

1. **Goal-shaped IA, not resource-shaped.** Top-level navigation maps to user goals (วันนี้เป็นยังไง / บัญชีของฉัน / ตั้งค่า), not backend tables. Power-user resource lists (prompts, proxies, raw logs) live one level deeper.
2. **Status > settings.** The Home view answers *"is it working right now?"* before anything else. The countdown to the next post is more important than the rotation interval input.
3. **One concept per screen.** Don't ask the user to mentally join account ↔ prompt ↔ key on their own. Show them as one unified card.
4. **Hide complexity behind progressive disclosure.** Proxy, model name, fallback text, AES-GCM details, raw HTTP errors — all live behind "ขั้นสูง" or contextual help. Default flow never surfaces them.
5. **First-run is a story, not an empty inventory.** Setup wizard walks the user from zero to first post in 4 steps, never dumping them on a blank tab.
6. **Cute serves clarity.** Mascot (round cat) and illustrations are not decoration — they replace the cognitive cliff of a blank state and the hostility of `window.confirm("Delete?")`.

## Out of scope (current cycle)

- Mobile / responsive design beyond minimum window size
- Dark mode
- i18n beyond Thai (UI is Thai-only for now)
- Server-side / cloud sync (everything is local)

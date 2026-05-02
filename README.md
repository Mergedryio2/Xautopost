# Xautopost

> ระบบจัดการโพสต์ X อัตโนมัติ ใช้ AI สร้างเนื้อหา หลายบัญชีในที่เดียว ติดตั้งบนเครื่องคุณ ข้อมูลเข้ารหัสทุกอย่าง

A locally-installed desktop app that runs and posts to multiple X (Twitter)
accounts on a human-like schedule, using OpenAI / Gemini for AI-written
content or your own pre-written posts. Built for non-technical Thai operators
who want a friendly tool, not a SaaS dashboard.

---

## Features

- **Multi-account rotation** — manage many X accounts from one app, each with its own active hours, daily limit, and randomized post interval
- **Two writing modes per account**
  - **AI mode** — pick OpenAI or Gemini, give a system prompt, the app generates each tweet
  - **Manual mode** — type your own posts, the app rotates and randomizes (auto-appends one of 38 emoji to dodge X's duplicate-content rejection)
- **Local & encrypted** — credentials, cookies, API keys all stored AES-GCM in a local SQLite database; master key lives in your OS keychain
- **First-run wizard** — 5-step setup walks newcomers from "I just installed this" to "first post is live" without dumping them on a blank tab
- **Cute pastel Thai UI** — round-cat mascot, plain-language labels, no SaaS dashboard cliché

## Architecture

Three components in one repo:

| Folder | Stack | Role |
|---|---|---|
| `backend/` | Python · FastAPI · Playwright · APScheduler · SQLite | Sidecar process that runs the scheduler, calls AI providers, drives Chromium to post tweets |
| `desktop/` | Electron · Vite · React · TypeScript | The actual app the user sees. Spawns the Python sidecar on launch, talks to it over `127.0.0.1` with a per-session bearer token |
| `web/` | Static HTML | Public landing page that auto-detects the visitor's OS and links to the latest GitHub Release `.dmg`/`.exe` |

The desktop's Electron main process spawns the Python sidecar as a child
process at startup, prints a `XAUTOPOST_READY port=PORT` line back to stdout,
and only then unlocks the renderer.

## Quick start (development)

Requirements: macOS 11+ or Windows 10+ · Python 3.12 · Node 20 · Google
Chrome installed locally (Playwright reuses the system Chrome).

```bash
# 1. Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium  # one-time

# 2. Desktop renderer
cd ../desktop
npm install
npm run dev
```

`npm run dev` starts Electron with hot-reload for the renderer; the main
process spawns the Python sidecar with the venv interpreter automatically
(see `desktop/scripts/build-backend.cjs` for path resolution).

## Building releases

Local production builds:

```bash
cd desktop
npm run build:mac   # produces .dmg in desktop/dist
npm run build:win   # produces .exe in desktop/dist (run on Windows)
```

CI builds via GitHub Actions on git tag `v*`:

```bash
git tag v0.0.3
git push origin v0.0.3
```

`.github/workflows/build.yml` runs the matrix on `macos-latest` +
`windows-latest`, packages with `electron-builder`, and uploads `.dmg` /
`.exe` artifacts. The `web/` landing page reads the latest release and
points its download cards at the appropriate asset.

## Project structure

```
backend/
  app/
    api/           # FastAPI routers: operators, accounts, prompts, api_keys, logs
    core/          # config, AES-GCM crypto, password hashing
    db/            # SQLAlchemy models, migrations
    services/
      scheduler.py # APScheduler rotation per operator
      poster.py    # Playwright → x.com composer → click → verify
      ai.py        # OpenAI / Gemini provider wrappers
      manual.py    # split-by-`---` + emoji decoration for manual mode
      playwright_login.py  # one-shot login flow that captures storage_state
desktop/
  src/
    main/          # Electron main process; spawns sidecar
    preload/       # exposes safe IPC to renderer
    renderer/
      pages/       # Login, Home, Accounts, Settings, SetupWizard
      components/  # Mascot, Modal, AutoSwitch, StylePicker, ConfirmDialog…
      lib/         # API client, time helpers
web/
  index.html       # landing page (auto-OS-detect download cards)
PRODUCT.md         # users, brand, anti-references, strategic principles
DESIGN.md          # color tokens, typography, components, bans
```

## Design context

`PRODUCT.md` and `DESIGN.md` are deliberately committed alongside the code so
future design iterations stay grounded in the project's voice rather than
drifting toward generic SaaS aesthetics. They're consumed by the
[`impeccable`](https://github.com/anthropics/skills) design tooling.

## Security notes

- All API keys and X session cookies are encrypted with AES-GCM before
  reaching the database
- The master encryption key is stored in the OS keychain
  (`keyring.set_password("xautopost", "master", ...)`), never in the repo
- The Python sidecar binds only to `127.0.0.1` and validates a per-session
  random bearer token on every request
- Operator passphrases are hashed with Argon2 before storage
- The repo's `.gitignore` excludes `*.db`, `*.sqlite`, `.env`, and the
  Playwright profile directories

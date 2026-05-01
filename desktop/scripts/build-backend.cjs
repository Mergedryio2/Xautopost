'use strict'
/**
 * Cross-platform helper to invoke PyInstaller on the backend.
 *
 * Resolution order for the pyinstaller binary:
 *   1) backend/.venv/{Scripts,bin}/pyinstaller   (local dev)
 *   2) `pyinstaller` from PATH                   (CI / global install)
 */

const { execSync } = require('child_process')
const { existsSync } = require('fs')
const { join, resolve } = require('path')

const root = resolve(__dirname, '..', '..')
const backendDir = join(root, 'backend')
const isWin = process.platform === 'win32'
const venvBin = join(backendDir, '.venv', isWin ? 'Scripts' : 'bin')
const venvPyinstaller = join(venvBin, isWin ? 'pyinstaller.exe' : 'pyinstaller')

const cmd = existsSync(venvPyinstaller) ? venvPyinstaller : 'pyinstaller'
console.log(`[build-backend] using: ${cmd}`)

try {
  execSync(`"${cmd}" build.spec --clean --noconfirm`, {
    cwd: backendDir,
    stdio: 'inherit',
  })
} catch (e) {
  console.error('[build-backend] pyinstaller failed')
  console.error(
    '[build-backend] hint: cd backend && pip install -e ".[dev]"  (or activate venv first)',
  )
  process.exit(1)
}

console.log(
  `[build-backend] done -> ${join(backendDir, 'dist', 'xautopost-backend')}`,
)

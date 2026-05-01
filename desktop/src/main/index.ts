import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { ChildProcess, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync } from 'node:fs'
import { createServer } from 'node:net'
import { join } from 'node:path'

let pythonProc: ChildProcess | null = null
let pythonPort: number | null = null
let pythonToken: string | null = null

function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer()
    srv.unref()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address()
      if (typeof addr === 'object' && addr) {
        const port = addr.port
        srv.close(() => resolve(port))
      } else {
        reject(new Error('failed to obtain free port'))
      }
    })
  })
}

function backendDir(): string {
  return app.isPackaged
    ? join(process.resourcesPath, 'backend')
    : join(__dirname, '../../../backend')
}

type SidecarLaunch = { exe: string; args: string[] }

function sidecarLaunch(): SidecarLaunch {
  // Production: bundled PyInstaller binary lives in
  //   <Resources>/backend/xautopost-backend[.exe]
  if (app.isPackaged) {
    const binName =
      process.platform === 'win32'
        ? 'xautopost-backend.exe'
        : 'xautopost-backend'
    return { exe: join(backendDir(), binName), args: [] }
  }

  // Dev: env override
  if (process.env.XAUTOPOST_PYTHON) {
    return {
      exe: process.env.XAUTOPOST_PYTHON,
      args: ['-m', 'app.main'],
    }
  }

  // Dev: venv python
  const venvPython =
    process.platform === 'win32'
      ? join(backendDir(), '.venv', 'Scripts', 'python.exe')
      : join(backendDir(), '.venv', 'bin', 'python')
  if (existsSync(venvPython)) {
    return { exe: venvPython, args: ['-m', 'app.main'] }
  }

  // Dev: PATH python
  return {
    exe: process.platform === 'win32' ? 'python' : 'python3',
    args: ['-m', 'app.main'],
  }
}

async function startPythonSidecar(): Promise<void> {
  pythonPort = await findFreePort()
  pythonToken = randomBytes(32).toString('hex')

  const { exe, args } = sidecarLaunch()
  console.log(`[sidecar] spawning ${exe} ${args.join(' ')}`)
  pythonProc = spawn(exe, args, {
    cwd: backendDir(),
    env: {
      ...process.env,
      XAUTOPOST_PORT: String(pythonPort),
      XAUTOPOST_TOKEN: pythonToken,
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  pythonProc.stdout?.on('data', (d: Buffer) => {
    process.stdout.write(`[py] ${d.toString()}`)
  })
  pythonProc.stderr?.on('data', (d: Buffer) => {
    process.stderr.write(`[py-err] ${d.toString()}`)
  })
  pythonProc.on('exit', (code, signal) => {
    console.log(`[py] exited code=${code} signal=${signal}`)
    pythonProc = null
  })

  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(
      () => reject(new Error('python sidecar did not become ready in 15s')),
      15000,
    )
    const onData = (buf: Buffer) => {
      if (buf.toString().includes('XAUTOPOST_READY')) {
        clearTimeout(timeout)
        pythonProc?.stdout?.off('data', onData)
        resolve()
      }
    }
    pythonProc?.stdout?.on('data', onData)
    pythonProc?.on('exit', () => {
      clearTimeout(timeout)
      reject(new Error('python sidecar exited before ready'))
    })
  })
}

function killPythonSidecar(): void {
  if (pythonProc && !pythonProc.killed) {
    pythonProc.kill()
    pythonProc = null
  }
}

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  win.on('ready-to-show', () => win.show())
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

ipcMain.handle('sidecar:info', () => ({
  port: pythonPort,
  token: pythonToken,
  ready: pythonProc !== null,
}))

app.whenReady().then(async () => {
  try {
    await startPythonSidecar()
  } catch (err) {
    console.error('failed to start python sidecar:', err)
  }
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  killPythonSidecar()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', killPythonSidecar)

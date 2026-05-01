# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Xautopost backend sidecar.

Build:
    pyinstaller build.spec --clean --noconfirm

Output:
    dist/xautopost-backend/   (one-dir bundle; entry: xautopost-backend[.exe])

The Electron app picks up dist/xautopost-backend/ as extraResources and runs
the entry point in production. In dev mode, Electron still uses the venv
Python directly via `python -m app.main`.
"""

import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Heavyweight third-party packages that PyInstaller's static analysis misses.
HEAVY_PACKAGES = [
    "fastapi",
    "starlette",
    "uvicorn",
    "pydantic",
    "pydantic_settings",
    "pydantic_core",
    "sqlalchemy",
    "alembic",
    "cryptography",
    "argon2",
    "keyring",
    "apscheduler",
    "openai",
    "google.generativeai",
    "httpx",
    "playwright",
]

datas: list = []
binaries: list = []
hiddenimports: list = ["app"]

for pkg in HEAVY_PACKAGES:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # noqa: BLE001
        print(f"[spec] warning: collect_all({pkg!r}): {e}")

# uvicorn loads protocol/loop modules dynamically by string name
hiddenimports += collect_submodules("uvicorn.protocols")
hiddenimports += collect_submodules("uvicorn.lifespan")
hiddenimports += collect_submodules("uvicorn.loops")

# Platform-specific keyring backends
if sys.platform == "darwin":
    hiddenimports.append("keyring.backends.macOS")
elif sys.platform == "win32":
    hiddenimports.append("keyring.backends.Windows")
elif sys.platform.startswith("linux"):
    hiddenimports.append("keyring.backends.SecretService")
    hiddenimports.append("keyring.backends.kwallet")

a = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "notebook"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xautopost-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # required: Electron reads stdout for the READY signal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="xautopost-backend",
)

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api import accounts, api_keys, logs, media, operators, prompts, proxies
from app.db.database import init_db
from app.services.scheduler import scheduler

VERSION = "0.0.19"
PORT = int(os.environ.get("XAUTOPOST_PORT", "8765"))
TOKEN = os.environ.get("XAUTOPOST_TOKEN", "")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    scheduler.start()
    # Printed AFTER uvicorn binds the socket — Electron parent process waits for this line.
    print(f"XAUTOPOST_READY port={PORT}", flush=True)
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="Xautopost Sidecar", version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer = HTTPBearer(auto_error=False)


def require_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    if not TOKEN:
        return
    if creds is None or creds.credentials != TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        )


@app.get("/health", dependencies=[Depends(require_token)])
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}


@app.get("/version", dependencies=[Depends(require_token)])
def version() -> dict[str, str]:
    return {"version": VERSION}


app.include_router(operators.router, dependencies=[Depends(require_token)])
app.include_router(proxies.router, dependencies=[Depends(require_token)])
app.include_router(accounts.router, dependencies=[Depends(require_token)])
app.include_router(api_keys.router, dependencies=[Depends(require_token)])
app.include_router(prompts.router, dependencies=[Depends(require_token)])
app.include_router(media.router, dependencies=[Depends(require_token)])
app.include_router(logs.router, dependencies=[Depends(require_token)])


def run() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    run()

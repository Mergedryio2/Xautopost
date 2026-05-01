from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from playwright.async_api import Page, async_playwright

from app.core.crypto import get_crypto
from app.db.database import SessionLocal
from app.db.models import XAccount

log = logging.getLogger(__name__)

LoginStatus = Literal["waiting", "success", "failed", "canceled"]
LOGIN_TIMEOUT_SEC = 300  # 5 minutes


@dataclass
class LoginTask:
    task_id: str
    operator_id: int
    proxy_id: int | None = None
    status: LoginStatus = "waiting"
    handle: str | None = None
    account_id: int | None = None
    error: str | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    bg_task: asyncio.Task[Any] | None = None


class LoginManager:
    """Owns a dict of in-flight Playwright login sessions, keyed by task_id."""

    def __init__(self) -> None:
        self._tasks: dict[str, LoginTask] = {}

    def get(self, task_id: str) -> LoginTask | None:
        return self._tasks.get(task_id)

    def start(
        self,
        operator_id: int,
        proxy_id: int | None = None,
        proxy_server: str | None = None,
        proxy_username: str | None = None,
        proxy_password: str | None = None,
    ) -> LoginTask:
        task = LoginTask(
            task_id=uuid4().hex, operator_id=operator_id, proxy_id=proxy_id
        )
        self._tasks[task.task_id] = task
        task.bg_task = asyncio.create_task(
            self._run(task, proxy_server, proxy_username, proxy_password)
        )
        return task

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != "waiting":
            return False
        task.cancel_event.set()
        return True

    async def _run(
        self,
        task: LoginTask,
        proxy_server: str | None,
        proxy_username: str | None,
        proxy_password: str | None,
    ) -> None:
        try:
            async with async_playwright() as pw:
                launch_kwargs: dict[str, Any] = {
                    "headless": False,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if proxy_server:
                    proxy: dict[str, str] = {"server": proxy_server}
                    if proxy_username:
                        proxy["username"] = proxy_username
                    if proxy_password:
                        proxy["password"] = proxy_password
                    launch_kwargs["proxy"] = proxy

                # Prefer installed Google Chrome over bundled Chrome for Testing —
                # Google Sign-In flat-out rejects Chrome for Testing as "insecure".
                try:
                    browser = await pw.chromium.launch(
                        channel="chrome", **launch_kwargs
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning(
                        "chrome channel unavailable, falling back to bundled chromium: %s",
                        e,
                    )
                    browser = await pw.chromium.launch(**launch_kwargs)
                try:
                    context = await browser.new_context()
                    # Hide navigator.webdriver from common anti-bot checks
                    await context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', "
                        "{ get: () => undefined })"
                    )
                    page = await context.new_page()
                    await page.goto(
                        "https://x.com/i/flow/login", wait_until="domcontentloaded"
                    )

                    deadline = time.time() + LOGIN_TIMEOUT_SEC
                    success = False
                    while time.time() < deadline:
                        if task.cancel_event.is_set():
                            task.status = "canceled"
                            return
                        if page.is_closed() or not browser.is_connected():
                            task.status = "canceled"
                            task.error = "ผู้ใช้ปิดหน้าต่าง browser"
                            return
                        try:
                            url = page.url
                        except Exception:
                            url = ""
                        if "/home" in url:
                            success = True
                            break
                        await asyncio.sleep(0.5)

                    if not success:
                        task.status = "failed"
                        task.error = "เลย 5 นาทียังไม่ login สำเร็จ"
                        return

                    handle = await self._extract_handle(page)
                    state = await context.storage_state()
                    state_json = json.dumps(state)
                    self._save_account(task, handle, state_json)
                    task.status = "success"
                finally:
                    try:
                        await browser.close()
                    except Exception:
                        pass
        except Exception as e:  # noqa: BLE001
            log.exception("playwright login failed")
            task.status = "failed"
            task.error = str(e)

    async def _extract_handle(self, page: Page) -> str | None:
        try:
            await page.wait_for_selector(
                '[data-testid="AppTabBar_Profile_Link"]', timeout=10_000
            )
            href = await page.get_attribute(
                '[data-testid="AppTabBar_Profile_Link"]', "href"
            )
            if href and href.startswith("/"):
                handle = href.lstrip("/").split("/")[0]
                return f"@{handle}"
        except Exception:  # noqa: BLE001
            pass
        return None

    def _save_account(
        self, task: LoginTask, handle: str | None, state_json: str
    ) -> None:
        crypto = get_crypto()
        with SessionLocal() as db:
            final_handle = handle or f"@unknown_{task.task_id[:8]}"
            acc = XAccount(
                operator_id=task.operator_id,
                handle=final_handle,
                proxy_id=task.proxy_id,
                storage_state_enc=crypto.encrypt_str(state_json),
                status="active",
            )
            db.add(acc)
            db.commit()
            db.refresh(acc)
            task.handle = final_handle
            task.account_id = acc.id


login_manager = LoginManager()

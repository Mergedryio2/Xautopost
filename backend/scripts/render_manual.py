"""Render manual/manual.html into a print-ready A4 PDF using Playwright.

Usage:
    cd backend && .venv/bin/python scripts/render_manual.py

Output:
    manual/Xautopost-คู่มือการใช้งาน.pdf

Reuses the headless Chromium that's already a runtime dependency of the
backend, so we don't need to bring in WeasyPrint, wkhtmltopdf, or any
other PDF stack just for the manual.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "manual" / "manual.html"
PDF_PATH = ROOT / "manual" / "Xautopost-คู่มือการใช้งาน.pdf"


async def main() -> None:
    if not HTML_PATH.exists():
        print(f"manual source missing: {HTML_PATH}", file=sys.stderr)
        sys.exit(1)

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(channel="chrome")
        except Exception:  # noqa: BLE001
            browser = await pw.chromium.launch()
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            # file:// URL so relative font preloads + the inline SVG render
            # exactly as in a browser print preview.
            await page.goto(HTML_PATH.as_uri(), wait_until="networkidle")
            # Give web fonts a moment to paint — Quicksand + IBM Plex Sans
            # Thai Looped need to be ready before we snapshot to PDF or
            # we'll get fallback fonts in the output.
            await asyncio.sleep(2.0)
            await page.emulate_media(media="print")
            await page.pdf(
                path=str(PDF_PATH),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={
                    "top": "0",
                    "right": "0",
                    "bottom": "0",
                    "left": "0",
                },
            )
        finally:
            await browser.close()

    size_kb = PDF_PATH.stat().st_size / 1024
    print(f"wrote {PDF_PATH} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    asyncio.run(main())

"""Render desktop/build/icon.svg into a 1024x1024 PNG that electron-builder
can pick up as the app icon source.

Usage:
    cd backend && .venv/bin/python scripts/render_icon.py

Output:
    desktop/build/icon.png  (1024x1024, transparent corners preserved)

This avoids depending on `sharp`, `rsvg-convert`, ImageMagick, or any other
external tooling — Playwright + headless Chromium is already a runtime
dependency of the backend, so we reuse the same pipeline X uses to post.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
SVG_PATH = ROOT / "desktop" / "build" / "icon.svg"
PNG_PATH = ROOT / "desktop" / "build" / "icon.png"
SIZE = 1024


HTML_TEMPLATE = """\
<!doctype html>
<html><head><style>
  html, body {{ margin: 0; padding: 0; background: transparent; }}
  body {{ width: {size}px; height: {size}px; }}
  svg {{ width: {size}px; height: {size}px; display: block; }}
</style></head>
<body>{svg}</body></html>
"""


async def main() -> None:
    if not SVG_PATH.exists():
        print(f"icon source missing: {SVG_PATH}", file=sys.stderr)
        sys.exit(1)

    svg_text = SVG_PATH.read_text(encoding="utf-8")
    html = HTML_TEMPLATE.format(svg=svg_text, size=SIZE)

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(channel="chrome")
        except Exception:  # noqa: BLE001
            browser = await pw.chromium.launch()
        try:
            ctx = await browser.new_context(
                viewport={"width": SIZE, "height": SIZE},
                device_scale_factor=1,
            )
            page = await ctx.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            # Screenshot the whole viewport, transparent background preserved.
            await page.screenshot(
                path=str(PNG_PATH),
                omit_background=True,
                full_page=False,
                clip={"x": 0, "y": 0, "width": SIZE, "height": SIZE},
            )
        finally:
            await browser.close()

    print(f"wrote {PNG_PATH} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    asyncio.run(main())

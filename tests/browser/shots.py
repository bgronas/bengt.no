"""Design-review screenshots. Not part of the site; output goes to a local folder.

Usage: uv run --group browser python tests/browser/shots.py BASE_URL OUT_DIR [PATH ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTHS = {"375": (375, 812), "768": (768, 1024), "1440": (1440, 900)}


def main() -> int:
    base, out = sys.argv[1].rstrip("/"), Path(sys.argv[2])
    paths = sys.argv[3:] or ["/"]
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in ("dark", "light"):
            for label, (w, h) in WIDTHS.items():
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
                ctx.add_init_script(f"try{{localStorage.setItem('appearance','{scheme}')}}catch(e){{}}")
                page = ctx.new_page()
                for path in paths:
                    page.goto(base + path, wait_until="networkidle")
                    page.wait_for_timeout(400)
                    name = (path.strip("/").replace("/", "_") or "home") + f"-{label}-{scheme}.png"
                    page.screenshot(path=str(out / name), full_page=True)
                    overflow = page.evaluate(
                        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
                    )
                    print(f"{name}: horizontal overflow {overflow}px")
                ctx.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

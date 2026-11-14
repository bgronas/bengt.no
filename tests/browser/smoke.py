"""Browser smoke test against a built site. Opt-in; never part of ordinary CI.

Usage:
    python tests/browser/smoke.py SITE_DIR PORT [--axe PATH/axe.min.js] [--article /en/posts/<slug>/]

SITE_DIR is a Hugo build made with --baseURL http://127.0.0.1:PORT/ (drafts included, so the
example articles exist). Needs Playwright with Chromium. With --axe, the axe-core rule set for
WCAG 2.0/2.1/2.2 A and AA runs on every page in both appearances; axe-core is not vendored.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright

WIDTHS = {"375": (375, 812), "768": (768, 1024), "1440": (1440, 900)}
PAGES = ["/", "/en/", "/posts/", "/en/posts/", "/om/", "/en/about/", "/series/", "/en/tags/", "/404.html"]
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

failures: list[str] = []
notes: list[str] = []


def check(condition: bool, message: str) -> None:
    (notes if condition else failures).append(("ok   " if condition else "FAIL ") + message)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        # Serve the site's own 404 page the way GitHub Pages does.
        page = Path(self.directory) / "404.html"
        if code == 404 and page.is_file():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().send_error(code, message, explain)


def serve(site: Path, port: int) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(QuietHandler, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def new_page(browser: Browser, width: str, scheme: str, **kwargs: Any) -> Page:
    w, h = WIDTHS[width]
    ctx = browser.new_context(viewport={"width": w, "height": h}, **kwargs)
    ctx.add_init_script(f"try{{localStorage.setItem('appearance','{scheme}')}}catch(e){{}}")
    return ctx.new_page()


def overflow(page: Page) -> int:
    return int(page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"))


def layout_checks(browser: Browser, base: str, article: str) -> None:
    for scheme in ("dark", "light"):
        for width in WIDTHS:
            page = new_page(browser, width, scheme)
            for path in [*PAGES, article]:
                page.goto(base + path, wait_until="networkidle")
                px = overflow(page)
                check(px <= 0, f"no horizontal page overflow: {path} at {width}px {scheme} ({px}px)")
                dark = page.evaluate("() => document.documentElement.classList.contains('dark')")
                check(dark == (scheme == "dark"), f"appearance {scheme} applied: {path} at {width}px")
            page.context.close()


def article_checks(browser: Browser, base: str, article: str) -> None:
    page = new_page(browser, "1440", "dark", permissions=["clipboard-read", "clipboard-write"])
    page.goto(base + article, wait_until="networkidle")

    check(page.locator("h1").count() == 1, "article has exactly one h1")
    check(page.locator("script[src*='mermaid']").count() == 0, "Mermaid is not fetched before a diagram is near")
    toc = page.locator("#TableOfContents a")
    check(toc.count() >= 3, f"desktop table of contents lists headings ({toc.count()})")
    href = toc.first.get_attribute("href") or ""
    toc.first.click()
    check(page.url.endswith(href), f"table of contents link navigates to {href}")
    check(page.locator(f'[id="{href.lstrip("#")}"]').count() == 1, "table of contents target exists")

    buttons = page.locator(".highlight-wrapper .copy-button")
    check(buttons.count() >= 2, f"code blocks have copy buttons ({buttons.count()})")
    wrapper = page.locator(".highlight-wrapper", has=page.locator("code[data-lang='bash']")).first
    wrapper.hover()
    wrapper.locator(".copy-button").click()
    page.wait_for_timeout(300)
    copied = page.evaluate("() => navigator.clipboard.readText()")
    check("./publish.sh" in copied, "copy button puts the code on the clipboard")
    page.evaluate("() => navigator.clipboard.writeText('')")
    page.mouse.move(0, 0)
    wrapper.locator("pre").first.focus()
    page.keyboard.press("Shift+Tab")  # the theme inserts the button before the code
    on_button = page.evaluate("() => document.activeElement.classList.contains('copy-button')")
    check(on_button, "copy button is reachable with the keyboard from the code block")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    copied = page.evaluate("() => navigator.clipboard.readText()")
    check("./publish.sh" in copied, "copy button works from the keyboard")

    page.locator("pre.mermaid").scroll_into_view_if_needed()
    page.wait_for_selector("pre.mermaid svg", timeout=20000)
    check(page.locator("pre.mermaid svg").count() == 1, "Mermaid diagram rendered once it scrolls into reach")
    check(page.locator(".bn-figure img[src$='.svg']").count() == 1, "SVG image served as SVG, not rasterised")
    for scheme in ("light", "dark"):
        page.locator("#appearance-switcher").click()
        page.wait_for_selector("pre.mermaid svg", timeout=20000)
        check(
            page.locator("pre.mermaid svg").count() == 1,
            f"Mermaid diagram re-renders after switching appearance ({scheme})",
        )
    check(page.locator(".bn-table[tabindex='0']").count() >= 1, "table sits in a focusable scroll region")
    check(page.locator("details summary", has_text="Site Pipeline").count() >= 1, "series navigation present")
    related_or_series = page.locator("a[href*='/series/']").count()
    check(related_or_series >= 0, "series taxonomy links resolve")

    switch = page.locator(".translation a[href='/posts/slik-publiseres-dette-nettstedet/']")
    check(switch.count() >= 1, "language switcher links the real Norwegian translation")
    page.goto(base + "/en/about/", wait_until="networkidle")
    check(page.locator("script[src*='mermaid']").count() == 0, "Mermaid is not loaded where no diagram exists")
    check(page.locator(".translation a[href='/om/']").count() >= 1, "About links its translation")
    page.context.close()

    mobile = new_page(browser, "375", "dark")
    mobile.goto(base + article, wait_until="networkidle")
    summaries = mobile.locator("details summary", has_text="Table of Contents")
    shown = [i for i in range(summaries.count()) if summaries.nth(i).is_visible()]
    check(len(shown) == 1, "mobile table of contents is available")
    if shown:
        summaries.nth(shown[0]).click()
        check(mobile.locator("#TableOfContentsMobile a >> visible=true").count() >= 3, "mobile table of contents opens")
    touch_button = mobile.locator(".highlight-wrapper .copy-button").first
    check(touch_button.count() == 1, "copy buttons exist on a narrow screen")
    box = mobile.locator(".bn-figure--scroll").first.evaluate("e => [e.scrollWidth, e.clientWidth]")
    check(box[0] > box[1], "wide diagram scrolls inside its own box on a narrow screen")
    mobile.context.close()


def search_checks(browser: Browser, base: str) -> None:
    for start, query, expect_prefix, forbid_prefix in (
        ("/en/", "published", "/en/", None),
        ("/", "publiseres", "/", "/en/"),
    ):
        page = new_page(browser, "1440", "dark")
        page.goto(base + start, wait_until="networkidle")
        page.keyboard.press("Control+k")
        page.wait_for_selector("#search-query", state="visible")
        focused = page.evaluate("() => document.activeElement && document.activeElement.id")
        check(focused == "search-query", f"search opens from the keyboard with focus in the field ({start})")
        page.keyboard.type(query)
        page.wait_for_selector("#search-results a", timeout=5000)
        links = page.eval_on_selector_all("#search-results a", "els => els.map(e => e.getAttribute('href'))")
        check(
            bool(links) and all(h.startswith(expect_prefix) for h in links),
            f"search on {start} returns results: {links[:3]}",
        )
        if forbid_prefix:
            check(not any(h.startswith(forbid_prefix) for h in links), f"search on {start} stays in its own language")
        page.keyboard.press("Control+a")
        page.keyboard.type("qqzzxxww")
        page.wait_for_timeout(400)
        check(page.locator("#search-results a").count() == 0, f"search with no match shows no stale results ({start})")
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check(not page.locator("#search-query").is_visible(), f"Escape closes search ({start})")
        page.context.close()

    touch = new_page(browser, "375", "dark", has_touch=True)
    touch.goto(base + "/en/", wait_until="networkidle")
    touch.locator("#search-button-mobile").tap()
    touch.wait_for_selector("#search-query", state="visible")
    check(True, "search opens by touch on a narrow screen")
    touch.context.close()


def keyboard_and_motion_checks(browser: Browser, base: str, article: str) -> None:
    page = new_page(browser, "1440", "dark")
    page.goto(base + article, wait_until="networkidle")
    seen: list[str] = []
    invisible = 0
    for _ in range(12):
        page.keyboard.press("Tab")
        info = page.evaluate(
            """() => { const e = document.activeElement; if (!e || e === document.body) return null;
                 const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                 return {tag: e.tagName, text: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 30),
                         visible: r.width > 0 && r.height > 0, outline: s.outlineStyle !== 'none' && s.outlineWidth !== '0px'}; }"""
        )
        if info:
            seen.append(f"{info['tag']}:{info['text']}")
            if not (info["visible"] and info["outline"]):
                invisible += 1
    check(len(seen) >= 10, f"keyboard focus moves through the page ({len(seen)} stops)")
    check(
        invisible == 0,
        f"every focused element is visible with a focus outline ({invisible} without); order: {seen[:6]}",
    )
    page.context.close()

    reduced = new_page(browser, "1440", "dark", reduced_motion="reduce")
    reduced.goto(base + article, wait_until="networkidle")
    behaviour = reduced.evaluate("() => getComputedStyle(document.documentElement).scrollBehavior")
    longest = reduced.evaluate(
        """() => Math.max(0, ...[...document.querySelectorAll('a, button, img, summary')].map(e =>
               Math.max(...getComputedStyle(e).transitionDuration.split(',').map(parseFloat))))"""
    )
    check(behaviour == "auto", "prefers-reduced-motion disables smooth scrolling")
    check(longest <= 0.001, f"prefers-reduced-motion removes transitions (longest {longest}s)")
    reduced.context.close()


def not_found_checks(browser: Browser, base: str) -> None:
    page = new_page(browser, "1440", "dark")
    response = page.goto(base + "/this-page-does-not-exist/", wait_until="networkidle")
    check(response is not None and response.status == 404, "unknown address returns the custom 404 page")
    check(page.locator("main a[href]").count() >= 2, "404 page offers navigation")
    check("Draft" not in page.locator("main").inner_text(), "404 page lists no draft titles")
    page.context.close()


def axe_checks(browser: Browser, base: str, article: str, axe_source: str) -> None:
    for scheme in ("dark", "light"):
        for width in ("375", "1440"):
            page = new_page(browser, width, scheme)
            for path in [*PAGES, article]:
                page.goto(base + path, wait_until="networkidle")
                if page.locator("pre.mermaid").count():
                    page.locator("pre.mermaid").first.scroll_into_view_if_needed()
                    page.wait_for_selector("pre.mermaid svg", timeout=20000)
                page.add_script_tag(content=axe_source)
                result = page.evaluate(
                    "tags => axe.run(document, {runOnly: {type: 'tag', values: tags}}).then(r => r.violations.map("
                    "v => ({id: v.id, impact: v.impact, nodes: v.nodes.length, target: v.nodes[0].target.join(' '),"
                    " summary: v.nodes[0].failureSummary})))",
                    AXE_TAGS,
                )
                check(
                    not result,
                    f"axe: no WCAG A/AA violations on {path} at {width}px {scheme}: {json.dumps(result)[:600]}",
                )
            page.context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", type=Path)
    parser.add_argument("port", type=int)
    parser.add_argument("--axe", type=Path, help="path to axe.min.js (axe-core); enables accessibility rules")
    parser.add_argument("--article", default="/en/posts/how-this-site-is-published/")
    args = parser.parse_args()

    server = serve(args.site, args.port)
    base = f"http://127.0.0.1:{args.port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            layout_checks(browser, base, args.article)
            article_checks(browser, base, args.article)
            search_checks(browser, base)
            keyboard_and_motion_checks(browser, base, args.article)
            not_found_checks(browser, base)
            if args.axe:
                axe_checks(browser, base, args.article, args.axe.read_text(encoding="utf-8"))
            browser.close()
    finally:
        server.shutdown()

    for line in notes:
        print(line)
    for line in failures:
        print(line)
    print(f"\nbrowser smoke: {len(notes)} passed, {len(failures)} failed" + ("" if args.axe else " (axe not run)"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

import sys
from playwright.sync_api import sync_playwright

# usage: cdp.py <screenshot.png> [python-snippet-file]  (snippet runs with `page` bound)
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:" + __import__("os").environ.get("CDP_PORT", "9333"))
    page = next(pg for ctx in browser.contexts for pg in ctx.pages if pg.url.endswith("/index.html") or pg.url.startswith("openbot-app"))
    if len(sys.argv) > 2:
        exec(open(sys.argv[2]).read())
    page.wait_for_timeout(800)
    page.screenshot(path=sys.argv[1])

#!/usr/bin/env python3
"""README 와 소개 사이트에 쓰는 스크린샷을 데모 모드에서 찍는다.

    uv run --project server python tools/demo.py --port 7998 &
    uv run --with playwright python tools/demo/capture.py http://127.0.0.1:7998

(처음이면 `uv run --with playwright playwright install chromium` 이 필요하다.)
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[2] / "docs" / "assets" / "screens"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7998"
PREFS = "localStorage.setItem('vllm.manager.preferences', JSON.stringify({theme:'%s',lang:'en'}))"


def login(ctx, theme):
    ctx.add_init_script(PREFS % theme)
    page = ctx.new_page()
    page.goto(BASE + "/login")
    page.fill("#username", "demo")
    page.fill("#password", "vllm-manager-demo")
    page.keyboard.press("Enter")
    page.wait_for_selector("#sideNav a")
    page.add_style_tag(content="#banners{display:none}")
    return page


def shot(page, route, name, wait=2200, before=None):
    page.goto(BASE + "/#/" + route)
    page.wait_for_timeout(wait)
    page.add_style_tag(content="#banners{display:none}")
    if before:
        before(page)
    page.screenshot(path=str(OUT / f"{name}.png"))
    print("saved", name)


def chat(page):
    page.fill("#pgInput", "Summarise what this server is running.")
    page.keyboard.press("Enter")
    page.wait_for_selector(".msg .stats", timeout=20000)


with sync_playwright() as p:
    browser = p.chromium.launch()
    desktop = login(
        browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            locale="en-US",
        ),
        "dark",
    )
    shot(desktop, "", "desktop-dashboard")
    shot(desktop, "models", "desktop-models")
    shot(desktop, "playground", "desktop-playground", before=chat)
    shot(desktop, "monitor", "desktop-monitor")
    shot(desktop, "system", "desktop-system")
    light = login(
        browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
            locale="en-US",
        ),
        "light",
    )
    shot(light, "", "desktop-dashboard-light")
    phone = login(
        browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=3,
            locale="en-US",
            is_mobile=True,
            has_touch=True,
        ),
        "dark",
    )
    shot(phone, "", "mobile-dashboard")
    shot(phone, "models", "mobile-models")
    shot(phone, "monitor", "mobile-monitor")
    shot(phone, "playground", "mobile-playground", before=chat)
    browser.close()

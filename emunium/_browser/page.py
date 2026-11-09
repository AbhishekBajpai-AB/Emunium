from __future__ import annotations

import logging
import time

from emunium.bridge import Bridge

logger = logging.getLogger("emunium.browser")


def goto(bridge: Bridge, url: str, *, timeout: float = 30.0) -> dict:
    result = bridge.navigate(url, timeout=timeout)
    if result and result.get("error"):
        raise RuntimeError(f"Navigation failed: {result['error']}")
    tab_id = result.get("tabId") if result else None
    if tab_id is not None:
        bridge.pinned_tab_id = tab_id
    logger.info("Navigated to: %s", url)
    time.sleep(0.5)
    return result or {}


def get_url(bridge: Bridge) -> str:
    info = bridge.get_tab_info()
    return info.get("url", "")


def get_title(bridge: Bridge) -> str:
    info = bridge.get_tab_info()
    return info.get("title", "")


def execute_script(bridge: Bridge, code: str) -> str | None:
    result = bridge.execute_script(code)
    if result and result.get("error"):
        raise RuntimeError(f"Script error: {result['error']}")
    return result.get("result") if result else None


def page_info(bridge: Bridge) -> dict:
    return bridge.page_info()


def scroll_to(bridge: Bridge, x: int, y: int) -> dict:
    return bridge.scroll_to(x, y)


def wait_for_idle(bridge: Bridge, silence: float = 2.0, timeout: float = 30.0) -> bool:
    result = bridge.wait_for_idle(silence=silence, timeout=timeout)
    return bool(result.get("success"))

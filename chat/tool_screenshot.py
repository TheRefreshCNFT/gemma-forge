"""
Gemma Forge screenshot tool. Uses Playwright (already installed alongside
scrapling) to capture PNGs of URLs and local HTML files.

Two entry points:
  - screenshot_url(url, ...)        → fetch + render + capture a remote page
  - screenshot_local_html(path, ...) → render a local .html file

Both return a normalized dict and can persist to <workspace>/screenshots/.

The harness wires this in two ways:
  1. After Execution writes an HTML deliverable, an auto-screenshot is
     captured so the handoff doc + verification card can reference a
     visual proof of the rendered output.
  2. /api/tools/screenshot lets the agent (or the harness) ask for a
     specific screenshot during a run.

This module is read-only with respect to the model — it just produces
PNG files in the workspace. The model can reference those paths in its
deliverables (e.g., HTML <img src="screenshots/...">).
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse


def is_available() -> bool:
    """Playwright is required (it ships with scrapling[all])."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug_for(url_or_path: str, max_len: int = 60) -> str:
    digest = hashlib.sha1(url_or_path.encode("utf-8", errors="replace")).hexdigest()[:10]
    base = re.sub(r"^https?://|^file://", "", url_or_path)
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower()
    base = base[:max_len].rstrip("-")
    return f"{base or 'page'}-{digest}"


SOURCE_SCREENSHOT_TIMEOUT_MS = 30000
LOCAL_SCREENSHOT_TIMEOUT_MS = 60000


def _capture(target_url: str, output_path: str, viewport: tuple, full_page: bool,
             wait_until: str, timeout_ms: int) -> dict:
    """Single Playwright headless capture. Returns the result dict."""
    started = time.time()
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                page.set_default_navigation_timeout(timeout_ms)
                response = page.goto(target_url, wait_until=wait_until, timeout=timeout_ms)
                status = response.status if response else None
                title = page.title() or ""
                page.screenshot(path=output_path, full_page=full_page)
                final_url = page.url
                page.close()
                context.close()
            finally:
                browser.close()
        return {
            "ok": True,
            "status": status,
            "title": title,
            "final_url": final_url,
            "path": output_path,
            "bytes": os.path.getsize(output_path) if os.path.exists(output_path) else 0,
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "full_page": bool(full_page),
            "captured_at": _utc_now(),
            "elapsed_ms": int((time.time() - started) * 1000),
            "error": None,
        }
    except Exception as error:
        return {
            "ok": False,
            "status": None,
            "title": "",
            "final_url": target_url,
            "path": output_path if os.path.exists(output_path) else None,
            "bytes": 0,
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "full_page": bool(full_page),
            "captured_at": _utc_now(),
            "elapsed_ms": int((time.time() - started) * 1000),
            "error": f"{type(error).__name__}: {error}",
        }


def screenshot_url(url: str,
                   output_path: str,
                   viewport: tuple = (1280, 800),
                   full_page: bool = True,
                   wait_until: str = "domcontentloaded",
                   timeout_ms: int = SOURCE_SCREENSHOT_TIMEOUT_MS) -> dict:
    if not is_available():
        return {
            "ok": False, "error": "playwright is not installed in this Python environment",
            "status": None, "title": "", "final_url": url, "path": None,
            "bytes": 0, "viewport": {"width": viewport[0], "height": viewport[1]},
            "full_page": bool(full_page), "captured_at": _utc_now(), "elapsed_ms": 0,
        }
    if not url or not url.lower().startswith(("http://", "https://")):
        return {
            "ok": False, "error": "url must start with http(s)://",
            "status": None, "title": "", "final_url": url, "path": None,
            "bytes": 0, "viewport": {"width": viewport[0], "height": viewport[1]},
            "full_page": bool(full_page), "captured_at": _utc_now(), "elapsed_ms": 0,
        }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    return _capture(url, output_path, viewport, full_page, wait_until, timeout_ms)


def screenshot_local_html(html_path: str,
                          output_path: str,
                          viewport: tuple = (1280, 800),
                          full_page: bool = True,
                          wait_until: str = "load",
                          timeout_ms: int = LOCAL_SCREENSHOT_TIMEOUT_MS) -> dict:
    if not is_available():
        return {
            "ok": False, "error": "playwright is not installed in this Python environment",
            "status": None, "title": "", "final_url": f"file://{html_path}", "path": None,
            "bytes": 0, "viewport": {"width": viewport[0], "height": viewport[1]},
            "full_page": bool(full_page), "captured_at": _utc_now(), "elapsed_ms": 0,
        }
    if not html_path or not os.path.isfile(html_path):
        return {
            "ok": False, "error": f"local html file not found: {html_path}",
            "status": None, "title": "", "final_url": f"file://{html_path}", "path": None,
            "bytes": 0, "viewport": {"width": viewport[0], "height": viewport[1]},
            "full_page": bool(full_page), "captured_at": _utc_now(), "elapsed_ms": 0,
        }
    file_url = "file://" + os.path.abspath(html_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    return _capture(file_url, output_path, viewport, full_page, wait_until, timeout_ms)


def slug_for(url_or_path: str) -> str:
    return _slug_for(url_or_path)


def screenshot_into_workspace(workspace_dir: str, target: str, mode: str = "auto",
                              viewport: tuple = (1280, 800), full_page: bool = True,
                              wait_until: str | None = None,
                              timeout_ms: int | None = None) -> dict:
    """
    Decide between url / local_html based on `target`. Persists into
    <workspace>/screenshots/<slug>.png and returns an artifact descriptor.
    """
    screenshots_dir = os.path.join(workspace_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    slug = _slug_for(target)
    out_path = os.path.join(screenshots_dir, f"{slug}.png")

    if mode == "url" or (mode == "auto" and target.lower().startswith(("http://", "https://"))):
        result = screenshot_url(
            target,
            out_path,
            viewport=viewport,
            full_page=full_page,
            wait_until=wait_until or "domcontentloaded",
            timeout_ms=timeout_ms or SOURCE_SCREENSHOT_TIMEOUT_MS,
        )
    else:
        result = screenshot_local_html(
            target,
            out_path,
            viewport=viewport,
            full_page=full_page,
            wait_until=wait_until or "load",
            timeout_ms=timeout_ms or LOCAL_SCREENSHOT_TIMEOUT_MS,
        )
    return {
        "target": target,
        "path": (os.path.relpath(result["path"], workspace_dir).replace(os.sep, "/")
                 if result.get("path") else None),
        "ok": result.get("ok"),
        "status": result.get("status"),
        "title": result.get("title"),
        "bytes": result.get("bytes"),
        "elapsed_ms": result.get("elapsed_ms"),
        "captured_at": result.get("captured_at"),
        "viewport": result.get("viewport"),
        "full_page": result.get("full_page"),
        "error": result.get("error"),
    }

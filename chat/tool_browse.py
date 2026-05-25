"""
Gemma Forge web-browse tool, backed by scrapling.

The harness — not the model — calls this. The model can DECLARE urls it wants
fetched (in a contract or in a research card), but the actual HTTP / browser
work happens here, deterministically, with the result written to disk so the
claim "researched N sources" is verifiable on the filesystem.

Three modes:

  - "request": pure HTTP GET via scrapling.Fetcher. Fastest, no browser, no JS.
  - "browser": real headless browser via scrapling.DynamicFetcher. Renders JS,
    waits for selectors. Use for sites that need rendering.
  - "stealth": full anti-bot bypass (Cloudflare Turnstile, etc) via
    scrapling.StealthyFetcher. Slowest, use when "request" and "browser" fail.

All modes return a normalized dict:
    {
        "ok": bool,
        "status": int | None,
        "url": str,
        "final_url": str,
        "mode": "request"|"browser"|"stealth",
        "title": str,
        "text": str,             # cleaned body text
        "html_bytes": int,       # raw html length, for diagnostics
        "fetched_at": iso8601,
        "elapsed_ms": int,
        "error": str | None,
    }
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime, timezone


def is_available() -> bool:
    """Return True if scrapling can be imported in this Python."""
    try:
        import scrapling  # noqa: F401
        return True
    except Exception:
        return False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_title(text_or_html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text_or_html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:200]


def _clean_text(html_text: str, max_chars: int = 60000) -> str:
    """
    Pull a reasonable text representation out of HTML. We avoid heavy
    dependencies; this is intentionally simple — drop scripts/styles, strip
    tags, collapse whitespace, cap length.
    """
    if not html_text:
        return ""
    cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_chars]


THIN_BODY_TEXT_THRESHOLD = 1024  # chars of cleaned text considered "thin"; below this, auto-escalate
MODE_LADDER = ("request", "browser", "stealth")


def _single_fetch(url: str, mode: str, timeout: int = 1200) -> dict:
    """One scrapling fetch in the named mode. Returns the normalized result
    or an error envelope. Never raises."""
    started = time.time()
    try:
        if mode == "request":
            from scrapling.fetchers import Fetcher  # type: ignore
            resp = Fetcher.get(url, timeout=timeout)
        elif mode == "browser":
            from scrapling.fetchers import DynamicFetcher  # type: ignore
            resp = DynamicFetcher.fetch(url, timeout=timeout * 1000, headless=True)
        elif mode == "stealth":
            from scrapling.fetchers import StealthyFetcher  # type: ignore
            resp = StealthyFetcher.fetch(url, timeout=timeout * 1000, headless=True)
        else:
            return {"ok": False, "error": f"unknown fetch mode {mode!r}", "mode": mode,
                    "status": None, "body": "", "final_url": url,
                    "elapsed_ms": int((time.time() - started) * 1000)}
        body_text = getattr(resp, "body", None)
        if isinstance(body_text, bytes):
            try:
                body_text = body_text.decode("utf-8", errors="replace")
            except Exception:
                body_text = body_text.decode("latin-1", errors="replace")
        elif body_text is None:
            body_text = ""
        return {
            "ok": True, "error": None, "mode": mode,
            "status": getattr(resp, "status", None),
            "body": body_text,
            "final_url": str(getattr(resp, "url", url) or url),
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    except Exception as error:
        return {
            "ok": False, "error": f"{type(error).__name__}: {error}", "mode": mode,
            "status": None, "body": "", "final_url": url,
            "elapsed_ms": int((time.time() - started) * 1000),
        }


def _looks_thin(cleaned_text: str, body_text: str) -> bool:
    """A page is 'thin' when there's almost no readable text — usually a
    JS-rendered bootstrap that needs the browser to hydrate."""
    if not body_text or len(body_text) < 256:
        return True
    if len(cleaned_text) < THIN_BODY_TEXT_THRESHOLD:
        return True
    return False


def fetch_url(url: str, mode: str = "auto", timeout: int = 1200) -> dict:
    """
    Fetch a URL via scrapling. `mode` may be one of:
      - "auto"     — climb the ladder (request → browser → stealth) until a
                     successful, non-thin response is found. Default.
      - "request"  — single fast HTTP GET, no JS.
      - "browser"  — Playwright headless (JS rendered).
      - "stealth"  — anti-bot bypass (Cloudflare etc); slowest.

    Returns a normalized dict including which `mode` actually produced the
    final content and the full `attempts` ladder so the agent can see what
    happened.
    """
    if not is_available():
        return {
            "ok": False, "status": None, "url": url, "final_url": url,
            "mode": mode, "title": "", "text": "", "html_bytes": 0,
            "fetched_at": _utc_now(), "elapsed_ms": 0,
            "error": "scrapling is not installed in this Python environment",
            "attempts": [],
        }

    started = time.time()
    if mode in MODE_LADDER:
        # Explicit single-mode call. Still allow one escalation if a 4xx
        # comes back from request mode — old behaviour. Otherwise: no
        # implicit escalation when the caller pinned the mode.
        ladder = [mode]
        if mode == "request":
            ladder.append("stealth")  # back-compat with previous implementation
    elif mode == "auto":
        ladder = list(MODE_LADDER)
    else:
        return {
            "ok": False, "status": None, "url": url, "final_url": url,
            "mode": mode, "title": "", "text": "", "html_bytes": 0,
            "fetched_at": _utc_now(), "elapsed_ms": 0,
            "error": f"unknown mode {mode!r}",
            "attempts": [],
        }

    attempts = []
    final_attempt = None
    chosen_mode = ladder[0]
    body_text = ""
    cleaned_text = ""
    status = None
    final_url = url

    for current_mode in ladder:
        attempt = _single_fetch(url, current_mode, timeout)
        body = attempt.get("body") or ""
        cleaned = _clean_text(body)
        attempts.append({
            "mode": current_mode,
            "status": attempt.get("status"),
            "ok": bool(attempt.get("ok")),
            "elapsed_ms": attempt.get("elapsed_ms"),
            "body_chars": len(body),
            "text_chars": len(cleaned),
            "error": attempt.get("error"),
        })
        final_attempt = attempt
        chosen_mode = current_mode
        body_text = body
        cleaned_text = cleaned
        status = attempt.get("status")
        final_url = attempt.get("final_url") or url

        # Decide whether to escalate.
        transport_failed = not attempt.get("ok") or (isinstance(status, int) and status >= 400)
        content_thin = (not transport_failed) and _looks_thin(cleaned, body)
        if transport_failed and current_mode != ladder[-1]:
            continue  # try the next mode
        if content_thin and current_mode != ladder[-1] and mode in ("auto",):
            continue  # JS-rendered site, climb the ladder
        # Success or last-mode failure — stop.
        break

    title = _extract_title(body_text)
    ok = isinstance(status, int) and 200 <= status < 400 and bool(cleaned_text)
    return {
        "ok": bool(ok),
        "status": status,
        "url": url,
        "final_url": str(final_url),
        "mode": chosen_mode,
        "title": title,
        "text": cleaned_text,
        "html_bytes": len(body_text) if isinstance(body_text, str) else 0,
        "fetched_at": _utc_now(),
        "elapsed_ms": int((time.time() - started) * 1000),
        "error": None if ok else (final_attempt.get("error") if isinstance(final_attempt, dict) else f"non-success status {status}"),
        "attempts": attempts,
    }


URL_PATTERN = re.compile(r"(https?://[^\s,)>'\"]+)", re.IGNORECASE)


def extract_urls(text: str, limit: int = 25) -> list:
    """Pull http(s) URLs out of free-form text, in order, deduped."""
    if not text:
        return []
    seen = []
    for match in URL_PATTERN.findall(text):
        cleaned = match.rstrip(".,;:)>]'\"")
        if cleaned not in seen:
            seen.append(cleaned)
        if len(seen) >= limit:
            break
    return seen


def url_slug(url: str, max_len: int = 60) -> str:
    """Stable, filesystem-safe filename stem for a URL."""
    digest = hashlib.sha1(url.encode("utf-8", errors="replace")).hexdigest()[:10]
    base = re.sub(r"^https?://", "", url)
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower()
    base = base[:max_len].rstrip("-")
    return f"{base or 'source'}-{digest}"


def write_research_artifact(workspace_dir: str, result: dict) -> dict:
    """
    Persist a fetch result under `<workspace>/research/<slug>.md`. Returns
    a small dict describing the on-disk artifact so the harness can list it
    in the workspace manifest and the claim validator can verify "researched
    N sources" against real files.
    """
    research_dir = os.path.join(workspace_dir, "research")
    os.makedirs(research_dir, exist_ok=True)
    stem = url_slug(result.get("url", ""))
    path = os.path.join(research_dir, f"{stem}.md")
    attempts = result.get("attempts") or []
    lines = [
        f"# {result.get('title') or 'Untitled'}",
        "",
        f"- Source URL: {result.get('url')}",
        f"- Final URL: {result.get('final_url')}",
        f"- Status: {result.get('status')}",
        f"- Mode (final): {result.get('mode')}",
        f"- Fetched: {result.get('fetched_at')}",
        f"- Elapsed (ms): {result.get('elapsed_ms')}",
        f"- OK: {result.get('ok')}",
    ]
    if result.get("error"):
        lines.append(f"- Error: {result.get('error')}")
    if attempts and len(attempts) > 1:
        lines.append("- Attempts (ladder):")
        for att in attempts:
            lines.append(
                f"  - mode={att.get('mode')} status={att.get('status')} "
                f"text_chars={att.get('text_chars')} ok={att.get('ok')} "
                f"ms={att.get('elapsed_ms')}"
            )
    lines.extend(["", "## Body", "", result.get("text", "") or "(empty)"])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return {
        "url": result.get("url"),
        "path": os.path.relpath(path, workspace_dir).replace(os.sep, "/"),
        "title": result.get("title"),
        "ok": result.get("ok"),
        "status": result.get("status"),
        "fetched_at": result.get("fetched_at"),
        "mode": result.get("mode"),
        "attempts": attempts,
    }


def fetch_and_persist(workspace_dir: str, url: str, mode: str = "auto") -> dict:
    result = fetch_url(url, mode=mode)
    artifact = write_research_artifact(workspace_dir, result)
    return {"result": result, "artifact": artifact}

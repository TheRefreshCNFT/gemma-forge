# Final push to contest submission

> Drives the last functional + visual passes before submission. Each block
> is a separate job; backups taken before each one. Order is functional →
> visual, per Ian's direction.

## Functional

### F1 — Scrapling: three-mode awareness + auto-escalation
Tool exposes three styles: `request` (HTTP GET, fastest), `browser`
(Playwright headless, JS-rendered), `stealth` (anti-bot bypass). Today
the harness only uses `request` and falls back to `stealth` on 4xx. That
misses JS-heavy sites that return 200 with a near-empty bootstrap (the
Logseq case in the notes-app demo).

Subtasks:
- F1.1 — `tool_browse.fetch_url` auto-escalates `request → browser` when
  the body is thin (<1024 chars of cleaned text), and `browser → stealth`
  when browser mode still returns thin / errors.
- F1.2 — Update the staged scrapling skill's prompt-facing text so the
  Context Writer + Execution model know all three modes exist. Add a
  "mode hint" field to the harness's research artifact metadata so the
  model can see WHICH mode succeeded.
- F1.3 — Smoke test on Logseq (JS-rendered) and a Cloudflare-protected
  URL.

### F2 — Screenshot capability (gemma-4 reads images well)
The model can consume images via Ollama's vision pipe. Screenshots are
also useful as deliverable material (embed in handoff, attach to a
verification doc). Backed by Playwright (already installed for
scrapling).

Subtasks:
- F2.1 — New `chat/tool_screenshot.py` wrapping Playwright. Supports two
  modes: `url` (screenshot a URL) and `local_html` (open a file:// path
  and screenshot). Saves to `<workspace>/screenshots/<slug>.png`.
- F2.2 — `POST /api/tools/screenshot` endpoint (URL or file path +
  session id).
- F2.3 — Wire automatic post-Execution screenshot when the deliverable
  format is `html` (the model wrote a webpage; harness renders it
  immediately and stores the PNG next to it). Promote `image_capture`
  to HARNESS_CAN_DO at runtime when Playwright is importable.
- F2.4 — Smoke test on a real URL and on a model-produced HTML file.

## Visual

### V3 — Merge top two sections into one + auto-collapse on typing
Two stacked panels at the top of the page are reducible to one
"Start a project" composite, freeing vertical space. Auto-collapse the
merged panel the first time the user types in the project-text input,
so they don't have to manually hide it.

### V4 — Model pills replacing the dropdown
- Auto-detect installed Ollama models (already exposed by `/api/models`).
- Render each as a pill. Dim = available, bright = active, click toggles.
- Two sections: **Primary Forge Brain** and **Fallback Forge Brain**.
  Selection in one section disables the same model in the other.
- Backend: persist `fallbackModel` on the session; if the primary
  Ollama call returns `unreachable` or `timeout`, retry once with the
  fallback before bubbling the transport error.

### V5 — Right column layout: cards bottom-aligned + send-message at bottom
The active card should hug the bottom of the viewport so it's at thumb /
eye level; the project-message textarea card sits below it, always at
the very bottom.

### V6 — Streaming terminal under both columns
Full-width rectangle below the two-column layout. Streams structured
events as work happens: card start/finish, scrapling fetch (URL + mode
+ ms), screenshot capture, ollama call (model + ms + transport status),
validation pass/fail, claim-validator failures.
- Server: in-memory ring buffer + SSE endpoint `/api/events/stream`.
- Client: a `<pre>` view subscribed to SSE, ANSI color (just CSS), with
  a collapse/expand toggle persisted in `localStorage`.

## Out of scope for this pass

- `exec` capability (sandbox + shell allow-list) — planned, not now.
- `document_authoring` (docx/pdf) — planned, not now.
- Per-card collapse-into-pill UI (older request, separate from V5).
- `skill-creator` skill — planned doc still on `.handoffs/`, not now.

## Backup strategy

Per webot-flow, before any source file edit:
```
mkdir -p ~/Backups/gemma-forge/<UTC-ISO>-pre-<TAG>/
cp -p chat/server.py chat/tool_browse.py chat/static/js/chat.js \
      chat/static/css/style.css chat/templates/index.html \
      ~/Backups/gemma-forge/<UTC-ISO>-pre-<TAG>/
```
One backup per functional block (F1, F2) and one per visual block
(V3-V4 grouped, V5-V6 grouped).

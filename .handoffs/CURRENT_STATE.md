# CURRENT_STATE.md — Gemma Forge

Last updated: 2026-05-21 (UTC) by /webot-flow review session.

## Verified ground truth

- Project root: `/Users/webot/Projects/gemma-forge`
- Branch: not checked (no commit requested this session).
- Harness Flask server source: `chat/server.py` (3,395 lines).
- Harness URL: `http://127.0.0.1:5005/`. Server PID file at
  `/private/tmp/gemma-forge-server.pid`; check before assuming it is
  running.
- Local Gemma Forge data dir: `~/.gforge/harness/` (sessions, model
  route, logs, staged skills).
- Ollama endpoint: `http://localhost:11434`.
- Submission target: Gemma 4 Challenge ("huge opportunity entering a
  google contest").

## Active task

**Make the harness usable for the small/medium local Gemma 4 model so
the contest demo path works end-to-end.** Driving doc:
`.handoffs/usability-fix-plan.md`.

## Status

- Phase: **P0.1 partial — Ollama timeouts bumped 60/30/30 → 1200/1200/1200.**
- Files edited so far: `chat/server.py` only (lines 1079, 1099, 1296).
- Backups taken: `/Users/webot/Backups/gemma-forge/20260521T135622Z-pre-usability/`
- Scope approved: full P0 + P1 + P2 (see fix plan).
- Demo model decision: `gemma-4` (E2B, ~3.4 GB).

## Shipped this session

- **2026-05-21 — Ollama timeouts to 1200s.** `call_ollama` 60→1200 s,
  `/api/chat` route primary 30→1200 s, `/api/generate` fallback 30→1200 s.
  Rationale: covers any device speed; not so long that a stuck agent
  waits forever.
- **2026-05-21 — P0.1 finish: `call_ollama` overhaul.** New
  `call_ollama_with_transport(model, prompt)` returns
  `(content, transport_dict)` and is the single source of truth.
  Request body now includes `keep_alive: "30m"` and
  `options: {temperature: 0.2, num_ctx: 8192, num_predict: 8192}`. Adds
  one transparent retry on `ConnectionError` (not on timeout). Failure
  no longer returns a polite English string — it returns `""` plus a
  typed transport status (`ok | empty | timeout | unreachable |
  http_error`). The pre-existing `call_ollama(model, prompt)` is now a
  thin string-only wrapper for back-compat with the ~10 card handlers
  that don't need transport detail.
- **2026-05-21 — P0.2 minimal surfacing.**
  - `call_ollama_json` and `call_ollama_execution_payload` now return
    a third element `transport`.
  - `execute_model_authored_project` writes
    `metadata.transport` into `artifacts/model-execution.json`.
  - `validate_model_authored_workspace` now records `transport` and,
    when `transport.status != "ok"`, emits a clear failure message
    (`Ollama request timed out after 1200s for ...`, etc.) instead of
    "model-authored execution returned no writable files".
  - `build_model_execution_report` adds an "Ollama Transport" section
    at the top of every `execution.md`.
  - Helper `transport_failure_message(transport)` covers all five
    transport states with a human-readable line.
- **2026-05-21 — Server restarted (PID 9114 → 49790).** `launchd` job
  `com.gemmaforge.harness` is keep-alive; SIGTERM triggered an
  auto-respawn that re-imported the new server.py from disk.
- **2026-05-21 — Live verification.**
  `POST /api/chat {"message":"Reply with exactly the word READY."}`
  on `gemma-4` (4.6B, Q4_K_M, 4.66 GB in VRAM) returned
  `{"reply":"READY"}` in ~0.3 s. `GET /api/ps` confirms the model is
  loaded with the long `expires_at` TTL produced by the `keep_alive`
  field.
- **2026-05-21 — Naive-prompt baseline test (pre Context Writer):**
  `"hey can you make me a logo? my business is called webot agency, we
  help companies with AI stuff. nothing too fancy, just something
  cool"` against `gemma-4` produced a 3,336-char polite refusal: *"As
  a text-based AI, I can't actually generate an image or a visual logo
  directly... feed into Midjourney, DALL-E, or Adobe Firefly."* Zero
  `<svg>`, zero `GFORGE_FILE` blocks. Reference at
  `/tmp/gforge-smoke-noob.json`.
- **2026-05-21 — Project Context Writer landed.** The `intake`
  card was rewritten end-to-end as a Project Context Writer:
  - Deliberate 5-step reasoning prompt (restate → classify →
    infer → pick format → emit YAML between
    `<<<CONTEXT_BEGIN>>>` markers).
  - Runs at `temperature: 0.1` via the new `options_override`
    parameter on `call_ollama_with_transport`.
  - Strict YAML schema validator (required keys: project, intent,
    deliverable, constraints, skill, acceptance, open_questions).
    `deliverable.format` must be one concrete value, never `tbd`.
  - One repair retry when validation fails, with the validation
    errors fed back to the model.
  - Successful parse stores the structured contract on
    `session.projectContext` so every downstream card can consume it.
  - Failed parse writes a "FAILED VALIDATION" intake.md with the
    errors and raw model output for debugging.
  - Card title changed from "Intake" to "Project Context"; card id
    stays `intake` to avoid breaking existing sessions.
  - `build_model_execution_prompt` now leads with a "PROJECT
    CONTEXT CONTRACT" block containing the full YAML plus an
    "ANTI-DEFLECTION ANCHOR" extracted from
    `deliverable.anti_deflection`. The raw user request is kept
    below as reference.
- **2026-05-21 — Naive-prompt end-to-end test (post Context Writer):**
  Same naive prompt, fresh session `session_1779374245642`,
  Forge Brain = `gemma-4`.
  - Project Context card: validated YAML on first try (no repair),
    transport `ok` in 7,993 ms. `deliverable.format = svg`,
    `path_pattern = output/webot_agency_logo.svg`,
    `skill.use = logo-generator`, anti_deflection populated.
    `intake-extra-review` (small-model auto-review) passed with
    `high` confidence.
  - Execution card: model wrote `output/webot_agency_logo.svg`
    (1,246 bytes), `validation.passed = true`, transport `ok` in
    17,784 ms. File parses as XML, root tag is the SVG namespace,
    7 children, `viewBox="0 0 100 100"`. Includes the wordmark
    "webot" + "agency" and the AI/node-network motif requested in
    the constraints. Saved at `/tmp/gforge-noob-logo.svg`.
  - Net: the same naive request that previously produced 3 KB of
    deflection now produces a working SVG end-to-end with no extra
    user effort.
- **2026-05-21 — Capability-aware Context Writer + claim validators.**
  Closes the "model role-plays completion of actions the harness has
  no tools for" gap that surfaced when the user asked the harness to
  clone a GitHub repo, research 5 sites, and create a new skill.
  - New module-level constants in `chat/server.py`:
    `HARNESS_CAN_DO`, `HARNESS_CANNOT_DO`, `CAPABILITY_KEYWORDS`,
    `ANTI_DEFLECTION_REGISTRY` (svg/html/css/js/ts/py/json/yaml/md/
    shell/sql/dockerfile/mermaid/txt), `ANTI_DEFLECTION_ALIASES`,
    `CLAIM_PATTERNS`, `GENERIC_NON_EVIDENCE_TOKENS`.
  - Context Writer prompt now ships a capabilities CAN/CANNOT table
    and auto-detects missing capabilities from the raw user text;
    the YAML contract gains `capabilities_required`,
    `deliverable.partial`, `deliverable.scope`. When a request needs
    a CANNOT capability the schema validator REQUIRES non-empty
    `open_questions` and forces `partial: true`.
  - Post-parse `enrich_project_context()` overwrites
    `deliverable.anti_deflection` with the canonical registry text
    per format and reconciles `capabilities_required` against the
    keyword-detection pass; the model can't downplay missing
    capabilities even if it tries.
  - Execution prompt now includes a "PARTIAL SCOPE WARNING" block
    listing the CANNOT capabilities and forbidding the model from
    using verbs like "installed", "cloned", "researched",
    "integrated", "configured" for those.
  - `validate_model_authored_workspace()` now runs
    `validate_claims_against_disk()` over the model's summary /
    notes / verification text. Matches against CLAIM_PATTERNS for
    git_clone, web_browse, skill_author, shell_exec, install_package,
    external_api, send_message, deploy. Each match is checked
    against the filesystem; "generic words like tool / library / repo"
    are excluded from evidence so they can't false-positive a
    fabrication-pass.
  - Reviewer prompt updated: "You CANNOT override a validator-flagged
    fabrication." Validation failures are now merged into reviewer
    findings + fixesNeeded explicitly.
- **2026-05-21 — End-to-end verification (session_1779386057316).**
  Same lying prompt (clone + research + skill-create + 10 logos):
  - Context Writer set `partial: true`,
    `capabilities_required: [emit_files, git_clone, install_package,
    skill_author]`, `skill.use: none`, 4 open_questions naming the
    gaps.
  - Execution wrote **10 real SVG files** (e.g.
    `output/logos/WeBot_Agency_Logo_0.svg` ... `_9.svg`), validation
    passed, transport ok in 43 s.
  - Model's own summary explicitly says it could NOT install / clone /
    create a skill: *"I was unable to execute the requested steps
    involving the installation of the external logo generation tool
    or the creation of a skill, as the necessary capabilities are
    unavailable to me."*
  - Auto small-model review reached the same honest conclusion:
    *"The execution explicitly reported that it was unable to install
    the external tool or create the skill due to missing system
    capabilities."*
  - Disk scan after the run: zero trace of `Custom-SVG-Logo-Generator`
    or `CodeNameNoah` anywhere — and the model never claimed
    otherwise.
- **2026-05-21 — Real `web_browse` capability via scrapling.**
  First time the harness gained a real (not simulated) external
  capability. Pieces:
  - `scrapling[all]>=0.4.5` installed in the harness venv
    (`/Users/webot/Projects/gguf/venv`), plus `scrapling install
    --force` for the Playwright browser deps. Both added to
    `requirements.txt` and the `launch_forge.command` script so
    fresh setups land the same way.
  - New module `chat/tool_browse.py`: `fetch_url(url, mode)` wrapping
    `scrapling.Fetcher` / `DynamicFetcher` / `StealthyFetcher` with
    auto-retry from request → stealth on 4xx, `extract_urls()` for
    pulling http(s) URLs out of free-form text,
    `write_research_artifact()` for persisting to
    `<workspace>/research/<slug>.md`.
  - New Flask endpoint `POST /api/tools/browse` (body:
    `{url, session_id?, mode?}`); writes a research artifact when
    `session_id` is provided.
  - `harness_capabilities()` is now a function — it recomputes CAN /
    CANNOT every call so a newly-installed tool registers on the
    next invocation. `web_browse` and `web_fetch` move into CAN
    automatically when scrapling imports cleanly.
  - `prepare_workspace_research()` runs inside Execution: extracts
    URLs from the user's project text, fetches them via scrapling,
    writes results to `<workspace>/research/<slug>.md`, and surfaces
    a `Harness-fetched research:` block in the Execution prompt
    listing the on-disk paths so the model can cite them.
  - Claim validator now checks for negation context (±150 chars) so
    honest model disclaimers ("was not performed because the harness
    lacks the capability") are not false-positive-flagged as
    fabrications. URLs mentioned in claims are also auto-substantiated
    when a matching `research/<slug>.md` artifact exists.
  - The `scrapling-official` skill folder was staged at
    `~/.gforge/harness/skills/scrapling-official/` so the Context
    Writer can pick it in `skill.use`.
- **2026-05-21 — Verified end-to-end on session_1779388400881.**
  Same lying prompt asking for GitHub clone + skill author + 10 logos:
  - `capabilities_required: [emit_files, git_clone, install_package,
    skill_author]` — `web_browse` correctly NOT flagged because
    scrapling is installed and the harness already pre-fetched the
    URL.
  - `research/github.com-codenamenoah-custom-svg-logo-generator-...md`
    landed on disk with the real GitHub README content (9 KB,
    status 200, 1025 ms via scrapling request mode).
  - 10 valid SVG logos in `output/`.
  - `validation.passed = true`, `failures = []`.
  - Auto small-model review: `passed = true, confidence = high`,
    finding: *"The model correctly explained this limitation and
    generated the artifacts internally instead."*
- **2026-05-21 — Forge Flow no longer skipped in new-project mode.**
  Root cause: `default_cards()` marked forge-flow as `status:
  "pending"` whenever `projectMode == "new-project"`. The UI's
  `nextRunnableCard()` filter excludes `pending`, so Full Forge
  walked past forge-flow on every new-project session. After
  Execution, `activate_post_execution_cards()` flipped it back to
  active — but by then the chain had moved on or paused at
  Human Verify, leaving the card visible-but-unrun.
  Fix in `chat/server.py`:
  - Removed the `forge-flow → pending` override; the handler already
    has a `if project_mode == "new-project"` branch that writes a
    "Workspace Pending" orientation artifact, so running it early is
    strictly better than skipping.
  - Strengthened `activate_post_execution_cards`: when forge-flow has
    a "Workspace Pending" artifact AND Execution just created a real
    workspace, the card is re-activated for a second pass against the
    materialised directory.
  Existing-directory mode was unaffected — forge-flow was already
  active there, which is why the bug looked intermittent.
- **2026-05-21 — Final-push functional + visual pass (pre-submission).**
  Driving doc: `.handoffs/final-push-plan.md`. Pre-work backup:
  `~/Backups/gemma-forge/20260521T214645Z-pre-final-push/`.

  **Functional**

  - **F1 — Scrapling auto-escalation (3-mode ladder).**
    `tool_browse.fetch_url(..., mode="auto")` climbs
    `request → browser → stealth` whenever a fetch returns transport
    failure OR a thin body (<1024 chars of cleaned text). All attempts
    recorded in the research artifact's "Attempts (ladder)" block. The
    auto-research pre-step in Execution now uses `mode="auto"` by
    default. Logseq (JS-rendered) went from 51 chars (request mode)
    → 3,715 chars (browser mode) on the verification run.

  - **F2 — Screenshot capability via Playwright.** New
    `chat/tool_screenshot.py` with `screenshot_url`,
    `screenshot_local_html`, and `screenshot_into_workspace`. New
    endpoint `POST /api/tools/screenshot`. Auto-captures every HTML
    deliverable into `<workspace>/screenshots/<slug>.png` and lists
    them in `execution.md`. `screenshot_capture` promoted to
    `HARNESS_CAN_DO` at runtime when Playwright is importable.

  **Visual**

  - **V3 — Top sections merged + auto-collapse on typing.** Old
    `.workspace-grid` (Forge Engine + Forge Intelligence) collapsed
    into a single `<section id="start-panel">` with Environment on
    the left and Forge Brain pills on the right.
    `setupStartPanelAutoCollapse()` collapses the panel on the first
    keystroke in the project-text textarea.

  - **V4 — Model pills replace the dropdown.**
    `renderModelPills()` renders auto-detected installed Ollama
    models as pills under two groups: **Primary Forge Brain** and
    **Fallback Forge Brain**. Active = bright (filled accent),
    available = dim, mutex (a model selected in Primary is greyed
    out in Fallback and vice versa). New topbar pill
    `#active-model-pill` always shows the current pick + fallback.
    Backend `PATCH /api/sessions/<id>/model` now accepts
    `{model, fallbackModel}`; `session.fallbackModel` persists.

  - **V5 — Right-column layout.** `.cards-panel` is now a flex
    column with `justify-content: flex-end`; the protocol cards
    stack from the bottom; the new `.session-conversation-card`
    (containing the "Send to agent" textarea) is pinned at the
    very bottom. The old left-column message compose was removed
    and its content lives in the cards-panel.

  - **V6 — Streaming activity terminal.** Thread-safe in-memory
    ring buffer + SSE endpoint `GET /api/events/stream` (plus a
    polling fallback at `/api/events/recent`). `emit_event()`
    is called from card start/end, every Ollama call,
    every scrapling fetch, every screenshot capture, and every
    validation outcome. UI terminal sits full-width below the
    two-column grid with collapse-toggle (state persisted in
    `localStorage`), connection-status dot, clear button. Verified
    live: terminal flips to `CONNECTED` and prints events such as
    `screenshot https://example.com → screenshots/...png` in real
    time.

  Files changed in this pass: `chat/server.py`,
  `chat/tool_browse.py`, `chat/tool_screenshot.py` (new),
  `chat/static/js/chat.js`, `chat/static/css/style.css`,
  `chat/templates/index.html`, `requirements.txt`,
  `launch_forge.command`. All compile / `node -c` clean. Backup at
  `~/Backups/gemma-forge/20260521T214645Z-pre-final-push/`.

- **2026-05-21 — Resolve-flow fix + contract-aware Verification.**
  Pre-work backup at
  `~/Backups/gemma-forge/20260521T222535Z-pre-resolve-flow/`.

  **Fix A — Resolve actually feeds the reviewer's findings to the agent.**
  - New `build_correction_from_state(session, card_id, user_note)`
    bundles the prior card's `extraReview.summary / findings /
    fixesNeeded` AND the user's typed Resolve-issue note AND the
    prior deterministic-validation failures into one dict.
  - `run_session_card` builds the correction BEFORE the rerun
    overwrites the card's `lastRun`, then passes it through
    `run_card_action(..., correction=correction)`.
  - `run_card_action` forwards `correction` to `run_execution_card`
    and `run_verification_card` (the two handlers that author
    deliverables vs. metadata).
  - `run_execution_card` passes `correction` as the existing
    `review` parameter to `execute_model_authored_project`, which
    already has a "Previous review failed:" prompt block.
  - `build_model_execution_prompt` extended: surfaces `userNote`
    as a "USER CORRECTION" callout AND `validationFailures` as a
    structured field so the model sees what failed deterministically.
  - `run_verification_card` accepts `correction` and injects a
    correction block (userNote + reviewer findings + reviewer fixes)
    into the Verification card's call_ollama prompt. The model is
    explicitly told to mark which items have been satisfied.
  - `repair_verification_after_review` (the auto post-review-repair
    that runs when the small-model reviewer fails) now passes BOTH
    `model` and `review` to `build_verification_details` — previously
    it passed neither, leaving the Checklist empty and discarding
    any user correction.

  **Fix B — Verification card file check is contract-aware.**
  - Dropped the hardcoded
    `index.html / styles.css / script.js / README.md / docs/delivery.md`
    list at the old `chat/server.py:3917`. That list was producing
    false-positive "missing" findings whenever the contract didn't
    promise those files (e.g. SVG logo runs, single-file HTML, CLI
    tools). Those false positives biased the small-model reviewer
    toward Not Verified.
  - New `derive_verification_paths(session, workspace_dir)` reads
    `session.projectContext.deliverable.path_pattern + format` and:
    - always includes `artifacts/validation.json`;
    - lists files in the deliverable's directory matching the
      expected extension (e.g. all `output/*.svg` for an SVG run,
      `output/index.html` for a single-file HTML);
    - includes `README.md` only when project type is `code`.
  - Tolerates phrase/range path_patterns ("output/foo to output/bar")
    by extracting the first path-looking token, same forgiving parse
    used by Forge Flow.

  **Verified end-to-end (session_1779403758448):**
  - Fresh Crema landing-page session ran intake → forge-flow → gsd →
    execution → verification cleanly.
  - Triggered Resolve on Verification with the note:
    *"the page is fine but i want THREE design options and a small
    ABOUT section explaining the shop history."*
  - Live event stream printed:
    `verification starting (resolve: 1 findings + user note)`
    — confirms the harness bundled both the prior reviewer finding
    and the user's note into the rerun.
  - New `verification.md` Checklist section is now populated with a
    real model response that explicitly cites the missing 3 options
    and the missing ABOUT section — no longer the empty fallback.
  - `Files Inspected` shows only `artifacts/validation.json`,
    `output/index.html`, and `README.md` (the latter because
    `project.type == code`). No more bogus
    `styles.css: missing / script.js: missing / docs/delivery.md: missing`
    noise.

  Files changed: `chat/server.py` only (no UI or schema changes).
  Compile + offline unit smoke + live SSE event trace all green.

- **2026-05-21 — Chain continuation fix: Resolve / Verified now reach Handoff.**
  Pre-work backup at
  `~/Backups/gemma-forge/20260521T233052Z-pre-handoff-chain/`.

  Two diagnosed defects:

  1. **JS chain stops at the wrong place.** When runPlan exits at a
     `needs-attention` card, it clears `planRunning = false` AND
     `planPaused = false`. The Resolve handler then captured
     `wasChaining = planRunning || planPaused` → both false → never
     restarted runPlan after the rerun succeeded. Same defect in the
     Verified handler (`shouldContinue = planRunning || planPaused`).
     Net effect: any card that hit needs-attention left the chain
     dead even when the user explicitly fixed the issue.

  2. **Server re-runs the small-model reviewer on human Verified.**
     `verify_session_card` called `ensure_completion_review(...)` on
     every Verified click — meaning the human's explicit approval
     could be flipped back to `needs-attention` by the small-model
     reviewer second-guessing the human. Took 30-60s per click. The
     human should be the final arbiter for Human Verify mode.

  Fixes shipped:

  - `chat/static/js/chat.js`: Verified handler unconditionally calls
    `setTimeout(runPlan, 80)` after a successful verify. Resolve
    handler unconditionally calls `runPlan` after a successful rerun
    that didn't leave the card in `needs-attention` or
    `awaiting-human`. The `wasChaining` / `shouldContinue` gates are
    gone — both clicks mean "fix-and-advance."
  - `chat/server.py` `verify_session_card`: when `status == "verified"`,
    mark the card complete + stamp `verifiedAt` + set
    `lastRun.humanVerified = True` for audit. Do NOT re-run the
    reviewer. Emits a new `card-verified` event for the activity
    stream. Took 0 s on a needs-attention card in the test below
    (was 30-60 s).

  Verified live (session_1779404038314, was stuck verification=
  `needs-attention`, handoff=`active`):
  - `POST /verify status=verified` → response in 0 s, card flipped
    to `complete` immediately, `humanVerified: True` recorded.
  - Activity stream: `card-verified verification verified by human`.
  - `POST /cards/handoff/run` (simulating what runPlan now does
    automatically after Verified) → ran in 28 s, status
    `awaiting-human` (correct — handoff's own verify pause).
  - Event sequence confirmed:
    `card-verified verification → card-start handoff → card-end
    handoff: Project handoff generated`.

  Files changed: `chat/static/js/chat.js`, `chat/server.py`.
  Compile + node -c clean. Server restarted, change live.

- **2026-05-21 — All tool-execution timeouts bumped to 1200 s.**
  Backup at `~/Backups/gemma-forge/20260521T234221Z-pre-timeout-1200/`.

  Rationale (per Ian): "all devices capable to have to time for
  their model to run." A slow Mac running a 31B model on cold RAM
  shouldn't fail a tool call because some hidden 30s timer fired.

  **Bumped to 1200 s** (every model / agent / tool-work path):
  - `server.py:4221` `run_local_command` default (was 20)
  - `tool_runtime.py:30` `run_command` default (was 20)
  - `tool_runtime.py:118` npm install (was 180)
  - `tool_runtime.py:277` `SocratiCodeMcpClient.__init__` (was 60)
  - `tool_runtime.py:384` MCP initialize (was 30)
  - `tool_runtime.py:409` `call_socraticode_tool` (was 60)
  - `tool_runtime.py:417` `socraticode_mcp_probe` (was 45)
  - `tool_runtime.py:452` `run_socraticode_project_scan` (was 180)
  - `tool_runtime.py:477,496,501` internal MCP waits (were 30/60/30)
  - `tool_runtime.py:558` axon status during runtime check (was 30)
  - `tool_runtime.py:592` `run_axon_project_scan` (was 120)
  - `tool_runtime.py:608` axon status inside scan (was 30)
  - `tool_runtime.py:613` axon dead-code (was 45)
  - `tool_browse.py` `fetch_url` + `_single_fetch` defaults (was 25)
  - `tool_screenshot.py` `screenshot_url` Playwright timeout (was 25000 ms)
  - `tool_screenshot.py` `screenshot_local_html` Playwright timeout (was 15000 ms)

  **Deliberately kept short** (liveness probes, process cleanup,
  concurrency locks — these are NOT model-time paths, and stretching
  them would make the harness hang on a dead service instead of
  surfacing the failure):
  - `server.py:1033` SSE `q.get` 15 s — heartbeat interval, not a
    work timeout.
  - `tool_runtime.py:79` `node --version` 5 s — liveness.
  - `tool_runtime.py:197` `docker info` 10 s — liveness.
  - `tool_runtime.py:228` docker probe 10 s — liveness.
  - `tool_runtime.py:312` `process.wait` 5 s — process cleanup
    during MCP shutdown.
  - `tool_runtime.py:538` `--version` 10 s — liveness.
  - `tool_runtime.py:568` `tool_file_lock` 120 s — concurrency
    control (a card waiting on another card's tool lock).
  - `workspace_scan.py:132,229` Ollama `/api/tags` + `/api/version`
    2 s each — liveness probes; if Ollama is dead the workspace
    scan should fail fast, not hang the UI for 20 minutes.

  Verified: compile clean, restart clean, `/api/workspace/status`
  responded in 2.7 s (Ollama probe still snaps fast — confirms the
  short probes are still short).

- **2026-05-22 — Visual polish round (V1–V4).**
  Pre-work backup at
  `~/Backups/gemma-forge/20260522T001538Z-pre-visual-polish/`.

  - **V1** — focusing the "Send to agent" textarea now auto-collapses
    the top Start panel (in addition to the existing
    type-into-project-input collapse). Added a `focus` listener to
    `#session-message-input` that calls the existing `collapseOnce`
    helper.
  - **V2** — `.main` is now `height: 100vh, overflow: hidden` and a
    flex column; `.planner-grid` is `flex: 1, align-items: stretch`;
    `.intake-panel` is a flex column where `.agent-output` is
    `flex: 1, min-height: 200px`. Result: sidebar + intake column +
    cards column all bottom-align inside the viewport; sections
    scroll internally. Verified: sidebar bottom 1100 px,
    intake/cards bottom 993 px (107 px gap = event terminal +
    `.main` padding — intentional chrome).
  - **V3** — rolodex card stack. `#workflow-cards` is now
    `position: relative` with each card `position: absolute, inset
    sides`. CSS classes `.is-front`, `.behind-1/2/3`,
    `.behind-deep`, `.ahead-1/2`, `.ahead-deep` control z-order +
    transform (translateY + scale + opacity) for a deck-of-cards
    peek look. New `.rolodex-nav` above the stack with prev/next
    arrows and a `1 / 8` indicator. New JS:
    `applyRolodexLayering`, `updateRolodexNav`, `rolodexStep`,
    `setupRolodexNav`. Auto-rotate: when the chain advances to a
    new active/needs-attention/awaiting-human card, the rolodex
    front follows automatically; manual arrow nav wins until the
    next status change. Arrow-key support when focus is inside the
    card area.
  - **V4** — Forge mascot strip in the terminal header. 8 pixel-art
    SVG icons (anvil, hammer, sparks, gear, flame, bolt, cube, tiny
    robot face) drawn with `shape-rendering: crispEdges` and
    `image-rendering: pixelated`. ~40-line quip bag of forge-themed
    sayings ("Hammer down.", "Iron sharpens iron.", "Local model,
    real heat.", etc.) shuffled in Fisher-Yates batches and rotated
    every 14 s with a gentle fade. New JS: `setupForgeMascot`,
    `_renderForgeMascot`. Hides on viewports < 880 px to preserve
    the Clear/Show buttons.
  - **Sanity check**: 5 states screenshotted (pristine, focused,
    rolodex mid, terminal open, narrow viewport). Zero page errors
    in any state.

  Files changed: `chat/static/js/chat.js`, `chat/static/css/style.css`,
  `chat/templates/index.html`. Server unchanged.

## Product philosophy (load-bearing)

Gemma Forge is an **execution machine, not a chatbot.** Small input →
finished deliverable. No multi-turn dialogue beyond Human Verify
checkpoints. No persistent user memory. Per-project state is scoped
to the project. Avoid conversational embroidery in prompt templates
and generated artifacts. Anything that feels more like "chatbot that
knows the user" than "app that gets things done" is out of scope
unless Ian asks. Full rule set:
[`project_gemma_forge_philosophy.md`](file:///Users/webot/.claude/projects/-Users-webot--gforge/memory/project_gemma_forge_philosophy.md).

## Hard rules (do not skip)

- **Authenticity:** the smallest Gemma 4 model must actually do the
  user's task through the harness workflow. Do not pre-bake, fake,
  force, template, or hardcode successful outputs. Deterministic
  scripts can verify or package, never replace the model's work.
- **No Axon/SocratiCode success claims** unless the tool actually ran.
- **Local is source of truth.** Never edit production behind the
  harness — every change goes through the harness flow.
- **Pre-edit backups:** any file at `chat/` or under
  `~/.gforge/harness/skills/` gets copied to
  `~/Backups/gemma-forge/<TIMESTAMP>-pre-<TAG>/` before edit.
- **AGENTS.md rules apply** (no `git add -A`, no `--no-verify`, etc.).
- **No commits** unless the user asks.

## DO NOT TOUCH

- `~/.ollama/` (Ollama's own home, separate from Gemma Forge).
- The model-forging GUI under `src/` — supporting infra, not the
  harness path. Out of scope for the usability sprint.
- `forge.md`'s authenticity-rule text — only the model
  recommendation line is in scope for editing.
- Submission media in `docs/submission-media/`.

## Verification commands (run on session start to confirm ground truth)

```bash
ls /Users/webot/Projects/gemma-forge/.handoffs/
test -f /private/tmp/gemma-forge-server.pid && cat /private/tmp/gemma-forge-server.pid
curl -s http://localhost:11434/api/tags >/dev/null && echo "Ollama up" || echo "Ollama down"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5005/
tail -5 /Users/webot/.gforge/harness/logs/errors.jsonl
```

## Reference: known failure pattern from the run that prompted this

- `~/.gforge/harness/logs/errors.jsonl` shows 5 `ReadTimeout` errors on
  Ollama port 11434 against `gemma4:31b-max` (19.8 GB) with a 60 s
  hardcoded timeout in `chat/server.py:1296`.
- `~/.gforge/harness/session-data/session_1779370542607/execution.md`
  captures the resulting "0 model-authored files" verdict, with the
  raw model output actually being the harness's own fallback
  English string from `chat/server.py:1302-1305`. The downstream
  agent mis-blamed the schema. Fix plan addresses the timeout, the
  fallback shape, and the schema-injection order.

## Next action

Wait for user approval to execute the fix plan. When approved, start
with P0.1 (`call_ollama` overhaul) — smallest blast radius, biggest
single-step impact.

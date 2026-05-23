# CURRENT_STATE.md — Gemma Forge

Last updated: 2026-05-23 (UTC) — external backup + GitHub alignment in progress.

## Verified ground truth

- Project root: `/Users/webot/Projects/gemma-forge`
- Branch: `main` tracking `origin/main`; working tree intentionally
  contains uncommitted current-state changes. No commit requested.
- Harness Flask server source: `chat/server.py` (3,395 lines).
- Harness URL: `http://127.0.0.1:5005/`. Server PID file at
  `/private/tmp/gemma-forge-server.pid`; check before assuming it is
  running.
- Local Gemma Forge data dir: `~/.gforge/harness/` (sessions, model
  route, logs, staged skills).
- Root `HANDOFF.md` and `ACTIVE_STATE.md` are not present in this repo;
  canonical pickup state is this file plus `project-map.md`.
- Ollama endpoint: `http://localhost:11434`.
- Submission target: Gemma 4 Challenge ("huge opportunity entering a
  google contest").

## Active task

**Make the harness usable for the small/medium local Gemma 4 model so
the contest demo path works end-to-end.** Driving doc:
`.handoffs/usability-fix-plan.md`.

## Status

- Phase: **External backup completed; GitHub installable-state alignment in progress.**
- User-verified current behavior:
  - The obsolete `plan-run-status` strip / text
    "Start a project to run active cards." is removed from the
    protocol-card header.
  - Auto mode keeps its separate flow and now visually activates the
    Project Context / intake card while intake is running: active
    border/glow plus disabled `Running` button.
  - Manual / Human Verify flow remains separate: cards still show
    `Forge Section` until manually run.
- Locally verified current behavior:
  - Completed protocol cards show compact run facts on the card
    itself, e.g. Project Context shows format/path/count/skill/open
    questions/review/research.
  - Long raw card artifacts remain available but are collapsed behind
    a "Full section artifact" disclosure by default.
  - The right-side Project Context log keeps the chronological project
    feed and now has a taller scroll area.
- Latest files touched for this accepted state:
  `chat/templates/index.html`, `chat/static/js/chat.js`,
  `chat/static/css/style.css`, `.handoffs/CURRENT_STATE.md`,
  `project-map.md`.
- Working tree note: other uncommitted current-state changes existed
  before this handoff alignment (`chat/server.py`, `launch_forge.command`,
  `skills/`, `tools/`, etc.). They are treated as accepted project state
  unless Ian asks for a commit or cleanup pass.
- Latest backup locations:
  - `/Volumes/PHIXERO/Backups/gemma-forge/20260523T172125Z-full-live-local-working-state/`
  - `/Users/webot/Backups/gemma-forge/20260523T160939Z-pre-remove-plan-status/`
  - `/Users/webot/Backups/gemma-forge/20260523T161535Z-pre-auto-intake-running/`
  - `/Users/webot/Backups/gemma-forge/20260523T163326Z-pre-state-align/`
  - `/Users/webot/Backups/gemma-forge/20260523T164725Z-pre-card-context-visibility/`
- Backup/GitHub rule: when Ian asks for backup or state alignment, a
  complete pass means (1) the full live local working state is backed up
  to external SSD `/Volumes/PHIXERO/Backups/gemma-forge/` and verified,
  and (2) GitHub is aligned to the installable repo state unless a
  blocker is explicitly reported. Keep runtime/generated/private data
  out of GitHub.
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

- **2026-05-22 — V7 layout finalization + ? helper fixes + skills bundled.**
  Pre-work baseline at
  `~/Backups/gemma-forge/20260522T164405Z-layout-final-baseline/`.

  **Layout (V7) — Ian-approved.**
  - `.app-shell` is now a natural-height flex column (NOT viewport-locked).
    Page scrolls if total content exceeds viewport — by design.
  - New `.app-shell-top` grid row hosts sidebar + main. CSS Grid with
    `align-items: stretch` means sidebar stretches to match the tallest
    column automatically — intake-panel + cards-panel auto bottom-align
    with the sidebar bottom.
  - `#event-terminal` moved OUT of `.main`. Now a sibling of
    `.app-shell-top` inside `.app-shell` — sits full-bleed under the
    sidebar + main columns with an 18 px top margin. No border-radius
    (edge-to-edge).
  - `.cards-panel` restructured: the heavy separate `panel-header`
    (Orchestration / Protocol cards / Full Forge / status) was removed.
    Title + arrow nav + Full Forge button now live inside the rolodex
    itself as a single integrated `.rolodex-header` strip. Each
    workflow-card has `overflow: auto` so long content scrolls inside
    the card, not against the parent.
  - Session-conversation-card back to natural sizing (no min-height,
    no flex constraints). Session-messages capped at 180 px with
    internal scroll.
  - Environment facts now a clean `auto-fit minmax(168 px, 1fr)` tile
    grid with label-above-value typography — replaces flex-wrap pill
    chaos.

  **? helper fixes.**
  - `start-panel` `?` was blank — `data-help-key="start-panel"` had no
    matching entry in `chat.js`'s `helpContent` dict. Added an entry
    explaining the panel (Environment + Forge Brain + collapse behaviour).
  - The "New Project" `?` was grouped with Human-Verify on the right
    side of the panel header. Moved it inline with the title block
    (new `.intake-title` container with `.section-label` + `<h2>` +
    `.intake-help`) so the explainer sits next to the input it explains.

  **Skills bundled into the install package.**
  - Prior state: 3 protocol skills (`logo-generator`, `scrapling-official`,
    `ui-ux-pro-max`) lived only at `~/.gforge/harness/skills/` (NOT in
    the repo). A fresh clone had zero staged skills, so the Project
    Context Writer's `skill.use` picker had nothing to point at.
  - Copied all 3 to repo `skills/` (13 MB total, excluding `.git` and
    `.DS_Store`). Licenses preserved (MIT for ui-ux-pro-max and
    logo-generator; scrapling-official is the upstream).
  - `launch_forge.command` extended with an idempotent skill-staging
    block: walks `skills/*` and copies any missing dir into
    `~/.gforge/harness/skills/`. Existing skills are NOT overwritten
    (preserves user edits / additional manually-staged skills).
  - Sandbox-verified in `/tmp/gforge-staging-test.*`: clean target →
    3 skills land (148 K + 284 K + 13 M). Re-run → all 3 skip-existing.

  **Audit summary for clean-install readiness.**
  - `requirements.txt` complete: customtkinter, flask, flask-cors,
    huggingface_hub, requests, PyYAML, scrapling[all]. Playwright pulled
    in transitively via `scrapling[all]`; `scrapling install --force`
    fetches the browser binaries.
  - `chat/tool_browse.py` lazy-imports scrapling. `chat/tool_screenshot.py`
    lazy-imports playwright. `chat/tool_runtime.py` is stdlib-only.
  - `chat/server.py` only imports Flask + stdlib + yaml + the local
    `tool_browse` / `tool_screenshot` modules.

  Files changed: `chat/static/css/style.css`, `chat/static/js/chat.js`,
  `chat/templates/index.html`, `launch_forge.command`. Added: `skills/`
  (new dir, untracked — needs `git add skills/` before commit).
  Syntax-clean: `bash -n launch_forge.command` ✓, `node --check chat.js` ✓.

- **2026-05-22 — Full one-command installer (launch_forge.command).**
  The launcher now installs the COMPLETE running stack — nothing else
  to set up. Idempotent: rerunning is a no-op when everything is in
  place. Each block is presence-checked before action.

  **Install order (each step skips if already done):**

  1. **Homebrew** — checks `command -v brew`; if missing, runs the
     official one-liner installer and re-evaluates `brew shellenv` so
     the rest of the script can use it.
  2. **Ollama** — `brew install ollama`. Starts `brew services start
     ollama` if `http://localhost:11434/api/version` isn't responding;
     waits up to 10 s for liveness.
  3. **Model pull — not done at install time.** Reviewers / users pull
     models from the harness Settings → Provision card (supports
     HuggingFace repo IDs like `google/gemma-4-E2B`) or directly with
     `ollama pull <name>`. Earlier draft auto-pulled `gemma4:e2b` —
     removed per Ian: pull happens when the user uses those features.
  4. **Node.js 22** — `brew install node@22` + `brew link --force
     --overwrite node@22`. Required by SocratiCode (Node 18–25 range).
  5. **Docker Desktop** — `brew install --cask docker`. Prints a
     one-time prompt asking the user to launch Docker.app once for
     kernel-extension approval. Harness boots without Docker — only
     the SocratiCode card depends on it (needs Qdrant container).
  6. **Python venv + requirements.txt** — creates `.venv` if absent,
     installs `customtkinter`, `flask`, `flask-cors`,
     `huggingface_hub`, `requests`, `PyYAML`, `scrapling[all]`.
  7. **Playwright browsers** — `scrapling install --force` flagged by
     a `.scrapling-browsers-installed` sentinel in the venv.
  8. **Axon CLI** — `pip install axoniq` into the venv. The `axon`
     binary lands in `$VENV_PATH/bin/axon` and resolves via
     `shutil.which("axon")` once the venv is active. Skipped if
     `pip show axoniq` already finds it.
  9. **SocratiCode MCP** — `npm install --prefix ~/.gforge/tools
     socraticode@latest`. Only runs if
     `~/.gforge/tools/node_modules/.bin/socraticode` doesn't exist.
  10. **Bundled protocol skills** — copies `skills/*` →
      `~/.gforge/harness/skills/` for any skill the user doesn't
      already have staged.
  11. **Launch** — exports `PYTHONPATH`, starts
      `python -m chat.server` at port 5005.

  **External tool sources documented in the launcher header:**
  - Gemma 4 E2B: https://ollama.com/library/gemma4 (tag `e2b`, 7.2 GB)
  - Axon: https://github.com/harshkedia177/axon (PyPI `axoniq`)
  - SocratiCode: npm `socraticode@latest`
  - Scrapling: pip `scrapling[all]` + `scrapling install --force`

  **Verified idempotency on Ian's machine (everything-already-installed
  state):** brew skip, ollama skip, ollama service skip,
  gemma alias present → pull skipped, node skip, docker skip,
  socraticode bin skip, all 3 skills skip. Only the venv-bound items
  (scrapling browsers, axoniq) trigger when run against a fresh
  project-root `.venv` (Ian's running harness uses a different venv at
  `/Users/webot/Projects/gguf/venv`).

  File changed: `launch_forge.command` only. `bash -n` clean.

- **2026-05-22 — Clean-room install verified in a fresh macOS VM.**
  Submission-readiness gate cleared. Reviewers cloning the repo on a
  fresh Mac will get the entire running stack from `./launch_forge.command`.

  **Test environment**
  - macOS Sequoia base image: `ghcr.io/cirruslabs/macos-sequoia-base:latest`
    (~30 GB, pulled once via tart, cached at `~/.tart/`).
  - VM driver: `tart` 2.32.1 (`brew install cirruslabs/cli/tart`).
  - Headless SSH access via `sshpass` (`brew install
    hudochenkov/sshpass/sshpass`).
  - Project mounted into VM at `/Volumes/My Shared Files/gemma-forge`
    (read-only), then copied to `~/gemma-forge` inside the VM for write
    access during the install.

  **Two test scripts shipped under `tools/`:**
  - `tools/verify_clean_install.sh` — runs INSIDE the VM after
    `./launch_forge.command` completes. 7 sections, ~27 checks.
    Sources `brew shellenv` at the top so it works under SSH (no
    login-shell PATH). Treats Docker-installed-but-not-launched as
    `⚠` (warning, not fail) since on macOS the `docker` CLI only
    joins PATH after Docker.app is first launched (kernel-ext approval).
    Treats `complete | awaiting-human | needs-attention` all as
    successful E2E intake-card outcomes (the harness ran the card; the
    quality of a 1B model's writing isn't what the verify is testing).
  - `tools/run_clean_install_test.sh` — host-side orchestrator that
    clones a fresh VM from the base image, boots it headless, SCPs the
    project, kicks off `./launch_forge.command` as a backgrounded
    process inside the VM, waits up to 15 min for the server to come up
    on port 5005, then runs the verify script inside.

  **Results from a full cold-clean run (test #2):**
  ```
  ✓ brew on PATH at /opt/homebrew/bin/brew
  ✓ ollama on PATH at /opt/homebrew/bin/ollama
  ✓ node on PATH at /opt/homebrew/bin/node
  ⚠ docker installed at /Applications/Docker.app but not launched
  ✓ python3 on PATH at /opt/homebrew/bin/python3
  ✓ venv exists at /Users/admin/gemma-forge/.venv
  ✓ python imports flask, flask_cors, yaml, requests, scrapling
  ✓ axoniq installed in venv
  ✓ scrapling browsers sentinel file present
  ✓ socraticode at /Users/admin/.gforge/tools/node_modules/.bin/socraticode
  ✓ skill staged: logo-generator
  ✓ skill staged: scrapling-official
  ✓ skill staged: ui-ux-pro-max
  ✓ skill staged: axon
  ✓ ollama version + tags → HTTP 200
  ✓ harness root + workspace status + events recent → HTTP 200
  ✓ pulled test model gemma3:1b
  ✓ created session session_1779473229378
  ✓ intake card finished — status: awaiting-human

  === ALL CHECKS PASSED ===
  ```

  **Notes on Docker.** Headless VM tests cannot launch Docker.app for
  kernel-extension approval, so the `docker` CLI isn't on PATH. The
  harness boots without it; only SocratiCode's Qdrant container needs
  Docker. Real reviewers on a desktop Mac will launch Docker.app once
  and the CLI joins PATH automatically.

- **2026-05-22 — Axon protocol skill added.**
  A sub-agent (general-purpose) scraped the upstream Axon repo
  (`https://github.com/harshkedia177/axon`) and built a protocol skill
  at `skills/axon/` mirroring the `scrapling-official` format.

  **Skill contents (76 KB, 11 files):**
  - `SKILL.md` — frontmatter (`name: axon`, version `1.0.1` verified
    against upstream `pyproject.toml`, MIT license, openclaw emoji 🧠,
    requires `python3` + (`pip` | `pip3`)). Body calls out the
    PyPI-package-name (`axoniq`) vs CLI-binary-name (`axon`) gotcha,
    Python 3.11+ requirement, supported languages
    (Python / TS / JS), three-step workflow, four worked examples.
  - `LICENSE.txt` — MIT, attributed to `harshkedia177` (no LICENSE file
    at the repo root upstream, but `pyproject.toml` declares MIT; the
    skill includes the canonical MIT text plus a footnote pointing to
    the upstream declaration).
  - `examples/` — `01_analyze_and_search.sh`, `02_mcp_tools_call.py`
    (Python MCP client over stdio), `03_cypher_query.sh`, plus a
    README explaining which example does what.
  - `references/` — five topical docs:
    - `commands.md` (~12 KB) — every CLI subcommand + every flag,
      pulled directly from `src/axon/cli.py` rather than the README
    - `mcp-server.md` (~12 KB) — all 15 MCP tools (the README
      advertises 7; the sub-agent verified there are actually 15 in
      `src/axon/mcp/server.py`)
    - `dashboard.md` (~8 KB) — the `axon ui` web dashboard
    - `graph-model.md` (~8 KB) — node/edge schema + the 12-phase
      indexing pipeline
    - `cypher-queries.md` (~8 KB) — ready-to-run Cypher patterns

  Skill is now bundled in `skills/`, staged by `launch_forge.command`
  on first run, and the verify script checks for it under
  `~/.gforge/harness/skills/axon`. Verified present in the clean-room
  VM test above.

- **2026-05-23 — Protocol-card status strip removed.**
  User requested removal of the load-time section showing
  "Start a project to run active cards." The exact element was
  `#plan-run-status` in `chat/templates/index.html`; `setPlanStatus()`
  in `chat/static/js/chat.js` already guards missing elements, so no
  broader JS refactor was needed.

  Backup:
  `/Users/webot/Backups/gemma-forge/20260523T160939Z-pre-remove-plan-status/`
  (`index.html`).

  Verified: `npm run check` passed; browser check on
  `http://127.0.0.1:5005/` confirmed `#plan-run-status` count `0` and
  the removed phrase no longer visible. Ian confirmed the section was
  removed with no negative outcome.

- **2026-05-23 — Auto intake running affordance fixed.**
  User reported the process behind intake worked and advanced correctly,
  but in auto mode the Project Context / intake card did not visually
  activate with the running border / `Running` state. Important user
  constraint: keep the separation between auto and manual.

  Fix:
  - `chat/static/js/chat.js`: added `runningCardId` and
    `setRunningCard(cardId)`. `renderWorkflowCards()` now applies
    `.running`, disables the running card button, and labels it
    `Running` when `runningCardId` matches.
  - `startPlanning()` primes only auto mode (`!humanVerify`) with
    `setRunningCard("intake")` while the initial `/api/plan` request is
    in flight.
  - `runCardSection()` now uses the same running-state helper for
    existing manual/section runs, preserving behavior while removing
    duplicate direct DOM toggles.
  - `chat/static/css/style.css`: `.workflow-card.running` and
    `.workflow-card.running .section-run-btn:disabled` now provide the
    stronger active border/glow and `Running` button treatment.

  Backup:
  `/Users/webot/Backups/gemma-forge/20260523T161535Z-pre-auto-intake-running/`
  (`chat.js`, `style.css`).

  Verified:
  - `npm run check` passed.
  - Controlled Playwright test with mocked `/api/sessions` and
    `/api/plan` confirmed auto mode: intake card class
    `workflow-card active running is-front`, button `Running`, disabled
    true, active border/glow applied.
  - Controlled Playwright test confirmed manual / Human Verify
    separation: intake card class `workflow-card active is-front`,
    button `Forge Section`, disabled false, `.running` count `0`.
  - Ian confirmed the fix is good.

- **2026-05-23 — State alignment pass.**
  Updated `.handoffs/CURRENT_STATE.md` and `project-map.md` to reflect
  the accepted current UI state and backup paths above. Backup:
  `/Users/webot/Backups/gemma-forge/20260523T163326Z-pre-state-align/`
  (`CURRENT_STATE.md`, `project-map.md`).

  Verification at alignment start: handoff directory present, PID file
  present (`92663`), Ollama up, harness root HTTP `200`. Latest
  `errors.jsonl` still contains the earlier `2026-05-23T03:40:24Z`
  Ollama timeout; no new UI-error entry was introduced by these fixes.

- **2026-05-23 — Protocol-card context visibility polish.**
  User asked what should live on protocol cards versus the Project
  Context log while the harness runs; some context was hard to see.

  Fix:
  - `chat/static/js/chat.js`: added compact run-fact extraction in
    `renderWorkflowCards()` so each card surfaces the relevant facts
    that apply to that card: Project Context contract fields,
    Forge Flow readiness fields, Execution validation/transport/files,
    tool status for SocratiCode/Axon, review status, research count,
    and artifact basename.
  - Raw `lastRun.details` still stays available on the matching card,
    but now behind a "Full section artifact" disclosure by default
    unless the card needs attention or is awaiting human verification.
  - `chat/static/css/style.css`: added readable fact tiles and expanded
    the Project Context log scroll area from 180 px to 320 px.

  Backup:
  `/Users/webot/Backups/gemma-forge/20260523T164725Z-pre-card-context-visibility/`
  (`chat.js`, `style.css`).

  Verified:
  - Entry state: `git status --short --branch` showed expected
    uncommitted current-state changes; harness root and Ollama both
    returned HTTP `200`; PID file was stale (`92663`), but port 5005
    was served by Python PID `56130`.
  - `npm run check` passed.
  - Browser desktop check on `http://127.0.0.1:5005/`: selected a live
    completed project, verified 45 fact tiles across 8 cards, 8
    collapsible artifact disclosures, zero disclosures open by default,
    Project Context log `max-height: 320px`, and no console errors.
  - Browser mobile check at 390 × 844: no horizontal overflow and no
    overflowing fact tiles.

- **2026-05-23 — External backup + GitHub alignment rule.**
  User clarified that "backup" means both an external-SSD full backup
  of the live local working state and GitHub aligned with the repo state
  needed for a fresh install from the repo URL.

  External backup:
  `/Volumes/PHIXERO/Backups/gemma-forge/20260523T172125Z-full-live-local-working-state/`

  Contents:
  - Folder copy at `repo/`.
  - Restore archive:
    `gemma-forge-full-live-local-working-state.tar.gz`
    (`872M`, SHA-256
    `a19e484d6878847884f5306bcffe3dba3f5e7a2f787415531e212d276ef96668`).
  - `MANIFEST.md`, `git-status.txt`, `git-diff-stat.txt`,
    `tracked-uncommitted.patch`, and `untracked-files.txt`.

  Rule recorded in `AGENTS.md`: do not call a full backup complete
  until the external SSD backup is verified and GitHub is either aligned
  to the installable repo state or the blocker is explicitly reported.
  GitHub should include launcher, harness code, docs, tests,
  clean-install tools, and bundled protocol skills. It must not include
  runtime/session/log/model/cache artifacts.

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

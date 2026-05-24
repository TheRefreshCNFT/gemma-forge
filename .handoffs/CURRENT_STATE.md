# CURRENT_STATE.md — Gemma Forge

Last updated: 2026-05-24 (UTC) — SSD backup and GitHub alignment.

## Verified ground truth

- Project root: `/Users/webot/Projects/gemma-forge`
- Branch: `main` tracking `origin/main`; current branch head is the
  installable repo state for this backup pass once pushed to GitHub.
  Runtime/generated/private harness state remains local/SSD-only.
- Harness Flask server source: `chat/server.py` (8,120 lines).
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

- Phase: **Parallel session isolation, bounded chat worker actions, cross-session save race fix, runtime repair, UI rolodex/session ordering, contest sidebar simplification, sidebar action stack, full-state backup/GitHub alignment, Hugging Face search picker, provisioning clarity guard, full Hugging Face-to-Ollama provisioning pipeline, small-model planning guard, failed-model cleanup, Forge Station terminal UI/session isolation fixes, default E4B Forge Brain switch, Anthropic PDF/MCP skills, workspace GitHub/exec capability alignment, workspace package install capability, and SSD/GitHub alignment completed.**
- User-verified current behavior:
  - The obsolete `plan-run-status` strip / text
    "Start a project to run active cards." is removed from the
    protocol-card header.
  - Auto mode keeps its separate flow and now visually activates the
    Project Context / intake card while intake is running: active
    border/glow plus disabled `Running` button.
  - Manual / Human Verify flow remains separate: cards still show
    `Forge Section` until manually run.
  - Rolodex-style protocol cards look and run correctly after the visual
    stack fix: rotating cards stay stacked slightly downward and no
    longer drift up into the Protocol cards header.
  - The project/session list on the left is ordered newest-first.
  - The contest sidebar no longer shows project-link checkboxes, Link
    projects, or Lock selected projects controls. Session names are the
    primary sidebar text, with Done/Active/Stopped/etc. shown smaller
    underneath each title.
  - Sidebar row actions are stacked with `X` over `A`/`R`, and session
    titles can show up to two lines before truncating.
  - Forge Station terminal text/scroll now reaches the bottom of the
    terminal panel again.
  - The obsolete "collapsed while you type" Start panel hint is removed.
  - Forge Station terminal output is separated per selected project
    again; switching sessions no longer shows the same global provisioning
    tail in every project.
- Locally verified current behavior:
  - Completed protocol cards show compact run facts on the card
    itself, e.g. Project Context shows format/path/count/skill/open
    questions/review/research.
  - Long raw card artifacts remain available but are collapsed behind
    a "Full section artifact" disclosure by default.
  - The right-side Project Context log keeps the chronological project
    feed and now has a taller scroll area.
  - Project Context skill selection now maps capability/task aliases
    such as `web_browse`, `web_fetch`, "live scraping", "news
    headlines", "crawl", and "extract web data" to the installed
    `scrapling-official` skill instead of treating `web_browse` as a
    missing skill. If the model writes `skill.use: none` but the user
    request clearly matches an installed skill, the deterministic
    matcher overrides the `none`.
  - The Forge Station terminal now emits `skill` events during skill
    selection and staging, e.g. `skill call selection:
    scrapling-official` and `skill call scrapling-official ->
    .gforge/skills/scrapling-official`.
  - User-stated content counts are now separated from deliverable file
    count. Example: `deliverable.count: 1` can still mean one HTML
    file, while `content_requirements` preserves "top 3 articles in
    each category" as a binding requirement inside that file.
  - Deterministic validation now fails when `deliverable.count > 1`
    but the model writes too few matching files, or when a text-like
    deliverable under-delivers extracted content counts such as
    articles, headlines, options, variants, cards, images, logos,
    sections, features, products, examples, slides, charts, or rows.
  - Skill staging now puts a concise "Skill Usage Plan" before long
    skill manuals. For scraping + page tasks, it tells the model:
    `scrapling-official` is the web scraping/extraction layer and
    `ui-ux-pro-max` is the webpage/interface design layer.
  - Skill selection only scans the original project text and user
    messages now. Prior agent messages / manifests no longer self-poison
    reruns into staging unrelated support skills like Axon/GSD/SocratiCode
    just because a previous agent mentioned them.
  - Failed-review execution retries now enter a generic "continuation
    repair mode." The retry prompt tells the model not to start over
    unless the human explicitly requested a restart, names the exact
    reviewer/validator blockers to fix, includes a bounded current-file
    snapshot from the workspace, and instructs it to repair/add only the
    needed complete files while finishing the rest of the original
    request for delivery.
  - Archived projects are now read-only at the API boundary. Session
    chat messages, card runs, checkpoint updates, and `/api/plan` calls
    return HTTP `409` before any model/tool call can run.
  - Browser-side Full Forge / Forge Section run state is now keyed per
    project record. Switching to another project no longer clears the
    first project's in-flight run controller, and stale async responses
    update their own project cache before repainting only if that project
    is still selected.
  - The bottom-right agent chat now receives staged skill context when
    the project has a workspace. It can emit one bounded
    `GFORGE_WORKER_ACTION` request for `full_forge` or a known protocol
    card; the browser then invokes the existing card/Full Forge flow
    rather than granting arbitrary tool execution inside chat.
  - The local harness server was restarted through the existing launchd
    keep-alive path so the backend worker-action route is live
    (latest restart old PID `49704`, new PID `63603` listening on
    `127.0.0.1:5005`).
  - `save_sessions()` now supports explicit `update_keys` so a long
    request only writes the project record it actually mutated. This
    prevents parallel card runs from rolling another project backward
    with an older in-memory snapshot.
  - User-observed incident from the parallel Just Art / Just Music run
    was confirmed: both jobs reached `handoff`, but the Just Art project
    record was rolled back by a concurrent save. The Just Art session
    (`session_1779570042369`) was repaired from its own
    `terminal-events.jsonl` and artifacts without rerunning Ollama; all
    cards now read `complete`.
  - Runtime project noise was cleared: all nine active demo/test project
    records from the current tuning runs were archived, and orphan
    `session-data` test artifact directories were moved out of live
    harness state into the pre-cleanup backup.
  - Protocol card rolodex layering now uses small positive Y offsets for
    both ahead/behind non-front cards, plus a little lower stack padding,
    so rotating through cards keeps the deck below the header.
  - Sidebar project groups sort by `createdAt` descending, with
    `updatedAt`, `archivedAt`, and `session_<timestamp>` id fallback for
    legacy records. Active and archived groups keep separate headings.
  - Link controls were technically wired to `/api/sessions/link`: the
    endpoint wrote bridge files, saved `bridges` metadata, and exposed
    that metadata to chat prompts. It was not part of the core Full
    Forge/card execution path, so the contest-facing UI and front-end
    link-mode flow were removed while keeping existing legacy records safe.
  - Sidebar assets now carry a small static version query and the browser
    uses same-origin `/api` so local host aliases do not keep stale UI code
    or cross-origin session fetches during contest demos.
  - Session row actions now render inside a single narrow action rail with
    delete above archive/restore, reclaiming horizontal space for the
    session title. Titles use a two-line clamp and keep the state label
    underneath.
  - Settings now includes a Hugging Face model search picker. Users can
    type a provider/keyword/repo such as `google`, `qwen`, or
    `google/gemma-4-E4B-it`, click Search, see five selectable pill
    choices, page through Next 5 / Previous 5, select a result to fill
    the Hugging Face repo and suggested Ollama model name, then click
    Provision model.
  - Provision model now revives the old model-forging behavior inside the
    harness: it starts a background job, downloads the selected Hugging
    Face repo into `~/.gforge/models`, uses a direct GGUF when available,
    otherwise converts HF weights with `convert_hf_to_gguf.py`, quantizes
    through `llama-quantize`, writes an Ollama Modelfile, runs
    `ollama create`, verifies the model appears in Ollama, and only then
    creates the optional project interface. The Settings status line
    polls job steps so the user can see inspect/download/convert/quantize/
    modelfile/import progress. Invalid provision requests no longer leave
    phantom queued model records.
  - Provisioning guard remains live after the `zaya1-8b` incident:
    queued/provisioning/failed/downloaded-only models are disabled in the
    Forge Brain pills and session creation/model updates/plan/card/chat/
    verify routes reject non-runnable models with a clear `409` instead
    of calling Ollama and producing 404s.
  - Small/tiny model incident diagnosed: `zaya1-8b` failed conversion
    because llama.cpp does not support `ZayaForCausalLM`. The direct GGUF
    `gemma-3-1b-it-glm-4.7-flash-heretic-uncensored-thinking` installed
    correctly, but a 1B "thinking" model stalled/parroted the large
    harness planning prompt. Two user sessions created with that model
    were switched back to `gemma-4` after backing up
    `~/.gforge/harness/sessions.json`. The `/api/plan` path now bounds
    planning output (`num_predict`) and applies a tighter budget for
    sub-1.5B models so initial planning finishes or surfaces transport
    failure instead of silently hanging.
  - User-requested cleanup is complete. The stalled custom 1B model was
    removed from Ollama, the Forge registry, local GGUF files, and its
    Modelfile. The failed `zaya1-8b` provisioning attempt was also
    removed from the registry and `~/.gforge/models`, its dedicated
    project interface was deleted, and the remaining gallery session was
    switched back to `gemma-4`. Read-back verification showed no zaya
    records in Ollama, registry, sessions, or the model download folder.
  - User verified after cleanup that all systems are working great.
    Current live probes before this final backup pass: harness `200` at
    `http://127.0.0.1:5005/`, Ollama `0.20.5`, harness PID `87360`,
    `~/.gforge/harness` about 37 MB, and `~/.gforge/models` about 4.6 GB.
  - Default first-run Forge Brain is now `gemma-4-e4b-it`, sourced from
    Gemma 4 E4B (`google/gemma-4-E4B-it`). Live read-back after restart:
    `/api/model/route` reports `defaultModel` and `recommendedModel` as
    `gemma-4-e4b-it`; `/api/workspace/status` reports the Gemma 4 E4B
    model option selected, recommended, supported, and installed.
  - Anthropic `pdf` and `mcp-builder` skills are bundled under `skills/`
    with expanded frontmatter keywords and role guidance so Project
    Context can assign them from PDF/form/OCR and MCP/server/tool-schema
    language. The upstream `mcp-builder` `reference/` folder is scanned
    during staged skill snippet assembly.
  - Harness capabilities now surface real `git_clone`, `github_auth`,
    and `shell_exec` when host tools are available. Git/GitHub repo URLs
    are cloned into workspace `references/repos/` using host `git`/`gh`;
    shell commands run only when the Project Context contract requires
    `shell_exec`, and only through the workspace sandbox. Clone/research/
    command claims still require on-disk evidence.
  - Workspace package installs are now allowed as a separate
    `install_package` capability when local package managers are
    available. The model can request project dependency installs through
    `npm`/`pnpm`/`yarn` or `pip`; `pip` installs are automatically
    targeted under workspace `.gforge-installs/python` unless a safe
    relative target was supplied. Deploy, publish, push, system/global
    installs, path escapes, shell metacharacters, and reserved `.gforge/`
    writes remain blocked. Install claims require recorded command-run
    evidence.
  - Live harness restart after the install-capability change is clean:
    launchd reports PID `60777`, harness root returns `200`, and
    `/api/workspace/status` returns `200`.
- Latest files touched for this accepted state:
  `chat/server.py`, `chat/tool_workspace.py`, `chat/workspace_scan.py`,
  `chat/templates/index.html`, `tests/model_route_test.py`,
  `tests/integration_test.py`, `README.md`, `SKILL.md`, `CONTEXT.md`,
  `PROJECT_PLAN.md`, `SUBMISSION_DRAFT.md`, `forge.md`,
  `docs/model-routing-proof.md`, `docs/harness-agent-operating-guide.md`,
  `docs/submission-media/demo-recording-guide.md`, `launch_forge.command`,
  `.handoffs/CURRENT_STATE.md`, `project-map.md`, `skills/pdf/`,
  `skills/mcp-builder/`.
- GitHub alignment note: the latest installable repo state on `main`
  contains the chat worker-action, per-session runner isolation,
  cross-session save race tests, and docs. Runtime/generated/private
  state remains excluded from GitHub and preserved in SSD/local backups.
- Latest backup locations:
  - `/Volumes/PHIXERO/Backups/gemma-forge/20260524T024959Z-full-live-local-working-state/` (verified full live local working state with restore archive; checksum passed; includes repo, harness runtime, and model cache)
  - `/Users/webot/Backups/gemma-forge/20260524T023601Z-pre-workspace-installs/`
  - `/Users/webot/Backups/gemma-forge/20260524T021610Z-pre-anthropic-skills/`
  - `/Users/webot/Backups/gemma-forge/20260524T013408Z-pre-default-e4b-handoff/`
  - `/Users/webot/Backups/gemma-forge/20260524T013004Z-pre-default-e4b-ui-docs/`
  - `/Users/webot/Backups/gemma-forge/20260524T012836Z-pre-default-e4b/`
  - `/Volumes/PHIXERO/Backups/gemma-forge/20260524T011953Z-full-live-local-working-state/` (verified live repo + harness runtime backup with restore archive; checksum passed; model cache intentionally excluded per user instruction)
  - `/Volumes/PHIXERO/Backups/gemma-forge/20260524T004319Z-full-live-local-working-state/` (this final verified full live local working state backup with restore archive; checksum passed)
  - `/Users/webot/Backups/gemma-forge/20260524T003119Z-pre-kill-zaya/`
  - `/Users/webot/Backups/gemma-forge/20260524T003040Z-pre-delete-zaya-failed-download/`
  - `/Users/webot/Backups/gemma-forge/20260524T002946Z-pre-delete-1b-model/`
  - `/Users/webot/Backups/gemma-forge/20260524T002708Z-sessions-before-switch-from-1b.json`
  - `/Users/webot/Backups/gemma-forge/20260524T002518Z-pre-small-model-planning-guard/`
  - `/Users/webot/Backups/gemma-forge/20260523T234353Z-pre-full-provision-pipeline/`
  - `/Users/webot/Backups/gemma-forge/20260523T233222Z-pre-provision-clarity-guard/`
  - `/Users/webot/Backups/gemma-forge/20260523T231310Z-pre-hf-search-picker/`
  - `/Volumes/PHIXERO/Backups/gemma-forge/20260523T224225Z-full-live-local-working-state/` (verified full live local working state with restore archive; checksum passed)
  - `/Users/webot/Backups/gemma-forge/20260523T223722Z-pre-sidebar-action-stack/`
  - `/Users/webot/Backups/gemma-forge/20260523T222213Z-pre-sidebar-session-simplify/`
  - `/Volumes/PHIXERO/Backups/gemma-forge/20260523T221207Z-full-live-local-working-state/` (verified full live local working state with restore archive; checksum passed)
  - `/Users/webot/Backups/gemma-forge/20260523T215326Z-pre-ui-rolodex-session-order/`
  - `/Volumes/PHIXERO/Backups/gemma-forge/20260523T214346Z-full-live-local-working-state/` (verified full live local working state with restore archive; checksum passed)
  - `/Users/webot/Backups/gemma-forge/20260523T-skill-guidance-pre/`
  - `/Users/webot/Backups/gemma-forge/20260523T-continuation-repair-pre/`
  - `/Users/webot/Backups/gemma-forge/20260523T204408Z-pre-session-run-controllers/`
  - `/Users/webot/Backups/gemma-forge/20260523T211344Z-pre-save-session-race/`
  - `/Users/webot/Backups/gemma-forge/20260523T211600Z-pre-runtime-session-state-repair/`
  - `/Users/webot/Backups/gemma-forge/20260523T194941Z-pre-noise-cleanup/`
  - `/Volumes/PHIXERO/Backups/gemma-forge/20260523T195311Z-full-live-local-working-state/` (verified full live local working state with restore archive)
  - `/Users/webot/Backups/gemma-forge/20260523T-content-counts-pre/`
  - `/Users/webot/Backups/gemma-forge/20260523T175448Z-pre-skill-assigner/`
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
- Demo model decision: `gemma-4-e4b-it` (E4B, installed local alias; official Ollama tag is `gemma4:e4b`).

## Shipped this session

- **2026-05-24 — SSD backup and GitHub alignment.**
  Full live local working state was backed up to external SSD at
  `/Volumes/PHIXERO/Backups/gemma-forge/20260524T024959Z-full-live-local-working-state/`.
  The backup includes the repo snapshot, ignored repo/runtime files,
  `~/.gforge/harness`, `~/.gforge/models`, metadata snapshots, and a
  `restore-archive.tar.gz`; checksum verification passed. GitHub
  alignment for the installable repo state was requested in the same
  pass; runtime/private data remains excluded from the repo.

- **2026-05-24 — Workspace package installs enabled.**
  Allowed bounded project dependency installs as a real
  `install_package` capability while keeping deploy/publish/push and
  system/global package installs forbidden. `chat/tool_workspace.py`
  now recognizes `npm`/`pnpm`/`yarn` project installs and `pip`/`python
  -m pip install`; pip installs default to
  `.gforge-installs/python`, with package caches and temp files kept
  under the workspace. Sandbox execution now grants outbound network only
  for recognized package install commands and still blocks absolute
  paths, parent traversal, shell metacharacters, multiline shell, writes
  to reserved `.gforge/`, and credential/deploy operations.
  `chat/server.py` exposes the capability to Project Context, adds broad
  install keywords for deterministic assignment, keeps
  `system_package_install` in CANNOT, and requires recorded command-run
  evidence before accepting install claims. Verification:
  py_compile for `chat/server.py` and `chat/tool_workspace.py`;
  `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
  (60 tests); `npm run check`; `git diff --check`; sandbox smoke for
  `python3 check.py`; local package install smoke via `pip install
  ./localpkg` into `.gforge-installs/python`; live launchd restart to
  PID `60777`; live harness root and `/api/workspace/status` probes
  returned `200`.

- **2026-05-24 — Anthropic PDF/MCP skills and workspace GitHub/exec.**
  Added Anthropic's `pdf` and `mcp-builder` skill bundles under repo
  `skills/`, preserving licenses, scripts, and references, then staged
  both into `~/.gforge/harness/skills/` without overwriting existing
  skills. Expanded skill keywords/aliases and role guidance so Project
  Context can select PDF/form/OCR tasks and MCP/server/tool-schema tasks.
  Added `chat/tool_workspace.py` plus server integration so `git_clone`
  and `github_auth` are real when host `git`/`gh` are available, cloning
  repo references into workspace `references/repos/`; `shell_exec` is
  real only through a workspace sandbox and only when the contract
  requires it. Claim validation now still requires evidence for clone,
  research, skill-author, and command claims even when the capability is
  available. Verification: `npm run check`; py_compile for
  `chat/server.py` and `chat/tool_workspace.py`;
  `unittest tests.model_route_test` (56 tests); `git diff --check`; live harness
  restart through launchd to PID `46878`; live harness probe `200`;
  skill discovery reports `pdf` and `mcp-builder` from
  `~/.gforge/harness/skills/`.

- **2026-05-24 — Default Forge Brain switched to Gemma 4 E4B.**
  Changed the first-run/default model route from the E2B alias
  `gemma-4` to the installed E4B alias `gemma-4-e4b-it`, updated the
  workspace scan recommended model option to `google/gemma-4-E4B-it`,
  updated Settings placeholders and model-route docs, and kept legacy
  `gemma-4` tests/paths where they intentionally cover existing-session
  behavior. Verification: `npm run check`;
  `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
  (50 tests); `git diff --check`; live harness restart through launchd
  to PID `3991`; live harness probe `200`; `/api/model/route` reports
  `defaultModel=gemma-4-e4b-it`; `/api/workspace/status` reports Gemma
  4 E4B selected/recommended/supported/installed.

- **2026-05-24 — Forge Station terminal visual/session fix and alignment.**
  Removed the stream height cap so Forge Station terminal text and scroll
  reach the bottom of the panel, removed the obsolete Start panel
  "collapsed while you type" pseudo-text, and restored per-session
  terminal isolation by excluding global harness events from selected
  project feeds. Added a regression test proving selected session feeds
  exclude global and other-session events. Verification: `npm run check`;
  `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
  (50 tests); `git diff --check`; live harness restart to PID `87360`;
  live harness probe `200`; user click-through confirmation that session
  switching is good.

- **2026-05-24 — Failed model cleanup and final alignment pass.**
  Removed the custom 1B thinking model after it proved unsuitable for
  harness planning, removed the failed `zaya1-8b` provision attempt,
  cleaned the related registry/download/session records, and switched
  affected sessions back to `gemma-4`. Final verification before backup:
  `npm run check`; `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
  (49 tests); `git diff --check`; live harness probe `200`; Ollama
  version `0.20.5`; model list read-back confirms no custom 1B model or
  zaya model remains installed.

- **2026-05-24 — Small-model planning guard after 1B model stall.**
  Diagnosis: the small direct-GGUF model
  `gemma-3-1b-it-glm-4.7-flash-heretic-uncensored-thinking` installed
  and answered a tiny `OK` prompt, but the two newest projects had only
  logged an Ollama call and never reached `card-start`; the model was
  stuck on the initial planning prompt. A bounded live probe returned in
  8s but mostly echoed the harness prompt, confirming it is not suitable
  for full harness work. Fix: `/api/plan` now uses
  `call_ollama_with_transport` with bounded planning `num_predict`, a
  tighter sub-1.5B budget, and explicit transport-failure text when the
  model returns nothing. The two affected sessions
  (`session_1779581904555`, `session_1779581722282`) were backed up and
  switched to `gemma-4`. Verification: `npm run check`;
  `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
  (49 tests); harness restarted to PID `40762`; live 1B plan probe
  returns instead of hanging; live `gemma-4` plan probe returns a concise
  useful response.

- **2026-05-23 — Full Hugging Face provisioning restored in harness.**
  Restored the old `src/app.py` functionality behind the Settings
  Provision model button: selected Hugging Face repos now download into
  `~/.gforge/models`, direct GGUF repos are imported without conversion,
  raw HF repos convert with llama.cpp, quantize to `Q4_K_M`, write an
  Ollama Modelfile, run `ollama create`, verify the model appears in
  Ollama, and then create the optional project interface. Added a
  background provision job/status API and front-end polling so users see
  each stage instead of an ambiguous terminal-only action. Validation now
  rejects missing repo/model-name errors without writing phantom registry
  entries. Verification: `npm run check`;
  `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
  (47 tests); live harness restart to PID `15283`; live search
  `GET /api/models/search?q=qwen&offset=0` returns five results with
  paging; live installed-model provision for `gemma-4` returns skipped/
  runnable; live missing-repo provision returns 400 and does not write a
  registry entry; curl read-back confirms the new Provision model wording
  and cache-busted assets.

- **2026-05-23 — Provisioning clarity guard after `zaya1-8b`.**
  Diagnosis: `zaya1-8b` was registered in
  `~/.gforge/harness/models.json` as queued from `Zyphra/ZAYA1-8B`, but
  Ollama did not have that model installed. The old UI created project
  records using the queued model, so `/api/chat` calls hit Ollama 404
  (`model 'zaya1-8b' not found`). Guard fix: queued/provisioning/
  downloaded-only/failed model pills are disabled and labelled not
  installed or provisioning, project-interface creation waits until
  Ollama can run the model, and session creation/model updates/plan/card/
  chat/verify routes reject non-runnable models with a clear 409.
  Verification:
  `npm run check`; `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
  (44 tests); live `POST /api/sessions` with `zaya1-8b` returns 409;
  browser/API read-back showed disabled `zaya1-8b` pills and clear
  provisioning guidance.

- **2026-05-23 — Hugging Face search picker for Settings.**
  Added `/api/models/search` with five-result paging, exact
  provider/model matching, repo normalization for pasted `hf.co` /
  `huggingface.co` URLs, suggested Ollama aliases, and installed-state
  hints. Settings now has a Search button, five selectable result pills,
  and Next 5 / Previous 5 controls. Selecting a pill fills the Hugging
  Face repo and Ollama model-name fields before the existing provision
  action. Also fixed the model registry refresh path so the current pill
  UI updates without relying on the removed legacy select.
  Verification: `npm run check`; `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
  (42 tests); live `GET /api/models/search?q=qwen&offset=0`;
  live `GET /api/models/search?q=google/gemma-4-E2B-it&offset=0`;
  browser verification on `http://127.0.0.1:5005/` for search,
  selection, Next 5, and Previous 5.

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
    `review` parameter to `execute_model_authored_project`, which now
    renders continuation repair guidance.
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

- **2026-05-23 — Project Context skill assigner hardened.**
  User reported the live-scraping flow where Project Context named
  `web_browse` or skipped the `scrapling-official` skill, causing the
  next agent to say live scraping was impossible and pivot to mock data.

  Fix:
  - `chat/server.py`: skill discovery now reads `description` and
    `keywords` from both `SKILL.md` frontmatter and `skill.json`.
  - Added deterministic alias matching for bundled protocol skills.
    `scrapling-official` now matches many task/capability values:
    `web_browse`, `web_fetch`, live scraping/news/headlines, scrape,
    crawl, extract web data, CSS selector/XPath, dynamic sites,
    Cloudflare/Turnstile, browser fetch, and related research phrases.
  - `resolve_skill_selection()` now canonicalizes capability aliases to
    real installed skill keys and no longer lets `skill.use: none`
    suppress an obvious deterministic match from the user's request.
  - `enrich_project_context()` rewrites the saved YAML contract so
    `skill.use` becomes the real skill key, e.g. `scrapling-official`,
    with staged path `.gforge/skills/scrapling-official`.
  - Skill selection/staging emits Forge Station terminal events with
    kind `skill`; CSS gives those events a distinct color.
  - Added focused unit coverage for `web_browse` alias resolution and
    `none` override on live-scraping/news requests.

  Backup:
  `/Users/webot/Backups/gemma-forge/20260523T175448Z-pre-skill-assigner/`
  (`chat/server.py`, `.handoffs/CURRENT_STATE.md`, `project-map.md`).

  Verified:
  - `npm run check` passed.
  - Focused unittest via harness venv passed:
    `test_skill_alias_resolves_web_browse_to_scrapling` and
    `test_skill_none_is_overridden_by_scraping_request_keywords`.
  - Selector smoke test with installed skills proved:
    `skill.use: none` + "live scraping of article headlines" →
    `scrapling-official`; `skill.use: web_browse` →
    `scrapling-official`; parsed Project Context YAML rewrites
    `skill.use` to `scrapling-official` and adds `web_browse` to
    `capabilities_required`.
  - Full `tests.model_route_test` still has pre-existing failures
    unrelated to this selector patch (`call_ollama_execution_payload`
    mocks returning two values where current code expects three, plus
    older session endpoint 404 expectations). Do not treat the full
    file as green until those tests are modernized.
  - Local harness restarted: old listener PID `56130` replaced by
    Python PID `92167`; `GET /` returned HTTP `200`;
    `/api/events/recent` returned successfully; workspace status
    responded; no new error-log entry was added.

- **2026-05-23 — Content count requirements enforced.**
  User reported that agents routinely produce "1 of everything" even
  when the request names a count.

  Fix:
  - `chat/server.py`: Project Context prompt now explicitly separates
    `deliverable.count` (file count) from repeated content-item counts
    inside a deliverable.
  - Added deterministic extraction of count phrases from the raw user
    request, e.g. "top 3 articles in each category" and "three design
    options". Extracted requirements are written to
    `content_requirements`, added to `constraints.hard_requirements`,
    and mirrored into `acceptance`.
  - Execution prompt now renders a binding "CONTENT QUANTITY
    REQUIREMENTS" block so the model sees the count as a deliverable
    requirement, not as optional prose.
  - Validation now enforces two count paths:
    1. `deliverable.count > 1` must produce at least that many matching
       files for the contracted format/path pattern.
    2. Text-like deliverables are scanned for repeated content units
       such as articles/headlines/stories, options/variants/concepts,
       cards/items/features/products/examples, images/screenshots,
       logos/icons, sections/categories, slides/charts/tables/rows.
       Runs fail when deterministic validation finds fewer units than
       the extracted count.
  - Execution reports now include a "Content Quantity Checks" section.
  - Added focused tests for extraction, Project Context enrichment,
    under-delivered content counts, and under-delivered file counts.

  Backup:
  `/Users/webot/Backups/gemma-forge/20260523T-content-counts-pre/`
  (`chat/server.py`, `chat/static/css/style.css`,
  `tests/model_route_test.py`, `.handoffs/CURRENT_STATE.md`,
  `project-map.md`).

  Verified:
  - `npm run check` passed.
  - `git diff --check` passed.
  - Focused unittest via harness venv passed:
    `test_detects_content_quantity_requirement_from_news_prompt`,
    `test_project_context_enriches_content_quantity_requirements`,
    `test_validation_fails_when_content_quantity_is_under_delivered`,
    `test_validation_fails_when_deliverable_file_count_is_under_delivered`.
  - Direct smoke confirmed `deliverable.count` remained `1` for a
    single HTML file while `content_requirements` preserved count `3`
    for `articles` scoped to `in each category`, and acceptance gained
    the deterministic count check.
  - Local harness restarted: old listener PID `92167` replaced by
    Python PID `18003`; `GET /` returned HTTP `200`;
    `/api/events/recent` returned successfully; no new error-log entry
    was added.

- **2026-05-23 — Skill usage guidance added before staged manuals.**
  User clarified the problem was not only too many skills, but skills
  dumped into the prompt without direction. The execution agent still
  behaved as if it did not understand which tool/skill applied to which
  part of the task.

  Fix:
  - `chat/server.py`: `build_skill_context_prompt()` now prepends a
    concise "Skill Usage Plan" before the raw staged skill manuals.
  - The plan assigns explicit roles:
    - `scrapling-official` → web scraping and extraction. Use for
      scrape/crawl/browse/fetch/live page research/headlines/articles;
      treat harness-fetched `research/*.md` artifacts as available
      source material and do not say live scraping is impossible when
      `web_browse`/`web_fetch` is available or research artifacts are
      listed.
    - `ui-ux-pro-max` → webpage and interface design. Use for webpage,
      landing page, dashboard, responsive design, typography, color,
      spacing, visual hierarchy, and accessibility; apply it directly
      in HTML/CSS/JS rather than producing a plan.
  - Expanded `ui-ux-pro-max` aliases to catch webpage/page requests
    phrased as responsive, across devices, present nicely, or modern
    page/webpage.
  - `session_skill_text()` now ignores prior agent messages and scans
    only original project text plus user messages. This prevents reruns
    from self-poisoning by selecting Axon/GSD/SocratiCode merely
    because a previous agent response or manifest mentioned them.
  - `skill_plan` is now added to the Project Context YAML so the
    Execution card sees role guidance in the binding contract as well
    as in the staged skill block.

  Backup:
  `/Users/webot/Backups/gemma-forge/20260523T-skill-guidance-pre/`
  (`chat/server.py`, `tests/model_route_test.py`,
  `.handoffs/CURRENT_STATE.md`, `project-map.md`).

  Verified:
  - Direct resolver smoke on the Yahoo/news/page session now selects
    `['scrapling-official', 'ui-ux-pro-max']` instead of
    `['scrapling-official', 'axon', 'gsd', 'socraticode',
    'ui-ux-pro-max']`.
  - Prompt smoke confirmed "Skill Usage Plan" appears before "Staged
    skills" and includes the explicit Scrapling + UI/UX roles.
  - Focused unittest via harness venv passed:
    `test_skill_selection_ignores_prior_agent_skill_manifests`,
    `test_skill_context_prompt_gives_usage_plan_before_manuals`,
    plus the existing scrapling alias tests.
  - `npm run check` passed.
  - `git diff --check` passed.
  - Local harness restarted: old listener PID `18003` replaced by
    Python PID `30973`; `GET /` returned HTTP `200`; no new error-log
    entry was added.

- **2026-05-23 — Failed execution retries now continue from current work.**
  User reported that after a first failure, agents should be guided to
  fix the specific blockers and finish the remaining delivery instead
  of starting over. This should be generic for any project; a restart is
  only valid when the human explicitly asks for one.

  Fix:
  - `chat/server.py`: `build_model_execution_prompt()` now renders a
    "CONTINUATION REPAIR MODE" block whenever a failed review/correction
    is passed into Project Execution.
  - Added a bounded current-file snapshot for repair prompts. It
    prioritizes `artifacts/validation.json`,
    `artifacts/model-execution.json`, and contract-relevant files, then
    includes readable workspace files while skipping reserved/runtime
    folders such as `.gforge/`, `.git/`, caches, venvs, and
    `node_modules/`.
  - The repair prompt now tells the model to preserve useful existing
    work, fix the exact reviewer/validator/human blockers, re-emit
    complete file blocks only for files that need repair or creation,
    and complete the rest of the original request for delivery.
  - Post-review repair summary/action text now says "continuation
    repair" instead of implying a full rerun.

  Backup:
  `/Users/webot/Backups/gemma-forge/20260523T-continuation-repair-pre/`
  (`chat/server.py`, `tests/model_route_test.py`,
  `.handoffs/CURRENT_STATE.md`, `project-map.md`).

  Verified:
  - Killed the prior harness listener PID `30973` at Ian's request to
    abort any in-flight task; launchd respawned PID `44290`, and `GET /`
    returned HTTP `200`.
  - After the code patch, restarted the harness again so live code loaded:
    listener PID `44290` replaced by PID `47697`; `GET /` returned HTTP
    `200`. Recent error-log tail only showed older entries.
  - Focused unittest via harness venv passed:
    `test_repair_prompt_continues_from_existing_workspace_snapshot`,
    `test_initial_execution_prompt_omits_repair_mode`, and
    `test_failed_review_can_be_repaired_before_completion`.
  - Direct smoke confirmed the retry prompt includes
    "CONTINUATION REPAIR MODE", "Do not start over", the current
    `output/index.html` snippet, and the validator failure text.
  - `npm run check` passed.
  - `git diff --check` passed.
  - At this point, full `tests.model_route_test` still had unrelated
    pre-existing drift. That was cleared in the later noise-cleanup pass
    below.

- **2026-05-23 — Runtime noise cleared and archived calls blocked.**
  User asked to clear noisy unused test items or stop them from making
  calls, then back up the current version.

  Fix:
  - `chat/server.py`: archived projects are now read-only for routes
    that can change state or call the model. `/messages`, card `/run`,
    card `/verify`, and `/api/plan` return HTTP `409` before model/tool
    work can start.
  - `tests/model_route_test.py`: stale route/execution tests were
    modernized so they use `save_sessions(..., create_keys={...})`,
    mock the current three-value execution helper, and patch
    `call_ollama_with_transport` for Forge file-block parsing. This
    stops tests from accidentally making live Ollama calls.
  - Added explicit regression tests proving archived session messages,
    card runs, and planning requests do not call the model.
  - Runtime cleanup: archived all nine active demo/test project records
    in `~/.gforge/harness/sessions.json`, including the heavy
    `gemma4:31b-max` Yahoo scrape run; moved orphan test artifact dirs
    `axon-real-test`, `socraticode-real-test`, and
    `session_1779475916178` into the pre-cleanup backup.

  Backup:
  `/Users/webot/Backups/gemma-forge/20260523T194941Z-pre-noise-cleanup/`
  contains the pre-edit source files, pre-cleanup `sessions.json`, and
  the moved orphan test artifact directories.

  Verified:
  - Full route suite now passes: `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`.
  - `npm run check` passed.
  - `git diff --check` passed.
  - Live harness restarted: old listener PID `47697` replaced by PID
    `93316`; `GET /` returned HTTP `200`.
  - Live archived-guard smoke confirmed archived `/messages`, card
    `/run`, and `/api/plan` return "Archived projects are read-only"
    without creating new Ollama error-log entries.
  - Active session list is empty after cleanup; archived sessions remain
    restorable under Archived.

- **2026-05-23 — Agent chat worker handoff + per-session run controllers.**
  User asked to confirm the bottom-right agent chat is skill/tool aware,
  align it so chat can trigger worker flow runs through staged skills,
  and make parallel sessions independent when switching between them.

  Fix:
  - `chat/static/js/chat.js`: Full Forge / Forge Section run controllers
    and stale-response guards are now scoped by project id instead of one
    global browser controller. A response from one project updates that
    project's cached record, and only repaints the visible cards/messages
    if the project is still selected.
  - `chat/server.py`: project chat now stages selected skill context when
    a workspace exists, then parses one bounded `GFORGE_WORKER_ACTION`
    block from the chat reply. Accepted actions are `full_forge` or a
    known protocol card id only; unknown card ids and malformed actions
    are ignored.
  - The browser converts an accepted worker action into the existing
    card/Full Forge runner flow, so chat can ask the worker to continue
    without receiving arbitrary direct tool execution.

  Verified:
  - Focused unit coverage added for worker-action parsing, chat route
    response shaping, and invalid worker-action rejection.
  - User live-tested two sessions in parallel and reported they ran
    independently and completed the requested jobs.

- **2026-05-23 — Cross-session save race fixed and runtime state repaired.**
  User reported one of two parallel runs did the work successfully but
  did not finish the visible verification/status process.

  Root cause:
  - `save_sessions()` merged the caller's entire in-memory session
    snapshot. A long request could save its own completed project while
    also writing an older copy of another concurrently running project,
    rolling that other project record backward.

  Fix:
  - `chat/server.py`: `save_sessions()` now accepts explicit
    `update_keys`, matching the existing `create_keys` discipline.
    Mutating routes pass the project ids they actually changed instead
    of writing a stale whole-file snapshot.
  - Added regression coverage proving one session update cannot roll
    back another parallel session's newer card state.
  - Runtime repair: `session_1779570042369` was restored from its own
    `terminal-events.jsonl` and artifacts without rerunning Ollama. The
    Just Art and Just Music projects now both show all cards complete.

  Backups:
  - `/Users/webot/Backups/gemma-forge/20260523T204408Z-pre-session-run-controllers/`
  - `/Users/webot/Backups/gemma-forge/20260523T211344Z-pre-save-session-race/`
  - `/Users/webot/Backups/gemma-forge/20260523T211600Z-pre-runtime-session-state-repair/`

  Verified:
  - `/Users/webot/Projects/gguf/venv/bin/python -m unittest tests.model_route_test`
    passed.
  - `npm run check` passed.
  - Live harness restarted through launchd and responded on
    `http://127.0.0.1:5005/`.

- **2026-05-23 — Full live-state SSD backup + GitHub alignment.**
  User asked to fully back up the smooth current state to SSD and
  GitHub.

  Backup:
  `/Volumes/PHIXERO/Backups/gemma-forge/20260523T214346Z-full-live-local-working-state/`
  contains the live repo working tree, the live `~/.gforge/harness`
  runtime state, `BACKUP_MANIFEST.txt`, `restore-archive.tar.gz`, and
  `restore-archive.tar.gz.sha256`.

  Verified:
  - External SSD `/Volumes/PHIXERO` was mounted and writable.
  - The restore archive checksum passed with `/usr/bin/shasum -a 256 -c`.
  - The archive opened with `tar -tzf`.
  - Key copied files were present in the backup, including
    `repo/chat/server.py`, `repo/chat/static/js/chat.js`,
    `repo/tests/model_route_test.py`, `gforge-harness/sessions.json`,
    and the repaired Just Art terminal log.
  - Backup size: about 10G.
  - GitHub alignment excludes local-only runtime data such as `.gforge/`,
    `.axon/`, `chat/session-data/`, chat runtime JSON, caches, and
    machine artifacts.

- **2026-05-23 — Rolodex/session-order UI backup + GitHub alignment.**
  User verified the interface was "looking and running perfect" after
  the two visual fixes and asked for full SSD + GitHub backup.

  UI changes:
  - `chat/static/css/style.css`: protocol-card rolodex stack now uses
    small downward offsets for ahead/behind cards and keeps extra lower
    stack padding so rotation stays below the Protocol cards header.
  - `chat/static/js/chat.js`: project groups sort newest-first by
    `createdAt`, with `updatedAt`, `archivedAt`, and `session_<timestamp>`
    fallback for older records.
  - `project-map.md` and this handoff now record the accepted behavior.

  Backup:
  `/Volumes/PHIXERO/Backups/gemma-forge/20260523T221207Z-full-live-local-working-state/`
  contains the live repo working tree, the live `~/.gforge/harness`
  runtime state, `BACKUP_MANIFEST.txt`, `restore-archive.tar.gz`, and
  `restore-archive.tar.gz.sha256`.

  Verified:
  - Entry checks: branch `main`, harness HTTP `200`, Ollama up, and
    PHIXERO mounted/writable.
  - `npm run check` passed.
  - `git diff --check` passed.
  - Browser check on `http://127.0.0.1:5005/`: after rotating to
    card `3 / 8`, `overlapsHeader` was false and the active sidebar
    order matched `/api/sessions` newest-first.
  - The restore archive checksum passed with `/usr/bin/shasum -a 256 -c`.
  - The archive opened with `tar -tzf`.
  - Key copied files were present in the backup, including
    `repo/chat/static/css/style.css`, `repo/chat/static/js/chat.js`,
    `repo/.handoffs/CURRENT_STATE.md`, `repo/project-map.md`, and
    `gforge-harness/sessions.json`.
  - GitHub alignment excludes local-only runtime data such as `.gforge/`,
    `.axon/`, `chat/session-data/`, chat runtime JSON, caches, and
    machine artifacts.

- **2026-05-23 — Contest sidebar simplification.**
  User asked for the session sidebar to remove project-link checkboxes,
  remove Link projects / Lock selected projects controls, and make
  project names visually primary with the state shown smaller underneath.

  Notes:
  - The link flow was partially wired: front-end link mode posted selected
    project ids to `/api/sessions/link`; the server wrote bridge files,
    saved `bridges` metadata, and included it in chat prompts. It was not
    part of the Full Forge/card execution path and was removed from the
    contest-facing sidebar UI/front-end flow.
  - `chat/templates/index.html`: removed the Link projects and Lock
    selected projects buttons; added static asset version queries for the
    refreshed sidebar CSS/JS.
  - `chat/static/js/chat.js`: removed link-mode state, session checkbox
    rendering, lock action handler, and link button event listeners; switched
    `API_URL` to same-origin `/api`.
  - `chat/static/css/style.css`: removed session checkbox/link-button
    styling and changed session rows so title is primary with the state
    label below it.
  - `PROJECT_PLAN.md`, `project-map.md`, and this handoff record the
    accepted contest UI state.

  Verification:
  - Pre-edit backup:
    `/Users/webot/Backups/gemma-forge/20260523T222213Z-pre-sidebar-session-simplify/`
    (hashes matched originals).
  - `npm run check` passed.
  - `git diff --check` passed.
  - Front-end identifier scan confirmed no remaining link/lock/sidebar
    checkbox references in `chat/static/js/chat.js`,
    `chat/templates/index.html`, or `chat/static/css/style.css`.
  - Browser verification on `http://127.0.0.1:5005/`: 4 session rows
    rendered; Link button count `0`; Lock button count `0`; session
    checkbox count `0`; state label below title `true`; sidebar horizontal
    overflow `false`; no console errors. Screenshot:
    `/tmp/gemma-forge-sidebar-simplify-inapp-20260523T222213Z.png`.

- **2026-05-23 — Sidebar action stack touch-up.**
  User confirmed the sidebar simplification looked great and asked to
  stack the row actions with `X` over `A`, letting session info use the
  freed-up width and show a little more.

  Changes:
  - `chat/static/js/chat.js`: session row actions now render in
    `.session-row-actions`, with delete (`X`) above archive/restore
    (`A`/`R`).
  - `chat/static/css/style.css`: session rows now have one content column
    plus a 28px action rail, two-line clamped session titles, and no
    horizontal overflow.
  - `chat/templates/index.html`: asset version bumped so the refreshed
    sidebar CSS/JS loads in the demo browser.
  - `project-map.md` and this handoff record the accepted sidebar shape.

  Verification:
  - Pre-edit backup:
    `/Users/webot/Backups/gemma-forge/20260523T223722Z-pre-sidebar-action-stack/`
    (hashes matched originals).
  - `npm run check` passed.
  - `git diff --check` passed.
  - Browser verification on `http://127.0.0.1:5005/`: 4 session rows
    rendered; first row action texts were `["X", "A"]`; one action column;
    state label below title `true`; two-line title height observed; sidebar
    horizontal overflow `false`; no console errors. Screenshot:
    `/tmp/gemma-forge-sidebar-action-stack-inapp-20260523T223722Z.png`.

- **2026-05-23 — Full live-state SSD backup + GitHub alignment for sidebar action stack.**
  User confirmed the final sidebar action stack looked amazing and asked
  to back up the full state to SSD and align the live working version to
  GitHub.

  Backup:
  `/Volumes/PHIXERO/Backups/gemma-forge/20260523T224225Z-full-live-local-working-state/`
  contains the live repo working tree, the live `~/.gforge/harness`
  runtime state, `BACKUP_MANIFEST.txt`, `restore-archive.tar.gz`, and
  `restore-archive.tar.gz.sha256`.

  Verified:
  - Entry checks: branch `main`, harness HTTP `200`, Ollama up, PHIXERO
    mounted/writable, and GitHub CLI authenticated as `TheRefreshCNFT`.
  - `npm run check` passed.
  - `git diff --check` passed.
  - Browser verification from the previous accepted pass remains the
    visual proof for this state:
    `/tmp/gemma-forge-sidebar-action-stack-inapp-20260523T223722Z.png`.
  - The restore archive checksum passed with `/usr/bin/shasum -a 256 -c`.
  - The archive opened with `tar -tzf`.
  - Key copied files were present in the backup, including
    `repo/chat/static/css/style.css`, `repo/chat/static/js/chat.js`,
    `repo/chat/templates/index.html`, `repo/.handoffs/CURRENT_STATE.md`,
    `repo/project-map.md`, and `gforge-harness/sessions.json`.
  - GitHub alignment excludes local-only runtime data such as `.gforge/`,
    `.axon/`, `chat/session-data/`, chat runtime JSON, caches, and
    machine artifacts.

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

Run a live intake/execution using a scraping/news/headlines webpage
request and confirm the Project Context `skill_plan` and Execution
skill block tell the model to use `scrapling-official` for scraping and
`ui-ux-pro-max` for webpage/interface design, with no unrelated
Axon/GSD/SocratiCode staging from prior agent messages.

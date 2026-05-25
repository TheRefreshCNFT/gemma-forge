# Gemma Forge Project Map

## Intent

Gemma Forge is a local Gemma 4 work harness for the Gemma 4 Challenge. Its core value is removing setup friction from local AI: scan the user's machine, use or prepare Ollama, select an appropriate Gemma 4 model, then guide project work through project-scoped protocol cards.

The Forge Harness is the product path. The earlier model-forging GUI remains supporting capability, but docs, launcher, packaging, and contest positioning now center the harness.

Non-negotiable authenticity rule: Gemma Forge must not pre-bake, fake, force, template, or hardcode successful task outputs. A valid result means the selected local Gemma model actually completes the user's requested task through the harness workflow; deterministic checks only verify or package that result.

## Repository Structure

- `README.md` - public overview, install path, and harness positioning.
- `CONTRIBUTING.md` - public contribution policy and PR expectations.
- `CONTEXT.md` - product memory, defaults, and contest intent.
- `PROJECT_PLAN.md` - current hardening plan and final submission needs.
- `SKILL.md` - agent-facing Gemma Forge harness behavior.
- `forge.md` - hidden always-on Forge operating context, similar in role to an `AGENTS.md` for the harness.
- `AGENTS.md` - local development and operating rules.
- `.github/CODEOWNERS` - repository ownership rule for public PR review.
- `.github/pull_request_template.md` - GitHub PR safety and verification checklist.
- `.gitignore` - excludes local project records, generated workspaces, Axon indexes, logs, model files, and environments.
- `package.json` - npm entrypoint for the required `npm run check` command.
- `pyproject.toml` - Python package metadata and `gemma-forge` CLI entrypoint.
- `LICENSE` - MIT license.
- `CONTEST_READINESS.md` - challenge checklist, repo plan, packaging path, and submission readiness.
- `SUBMISSION_DRAFT.md` - DEV Build With Gemma 4 submission draft.
- `launch_forge.command` - macOS launcher that starts the Forge Harness.
- `.planning/` - local planning artifacts for the contest sprint.
- `skills/` - bundled protocol skills staged by the launcher into
  `~/.gforge/harness/skills/` for one-package installs.
- `tools/` - clean-install verification/orchestration scripts used to
  prove a fresh clone can install and run the harness.
  - `tools/harness_service.sh` - canonical macOS service helper for the
    live harness. Use `npm run harness:start`, `npm run harness:stop`,
    `npm run harness:restart`, `npm run harness:status`, `npm run
    harness:logs`, or `npm run harness:open`; it manages the launchd
    KeepAlive service `com.webot.gemma-forge.harness`.
  - `tools/provision_clean_install.py` - first-use provisioner called by
    `launch_forge.command` after package install; pulls the embedding
    model, verifies bundled skills, initializes SocratiCode/Qdrant, and
    writes the Axon project index before the app launches.
- `.git/` - initialized local git metadata pointing at public GitHub repo `https://github.com/TheRefreshCNFT/gemma-forge`.

## Harness Code

- `chat/server.py` - Flask harness on port `5005`; serves UI, stores project records, reads `forge.md`, calls Ollama, records model route, exposes error log.
- `chat/tool_workspace.py` - workspace-scoped Git/GitHub reference cloning and sandboxed command execution helpers used by Project Execution.
- `chat/tool_runtime.py` - product-owned SocratiCode MCP bridge, SocratiCode install/runtime checks, Docker/Qdrant probes, Axon CLI health, and serialized Axon project scans.
- `chat/workspace_scan.py` - local resource scanner for CPU, RAM, disk, Ollama, Gemma model availability, `llama.cpp`, skills, SocratiCode, and Axon.
- `chat/templates/index.html` - Forge Harness UI shell.
- `chat/static/js/chat.js` - workspace scan rendering, model routing status, error log UI, project management, protocol cards, checkpoints.
- `chat/static/css/style.css` - responsive Forge Harness styling.
- `chat/static/assets/forge-logo.svg` - Forge logo mark.
- `chat/__init__.py` - package marker for `python -m chat.server` and `gemma-forge`.

## Supporting Model Forge Code

- `src/app.py` - CustomTkinter model download/conversion/import GUI; now launches the Forge Harness through `python -m chat.server`.
- `src/config.py` - configurable paths, including `~/.gforge` defaults for Gemma Forge assets.
- `src/hf_engine.py` - Hugging Face token loading, model search, format detection.
- `src/utils.py` - Ollama installation/version/running checks.

## Docs And Proof

- `docs/harness-agent-operating-guide.md` - how the local Gemma agent should operate the harness for users.
- `docs/model-routing-proof.md` - proof path for `gemma-4` model routing.
- `docs/python-verification-fine-tuning.md` - handoff for the Python/script verification fixes and the pattern to port next-language validation.
- `docs/submission-media/` - screenshots, deterministic demo clip, local ComfyUI mood clips, and demo recording guide for the submission video.
- `smoke-tests/hello-color-world/` - orchestration smoke-test deliverable with validation and screenshot artifact.

## Tests

- `tests/integration_test.py` - local pipeline test for download, conversion, quantization, Ollama import, and list verification.
- `tests/maintenance_access_test.py` - controlled Gemma Forge maintenance allowlist, action application, Ollama command gating, and sandbox-denial tests.

## Runtime Defaults

- Gemma Forge home: `~/.gforge`.
- Harness data: `~/.gforge/harness`.
- Harness error log: `~/.gforge/harness/logs/errors.jsonl`.
- Model route proof: `~/.gforge/harness/model-route.json`.
- Hidden Forge context: `~/.gforge/harness/forge.md`.
- Ollama home: `~/.ollama`.
- Ollama API endpoint: `http://localhost:11434`.
- Harness URL: `http://127.0.0.1:5005/`.
- Initial recommended Forge Brain: `gemma-4-e4b-it`.
- Default embedding model for SocratiCode: `nomic-embed-text:latest`.
- Current public repo: `https://github.com/TheRefreshCNFT/gemma-forge`.
- Full-state external backups: `/Volumes/PHIXERO/Backups/gemma-forge/`.
- Backup policy: a full backup/state-alignment request means the live
  local working state is backed up to the external SSD and GitHub is
  aligned with the installable repo state. Routine alignment backups can
  omit `~/.gforge/models` when Ian says the model cache does not need to
  be backed up again; repo and harness runtime/session state still get
  preserved.

## Current Behavior

- Startup shows "Setting up workspace" while scanning local resources.
- The macOS launcher now treats first-use provisioning as part of install,
  not a later surprise: after installing dependencies it stages all bundled
  skills, pulls `nomic-embed-text:latest`, runs SocratiCode/Qdrant indexing
  for the checkout, and runs Axon analysis so Settings can report ready
  tool state before the app launches. Set `GFORGE_ALLOW_DEGRADED_TOOLS=1`
  only when intentionally launching with degraded support tools.
- Forge Engine reports system, Ollama, tools, model paths, SocratiCode install/MCP/Qdrant state, Axon CLI/index state, and subagent capacity.
- Forge Intelligence defaults to `gemma-4-e4b-it` on first run. The one-command installer uses this fixed first-run default instead of asking users to choose a model size during setup; the default E4B / 4B-class lane uses a readiness budget of about 10 GB disk and 8 GB RAM, while the current quantized Ollama artifact is about 5 GB on disk. After install, users can still import installed Ollama models or provision other compatible Hugging Face repos from Settings.
- Forge Brain selection is sent to project creation, planning, card runs, and project messages.
- Every model-backed harness call records the attempted model route.
- Initial planning calls use a bounded `num_predict` budget, with a
  tighter budget for sub-1.5B models. This keeps tiny models from making
  new projects look frozen before the first protocol card starts, and
  transport failures are surfaced as plan text.
- Settings can import installed Ollama models, search Hugging Face by
  provider/keyword/repo, select from five paged model-result pills,
  provision the selected repo into Ollama, show model route status, and
  open the error log.
- Hugging Face provisioning now starts the old model-forge pipeline from
  the harness: download the selected repo into `~/.gforge/models`, use a
  direct GGUF when available, otherwise convert with
  `convert_hf_to_gguf.py`, quantize with `llama-quantize`, write an
  Ollama Modelfile, and run `ollama create`. The UI polls the provision
  job and only creates a project interface after the model is runnable.
  Queued/provisioning/failed/downloaded-only models remain disabled in
  the Forge Brain pills and cannot start/run project work until Ollama
  lists them as installed.
- Each project record stores project messages, cards, archive state, model
  selection, and project directory state. Legacy bridge metadata may exist
  on older records, but the contest UI no longer exposes project linking.
- Session persistence saves only the project records a request actually
  changed. This prevents parallel long-running card requests from writing
  stale snapshots over another project's newer card state.
- Full Forge runs active protocol cards in order.
- The left project sidebar lists active projects newest-first and keeps
  archived projects in their own newest-first group. On desktop, the
  sidebar/session rail reaches at least the bottom of the viewport even
  when the Start panel is collapsed; mobile/tablet shows the main work area
  first and moves the project/session rail below it.
- The contest sidebar does not show project-link checkboxes, Link
  projects, or Lock selected projects controls. Session titles are the
  primary text with up to two visible lines; the state label sits smaller
  underneath each title. Row actions are stacked in a narrow right rail
  with delete (`X`) over archive/restore (`A`/`R`).
- Full Forge and individual Forge Section run state is tracked per
  project in the browser. Switching projects while one project is running
  keeps the in-flight request scoped to its original project, updates that
  project's cached record when it finishes, and only repaints the visible
  cards/messages if that project is still selected.
- The Protocol cards header no longer renders the old inline
  `plan-run-status` strip; status is shown through card state, buttons,
  sidebar project state, and the Forge Station activity stream.
- Forge Station's terminal stream fills the available terminal body down
  to the bottom border, and selected project feeds show only that
  project's events. Global harness/provisioning events remain outside
  selected project terminal histories so switching projects keeps the
  activity stream visually distinct.
- The Start panel collapse affordance no longer adds the obsolete
  "collapsed while you type" text.
- Auto-run startup visually marks the Project Context / intake card as
  running while the initial planning request is in flight: the card gets
  the active running border/glow and its button reads `Running`.
- Protocol cards now surface compact run facts on the card they apply
  to: contract fields for Project Context, readiness fields for Forge
  Flow, validation/transport/files for Execution, tool status for
  SocratiCode/Axon, plus review/research/artifact facts. The full raw
  card artifact stays available behind a "Full section artifact"
  disclosure.
- The rolodex card stack stays below the Protocol cards header while
  rotating. Non-front cards use small downward offsets for a neat deck
  instead of sliding upward into the header text.
- The Project Context section remains the chronological project feed;
  its scroll area is taller so card-specific facts can live on cards
  while the feed stays readable.
- Manual / Human Verify remains separate: cards keep their manual
  `Forge Section` button state until the user runs a section.
- Conditional cards are runnable by Full Forge when visible; protocols that should not run are moved to inactive or pending.
- New-project mode may include a desired directory path. Project Execution creates that directory if missing, while existing-directory mode requires the path to already exist.
- Human verify pauses after card work; Verified continues, Not Verified captures the issue and reruns the section, Help asks the agent for guidance.
- Archived projects are read-only at the API boundary. Project messages,
  card runs, checkpoint updates, and `/api/plan` calls return `409`
  before any model/tool call can run, so archived cleanup/test projects
  cannot keep making calls from stale UI state.
- Each Forge Section calculates a research-pass budget: up to 2 passes for small tasks, up to 4 for larger tasks, and records used passes on the card.
- When the selected Forge Brain is 8B parameters or smaller, the server runs one extra independent review before any section can be marked complete.
- Failed extra reviews trigger up to two post-review continuation repair attempts, clear stale pre-repair research notes, then rerun the review; only still-failing sections move to `needs-attention`.
- Continuation repair prompts tell the model not to start over unless the human explicitly requested a restart, include reviewer/validator blockers, provide a bounded current-file snapshot from the workspace, and ask for only the complete repaired/added files needed to finish the original request.
- Project Execution has no built-in task generator; it writes only file content returned by the selected Gemma model and records model-authored execution metadata for verification. It accepts strict JSON or the Forge file-block payload so small local models do not have to escape long HTML/CSS through JSON.
- Project Execution stages installed Forge skills into the workspace under `.gforge/skills`, writes a skill manifest, injects requested skill instructions into the Gemma prompt, and reserves `.gforge/` so the model cannot overwrite harness support context.
- Bundled Forge skills now include `code-writer`, `pdf` from Anthropic's
  PDF skill, and `mcp-builder` from Anthropic's MCP builder skill,
  alongside `logo-generator`, `scrapling-official`, `ui-ux-pro-max`,
  `axon`, `socraticode`, `gsd`, and Forge Flow (`skills/webot-flow/`). These skills include
  expanded routing keywords so Project Context can assign them from
  runnable code, logo/brand, PDF/form/OCR, MCP/server/tool-schema,
  browser/scraping, UI/UX, semantic codebase, graph/impact, and planning
  language.
- Project Execution can clone GitHub/GitLab/Bitbucket repository
  references into `references/repos/` using host `git` and authenticated
  `gh` when available, then lists the real cloned paths in the execution
  prompt and report.
- Project Execution can run bounded workspace commands only when the
  Project Context contract requires `shell_exec` or `install_package`.
  Commands run after model-authored files are written, from the
  workspace root, through a sandbox that can write only inside the
  workspace. Project package installs are allowed through
  `npm`/`pnpm`/`yarn` or `pip`; pip installs are targeted under
  `.gforge-installs/python` unless the model supplied an explicit safe
  relative target. Deploy, publish, push, system/global installs,
  absolute paths, parent traversal, pipes, and multiline shell remain
  blocked.
- Workspace execution now has a controlled "workspace yolo" path: when a
  model-authored Python script imports non-stdlib packages, the harness
  infers the packages and prepends a workspace-local pip install into
  `.gforge-installs/python` before running the script. PDF/OCR jobs also
  get the known `pypdf`/`pdfplumber`/`reportlab` packages. Package installs
  and script-file commands receive a bounded 300-second timeout, while
  ordinary commands keep the 60-second cap. Before each retry, stale matching
  deliverables are moved to `.gforge/attempt-backups` so old bad outputs
  cannot satisfy validation. Deterministic validation fails if any requested
  workspace command is skipped/failed, `.pdf` outputs must parse as real PDFs
  instead of only having a `%PDF` header, and generated PDF text can be used
  for content-count checks such as category reports. Python script deliverables
  are syntax-checked, and script-created file/directory counts are inferred from
  the contract/acceptance when needed, validated by running the script in a
  temporary workspace, and then deleted rather than treated as final deliverables.
  HTML/CSS/JavaScript/SQL deliverables now get static read-only integrity
  validation: `.html`/`.htm` files fail on clear tag-pair mismatches, `.css`
  files fail on unclosed comments/strings or unbalanced brackets/braces/
  parentheses, `.js`/`.mjs`/`.cjs` files are parsed with `node --check` without
  executing model-authored code, and `.sql` files receive a lightweight
  non-executing sanity scan for empty/non-SQL files, unclosed SQL strings or
  comments, dollar-quoted string closure, and unbalanced parentheses. SQL content
  counts use actual statement shapes, e.g. `INSERT INTO`, ignoring comments and
  string literals; structural SQL statement counts are exact unless the request
  says "at least" or another minimum-count phrase. Existing local-link validation
  still checks referenced assets against disk. HTML bundle contracts treat linked CSS/JS as support
  files, so "one HTML page and one linked CSS/JS file" validates as one primary
  HTML deliverable plus support files instead of extra HTML files. HTML content
  counts ignore CSS/JS support-code text and count specific UI elements such as
  `status-card` elements from the HTML. List-scoped content requirements such as
  "three sample system checks" count rendered `<li>` entries in the HTML, and
  "no CSS file" contracts block separate `.css` artifacts or CSS links while
  allowing `<style>` blocks or inline `style` attributes inside the HTML.
- Auto-generated execution workspace names are compact now. The harness prefers
  the Project Context project name, e.g. `local-ai-validation-lab-dashboard`,
  and otherwise uses a short collapsed slug. User-provided project directories
  are still preserved exactly.
- Verification is read-only with respect to deliverables: it can rebuild the
  verification report and rerun deterministic checks against existing artifacts,
  but it cannot rerun Project Execution or overwrite model-authored files. If
  issues remain, it routes back to the responsible Forge Section. Passed
  deterministic validation is authoritative for Verification; support-tool
  findings such as Axon dead-code output are advisory for simple fresh-script
  deliverables. Verification now receives staged skill context for read-only
  review, matching the Context Writer, worker, and chat agent context path.
- Small-model extra review can still trigger repairs for concrete artifact
  mismatches, but a reviewer cannot overrule a passed deterministic validation
  count/path/PDF/content-quantity gate. This prevents false-positive review
  feedback such as treating "at least 3 categories" as "exactly 3" from
  deleting good generated outputs during continuation repair.
- Gemma Forge self-maintenance runs through a controlled allowlist. When the
  request is to change the harness itself, Project Execution snapshots exact
  repo/runtime targets into `references/maintenance-targets/`; outside-workspace
  file changes must be requested in `artifacts/maintenance-actions.json` using
  validated `copy_file`, `write_file`, or `copy_tree` actions. The harness
  applies only targets on the allowlist, records backups under
  `~/.gforge/harness/maintenance-backups/`, and gates Ollama CLI commands to
  explicit model maintenance.
- Project chat stages the same selected skill context when a workspace
  exists. The chat agent may request a worker handoff by emitting one
  bounded `GFORGE_WORKER_ACTION` block for `full_forge` or a known
  protocol card; the browser turns that into the existing card/Full Forge
  flow instead of giving chat arbitrary tool execution.
- Project Context / skill staging recognizes deterministic aliases for
  installed skills. For live scraping tasks, capability/task values such
  as `web_browse`, `web_fetch`, scrape/crawl, live news/headlines,
  article extraction, dynamic sites, Cloudflare/Turnstile, and CSS/XPath
  selector language map to the bundled `scrapling-official` skill. The
  saved Project Context is canonicalized to the real skill key, and the
  Forge Station terminal emits visible `skill` events when skills are
  selected or staged.
- Project Context now includes an installed user-facing skill capability
  catalog so the model sees what each harness skill is for before writing
  the contract. Skill routing is tested for simple no-tool tasks, UI/UX
  interface work, Scrapling browser/scraping work, SocratiCode semantic
  codebase discovery, Axon structural graph/impact analysis, combined
  code-intelligence requests, logo generation, runnable code, PDF/OCR
  work, and MCP server/tool-schema work. Generic MCP keywords such as bare
  `auth` no longer steal ordinary codebase-search requests.
- Skill routing aliases now include more human, non-tool phrasing for every
  bundled skill: data mining/harvesting/deep research for Scrapling, make
  it look professional/mobile friendly for UI/UX, little command-line
  utility/process files for Code Writer, brand symbol/app icon for Logo
  Generator, pull text from scanned documents for PDF, local tool server/API
    as agent tools for MCP, find in this repo for SocratiCode, what breaks if
    for Axon, task breakdown/milestones for GSD, and orient/backup/protect
  live for Forge Flow. Broad web-research phrases are guarded so codebase
  search requests stay with SocratiCode instead of accidentally staging
  Scrapling.
- Project Context separates deliverable file count from repeated content
  counts. `deliverable.count` remains "how many files"; raw user phrases
  like "top 3 articles in each category" or "three design options" are
  preserved as `content_requirements`, injected into Execution, and
  enforced by deterministic validation for text-like deliverables.
- Project Context now treats any explicit local file or directory path as
  source material. Project Execution imports those files into
  `references/input/`, writes `references/source-inputs.md`, and tells the
  model to use copied workspace-relative paths plus command evidence rather
  than inventing filenames or using original `/Users/...` paths.
- GSD planning now receives the full Project Context contract, source
  inputs, skill plan, tool plan, model profile, and hard count gates. The
  bundled `skills/gsd/` install state includes the full workflow suite
  (workflows, prompts, agents, references, templates, hooks), not just the
  stub `SKILL.md`. The GSD card now explicitly stages `gsd` and injects a
  `GSD Skill Context` block into planning.
- Project Execution skill context starts with a concise usage plan before
  raw skill manuals. For scraping + webpage tasks, `scrapling-official`
  is identified as the scraping/extraction layer and `ui-ux-pro-max` as
  the webpage/interface design layer. Skill selection ignores prior agent
  messages so reruns do not stage unrelated support skills just because a
  previous artifact mentioned them. Prompt snippets are loaded from ordered
  entrypoints (`OUTPUT.md`, `SKILL.md`, `skill.json` summary, then
  whitelisted deep docs) and budget is split across requested skills so one
  long manual cannot hide later requested skills. UI/UX Pro Max exposes Quick
  Reference / Pre-Delivery Checklist excerpts, and GSD exposes plan-phase
  anti-shallow rules plus planner-agent guidance.
- The launcher refreshes bundled staged skills in `~/.gforge/harness/skills/`
  when the repo copy is newer/fuller or required deep files are missing.
  It also strips stale `.git`, cache, `.DS_Store`, and AppleDouble artifacts
  from staged bundled skill copies. Clean-install provisioning and verification
  fail if the required deep GSD or UI/UX Pro Max files are absent.
- Axon and SocratiCode are support-tool cards; skipped, unavailable, and degraded states are shown explicitly and never claimed as successful tool runs.
- Axon runs only when graphable source files exist. HTML-only work is reported as not Axon-indexable instead of triggering a false structural scan.
- SocratiCode is installed under `~/.gforge/tools` when needed and is called through a real MCP stdio bridge from the Flask harness.
- SocratiCode cards run real `codebase_index`, `codebase_status`, `codebase_search`, and `codebase_graph_status` calls against the selected project directory.
- Axon cards run serialized `axon analyze`, `axon status`, and `axon dead-code` calls against the selected project directory to avoid app-owned lock collisions.
- Readiness checks now include real SocratiCode MCP and Axon project probes rather than treating skill folders or metadata as tool readiness.
- Inactive and pending cards are hidden from the main workflow and listed under Skipped protocols.
- Active, archived, running, review, stopped, and complete projects have distinct sidebar states.

## Known Remaining Work

- Record final demo video.
- Confirm no local project record, token, model, generated workspace, or log data enters the public repo.
- Keep public GitHub protections aligned so outside contributors can submit PRs but cannot write directly to `main`.
- Broaden deterministic verification beyond file/authenticity checks without adding task-specific generators.

# Gemma Forge Project Map

## Intent

Gemma Forge is a local Gemma 4 work harness for the Gemma 4 Challenge. Its core value is removing setup friction from local AI: scan the user's machine, use or prepare Ollama, select an appropriate Gemma 4 model, then guide project work through project-scoped protocol cards.

The Forge Harness is the product path. The earlier model-forging GUI remains supporting capability, but docs, launcher, packaging, and contest positioning now center the harness.

Non-negotiable authenticity rule: Gemma Forge must not pre-bake, fake, force, template, or hardcode successful task outputs. A valid result means the selected local Gemma model actually completes the user's requested task through the harness workflow; deterministic checks only verify or package that result.

## Repository Structure

- `README.md` - public overview, install path, and harness positioning.
- `CONTEXT.md` - product memory, defaults, and contest intent.
- `PROJECT_PLAN.md` - current hardening plan and final submission needs.
- `SKILL.md` - agent-facing Gemma Forge harness behavior.
- `forge.md` - hidden always-on Forge operating context, similar in role to an `AGENTS.md` for the harness.
- `AGENTS.md` - local development and operating rules.
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
- `.git/` - initialized local git metadata pointing at private GitHub repo `https://github.com/TheRefreshCNFT/gemma-forge`.

## Harness Code

- `chat/server.py` - Flask harness on port `5005`; serves UI, stores project records, reads `forge.md`, calls Ollama, records model route, exposes error log.
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
- `docs/submission-media/` - screenshots, deterministic demo clip, local ComfyUI mood clips, and demo recording guide for the submission video.
- `smoke-tests/hello-color-world/` - orchestration smoke-test deliverable with validation and screenshot artifact.

## Tests

- `tests/integration_test.py` - local pipeline test for download, conversion, quantization, Ollama import, and list verification.

## Runtime Defaults

- Gemma Forge home: `~/.gforge`.
- Harness data: `~/.gforge/harness`.
- Harness error log: `~/.gforge/harness/logs/errors.jsonl`.
- Model route proof: `~/.gforge/harness/model-route.json`.
- Hidden Forge context: `~/.gforge/harness/forge.md`.
- Ollama home: `~/.ollama`.
- Ollama API endpoint: `http://localhost:11434`.
- Harness URL: `http://127.0.0.1:5005/`.
- Initial recommended Forge Brain: `gemma-4`.
- Current private repo: `https://github.com/TheRefreshCNFT/gemma-forge`.
- Full-state external backups: `/Volumes/PHIXERO/Backups/gemma-forge/`.
- Backup policy: a full backup/state-alignment request means the live
  local working state is backed up to the external SSD and GitHub is
  aligned with the installable repo state.

## Current Behavior

- Startup shows "Setting up workspace" while scanning local resources.
- Forge Engine reports system, Ollama, tools, model paths, SocratiCode install/MCP/Qdrant state, Axon CLI/index state, and subagent capacity.
- Forge Intelligence recommends `gemma-4` on first run and shows supported local model lanes without locking the selector.
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
  archived projects in their own newest-first group.
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
- Project Context separates deliverable file count from repeated content
  counts. `deliverable.count` remains "how many files"; raw user phrases
  like "top 3 articles in each category" or "three design options" are
  preserved as `content_requirements`, injected into Execution, and
  enforced by deterministic validation for text-like deliverables.
- Project Execution skill context starts with a concise usage plan before
  raw skill manuals. For scraping + webpage tasks, `scrapling-official`
  is identified as the scraping/extraction layer and `ui-ux-pro-max` as
  the webpage/interface design layer. Skill selection ignores prior agent
  messages so reruns do not stage unrelated support skills just because a
  previous artifact mentioned them.
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
- Make the private repo public when submission materials are ready.
- Broaden deterministic verification beyond file/authenticity checks without adding task-specific generators.

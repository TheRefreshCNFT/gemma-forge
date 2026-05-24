# forge.md

Gemma Forge operating context:

- Non-negotiable authenticity rule: do not pre-bake, fake, force, template, or hardcode successful task outputs. Only real verified results count.
- Real verified results mean the selected local Gemma model completes the user's requested task through the harness workflow.
- Scripts, validators, screenshots, and deterministic checks may verify or package results, but they must not replace Gemma 4 doing the requested work.
- If Gemma 4 did not actually complete the requested task, say the run is unverified or failed and repair the orchestration instead of presenting success.
- Axon and SocratiCode are support tools, not proof of user-facing task completion by themselves. If a support tool fails because of local environment setup, report the degraded tool state plainly and continue only when execution and verification artifacts prove the requested work.
- Do not claim Axon or SocratiCode ran unless the command/tool actually ran. If a tool is skipped, host-assisted, unavailable, or degraded, state that exact status and why.
- Treat every visible conversation as a project workspace, not a global chat.
- If the user asks to change Gemma Forge itself, treat that as a Gemma Forge
  maintenance project, not a casual settings chat. Examples: add/provision a
  model, remove a model, set the default model, add/update/remove a skill,
  change installer behavior, update routing, edit harness UI, or repair tool
  readiness. Use the Gemma Forge repo/workspace as the target project, run the
  normal context/planning/execution/verification flow, and leave evidence.
- Maintenance agents are allowed to perform the requested harness work only
  through explicit project-scoped capabilities: edit repo files, stage bundled
  skills, update local harness config/state, run bounded commands, and verify
  with model route, workspace status, skill staging, tests, or clean-install
  checks. Do not treat "harness work" as permission for arbitrary destructive
  system changes.
- Maintenance does not grant raw filesystem access. The harness snapshots exact
  allowlisted Gemma Forge targets into `references/maintenance-targets/`.
  Outside-workspace file changes must be requested through
  `artifacts/maintenance-actions.json` using validated `copy_file`,
  `write_file`, or `copy_tree` actions; if a needed target is not listed, stop
  and report the missing target instead of improvising.
- The internal record may be stored as a session, but do not expose that as the user-facing concept.
- If the user does not know what to do, translate their intent into the next harness action.
- Explain which control to use only when the harness cannot perform that action from the current message.
- Use Full Forge for end-to-end active-card execution and Forge Section for one protocol card.
- Use the selected Forge Brain for project work. The first-run recommendation can be `gemma-4-e4b-it`, but the user's selected model wins.
- Installed Gemma Forge skills are staged into each project workspace under `.gforge/skills`. Use those staged relative paths and included instructions instead of claiming absolute `/Users/...` skill paths are inaccessible.
- Treat staged skills as capability guides with clear boundaries:
  - `code-writer`: implementation layer for Python, JavaScript, TypeScript, HTML/CSS, SQL, shell, tests, parsers, CLIs, API clients, and runnable local code.
  - `logo-generator`: SVG logo/icon/brand-mark generation and showcase workflows.
  - `ui-ux-pro-max`: UI/UX, design systems, dashboards, responsive layout, visual states, charts, accessibility, and polished presentation.
  - `scrapling-official`: first browser/scraping option for URLs, crawling, JS-rendered pages, adaptive extraction, and anti-bot/stealth cases.
  - `socraticode`: semantic codebase search, indexing, relevant-file discovery, context artifacts, and dependency orientation.
  - `axon`: structural code graph, call graph, dead code, dependency impact, blast radius, and graph queries.
  - `gsd`: planning, orchestration, phases, milestones, workstreams, execution routing, and verification gates.
  - `pdf`: PDF read/extract/OCR/forms/manipulation/generation.
  - `mcp-builder`: MCP server/tool/resource/prompt/transport design and implementation.
- SocratiCode and Axon are higher-level code intelligence tools. Keep them inactive for simple fresh-file/content tasks and use them when existing-codebase discovery or structural analysis is actually needed.
- Route skills from human phrasing too: data mining/harvesting/deep research can mean Scrapling when web/source context is present; make it look professional/mobile friendly means UI/UX; little command-line utility/process files means Code Writer; brand symbol/app icon means Logo Generator; pull text from scanned documents means PDF; API as agent tools/local tool server means MCP Builder; find in this repo means SocratiCode; what breaks if means Axon; task breakdown/milestones means GSD; orient/backup/protect live means Webot Flow.
- UI/UX Pro Max and Code Writer may work together: UI/UX owns design direction; Code Writer owns concrete implementation.
- Scrapling and Code Writer may work together: Scrapling owns source acquisition; Code Writer owns parsing, transformation, and packaging.
- GitHub/Git repository references can be cloned by the harness into the project workspace under `references/repos/` using host `git`/authenticated `gh` when available. Use those workspace paths; never expose tokens.
- Bounded shell execution is workspace-scoped and sandboxed. Only trust a command as run when the execution report shows a real workspace command run. Workspace package installs are allowed only through the sandbox for project dependencies (`npm`/`pnpm`/`yarn` or `pip` targeted inside the workspace); deploy, publish, push, system/global installs, secrets, and path escapes are still out of scope.
- Do not claim a staged skill script, external API, image model, or shell command ran unless the harness actually ran it. Generate the requested deliverables with Gemma or list the needed workspace-safe command for a verified step.
- For model maintenance, verify the actual route and Ollama state after any
  change. For skill maintenance, verify the skill is in the installable repo,
  staged into `~/.gforge/harness/skills` when needed, visible to routing, and
  covered by a routing or execution check when practical.
- When deliverables are generated from staged skill instructions, say the staged skill instructions were used. Do not describe that as simulated skill execution.
- Ask whether a project directory already exists when the answer changes the workflow.
- Use Human verify when the user wants checkpoints; use auto-run when they want uninterrupted execution.
- Archive finished or paused projects to keep the active list focused.
- Delete only removes the selected project record and its artifacts; never delete or weaken forge.md.
- Link projects only when two project threads need shared context while remaining separately scoped.
- When unsure, give a direct next action and a short reason. Do not assume the user knows Ollama, models, terminals, or project setup.

Axon command reference:

- `axon analyze` - index the current repo into the structural graph.
- `axon status` - show index status for the current repo.
- `axon list` - list indexed repositories.
- `axon clean` - delete the current repo index.
- `axon query` - search the graph.
- `axon context <symbol>` - show callers, callees, and related context.
- `axon impact <symbol>` - show blast radius before changing a symbol.
- `axon dead-code` - list unreachable or unused code.
- `axon cypher` - run raw graph queries.
- `axon setup` - configure MCP integration.
- `axon watch` - watch files and re-index on changes.
- `axon diff` - compare branch structure.
- `axon mcp` - start stdio MCP server.
- `axon host` - run shared Axon host.
- `axon serve` - serve MCP with optional watching.
- `axon ui` - launch Axon UI.

SocratiCode command reference:

- `codebase_index` - start indexing a project.
- `codebase_status` - check index, watcher, and graph state.
- `codebase_search` - semantic and keyword search across indexed code.
- `codebase_update` - incrementally refresh changed files.
- `codebase_graph_build` - build dependency graph.
- `codebase_graph_status` - check graph build state.
- `codebase_graph_circular` - find circular dependencies.
- `codebase_remove` - delete an index.

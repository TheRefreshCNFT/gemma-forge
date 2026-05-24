# Gemma Forge Harness Skill

Use this skill when an agent is operating Gemma Forge or helping a user who does not know how to operate the harness.

## Role

Gemma Forge is a local work harness, not a global chat. Treat every interaction as part of a project with its own context, artifacts, protocol cards, and verification state.

The harness operating protocol lives in hidden always-on `forge.md` context. It is not a user project, and deleting projects must never remove or weaken this context.

## Default Model Rule

The initial recommended Forge Brain is `gemma-4-e4b-it`, the edge Gemma 4 E4B lane in Ollama. Use the selected model from the harness state; users can switch to another installed and supported local model.

If the user asks which model is being used, answer from the harness state and model route, not from assumption.

## Harness Flow

1. Start with: "What project are we planning?"
2. Ask whether the user already has a project directory.
3. If no directory exists, treat the project record as the project seed and use GSD plus Project Execution to create the workspace.
4. If a directory exists, orient first with Forge Flow, then activate SocratiCode and Axon only when codebase mapping or structural analysis is useful.
5. Stage user-facing skills by capability fit:
   - Code Writer for runnable source-code artifacts.
   - Logo Generator for SVG logo/icon/brand-mark work.
   - UI/UX Pro Max for interface/design-system/presentation work.
   - Scrapling for browser/scrape/crawl/web extraction work.
   - SocratiCode for semantic codebase discovery.
   - Axon for structural code graph and impact analysis.
6. Use Full Forge for end-to-end active-card execution.
7. Use Forge Section when the user wants only one card.
8. Honor Human verify checkpoints when enabled.
9. On Not Verified, collect the issue, repair, retest, and return to verification.
10. Archive completed or paused projects; delete only when the user wants permanent removal.
11. Link projects only when separate projects need shared context.

## Gemma Forge Maintenance Requests

If the user asks to change Gemma Forge itself, treat it as a project task
against the Gemma Forge repo/workspace.

Examples:

- Add, provision, remove, or set the default model.
- Add, update, remove, stage, or test a Forge skill.
- Update the installer, clean-install provisioning, readiness checks, routing,
  model route, tool state, UI, or harness operating guide.

Required behavior:

1. Use Forge Flow and GSD as normal project discipline.
2. Use Project Context to capture the requested harness change precisely.
3. Use Code Writer for implementation changes and the relevant domain skill
   for the work: e.g. SocratiCode/Axon for codebase intelligence, Skill
   Creator-style guidance for new skills, UI/UX Pro Max for harness UI, or
   Scrapling for web-source ingestion.
4. Verify with concrete evidence: `npm run check`, focused routing tests,
   model route/status read-back, skill staging read-back, clean-install
   provisioning checks, or UI/browser checks when applicable.
5. Do not treat "work on the harness" as permission for arbitrary destructive
   system changes. Stop before deleting models, skills, or runtime state unless
   the user explicitly requested that destructive action.
6. Outside-workspace maintenance changes go through the harness allowlist:
   inspect `references/maintenance-targets/`, then emit
   `artifacts/maintenance-actions.json` with `copy_file`, `write_file`, or
   `copy_tree` actions for listed targets only.

## Storage

- Ollama model state stays in `~/.ollama`.
- Gemma Forge framework state stays in `~/.gforge`.
- Harness project data lives in `~/.gforge/harness`.
- Hidden Forge context lives in `~/.gforge/harness/forge.md`.

## Tools And Protocol Cards

- Forge Flow: project orientation, state protection, handoff discipline.
- GSD: phase planning, success criteria, execution routing.
- Project Execution: materialize files, validate, repair, retest, deliver.
- Code Writer: Python, JavaScript, TypeScript, HTML/CSS, SQL, shell, tests,
  parsers, CLIs, API clients, and runnable local code.
- Logo Generator: SVG logo/icon/brand-mark concepts and showcase workflows.
- UI/UX Pro Max: UI/UX, design systems, dashboards, responsive layouts,
  visual states, charts, and accessibility.
- Scrapling: first browser/scraping/crawling path for live URLs, JS-rendered
  pages, adaptive extraction, and anti-bot/stealth cases.
- SocratiCode: semantic codebase exploration when code exists.
- Axon: structural analysis, impact checks, dead-code review.
- Verification: test or inspect the user-visible result.

Route by human phrasing too. Examples: "data mining" or "source harvesting"
can mean Scrapling when web/public-source context is present; "make it look
professional" means UI/UX; "little command line utility" means Code Writer;
"brand symbol" means Logo Generator; "pull text from scanned documents" means
PDF; "API as agent tools" means MCP Builder; "find in this repo" means
SocratiCode; "what breaks if" means Axon; "break this into milestones" means
GSD; "orient and back up first" means Webot Flow.
- Handoff: preserve what shipped, what was verified, and the next action.

---
name: gsd
description: Use the local Get Shit Done planning workflow package for project initialization, phase planning, execution routing, verification, and roadmap maintenance. Use when the user mentions GSD, /gsd-* commands, .planning, phases, milestones, or autonomous project planning.
---

# GSD

GSD is a local planning workflow package under this skill directory. It contains command-style workflows in `workflows/`, supporting agent prompts in `agents/`, references in `references/`, and document templates in `templates/`.

## How To Use In Codex

1. Identify the requested GSD command or intent.
2. Open the matching file in `workflows/`.
3. Treat XML-like blocks such as `<gsd-arguments>`, `<gsd-execute>`, and `<gsd-paste>` as source workflow metadata, not as something Codex executes automatically.
4. Translate the workflow into normal Codex actions: read files, ask short questions when required, edit `.planning/` artifacts, run shell checks, spawn subagents only when the user explicitly asks for parallel agent work, and report verification.
5. Prefer the workflow's stated inputs, outputs, success criteria, and required reading over improvising a new process.

## Common Routing

- New project: `workflows/new-project.md`
- Existing codebase map: `workflows/map-codebase.md`
- Freeform router: `workflows/do.md`
- Quick task: `workflows/quick.md`
- Phase discussion: `workflows/discuss-phase.md`
- Phase planning: `workflows/plan-phase.md`
- Phase execution: `workflows/execute-phase.md`
- Review/verification: `workflows/verify-work.md`
- Help/reference: `workflows/help.md`

## Compatibility Notes

- The original package includes Claude/NullClaw command runtime markers. In Codex, use them as structured guidance and perform the equivalent file, shell, and planning actions directly.
- Paths inside the package that reference `~/.claude/get-shit-done` are legacy source references. In Gemma Forge, use the currently staged `gsd/` skill directory as the package root.
- Do not assume slash commands dispatch automatically. If the user writes `/gsd-*`, load the matching workflow file yourself.

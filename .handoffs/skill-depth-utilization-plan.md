# Gemma Forge — Skill Depth Utilization Plan

> Status: **implemented 2026-05-24**. Pinpoint changes landed in
> `chat/server.py`, `launch_forge.command`, `tools/provision_clean_install.py`,
> `tools/verify_clean_install.sh`, and `tests/model_route_test.py`. Live staged
> `gsd` and `ui-ux-pro-max` were refreshed from repo into
> `~/.gforge/harness/skills/`. Pre-edit backup:
> `/Users/webot/Backups/gemma-forge/20260524T213854Z-pre-skill-depth-utilization/`.

Below is the original plan that was executed.

**Goal**
Make skill usage real without rebuilding the harness: skills should be discoverable, staged, prompt-visible, and verifiably used by Project Context, GSD Planning, Project Execution, chat worker, and Verification.

**Phase 1: Baseline And Backup**
Before edits, follow `webot-flow`: read current state, confirm harness/branch/Ollama, then back up any touched files under `chat/`, `tools/`, `launch_forge.command`, and `skills/`.

Files likely touched:
`chat/server.py`, `launch_forge.command`, `tools/provision_clean_install.py`, `tools/verify_clean_install.sh`, selected skill entrypoint files under `skills/`.

**Phase 2: Fix Skill Staging Depth**
Problem: launcher skips existing staged skill folders, so a shallow live `gsd` can persist forever.

Update staging so bundled skills refresh when the repo copy is newer/fuller, or when required deep files are missing.

Minimum checks:
- `gsd/workflows/plan-phase.md`
- `gsd/agents/gsd-planner.md`
- `gsd/templates/roadmap.md`
- `ui-ux-pro-max/skill.json`
- `ui-ux-pro-max/src/ui-ux-pro-max/templates/base/quick-reference.md`
- `ui-ux-pro-max/src/ui-ux-pro-max/scripts/search.py`

Keep it surgical: replace only generated staged copies under `~/.gforge/harness/skills`, not user workspaces.

**Phase 3: Add Prompt Entrypoints**
Problem: the loader misses `skill.json` bundle layouts and reads only `SKILL.md` plus a few folders.

Add a small ordered prompt-entry rule:

1. `OUTPUT.md` if present
2. `SKILL.md` if present
3. `skill.json` summary if no `SKILL.md`
4. selected known docs for bundle-style skills

For UI/UX Pro Max, load a concise digest plus:
- `src/ui-ux-pro-max/templates/base/quick-reference.md`
- relevant parts of `src/ui-ux-pro-max/templates/base/skill-content.md`

For GSD, load:
- `SKILL.md`
- selected workflow by intent, e.g. `workflows/new-project.md`, `plan-phase.md`, `execute-phase.md`, `verify-work.md`
- selected agent/reference excerpts only when needed

Do not paste the whole skill directory. Use budgeted, whitelisted entrypoints.

**Phase 4: Make GSD Card A Real Skill Consumer**
Problem: `run_gsd_card` currently uses a custom planning prompt, not the staged GSD package.

Update the GSD card path so it stages/loads GSD context before calling the model. Then `build_planning_prompt` should include a "GSD Skill Context" section when available.

Expected result: major planning work sees actual GSD workflow guidance, not only "use GSD perspective."

**Phase 5: Carry Skill Context Through Worker And Verifier**
Execution already receives `skill_context.prompt`; Verification already receives it too. After Phase 3, both become deeper automatically.

Add one explicit verifier rule: "evaluate against the staged skill's stated output/quality rules where applicable." For UI/UX, that means states, layout, accessibility, visual hierarchy, responsive behavior. For GSD, that means phases, acceptance criteria, dependencies, verification gates.

**Phase 6: Tests**
Add focused tests, not broad rewrites:

- UI routing test still selects `ui-ux-pro-max`.
- UI prompt test proves the worker prompt contains deep UI markers like `Generate Design System`, `Pre-Delivery Checklist`, or `Quick Reference`.
- GSD staging test proves live staged GSD includes `workflows/` and `agents/`.
- GSD prompt test proves planning prompt contains selected GSD workflow text.
- Clean-install test fails if required deep skill files are missing.

**Phase 7: Live Validation**
Run a harmless local harness task:

- UI test: "Design a professional responsive SaaS dashboard with charts, empty/loading/error states, and accessibility."
- GSD test: "Plan a major multi-phase project with milestones, workstreams, acceptance checks, and verification gates."

Then inspect:
- `intake.md`: correct `skill.use`
- workspace `.gforge/skills/`: deep files present
- `execution.md` / `verification.md`: staged skill context listed
- generated artifact quality reflects the skill rules

**My Take**
This is not a major modification. It is mostly better staging, better prompt entrypoints, and better tests. The architecture can stay intact. The highest-value fix is making `gsd` stage the full repo bundle and making `ui-ux-pro-max` expose a proper prompt-facing entrypoint instead of relying on its `skill.json` alone.

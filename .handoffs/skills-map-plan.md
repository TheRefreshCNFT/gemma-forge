# Plan: `skills-map.md` — declarative skill registry

> Status: **planned, not started.** Awaiting answers to the two
> scoping questions at the bottom before I touch code.

## Why

Today `prepare_workspace_skill_context()` calls
`discover_installed_skills()` (walks every install root) and stages
**every** harness/gforge/project skill into the workspace via
`shutil.copytree()`. For the noob-test session we just ran, that
copied ~60 KB of skill content even though only `logo-generator` was
relevant. Multiply per session and the workspaces bloat fast.

The cleanup we want: skills are *declared* in one place; the harness
stages only the skill(s) the Context Writer chose for this project,
plus any defaults.

## File: `~/.gforge/harness/skills/skills-map.md`

Same frontmatter style as Project Context. One file, auto-maintained.

```yaml
---
schema_version: 1
generated_at: 2026-05-21T14:50:00Z
defaults: []                  # skill keys ALWAYS staged in every workspace
skills:
  - key: logo-generator
    name: "Logo Generator"
    path: /Users/webot/.gforge/harness/skills/logo-generator
    source: harness
    summary: >
      Generates SVG logo variants from a brand/product description.
      Tool-less: emits raw SVG inside GFORGE_FILE blocks; no external
      image APIs required.
    triggers: [logo, brand mark, icon, identity, wordmark]
    deliverable:
      type: design_deliverable
      format: svg
      path_pattern: output/logo-NN.svg
    version: 0.2.0
    last_updated: 2026-05-20T23:57:00Z

  - key: ui-ux-pro-max
    name: "UI/UX Pro Max"
    path: /Users/webot/.gforge/harness/skills/ui-ux-pro-max
    source: harness
    summary: >
      Design system intelligence for web and mobile UIs (50+ styles,
      palettes, font pairings). Use for full-page design tasks.
    triggers: [ui design, ux, design system, color palette, dashboard, landing page]
    deliverable:
      type: design_deliverable
      format: html
      path_pattern: design/index.html
    version: 0.1.0
    last_updated: 2026-05-09T11:58:00Z
---

# Gemma Forge Skills Map

Auto-maintained registry of every installed skill the Project Context
Writer can choose from.

## How the harness uses this

- The Project Context Writer reads ONLY this file (summary + triggers)
  when selecting `skill.use`. It does not read each skill's full
  SKILL.md.
- After Intake completes, only the union of `defaults` +
  `projectContext.skill.use` gets staged into the session workspace.
- The `skill-creator` skill (planned separately) appends to this file
  whenever it authors a new skill.

## How to edit by hand

- Edit `summary` or `triggers` to change how the Context Writer
  recognizes a skill.
- Add a key to `defaults:` to force-stage that skill in every session.
- `path` / `source` / `last_updated` are derived from the filesystem
  and get overwritten on every rebuild.
```

## Harness changes

1. **`SKILLS_MAP_FILE`** constant pointing at
   `~/.gforge/harness/skills/skills-map.md`.

2. **`rebuild_skills_map()`** — scans `discover_installed_skills()`,
   reads each `SKILL.md`'s frontmatter for `name` / `description` /
   `triggers` / `deliverable`, writes the consolidated map. Preserves
   the existing `defaults:` list and any manual edits to
   `summary`/`triggers` (re-merges instead of overwriting). Idempotent.

3. **`read_skills_map()`** — parses the file, returns
   `{defaults: [keys], skills: {key: info}, body: str}`. If the file
   doesn't exist, calls `rebuild_skills_map()` once.

4. **Context Writer prompt** — pass parsed map entries
   (key/name/summary/triggers/deliverable) instead of the current full
   `staged_skills` list. Drops ~10 KB of irrelevant SKILL.md text from
   the prompt.

5. **`prepare_workspace_skill_context()`** — change selection from
   "all sources in {harness,gforge,project}" to:
   ```
   selected_keys = set(map["defaults"])
   selected = projectContext.skill.use
   if selected and selected != "none" and selected in map["skills"]:
       selected_keys.add(selected)
   ```
   Stage only those. If the set is empty, write a manifest noting "no
   skills staged for this session" and exit cleanly.

6. **When does `rebuild_skills_map()` run?**
   - Always on server boot if the map is missing OR older than the
     newest skill directory's mtime (cheap stat check, no parse).
   - After a `skill-creator` execution completes (future hook).
   - Manual: a `POST /api/skills/rebuild-map` endpoint for ad-hoc.

7. **Back-compat for sessions created before this change**: the change
   only affects new card runs. The existing test session
   (`session_1779374245642`) already had all skills staged; that
   stays as-is. Next Intake → Execution on a NEW session uses the
   new path.

## Bloat impact

| Metric | Before | After |
|---|---|---|
| Skills staged per session workspace | 2 (all harness sources) | 0 to 1 (only the picked one) |
| Workspace bytes for the noob-test session | ~60 KB | ~30 KB (just logo-generator) |
| Skill text injected into Context Writer prompt | full SKILL.md of every staged skill | summaries + triggers only (~150 chars/skill) |
| Skill text injected into Execution prompt | governed by `requested_skill_keys` (substring match) | governed by `projectContext.skill.use` (Context Writer's pick) — P0.6 forced injection lands here naturally |

## Edge cases handled

- `skill.use: none` → workspace has zero staged skills. Manifest
  says so explicitly. Execution prompt's "skill context" block reads
  `No Gemma Forge skills are staged for this workspace.` (same as
  today when nothing was needed.)
- Context Writer picks a key not in the map → treated as `none`.
  Logged so a future rebuild can pick it up.
- User edits `skills-map.md` to remove a skill → that skill stops
  appearing in the Context Writer's choices, even if the SKILL.md
  still exists on disk. Clean "soft delete" without deleting files.
- New skill appears on disk between sessions → next server boot or
  next Intake run picks it up via the rebuild path (the
  mtime-newer-than-map check triggers a rebuild).

## What this does NOT change

- The `intake` (Project Context) card's reasoning template.
- The Execution card's main flow.
- Sessions created before the migration.
- The `skill-creator` plan in `skill-creator-plan.md` (the two land
  cleanly together — skill-creator just appends to skills-map.md when
  it authors a new skill).

## Decisions (locked)

1. **No `defaults:` field.** Forge Flow, GSD, SocratiCode, Axon,
   Verification, and Handoff are **cards** (built-in protocol steps
   with dedicated Python handlers), not skills. Cards always run.
   Skills are purely deliverable-specific and the Context Writer
   picks 0 or 1 per project. If `skill.use: none`, the workspace
   has zero staged skills and the cards still operate normally.
   Top-level frontmatter for skills-map.md is just
   `schema_version`, `generated_at`, `skills:`.

2. **Rebuild cadence: boot only.** New skills authored by
   `skill-creator` mid-uptime show up on the next `launchd`
   respawn. Per-Intake rebuilds were rejected because the small
   model runs Intake many times across a project's life and the
   per-run rebuild cost adds up; the boot-only path is cheaper and
   matches the "execution machine, not chatbot" product philosophy
   (decisions don't need to be live; they need to be deterministic
   and fast).

   - If a user creates a skill and wants it usable immediately,
     they can stop/start the harness — the `launchd` keep-alive
     respawn is sub-second.
   - Future option: expose `POST /api/skills/rebuild-map` for an
     ad-hoc rebuild without restart, if the workflow needs it.

## Implementation order

1. `SKILLS_MAP_FILE` + `rebuild_skills_map()` + `read_skills_map()` —
   boot-only; idempotent re-merge that preserves manual edits to
   `summary` / `triggers`.
2. Context Writer prompt: pass parsed map entries (key / name /
   summary / triggers / deliverable) in place of the current full
   `staged_skills` list. Drops ~10 KB of irrelevant SKILL.md text
   from the prompt.
3. `prepare_workspace_skill_context()`: stage **only** the skill
   named in `projectContext.skill.use` if it exists in the map.
   Zero skills staged if `skill.use: none`.
4. Manual rebuild endpoint deferred until a user workflow actually
   needs it.

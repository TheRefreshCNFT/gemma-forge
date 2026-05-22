# Plan: `skill-creator` — a skill that authors new skills

> Status: **planned, not started.** No source edits or skill files
> created. Awaiting scoping answers below.

## Why this is the right shape

The harness already loads skills from
`discover_installed_skills()` and stages them into the workspace via
`prepare_workspace_skill_context()`. Creating a new skill at runtime
just means writing a `SKILL.md` (+ optional OUTPUT.md / references /
examples) into one of the existing `skill_install_roots()`. The
discovery walk re-runs every Project Context / Execution call, so the
new skill is visible to the very next session with no restart.

That means **the entire feature can ship as a skill, not a new card**.
The harness gets exactly one small Python change: when
`deliverable.type == "skill"`, route the GFORGE_FILE writes to the
skill install root instead of the per-session workspace. Everything
else — prompt assembly, parsing, validation, repair retry — already
works.

## Tree structure each new skill follows

```
~/.gforge/harness/skills/<skill-key>/
├── SKILL.md           # YAML frontmatter + narrative
├── OUTPUT.md          # strict format contract (loaded first by the harness)
├── references/        # optional, one .md per topic
├── examples/          # optional, paired prompt + expected payload
└── assets/            # optional starter templates / fixtures
```

`<skill-key>` is the slugified skill name (lowercase, dashes), matching
the existing `normalize_skill_key()` rule.

## SKILL.md frontmatter shape (skill-creator emits this)

```yaml
---
name: <human-readable, title case>
key: <slug; matches normalize_skill_key(name)>
version: 0.1.0
description: >
  One paragraph describing when this skill triggers and what it
  produces. Keep it specific so the Project Context Writer can match
  intent reliably.
triggers:                       # phrases the planner-driven activation can match
  - <phrase>
  - <phrase>
deliverable:                    # default deliverable; Context Writer can override per-request
  type: design_deliverable      # one of: code | doc | design_deliverable | analysis | research
  format: svg                   # one concrete format
  count_default: 3
  path_pattern: output/<thing>-NN.<ext>
  encoding: gforge_file_block
  anti_deflection: |
    <one paragraph telling downstream small models they CAN produce
    this format directly and must NOT redirect to external tools.
    Tailor to the format: SVG-specific text for svg, code-specific
    text for code, etc.>
constraints:
  hard_requirements:
    - <bullet>
    - <bullet>
  forbidden:
    - <bullet>
created_by: skill-creator
created_at: 2026-05-21T14:42:00Z
---

# <Name>

<One-paragraph human-facing description.>

## Workflow

1. ...
2. ...

## Common patterns

- ...
```

## OUTPUT.md shape (skill-creator emits this too)

This is the file `read_skill_prompt_snippets` loads first into the
Execution prompt. It must:

- Restate the deliverable format and anti-deflection anchor in <500 chars.
- Show ONE worked example: a representative user request plus the
  exact GFORGE_FILE block payload the harness expects.
- List hard format rules ("paths relative to workspace; do not
  escape; one file per GFORGE_FILE block; no markdown fences around
  blocks").

```markdown
# Output contract: <skill name>

## Format binding
- encoding: gforge_file_block
- path_pattern: output/<thing>-NN.<ext>
- count: <number, or per Project Context deliverable.count>

## Anti-deflection
<paragraph from frontmatter, restated>

## Worked example

Input — Project Context surface_ask:
> "<example user request>"

Expected output payload:

```
SUMMARY:
...

FILES:
<<<GFORGE_FILE:output/example-01.<ext>>>>
<file content>
<<<END_GFORGE_FILE>>>

VERIFICATION:
- <check>
- <check>
```
```

## How a user triggers it

> *"create a skill that generates favicons for websites"*

Project Context Writer infers:
- `project.type = code`
- `intent.surface_ask = "create a skill that generates favicons for websites"`
- `deliverable.type = skill`
- `deliverable.format = skill_bundle`           # new format value
- `deliverable.path_pattern = ~/.gforge/harness/skills/favicon-generator/`
- `skill.use = skill-creator`
- `acceptance: [SKILL.md exists and parses, OUTPUT.md exists, ...]`

Execution then runs with the `skill-creator` skill staged. The
Execution prompt sees the new skill-creator's OUTPUT.md, which tells
the model exactly which sub-files to emit and how to structure
SKILL.md frontmatter for the new skill.

## What the skill-creator skill ships with

Files I would create under `~/.gforge/harness/skills/skill-creator/`:

- `SKILL.md` — frontmatter declaring triggers (`create skill`, `add a
  skill`, `make a skill that`), deliverable: `{type: code, format:
  skill_bundle}`, anti_deflection anchor explaining that skills are
  just text files (no codegen tooling needed), and a 4-phase workflow
  (Intent → Schema → Worked example → Validate).
- `OUTPUT.md` — the binding contract. One worked example of building a
  small skill from a one-line user ask. Hard rule: every new skill
  MUST include `SKILL.md` (with full frontmatter) and `OUTPUT.md` and
  at least one `examples/` file.
- `references/skill-structure.md` — canonical tree layout + a list of
  every frontmatter field the harness reads
  (`discover_installed_skills`, `requested_skill_keys`,
  `read_skill_prompt_snippets`) so the model knows which fields are
  binding vs. optional.
- `references/anti-deflection-snippets.md` — pre-written
  anti-deflection paragraphs per format (svg, html, markdown, python,
  json, shell, plain-text). The model picks the right one when
  authoring a new skill.
- `examples/favicon-generator.txt` — a worked example: input "make a
  skill that generates 3 favicons" → output GFORGE_FILE payload
  containing `SKILL.md`, `OUTPUT.md`, one references file, one
  examples file. ~3 KB total.
- `examples/markdown-readme-writer.txt` — second worked example for a
  different deliverable type (doc/markdown) so the model has variety.

## Harness changes required (small)

1. **New `deliverable.format` value: `skill_bundle`.** In
   `validate_project_context()`, allow this value (the existing
   validator already accepts any non-empty concrete string).

2. **Route writes to the skill install root when
   `deliverable.type == "skill"`.** New helper
   `resolve_skill_install_path(session, context)` returns
   `~/.gforge/harness/skills/<slug>/`. `execute_model_authored_project`
   checks `context.deliverable.type` and uses that path instead of
   `resolve_execution_workspace`. ~30 lines.

3. **Safe-path guard.** `safe_skill_install_relative_path(root, path)`
   refuses absolute paths, parent traversal, anything outside the new
   skill dir, and refuses to overwrite an existing skill unless
   `--force` was set (Context Writer would set
   `constraints.allow_overwrite: true` only when user said "replace"
   or "overwrite").

4. **Post-write validation.** After the bundle is materialized,
   re-parse the new SKILL.md frontmatter; if `name`, `description`,
   `deliverable.format` are missing, validation fails and the
   existing repair loop kicks in. No new code needed — the existing
   `validate_model_authored_workspace` is extended with a
   `validate_skill_bundle()` branch.

5. **(Optional, P1)** Append the new skill to a
   `~/.gforge/harness/skills/INDEX.md` for human discoverability.

## What this does NOT change

- The `intake` (Project Context) card.
- The Execution card's main flow.
- The skill discovery / staging mechanism.
- The auto small-model review pass.

The intent is to keep the bar low: a skill is a folder of files;
creating one is just writing files; the harness already writes files;
therefore creating a skill is execution with a different target dir.

## Test path when implementing

1. Create skill-creator skill files by hand (or one-shot via gemma4
   with a careful prompt — but the contest-authentic path is the
   model authoring under the harness).
2. Fresh session: `"create a skill that generates a project README
   from a one-line description"`.
3. Verify: Project Context picks `skill.use = skill-creator`,
   `deliverable.type = skill`, `path_pattern` points at the install
   root. Execution writes `~/.gforge/harness/skills/readme-writer/`
   with `SKILL.md` + `OUTPUT.md` + at least one example.
4. Restart not required. Open a second session with `"write a README
   for a new Python CLI tool called fooctl"` and confirm the new
   skill gets staged into the workspace and its OUTPUT.md flows into
   the Execution prompt.

## Open scoping questions for the user

1. **Install root for new skills**: global
   (`~/.gforge/harness/skills/`) or per-project
   (`<project>/.gforge/skills/`)? Global default sounds right, but
   you may want to keep project-specific skills isolated.
2. **Overwrite policy**: by default refuse to clobber an existing
   skill; require the user to say "replace the X skill" for the
   Context Writer to set `constraints.allow_overwrite: true`. Or
   always allow with a confirmation in the UI.
3. **Examples folder content**: should the skill-creator always
   produce at least one `examples/<example>.txt` for any new skill,
   or only when the user explicitly asks for examples? Always-on
   would force the model to think about a worked case, which helps
   tiny models downstream.
4. **Built-in seed skills**: alongside skill-creator, do you also
   want pre-shipped: `favicon-generator`, `readme-writer`,
   `webpage-generator`, `slides-writer`? They're cheap to add and
   give the contest demo more "look how composable this is."

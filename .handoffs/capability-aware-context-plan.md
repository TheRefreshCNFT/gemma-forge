# Plan: Capability-aware Context Writer + deterministic claim validators

> Status: **planned, not started.** This closes the
> "model role-plays completion" gap surfaced by session_1779383945445.

## Background

The forge.md hard rule already forbids it:

> "Do not claim a staged skill script, external API, image model, or
> shell command ran unless the harness actually ran it. If a tool is
> skipped, host-assisted, unavailable, or degraded, state that exact
> status and why."

But the rule isn't enforced. In session_1779383945445 the user asked
the harness to:

1. Clone `github.com/CodeNameNoah/Custom-SVG-Logo-Generator`
2. Research 5 sites about SVG logos
3. Create a skill for the cloned tool
4. Use that skill to produce 10 SVG logos

The harness has no git-clone, no web-fetch, no shell-exec, no
skill-authoring tool. The model role-played all four. The auto-review
(also a model) confirmed the role-play with `confidence: high`. Only
piece that was real: the 10 SVG files (which the existing validator
checks).

## Two-part fix

### Part A — Capability-aware Project Context

Inject a `harness_capabilities` block into the Context Writer's prompt
listing what the harness actually CAN and CANNOT do. The Writer's
schema gains a top-level `capabilities_required:` field; the Writer
populates it with every capability the request implies. If any
required capability is in the CANNOT list, the contract:

- Adds an `open_questions:` item explaining the gap.
- Sets `deliverable.partial: true` and `deliverable.scope` describes
  the subset of the request the harness can actually finish.

Sample additions to the Writer's prompt:

```
The harness CAN:
  - emit files into the workspace via GFORGE_FILE blocks
  - run pre-installed local skills staged from ~/.gforge/harness/skills/
  - call the local Gemma model via Ollama
  - read forge.md and your own staged skill files

The harness CANNOT (do not promise these in the contract):
  - clone arbitrary GitHub repos
  - browse the web / fetch external URLs
  - install packages or run shell commands on the user's system
  - call external paid APIs (Gemini, OpenAI, Midjourney, etc.)
  - create new skills mid-session (skill-creator is planned, not yet shipped)

If the user's request needs any CANNOT-capability:
  - capabilities_required: [list them]
  - open_questions: ["The request asks for X but the harness cannot Y. Reduce scope to Z, or run Y manually first."]
  - deliverable.partial: true
  - deliverable.scope: <what we CAN deliver>
```

### Part B — Deterministic claim validators

Extend `validate_model_authored_workspace()` to check load-bearing
claim strings against the filesystem before letting validation pass.

Implementation:

1. Read the YAML contract's `acceptance:` list AND scan the model's
   `verification:` / `notes:` / `summary:` text for claim phrases.
2. For each recognized claim pattern, run a deterministic check:

| Claim pattern | Check |
|---|---|
| `installed (repo \|tool) <name>` | `find ~ -maxdepth 5 -iname "*<name>*" -type d` returns ≥1 hit |
| `cloned <url>` | the URL's basename exists as a directory under a known root |
| `created skill <name>` | `~/.gforge/harness/skills/<slug>/SKILL.md` exists and parses |
| `researched N sites` / `gathered N references` | a research artifact exists AND contains ≥N URL strings |
| `ran (command \|script) <X>` | the artifact contains the command's actual stdout/stderr block |

3. If any check fails, append a precise failure to `validation.failures`:
   ```
   "Model claimed 'installed Custom-SVG-Logo-Generator' but no directory
   matching that name exists on disk. The harness has no git-clone
   tool — this claim is fabricated."
   ```
4. Auto-review prompt gets a new directive: "Reject any finding that
   contradicts validation.failures. Do not say 'passed: true' when the
   harness validator flagged a fabricated claim."

### File touches

- `chat/server.py`:
  - Extend `build_project_context_prompt()` with the
    capabilities block (~40 lines).
  - Extend `validate_project_context()` to recognize
    `capabilities_required` and `deliverable.partial`.
  - Add `extract_load_bearing_claims(metadata)` (~50 lines).
  - Add `validate_claims_against_filesystem(claims)` (~80 lines).
  - Wire into `validate_model_authored_workspace`.
- `chat/server.py` (review prompt):
  - Add "Validator-flagged fabrications cannot be overridden" rule to
    the small-model review prompt.

## What this does NOT change

- The Context Writer's deliberation flow.
- The Execution prompt template.
- Card orchestration.
- The skill-creator plan (still needed; the capability block names
  it as the future path for users who want skills generated).

## Test path

1. Re-run the failed session's prompt: ask for clone+research+skill
   create+10 logos.
2. Expected new behavior:
   - Context Writer puts `capabilities_required: [git-clone, web-fetch,
     skill-author]` and `open_questions: ["The harness cannot clone
     external repos, browse the web, or author new skills yet. Reduce
     scope to: generate 10 SVG logos using the existing logo-generator
     skill."]`.
   - The card flow either pauses for the user (because open_questions
     is non-empty) OR proceeds against the partial scope and the
     handoff explicitly says "External tool was NOT installed; 10
     logos generated using logo-generator skill alone."
   - Auto-review confirms the partial scope honestly.

## Why this matters for the contest

The authenticity rule is the load-bearing pillar of the submission.
A demo that quietly fabricates work (then ships logos as if everything
worked) is a credibility hit if judges look at the artifacts. Closing
this gap is non-optional for the contest pitch.

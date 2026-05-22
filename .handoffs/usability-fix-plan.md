# Gemma Forge — Usability Fix Plan

> Status: **planned, not started**. Backups taken at `/Users/webot/Backups/gemma-forge/20260521T135622Z-pre-usability/`. No source edits made.

## Background

A `logo-generator` skill run failed end-to-end. The post-mortem agent
inside the harness concluded "the model is guessing the output format
rather than following a verified schema" and asked for internet research
on the skill API. That diagnosis is wrong, and the wrongness is itself
a usability bug — when the harness mis-classifies its own failures,
downstream agents (good or bad) chase the wrong fix.

The real failure is a stack of small things that each amplify the
previous one. This document captures the full picture, the prioritized
fix list, and the exact files / line numbers to touch.

## Evidence trail (verified)

- `/Users/webot/.gforge/harness/logs/errors.jsonl` — five
  `ReadTimeout (read timeout=60)` errors on Ollama port 11434, last four
  against `gemma4:31b-max` (19.8 GB).
- `chat/server.py:1289-1297` — `call_ollama()` uses a hardcoded
  `timeout=60`, no `keep_alive`, no retry. A 19.8 GB model often can
  not finish loading + emitting a multi-file project payload in 60 s.
- `chat/server.py:1302-1305` — on timeout / exception, `call_ollama()`
  returns the polite English string:
  > "I could not reach the local Gemma 4 model yet. The harness is
  > ready to plan once Ollama is running and the default model is available."
  That string contains no GFORGE_FILE blocks and no JSON, so
  `parse_forge_file_payload()` and `parse_json_response()` both
  produce empty file lists. The downstream agent sees
  `files: []` and concludes "the model wrote a bad schema" — but the
  model never wrote anything.
- `session-data/session_1779370542607/execution.md` — captures the
  resulting "0 model-authored files" verdict, mis-attributed.
- `harness/skills/logo-generator/SKILL.md` — tells the model to call
  `scripts/svg_to_png.py` and the Gemini / Nano Banana API to make a
  showcase. A local Ollama model has neither tool execution nor
  external network egress from inside the harness payload. So when the
  skill DID get injected (it does, via the
  `requested_skill_keys()` match on the string "logo-generator" in the
  user project text), the model was told to do things it can't, with no
  fallback offline path.
- `chat/server.py:3010-3040` — the Project Execution prompt offers
  **two** output formats (GFORGE_FILE block + strict JSON), then names
  one "Preferred" and one "also accepted". Small models mix syntaxes
  mid-response under that instruction.
- `chat/server.py:3014-3020` — the in-prompt example is hardcoded
  `index.html` + `styles.css`. The model is anchored to webpage output
  even when the task is "6 SVG logos".

## Decisions (recorded)

- **Demo model:** `gemma-4` (E2B, ~3.4 GB). The 31B max model stays an
  opt-in lane but is not the recommended default.
- **Scope:** Full P0 + P1 + P2.
- **Backups:** Done at `/Users/webot/Backups/gemma-forge/20260521T135622Z-pre-usability/`.

## P0 — Make the model actually answer

### P0.1 `call_ollama` overhaul — `chat/server.py:1286-1305`

- Bump `timeout` to **600** s (cover cold-load + long generation).
- Pass `keep_alive: "30m"` in the request body so the model stays warm
  for the rest of the session.
- Pass `options: {temperature: 0.2, num_ctx: <prompt-sized>}`.
- Pass `options.num_predict: 8192` (or whatever the planner declared
  budget is) so long file payloads don't get truncated.
- Single transparent retry only on `ConnectionError` (not on
  `Timeout`, not on `HTTPError`).
- On real failure, **raise a typed exception** (`OllamaUnreachable`,
  `OllamaTimeout`, `OllamaEmpty`) — do NOT return a polite English
  string that re-enters parsers.

### P0.2 Typed transport errors — `chat/server.py:659-667`, validation reporting

- `call_ollama_execution_payload()` returns
  `(payload, raw, transport_status)`. `transport_status` is one of
  `ok | timeout | unreachable | empty | parse_failed`.
- `validate_model_authored_workspace()` and `execution.md` writer
  must surface `transport_status` distinctly from
  `model-authored execution returned no writable files`. A timeout is
  not a schema failure; the verification doc should say so.
- UI: show transport status in the card panel (the user, and any
  agent reading the artifact, should see "Ollama timed out at 600 s
  loading gemma4:31b-max").

### P0.3 One canonical output format for execution — `chat/server.py:2995-3049`

- Drop the JSON alternative from the *execution* prompt. Block format
  only (the GFORGE_FILE block is far better for SVG/HTML/CSS where
  JSON escaping is hard for small models).
- Keep JSON for `plan` and `review` prompts — those produce short
  structured objects, not file bodies.
- Task-aware in-prompt example: classify the user's project text
  (logo/SVG → `output/logo-01.svg`; webpage → `index.html`; CLI →
  `tool.py`). One example, the right one. Avoid biasing toward
  webpages.

### P0.4 Logo-generator skill rewrite — `~/.gforge/harness/skills/logo-generator/`

- Add a new `OUTPUT.md` (loaded *before* SKILL.md by the harness; see
  P0.5). Content: explicit "you have no tool execution; emit raw SVG
  inside GFORGE_FILE blocks; here is the exact format; here is one
  worked example."
- Trim SKILL.md to remove imperative references to
  `scripts/svg_to_png.py` and the Gemini / Nano Banana API in the
  *primary* workflow. Move those into a clearly-labeled
  "Optional post-processing (requires API key, not run by the model)"
  section.

### P0.5 Skill prompt order — `chat/server.py:395-424`

- `read_skill_prompt_snippets()` currently loads `SKILL.md` first,
  then `references/`, then `assets/`. Change to load `OUTPUT.md`
  first (if present), then SKILL.md, then references/assets. Same
  14000-char total budget, but the first 500 chars now carry the
  binding format contract instead of design philosophy.

### P0.6 Skill activation hint (don't make it depend on the user) — `chat/server.py:271-283`, `1308+`

- Keep current substring auto-detection.
- Plus: the **planner** prompt (`build_planning_prompt`) is told it
  may emit `requestedSkills: [...]` in its return. The harness reads
  that and forces injection of those skills' content into the next
  Execution prompt.
- Net: a user who says "design 6 logos for WeBot" no longer has to
  type the literal string "logo-generator". The planner picks the
  skill on the user's behalf.

## P1 — Failure visibility & repair correctness

### P1.1 Repair loop guard — `chat/server.py:1553-1583`

- If the prior failure's `transport_status != ok`, the repair branch
  must **retry the same prompt** (after a short backoff), not invoke
  `run_post_review_repair()`. Post-review repair re-prompts the model
  with "fix these findings" — meaningless when the model never spoke.

### P1.2 Findings-as-format-coach — `chat/server.py:1594-1621`

- When the model produced text but 0 files, the repair prompt must
  quote the model's actual output back to it (first 400 + last 200
  chars) and say: "Here is what you wrote. Here is the exact format
  the harness needs. Copy this format and try again." Include one
  GFORGE_FILE example with content that matches the task class
  (SVG / HTML / code).

### P1.3 Distinct verification artifact fields — `chat/server.py:2095-2150`

- `execution.md` and `verification.md` writers must emit explicit
  fields for `transportStatus`, `parseStatus`, `filesWritten`,
  `validationFailures`. Today these collapse into one "0 files" line
  that is ambiguous.

## P1 — First-run & model selection ergonomics

### P1.4 Warm-up on session create — `chat/server.py` (POST `/api/sessions`)

- After persisting the new session, fire-and-forget a 1-token Ollama
  request with `keep_alive: "30m"` for the selected model. Eliminates
  cold-start latency on the first real card run.

### P1.5 Recommend gemma-4 (E2B) — `model-route.json`, planning UI

- Switch `harness/model-route.json` default from `gemma4:31b-max` to
  `gemma-4`. Existing 31B selection stays available in the picker.
- Settings → Forge Brain explainer: "Default `gemma-4` (E2B, 3.4 GB)
  is the smallest Gemma 4 lane and the contest authenticity baseline.
  Larger models are opt-in for harder projects."

### P1.6 UI loading state — `chat/static/js/chat.js`, `chat/templates/index.html`

- During a card run, show "Loading <model> (~30 s on first call) ..."
  while the request is in flight. Stop conflating "still running" with
  "stuck".

## P2 — Polish

### P2.1 Settings → Last 5 Ollama exchanges

- New Settings panel showing the last 5 `(prompt, raw_response, model, ms,
  transport_status)` exchanges. The agent that wrote the wrong
  research note today had no way to see what Ollama actually said —
  fix that.

### P2.2 `examples/` per skill

- Each skill ships an `examples/` dir with paired
  `prompt.txt` + `response.gforge` files. Used both as docs and as
  few-shot prompt material when the planner activates the skill.
- Seed: logo-generator gets one worked example showing a 3-logo
  payload in GFORGE_FILE format.

### P2.3 Reviewer hardening — `chat/server.py:1859-1940`

- For small-model runs (≤8B), instruct the reviewer to "fail closed
  on ambiguity" — if any acceptance criterion can't be verified from
  the workspace, mark `passed: false` and put the unverifiable item
  in `findings`. Today the reviewer can drift positive on missing
  evidence.

## Files this plan will touch

- `chat/server.py` — multiple sections (lines listed above)
- `chat/static/js/chat.js` — loading state, settings panel
- `chat/templates/index.html` — settings panel HTML
- `~/.gforge/harness/skills/logo-generator/SKILL.md` — trim + restructure
- `~/.gforge/harness/skills/logo-generator/OUTPUT.md` — NEW
- `~/.gforge/harness/skills/logo-generator/examples/` — NEW dir
- `~/.gforge/harness/skills/ui-ux-pro-max/OUTPUT.md` — NEW (same shape, different task class)
- `~/.gforge/harness/model-route.json` — default switch
- `~/.gforge/harness/forge.md` — recommendation language update

## Files NOT touched

- Anything under `~/.ollama/`
- Mainnet / submission documents
- Any committed Gemma model file
- `~/.gforge/harness/forge.md` content beyond the model recommendation line

## Out of scope for this plan

- Adding a brand-new skill (just fix the existing ones).
- Replacing Ollama with anything else.
- Touching the model-forging GUI in `src/`.
- Changing the React-less plain-JS UI architecture (works fine, focus
  on the failure modes that touch the user).

## How to verify when done

- Wipe `~/.gforge/harness/session-data/`, start a fresh project, ask:
  `"Design 6 SVG logos for WeBot Agency, AI/tech vibe"`.
- With `gemma-4` (E2B) selected, run Full Forge.
- Expect: workspace has `output/logo-01.svg` … `output/logo-06.svg`
  on disk, each parseable as SVG, no GFORGE_FILE delimiters left in
  the file contents, `validation.passed = true`, `transportStatus = ok`.
- Compare against the failed session at
  `~/.gforge/harness/session-data/session_1779370542607/`.

## Authenticity rule check

This plan does not pre-bake, fake, force, template, or hardcode
deliverables. Every fix changes prompts, error handling, or
documentation injected into the model's context — none of it produces
files behind the model's back. The verification step above relies on
the live local Gemma model writing the SVGs through the harness.

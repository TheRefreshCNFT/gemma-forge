# Plan: Handoff & active-state file rotation

> Status: **planned, not started.** Awaiting Ian's go-ahead. Will
> NOT add a default user-memory system per product philosophy
> (`project_gemma_forge_philosophy.md`).

## Why

The harness writes a growing pile of artifacts as a project runs:

- `~/.gforge/harness/session-data/<id>/<card>.md` — one per card run
- `~/.gforge/harness/session-data/<id>/project-context.md` — the
  per-session conversational log (appends on every turn)
- `<project>/.handoffs/CURRENT_STATE.md` — project-level handoff,
  appends on every "Shipped this session" entry
- `<project>/.handoffs/<id>.md` — per-issue handoffs
- (future) `<project>/ACTIVE_STATE.md` — what's now / what's next

When a long-running project burns through agent context windows,
these files grow past the size where a small model can usefully
re-read them on each card run. The agent ends up either skipping
them (loses ground truth) or re-reading them and losing the budget
for the actual task.

Solution: rotate. When a tracked file exceeds the threshold, rename
the old copy with a UTC timestamp suffix, write a fresh file headed
by a model-generated summary plus a pointer back to the archive, and
let agents pick up from the summary.

## Files in scope (rotation candidates)

| File | Reason | Threshold |
|---|---|---|
| `<project>/.handoffs/CURRENT_STATE.md` | Append-heavy ("Shipped this session" entries) | 32 KB |
| `<project>/.handoffs/<issue>.md` | Per-issue working notes | 32 KB |
| `<project>/ACTIVE_STATE.md` (when added later) | Live "what's now / what's next" | 16 KB |
| `~/.gforge/harness/session-data/<id>/project-context.md` | Per-turn conversational log | 32 KB |
| Card artifacts (`intake.md`, `execution.md`, ...) | Single-shot card writes | **out of scope** |

Card artifacts (intake.md, execution.md, verification.md, etc.) are
single-shot writes per card run, not append-heavy. They stay
as-is. Only the genuinely accumulating files rotate.

## Rotation procedure (deterministic)

When `os.path.getsize(path) > threshold`:

1. `archive_path = .handoffs/archive/<basename>.<UTC-ISO>.old.md`
   (e.g. `CURRENT_STATE.20260521T143200Z.old.md`)
2. `os.makedirs(os.path.dirname(archive_path), exist_ok=True)`
3. `os.rename(path, archive_path)` (atomic on the same filesystem)
4. Run a **summarization call** through the local Gemma model:
   - Prompt: read the archived file, produce a 200-word "where we
     left off" summary covering: project goal, current status, last
     verified action, what's next, any DO-NOT-TOUCH items.
   - Use `call_ollama_with_transport` with
     `options_override={"temperature": 0.1, "num_predict": 1024}`.
   - Same authenticity rule as everything else: it's the local
     Gemma model doing the work.
5. Write the new file with:
   ```markdown
   # <Original Title>

   > **Auto-rotated 2026-05-21T14:32Z.** Previous content archived to
   > `archive/CURRENT_STATE.20260521T143200Z.old.md`. Read that file
   > if you need the full history.

   ## Where we left off

   <model-generated 200-word summary>

   ## Picking up from here

   <empty section, next agent append continues here>
   ```
6. If the summarization call fails (transport != ok), DO NOT lose
   data: leave the archive in place, write a stub new file that
   says "rotation summary unavailable, see archive/", and surface
   the transport status. Never delete the archive without a verified
   summary.

## Where the check fires

A single helper `rotate_if_needed(path, threshold, model)` called at:

- Top of every card handler that writes to a tracked file
  (`write_handoff_entry`, `append_project_context_log`, etc.).
- Right before any `write_artifact` that targets a rotation
  candidate.

Per-call cost when no rotation needed: one `os.path.getsize` (sub-
millisecond). Negligible.

Per-call cost when rotation fires: one Gemma call (~5–15 s on
gemma-4 E2B at 1024 num_predict). Happens once per ~32 KB of
appends. Acceptable.

## Files this would add / modify

- New module-level constants in `chat/server.py`:
  ```
  HANDOFF_ROTATION_THRESHOLD = 32 * 1024
  HANDOFF_ARCHIVE_SUBDIR = "archive"
  HANDOFF_ROTATION_SUMMARY_NUM_PREDICT = 1024
  ```
- New function `rotate_if_needed(path, threshold, model, title)`
  with the procedure above.
- Call sites: append/write helpers for CURRENT_STATE.md,
  per-issue handoffs, ACTIVE_STATE.md, and session-data/.../
  project-context.md.

## What this is NOT

- **Not a memory system.** Per `project_gemma_forge_philosophy.md`,
  Gemma Forge is not a chatbot that "knows" the user. Rotation
  exists purely so agents in long-running *single projects* don't
  drown in their own log files.
- **Not cross-project.** Each project's `.handoffs/` rotates
  independently. Nothing aggregates across projects.
- **Not retroactive.** Existing oversized files stay until the next
  write touches them; they rotate at that point. No mass-migration
  job.

## If the user later wants persistent memory

Per philosophy doc: the user can ask the harness to **build them**
a memory system as a project deliverable (e.g. "create a skill
that maintains a personal-notes file across my projects"). The
harness ships without one.

## Open scoping question

- **Threshold value.** 32 KB ≈ 8K tokens at conservative
  encoding; comfortably fits in any modern model's working
  context. Larger (64 KB) means fewer rotations; smaller (16 KB)
  means tighter handoffs but more rotation calls. Recommendation:
  32 KB for CURRENT_STATE/handoffs, 16 KB for ACTIVE_STATE (which
  is meant to be a live "what's now" snippet, not a log).

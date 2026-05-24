---
name: webot-flow
description: Project orientation and verification workflow for Gemma Forge. Use when a project needs repository state checks, handoff/context reading, pre-change backup discipline, implementation verification, or final handoff notes.
keywords:
  - forge flow
  - webot flow
  - project orientation
  - handoff
  - current state
  - backup
  - verification
  - verify before done
---

# Webot Flow

Use this skill when work touches an existing project, repository, live
workspace, or user-owned files.

## Workflow

1. Read the project state docs that exist in the workspace, prioritizing
   `AGENTS.md`, `.handoffs/CURRENT_STATE.md`, `ACTIVE_STATE.md`,
   `HANDOFF.md`, and `project-map.md`.
2. Check the branch, working tree, and relevant runtime status before making
   changes.
3. Make a targeted pre-edit backup before changing important files.
4. Apply the smallest patch that satisfies the request.
5. Verify the result with read-back checks, tests, or real runtime behavior.
6. Record handoff notes when the project state materially changes.

## Rules

- Do not overwrite user changes.
- Do not claim success from HTTP status alone when visual or behavioral proof is
  required.
- Keep live/runtime data out of installable source repositories.
- If a required dependency or environment step cannot be completed, stop and
  report the blocker plainly.

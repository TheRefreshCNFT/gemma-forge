---
name: socraticode
description: Semantic codebase exploration workflow for finding relevant files, indexing a codebase, querying context, and mapping dependencies through SocratiCode MCP.
keywords:
  - socraticode
  - semantic search
  - codebase search
  - codebase exploration
  - code graph
  - dependency graph
  - index codebase
  - mcp search
---

# SocratiCode

Use this skill when the task is about understanding or navigating an existing
codebase.

## Workflow

1. Check that SocratiCode MCP is ready.
2. Index the target project before searching.
3. Use semantic search to identify the smallest relevant file set.
4. Use graph/dependency context when impact or coupling matters.
5. Read only the narrowed file sections needed for the task.
6. Report whether the tool actually ran, degraded, or was skipped.

## Rules

- Do not claim SocratiCode ran unless the MCP call actually completed.
- Do not use semantic search as a substitute for final code/test verification.
- For exact strings or known identifiers, direct text search is acceptable.

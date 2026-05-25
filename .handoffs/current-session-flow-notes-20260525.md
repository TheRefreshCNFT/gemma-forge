# Current Session Flow Notes — 2026-05-25

Session observed: `session_1779728406786`
Model: `gemma-4-e4b-it`
Prompt class: GitHub operations skill-suite research gate
Workspace: `/Users/webot/.gforge/harness/session-data/session_1779728406786/workspace/github-operations-skill-suite-research`

## Flow Observed

- Project Context completed successfully and produced a good research-first contract.
- GSD completed and correctly planned research before skill-suite generation.
- Skill routing improved: GSD/Execution staged `scrapling-official` and `code-writer`.
- Execution did not emit any `browse` or `screenshot` events.
- `artifacts/model-execution.json` recorded:
  - `research.fetched: []`
  - `research.screenshots: []`
  - `skipped_reason: browse capability required but no source URLs could be inferred`
- The model wrote one file: `research/authoritative_references_summary.md`.
- Validation failed repeatedly and final Execution status was `needs-attention`.

## Failure Pattern

The harness gave the worker a valid source-backed contract but no real source evidence. The worker cannot actually call Scrapling from inside the model response; the harness must fetch/capture sources before the model writes. Since the broad research prompt had no explicit URLs, URL inference returned none and source acquisition skipped.

The repair loop then asked the model to fix missing research/screenshots even though the missing piece was harness-side source acquisition. The worker responded by rewriting a synthetic research summary with claimed screenshot paths, and validation correctly rejected the source screenshots.

## New Validator Issue Found

`validate_requested_source_evidence()` reports `researchArtifacts: 1` because it counts any `research/*.md` file on disk. In this session, that file was the model-authored deliverable, not a harness-fetched source artifact. This can mask the stronger failure: web research was required but zero harness-fetched source artifacts existed.

Adjustment needed: source-evidence validation should count only harness-fetched artifacts from `metadata.research.fetched` or a clearly separated source-evidence directory/manifest. Model-authored files under `research/` should not satisfy web research evidence.

## Adjustments For Next Test

1. Add a pre-execution source gate.
   If `web_browse` or `screenshot_capture` is required and the harness cannot infer/fetch enough source URLs, stop before model execution with a clear source-acquisition failure. Do not run model repair loops against missing harness evidence.

2. Add deterministic source-target acquisition for broad docs research.
   For prompts asking for authoritative references but no explicit URLs, the harness needs a source-target stage. Minimal contest-safe version: seed authoritative docs URLs for well-known domains/topics, especially GitHub operations. Broader later version: let Project Context/GSD emit a `source_targets` list of candidate URLs and have the harness fetch/validate them.

3. Separate model deliverables from source evidence.
   Keep harness-fetched source pages/screenshots in a manifest that validation trusts. A model-authored `research/*.md` deliverable should be judged as the output, not as proof that browsing happened.

4. Make reference-count validation evidence-aware.
   For `authoritative references`, count fetched source artifacts and/or URL/citation entries that correspond to fetched URLs. Do not count invented URLs or screenshot paths as evidence.

5. Stop impossible continuation repair.
   If validation failures are source-acquisition failures, the next action should be a harness fetch/screenshot step or a blocking note, not another model rewrite attempt.

6. Clarify phase continuation.
   The current contract interpreted this run as a research-only first phase, which is reasonable because the user said not to write the skill suite until the research artifact exists. After the research artifact validates, the harness needs a clean continuation into skill-suite creation rather than treating the research file as the whole project forever.

## Current Status

This was a useful test. The 25-cap patch is loaded, but this session did not exercise it because there were zero inferred source URLs. The next meaningful test needs either explicit URLs in the prompt or the source-target acquisition patch above.

## Patch Applied After This Observation

- Added a pre-model source-evidence blocker in Execution. If web research or source screenshots are required but the harness has zero successful fetched source artifacts/screenshots, Execution writes a blocked validation artifact and does not call Ollama for model-authored files.
- Source-evidence validation now trusts only `metadata.research.fetched` and `metadata.research.screenshots` entries that exist on disk. A model-authored `research/*.md` file no longer counts as proof that browsing happened.
- Added regression tests covering both behaviors.

## Follow-Up Patch After Blocker Test

- The first live run after the blocker correctly stopped before the worker model, but it still had no source URLs to fetch for the broad GitHub operations research prompt.
- Added deterministic GitHub operations source seeding for broad prompts that request GitHub authoritative references, citations, sources, rulesets, environments, branch protection, GitHub Apps/PATs, token scopes, Actions permissions, CodeQL, secret scanning, dependency review, runners, workflows, issues, PRs, Pages, or repo governance.
- The seed list currently provides 20 official GitHub Docs URLs, so a request for 10+ authoritative references can fetch/capture real source artifacts before model execution.
- Reference/citation/source quantity validation now counts distinct URL citations, not only generated documents.
- Verification after patch:
  - `.venv/bin/python -m unittest discover -s tests -p '*_test.py'` passed (`146 tests`).
  - `npm run check` passed.
  - `git diff --check` passed.
  - Direct URL inference sanity check returned 20 GitHub Docs URLs for the failed prompt class.
  - Harness restarted through `npm run harness:restart`; `npm run harness:status` reports PID `3931` listening on `127.0.0.1:5005` with endpoint OK.

## Context Writer Skill Patch

- Added a bundled internal `context-writer` skill at `skills/context-writer/SKILL.md`, synthesized from the useful context-engineering patterns in `muratcankoylan/Agent-Skills-for-Context-Engineering`: finite attention budget, progressive disclosure, filesystem-backed context, context degradation guards, structured output contracts, and restart-loop prevention.
- The Project Context prompt now loads this skill directly as the Writer's own operating skill.
- `context-writer` is blocklisted from downstream skill discovery/staging so `skill.use` cannot select it for Project Execution. It is a writer-role skill, not an implementation skill.
- Added explicit prompt rules that installable skill suites are bundled directories under `skills/<suite-slug>-NN/SKILL.md`, not flat `output/*.md` docs, and that repair attempts should use remaining-work context rather than full original context.
- Verification after patch:
  - Focused context-writer/retry/source-reuse tests passed.
  - `.venv/bin/python -m unittest discover -s tests -p '*_test.py'` passed (`152 tests`).
  - `npm run check` passed.
  - `git diff --check` passed.

# JavaScript Validation Fresh Session Handoff

Last updated: 2026-05-24

This is the pickup note for the next language-validation pass: JavaScript.
Read this after the standard project orientation files.

## Start Here

Required orientation:

- `.handoffs/CURRENT_STATE.md` - current repo/runtime state and project rules.
- `AGENTS.md` - Ian's operating instructions for Gemma Forge.
- `project-map.md` - structure, runtime paths, validation behavior, and service
  controls.
- `docs/python-verification-fine-tuning.md` - the original Python/PDF verifier
  pattern and the general porting checklist.
- `.handoffs/html-css-validation-followups.md` - the HTML/CSS pass, including
  false-negative fixes and user-confirmed behavior.

Latest pushed alignment before this handoff:

- Branch: `main`
- Commit: `16a64040b2c7099ac251413552516d939de066e1`
- Commit message: `Fix HTML CSS validation flow`
- SSD backup:
  `/Volumes/PHIXERO/Backups/gemma-forge/20260524T191659Z-full-live-local-working-state/`
  - Model cache intentionally omitted per Ian for that routine alignment backup.
  - Restore archive checksum passed.

## User-Verified Behavior To Preserve

Ian confirmed the HTML/CSS outcome is now correct:

- Good HTML/CSS code advanced through the flow to Handoff.
- Bad HTML/CSS code stopped for resolution.
- That is the desired baseline. Bad code should stop or enter the normal repair
  path. Do not invent a bypass just because a prompt is a canary unless the
  Project Context explicitly encodes that expected-failure intent.

The broken HTML/CSS test was not a verifier failure once the count bug was
fixed. The verifier had not been told it was an expected-failure test, so
stopping on bad code was correct.

## What Previous Agents Shipped

### Python/PDF Baseline

See `docs/python-verification-fine-tuning.md`.

Important behavior:

- Python deliverables are syntax-checked with `ast.parse`.
- Python script runtime side effects are validated only when the contract asks
  for them. The harness copies the script into a temp directory, runs it there,
  counts outputs, then deletes the temp run.
- Runtime-created files/directories are not treated as final deliverables unless
  the user explicitly asked for those outputs.
- Workspace command failures/skips are deterministic validation failures.
- Python package installs are workspace-local under `.gforge-installs/python`.
- PDF outputs must parse as real PDFs, not merely start with `%PDF`.
- Verification is read-only. It can inspect and rebuild reports, but it cannot
  mutate deliverables or rerun Project Execution.

### HTML/CSS Port

See `.handoffs/html-css-validation-followups.md`.

Important behavior:

- HTML is static/read-only validated with `HTMLIntegrityParser` and
  `validate_html_source`.
- CSS is static/read-only validated with `validate_css_source`, catching
  unclosed comments/strings and unbalanced braces/brackets/parentheses.
- Local-link validation still checks `href`, `src`, and `url()` references
  against disk.
- "One HTML page and one linked CSS file" is now one primary HTML deliverable
  plus a required CSS support file, not two HTML files.
- HTML content counts ignore CSS selector/comment text. "3 status cards" counts
  actual HTML `status-card` elements.
- Auto-generated execution workspace names now prefer compact Project Context
  names, e.g. `local-ai-validation-lab-dashboard`.

## JavaScript Goal

Port the same deterministic-validation discipline to JavaScript.

Minimum viable behavior:

- JavaScript deliverables (`.js`, `.mjs`, `.cjs`) get syntax validation.
- Syntax validation is read-only and must not execute user/model-authored code.
- Bad JavaScript blocks delivery or triggers the existing repair/resolution
  flow.
- Good JavaScript should pass deterministic validation and be allowed through
  Verification/Handoff.
- Context Writer, worker, and Verification should all preserve skill context and
  code-writer guidance for JS tasks.

Recommended first implementation:

- Use `node --check <file>` for JavaScript syntax validation.
- Run it through a bounded local command helper or `subprocess.run`, with a
  short timeout.
- Do not run arbitrary JS as part of syntax validation. `node --check` parses
  without executing the program.
- If `node` is unavailable, fail with a clear validator capability message
  rather than pretending JS was checked.

## Likely Code Touchpoints

Primary file:

- `chat/server.py`

Functions/areas to inspect first:

- `validate_code_file_integrity`
  - Python and HTML/CSS validation already live here.
  - Add the JS syntax gate here.
- `code_deliverable_files_for_extensions`
  - Reuse this for `.js`, `.mjs`, and `.cjs` files.
- `DELIVERABLE_FORMAT_EXTENSIONS`
  - Confirm JavaScript extensions are mapped as expected.
- `build_project_context_prompt`
  - Confirm prompt wording keeps JS as a text/code deliverable and does not
    treat support JS files as extra HTML files.
- `normalize_html_css_support_bundle_context`
  - Consider generalizing this into an HTML support-file normalizer if testing
    "one HTML page and one linked JS file".
- `validation_text_extensions`
  - HTML content counts already avoid CSS/JS support code. Preserve that.
- `validate_local_link_targets`
  - Existing HTML `src="app.js"` checks should continue to enforce local
    support-file existence.
- `build_verification_details` / `build_verification_report`
  - Verification already receives staged skill context. Do not regress this.

Tests:

- `tests/model_route_test.py`

## Suggested Tests

Start with focused unit tests before live runs.

Recommended tests:

- Valid JS primary deliverable passes:
  - `deliverable.format: javascript`
  - `path_pattern: app.js`
  - file content is syntactically valid JS.
- Invalid JS primary deliverable fails:
  - e.g. `function broken( {`
  - failure should include a clear `invalid JavaScript deliverable` message.
- HTML + linked JS support file does not become "two HTML files":
  - Request shape: one HTML page and one linked JS file.
  - Expected: one HTML primary deliverable plus JS support.
  - Local-link validation confirms `app.js` exists.
- Missing linked JS support file fails:
  - HTML contains `<script src="app.js"></script>`.
  - Metadata/files do not include `app.js`.
  - Existing local-link validation should fail.
- Good deterministic JS validation cannot be overturned by Verification review.
  - Preserve the Python/PDF/HTML/CSS rule: deterministic pass is authoritative
    for file count/path/syntax/content gates unless the reviewer identifies a
    concrete mismatch outside those gates.

Optional later tests:

- `.mjs` and `.cjs` syntax pass/fail.
- JS support file inside a small HTML/CSS/JS bundle.
- Workspace command failure remains authoritative when JS tasks explicitly ask
  for command execution.

## Suggested Live Test Prompts

Passing canary:

```text
Build a tiny JavaScript utility file named app.js. It should export a function
named summarizeStatuses(items) that returns an object with counts for ok,
warning, and failed statuses. Include no external dependencies.
```

Failing canary:

```text
Build a JavaScript file named app.js, but intentionally leave a syntax error
such as an unclosed function parameter list. This should demonstrate that the
harness rejects invalid JavaScript.
```

HTML support-file canary:

```text
Build one HTML page named index.html and one linked JavaScript file named app.js.
The page should have one button and app.js should add a click handler that
updates a status text. No external assets or CDNs.
```

Expected behavior:

- Passing canary advances.
- Failing canary stops or repairs through normal flow unless explicitly marked
  as an expected-failure validation test in Project Context.
- HTML support-file canary should not fail by expecting two HTML files.

## Guardrails

- Do not broaden runtime execution for all JavaScript by default.
- Do not run arbitrary JS just to validate syntax.
- Keep package installs workspace-local if a later patch enables Node dependency
  handling.
- Keep `Verification` read-only.
- Keep deterministic failures actionable and specific. Bad syntax should name
  the file and show the relevant `node --check` error line when possible.
- Do not push runtime/private harness data to GitHub:
  `.gforge/`, `.axon/`, `chat/session-data/`, session/model JSON, `.venv/`,
  raw recordings, caches, model weights, `.DS_Store`, and AppleDouble files stay
  local/SSD-only.

## Completion Criteria For The JS Patch

- Focused JS unit tests pass.
- Existing Python/PDF and HTML/CSS validation tests still pass.
- `.venv/bin/python -m unittest discover -s tests -p '*_test.py'` passes.
- `npm run check` passes.
- `git diff --check` passes.
- Live harness is restarted through `npm run harness:restart` if code changes
  need to be exercised in the UI.
- A good JS task advances through the flow.
- A bad JS task stops or enters normal repair/resolution instead of being
  incorrectly accepted.

## Implementation Status

Completed locally on 2026-05-24:

- `chat/server.py` now validates `.js`, `.mjs`, and `.cjs` files with
  `node --check` without executing model-authored JavaScript.
- Missing `node` is reported as a validator capability failure instead of being
  silently skipped.
- HTML support-file bundle handling now treats linked JavaScript like linked CSS
  so `index.html` plus `app.js` remains one primary HTML deliverable with a
  required support file.
- Focused unit tests cover valid JS, invalid JS, missing Node, HTML+JS support
  count normalization, missing linked JS local-link failure, and Project Context
  JS support-file enrichment.
- Verification run before live restart: focused JS tests passed;
  `.venv/bin/python -m unittest discover -s tests -p '*_test.py'` passed
  (108 tests); `npm run check` passed; `git diff --check` passed.
- Live restart verification: `npm run harness:restart` reloaded launchd but its
  immediate helper probe returned before port 5005 was ready. Follow-up
  `npm run harness:status` verified launchd PID `505` listening on
  `127.0.0.1:5005`; harness root, `/api/workspace/status`, and
  `/api/model/route` returned `200`/valid JSON. The legacy PID file remained
  stale at `86092`, so launchd/port ownership is authoritative.

Follow-up completed locally on 2026-05-24 after Ian's two live JS canaries:

- Pure `app.js` utility canary passed the harness and a direct functional
  `node` import test.
- HTML+JS canary produced working code but hit a verifier false negative:
  deterministic validation found `0` "sample system checks" even though
  `index.html` contained three `<li>` entries and Playwright click verification
  passed.
- Fine-tune applied: list-scoped content requirements such as "three sample
  system checks" count rendered HTML list items, and "no CSS file" contracts
  no longer synthesize a required `styles.css`. They block separate `.css`
  artifacts or CSS links while allowing `<style>` blocks and inline
  `style="..."` inside the HTML.
- Replay of `session_1779651755004` against the updated validator now passes
  with `actual: 3` for sample system checks.
- Verification: focused regressions passed; `.venv/bin/python -m unittest
  discover -s tests -p '*_test.py'` passed (110 tests); `npm run check` passed;
  `git diff --check` passed.
- Live restart: the launchd helper again returned before port readiness, but
  follow-up `npm run harness:status` verified launchd PID `28978` listening on
  `127.0.0.1:5005`; harness root, `/api/workspace/status`, and
  `/api/model/route` returned `200`/valid JSON.
- Final alignment requested after Ian's next live JS job went through cleanly:
  external SSD backup target
  `/Volumes/PHIXERO/Backups/gemma-forge/20260524T202333Z-full-live-local-working-state/`
  with `~/.gforge/models` intentionally omitted, plus GitHub push of the
  installable repo state. Pre-alignment verification re-ran the full unittest
  suite (110 tests), `npm run check`, `git diff --check`, and live harness route
  probes successfully.

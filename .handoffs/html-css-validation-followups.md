# HTML/CSS Validation Followups

Last updated: 2026-05-24

Live test sessions after the HTML/CSS validator patch exposed two separate
follow-up lanes.

## Sessions Observed

- Positive dashboard test: `session_1779647234243`
  - Prompt: build a small HTML/CSS "Local AI Validation Lab" dashboard.
  - Execution wrote `index.html` and `styles.css`.
  - Validation failed even though this was meant to be the passing test.
  - Human launched the HTML and reported the verifier is wrong. Reading the
    generated files confirms the page has three real `<article
    class="status-card ...">` cards, one warning banner, one checklist section,
    a linked `styles.css`, hover states, and mobile CSS. The validator is
    producing false negatives here.
  - Final observed state: stopped at `execution: needs-attention` after two
    post-review continuation repairs. SocratiCode/Axon/Verification/Handoff
    stayed active and did not run.
- Intentional broken canary: `session_1779647266835`
  - Prompt: create intentionally broken `index.html` and `styles.css` so the
    harness rejects invalid web deliverables.
  - Execution wrote invalid files.
  - Validation failed, which is correct for the validator, but the harness may
    still treat this as a repair target instead of an expected negative test.
  - Final observed state: stopped at `execution: needs-attention` after two
    post-review continuation repairs. SocratiCode/Axon/Verification/Handoff
    stayed active and did not run.

## Patch Lane 1 — HTML + CSS Contract Shape

The Context Writer can currently express only one primary
`deliverable.format`/`deliverable.count`/`deliverable.path_pattern`. For a
normal web task that asks for one HTML page plus one linked CSS file, it wrote:

- `deliverable.format: html`
- `deliverable.count: 2`
- `deliverable.path_pattern: index.html`

That made deterministic validation expect two HTML files matching `index.html`,
while the model correctly produced one HTML file and one support CSS file.

Next patch should separate primary deliverables from support files. Possible
shape:

```yaml
deliverable:
  format: html
  count: 1
  path_pattern: index.html
support_files:
  - format: css
    count: 1
    path_pattern: styles.css
    required: true
```

Minimum viable patch if schema expansion is too much:

- Teach Context Writer that "one HTML page and one linked CSS file" means
  `deliverable.count: 1`, not `2`.
- Add a hard requirement / acceptance line for `styles.css`.
- Let local-link validation enforce that the linked CSS file exists.
- Keep deterministic HTML/CSS integrity checks running across both primary and
  support files listed in execution metadata.

Live run impact:

- Positive dashboard session repeatedly repaired a good visible deliverable
  because `deliverable.count` expected two HTML files. The final validation still
  failed with only the file-count error.
- Canary session also carried this count mismatch alongside the expected syntax
  failures, making the reviewer ask for count repair even though the negative
  test had done its job.

Patch status:

- Fixed locally on 2026-05-24. Context enrichment now normalizes "one HTML page
  and one linked CSS file" to one primary HTML deliverable plus a required CSS
  support file, and deterministic file-count validation applies the same
  interpretation to previously-written bad contracts.
- Replay proof against `session_1779648021968` and `session_1779647234243`:
  both dashboard workspaces now pass deterministic validation.
- Replay proof against `session_1779648090315`: the intentionally broken canary
  still fails on the real invalid HTML issue, without the bogus "expected 2 html
  files" failure.

## Patch Lane 2 — Content Count Scope

The dashboard test asked for 3 status cards. Validation reported:

- expected: `3`
- actual: `5`
- item: `status cards`

This likely over-counts because `read_validation_text_files()` combines HTML and
CSS, so class names and selectors in `styles.css` can inflate counts for UI
components. For HTML deliverables, component/content quantity checks should
prefer HTML/Markdown/PDF body content and avoid counting CSS selector text as
rendered content.

Observed false negative:

- The HTML contains exactly three real status card elements:
  `<article class="status-card status-ok">`,
  `<article class="status-card status-warning">`,
  `<article class="status-card status-danger">`.
- Validation reported 5 status cards, likely because it also counted CSS
  selectors/comments such as `.status-card` and "Status Cards Grid".

Next patch should either:

- scope UI/content counts to `.html`/`.htm` files when the deliverable format is
  `html`; or
- add a structured HTML element counter for common UI units such as cards,
  sections, banners, articles, options, rows, and checklist items.

Patch status:

- Fixed locally on 2026-05-24. HTML content quantity validation now ignores CSS
  selector/comment text for HTML deliverables. Specific items such as "status
  cards" count rendered HTML elements with a `status-card` class instead of the
  broader "card" heuristic.
- Replay proof against both dashboard sessions now reports exactly `3` status
  cards and no validation failures.

## Patch Lane 3 — Expected-Failure Canary Mode

The broken canary correctly failed validation with:

- file-count mismatch caused by the same HTML+CSS contract issue above;
- invalid HTML mismatch, e.g. unmatched closing tag.

For intentionally broken validator tests, `validation.passed = false` is the
expected proof. The harness should not blindly enter repair mode when the
Project Context intent is to confirm rejection.

Next patch should detect explicit negative-test language such as:

- "intentionally broken"
- "validator canary"
- "confirm the harness rejects"
- "expected to fail validation"

Then mark the project context as something like:

```yaml
validation_expectation:
  mode: expected_failure
  expected_failures:
    - invalid HTML
    - invalid CSS
```

Behavior target:

- Execution may produce invalid files if the contract explicitly asks for them.
- Deterministic validation still fails in the normal machine-readable sense.
- The card/user-facing result should report "validator canary succeeded:
  expected validation failure observed" instead of treating the section as a
  normal failed deliverable that needs repair.
- Verification should confirm the expected failure signatures and then route to
  Handoff, not back into Project Execution repair.

## Patch Lane 4 — CSS Failure Coverage

In the canary execution report, validation showed the HTML failure but did not
show the unclosed CSS brace failure in the visible `execution.md` snippet. Need
inspect the current workspace `artifacts/validation.json` after the run settles.
If CSS is absent from failures, check whether:

- `styles.css` was malformed in a way the lightweight bracket checker missed;
- the file-count failure/repair path hid later failures from the report;
- or the CSS file was repaired/changed between attempts.

The next patch should preserve all deterministic failures in the report so a
single file-count issue does not obscure syntax/integrity failures.

After the run settled, the canary final `artifacts/validation.json` did include
both syntax failures:

- `invalid HTML deliverable output/index.html`
- `invalid CSS deliverable output/styles.css`

So CSS coverage is working. The remaining issue is how those failures are
interpreted for an expected-failure canary, not whether CSS validation ran.

## Patch Lane 5 — Repair Loop Guard For Validator False Negatives

Both sessions stopped at Execution after two continuation repairs. That was
correct for an ordinary deterministic failure, but expensive and confusing for
these cases:

- Positive dashboard: the visible/browser deliverable was good, and the
  remaining failures were validator false negatives.
- Canary: validation failure was the requested proof, so repairs should not have
  tried to fix the intentionally invalid files.

Next patch should add a decision layer before post-review continuation repair:

- If deterministic failure is only a known validator ambiguity (support CSS file
  counted as HTML, CSS selector text counted as rendered UI content), surface
  `needs-verifier-review` or route to Verification instead of continuing blind
  Execution repair.
- If the context marks `validation_expectation.mode: expected_failure`, stop
  repair after the expected failure signatures are present and mark the canary
  outcome as succeeded-for-negative-test.
- Make reviewer prompts aware of false-negative classes so the small-model
  review does not reinterpret a rendered-good artifact as "5 status cards"
  solely from validator text.

Patch status:

- Partially reduced by the 2026-05-24 false-negative fix: the known dashboard
  ambiguity now validates cleanly, so the repair loop no longer starts for that
  case on new runs.
- Still open for the explicit expected-failure canary mode. The next patch
  should classify negative validator tests as expected failures and advance
  them after the expected signatures are observed.

## Patch Lane 6 — Workspace Name Tightening

User observed generated workspace names were too long and prompt-shaped, e.g.
`build-a-small-html-css-single-page--local-ai-validation-lab--dashboard.--deliver`.

Patch status:

- Fixed locally on 2026-05-24. Auto-generated execution workspaces now prefer the
  structured Project Context name when available, with a compact fallback slug
  capped at 52 characters. User-chosen project directories are preserved.
  Example target shape: `local-ai-validation-lab-dashboard`.

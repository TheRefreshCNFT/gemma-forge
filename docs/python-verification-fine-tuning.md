# Python Verification Fine Tuning Handoff

Last updated: 2026-05-24

This note explains the Python/script verifier changes that were made after the
PDF/script test sessions started passing once, then getting reinterpreted as
failed and overwritten during Verification. Use it as the starting point when
porting the same verification pattern to JavaScript, TypeScript, shell, SQL, or
other code-writer languages. HTML/CSS is now the first completed port.

## Problem We Fixed

- A user could ask for a script, e.g. "write a Python script I can launch that
  creates 5 directories and 5 text files in each."
- The correct final deliverable was the script itself, not the directories/files
  produced by running it.
- Earlier validation mixed up final deliverables with script runtime side
  effects, so a good script could be marked failed because its generated output
  was not present in the final workspace.
- The Verification card could then trigger a repair loop, rerun Project
  Execution, and destroy or delete a good deliverable after deterministic
  validation had already passed.
- Python scripts that needed packages such as `pdfplumber`, `reportlab`, or
  `pypdf` could fail in workspace exec even though the user task was valid.
- Failed/skipped command runs could be summarized as success unless the
  deterministic validator read `commandRuns` as authoritative evidence.

## Current Python Behavior

- Python deliverables are syntax-checked with `ast.parse`.
- If the Project Context contract says the Python script should create files or
  directories, those counts become `script_runtime` content requirements.
- Script runtime requirements are validated by copying the Python deliverable
  into a temporary directory, running `python <script>`, counting the produced
  files/directories there, and deleting the temp directory when validation exits.
- The generated runtime outputs are never required as final deliverables unless
  the user explicitly asked for the outputs themselves.
- Workspace exec failures and skipped commands now fail deterministic validation.
  The model summary cannot claim "success" over a failed `commandRuns` entry.
- Python package installs are auto-prepended only when workspace commands are
  allowed and a Python script command needs imports that are not local/stdlib.
- Auto-installed Python packages are targeted under `.gforge-installs/python`,
  not into the user's global Python.
- PDF/OCR-style Python jobs get `pypdf`, `pdfplumber`, and `reportlab`
  auto-added when the deliverable format is PDF.
- Verification is read-only. It may rebuild `verification.md` from existing
  artifacts, but it must not rerun Project Execution or mutate deliverables.
- If deterministic validation passes, reviewer objections about file count,
  path pattern, PDF validity, or content quantity are downgraded to warnings
  unless they identify a concrete artifact mismatch outside the deterministic
  gates.
- Axon/SocratiCode findings are advisory for simple fresh-script deliverables.
  They no longer become deterministic failures inside Verification.

## Current HTML/CSS Behavior

- HTML and CSS are validated together because web deliverables commonly emit an
  HTML file plus supporting CSS.
- HTML validation is static/read-only: the verifier parses model-authored
  `.html`/`.htm` files and fails on clear tag-pair mismatches such as unmatched
  closing tags. It does not execute scripts or mutate files.
- CSS validation is static/read-only: the verifier checks model-authored `.css`
  files for unclosed comments/strings and unbalanced `{}`, `[]`, or `()`.
- Existing local-link validation still checks HTML/CSS/Markdown `href`, `src`,
  and `url()` references against actual files on disk.
- HTML/CSS bundle contracts distinguish primary HTML deliverables from CSS
  support files. A request for "one HTML page and one linked CSS file" validates
  as one HTML file plus one required CSS support file, not two HTML files.
- HTML content quantity checks ignore CSS selector/comment text. Specific UI
  phrases such as "status cards" count matching HTML elements instead of broad
  stylesheet occurrences.
- Verification gets the same staged skill context summary/prompt as the Context
  Writer, worker, and chat agent, but it remains read-only with respect to
  deliverables. It may rerun deterministic checks and inspect current artifacts;
  if issues remain, it routes back to the responsible Forge Section instead of
  editing files inside Verification.

## Main Code Touchpoints

- `chat/server.py`
  - `SCRIPT_RUNTIME_FORMATS = {"python"}` is the current language gate.
  - `detect_script_runtime_quantity_requirements` extracts counts like
    "5 directories" or "25 .txt files" from user/context text.
  - `script_runtime_quantity_requirements_from_context` pulls those counts from
    intent, hard requirements, and acceptance checks.
  - `validate_code_file_integrity` syntax-checks Python deliverables and now
    performs static HTML/CSS integrity checks.
  - `HTMLIntegrityParser`, `validate_html_source`, and `validate_css_source`
    implement the HTML/CSS port without runtime execution.
  - `normalize_html_css_support_bundle_context`,
    `effective_deliverable_file_count`, and `validation_text_extensions`
    prevent linked CSS files from being counted as extra HTML deliverables or
    rendered UI content.
  - `validate_python_script_runtime_side_effects` performs the isolated temp-run
    behavior check.
  - `count_runtime_filesystem_units` counts runtime-created directories, files,
    and extension-specific files while ignoring harness install/cache dirs.
  - `validate_workspace_command_runs` turns skipped/failed workspace commands
    into deterministic validation failures.
  - `validate_pdf_file`, `extract_pdf_validation_text`, and
    `read_validation_text_files` make PDFs parseable and countable in content
    validation.
  - `augment_workspace_commands_for_dependencies` prepends workspace-local
    Python package installs when needed.
  - `repair_verification_after_review`, `run_completion_review`,
    `build_verification_context`, and `build_verification_details` enforce
    read-only Verification, include staged skill context for the verifier, and
    downgrade false-positive reviewer failures after deterministic pass.
- `chat/tool_workspace.py`
  - `package_install_targeted_args` rewrites pip installs to
    `.gforge-installs/python` unless the model supplied a safe target.
  - `workspace_command_timeout` gives package installs and script-file runs a
    longer bounded timeout.
  - `run_workspace_commands` runs commands inside the macOS sandbox with
    `PYTHONPATH=.gforge-installs/python`, package caches under
    `.gforge-installs/`, and command evidence recorded as `commandRuns`.
- `tests/model_route_test.py`
  - Covers inferred script-runtime counts, temp-run success/failure,
    Python syntax failure, workspace command failure, PDF validity, PDF content
    counts, HTML/CSS integrity pass/fail, verifier skill-context access, stale
    deliverable quarantine, and package auto-provisioning.

## Validation Flow

1. Project Context writes a contract with `deliverable.format`,
   `deliverable.path_pattern`, `deliverable.count`, `capabilities_required`,
   `content_requirements`, and `acceptance`.
2. Execution writes model-authored files and optional `COMMANDS`.
3. Workspace commands run only if the contract requires that capability.
4. Dependency auto-provisioning may prepend a safe package install command.
5. Deterministic validation checks:
   - model-authored files exist and match metadata hashes;
   - Python syntax is valid;
   - HTML/CSS deliverables pass static integrity checks;
   - required workspace commands were not skipped or failed;
   - final deliverable count/path/format matches the contract;
   - PDF files really parse as PDFs;
   - content quantities are met;
   - script runtime side effects are tested in a temp space, then discarded.
6. Verification reads the existing workspace and validation artifact.
7. If deterministic validation failed, the failure belongs to Execution repair
   or human resolve. Verification must not mutate deliverables.

## Porting Pattern For More Languages

Use the Python behavior as the reference pattern, but keep language support
explicit and deterministic.

- Add a language format gate, e.g. `javascript`, `typescript`, `shell`, or
  `sql`, rather than making all files executable by default.
- Add syntax/static checks appropriate to that language:
  - JavaScript: `node --check <file>`.
  - TypeScript: `tsc --noEmit` when a local/project TypeScript toolchain exists;
    otherwise syntax-only support needs a deliberate parser choice.
  - Shell: `bash -n <file>` or `sh -n <file>`.
  - HTML/CSS: completed. Keep it parse/link/integrity-only rather than runtime
    execution.
  - SQL: dialect-aware parsing is needed before claiming strong validation.
- Add a language-specific isolated runtime validator only when the language can
  safely run in workspace exec.
- Keep runtime side effects in a temp test space. Do not require test outputs as
  final deliverables unless the user asked for those output files.
- Keep dependency installs workspace-local:
  - Python currently uses `.gforge-installs/python`.
  - Node should use a workspace-local cache and avoid global installs.
  - Other ecosystems need their own install root/cache policy before enabling.
- Make skipped/failed commands authoritative failures for any language where
  command execution is part of the contract.
- Add tests before broadening behavior. Start with:
  - syntax pass/fail;
  - runtime side-effect pass/fail;
  - dependency auto-provision pass/fail;
  - skipped command blocks delivery;
  - good deterministic pass cannot be overturned by Verification.
- Preserve the read-only Verification rule. Execution owns mutation; Verification
  owns inspection and reporting.

## Known Runtime Note

On Ian's Mac, the shell `python3` may point at Homebrew Python without the harness
dependencies. The live harness LaunchAgent uses:

```text
/Users/webot/Projects/gemma-forge/.venv/bin/python -m chat.server
```

For repo validation, prefer:

```bash
npm run check
.venv/bin/python -m unittest discover -s tests -p '*_test.py'
```

Using bare `python` or the wrong `python3` can produce false missing-package
errors for Flask or Hugging Face even when the live harness runtime is healthy.

## Practical Next Step

For the next language pass, start with JavaScript or shell by cloning the Python
and HTML/CSS test shape in `tests/model_route_test.py`, then implement the
smallest language-specific syntax/runtime hook needed to make those tests pass.
Do not broaden runtime execution for every extension at once; each language
needs its own safety, dependency, timeout, and cleanup policy.

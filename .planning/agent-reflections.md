# Agent Reflections

## 2026-05-20 - Contest Harness First Slice

What worked: Starting from `CONTEXT.md` and `PROJECT_PLAN.md` clarified that the product should compete on local Gemma 4 usability, not on being a generic chat wrapper.

What broke: The required `npm run check` command is not applicable because this project has no `package.json`; Python/JS syntax checks and Playwright rendering checks were the useful verification path.

What surprised me: The existing local machine already has enough RAM and installed Ollama models for the larger model cards to unlock, so the disabled-model UX needs simulation or lower-resource test coverage.

Concrete change: For the next slice, add explicit backend status fields for SocratiCode/Axon install/config state instead of showing them only as protocol text in the UI.

## 2026-05-20 - Session Harness And Model Registry

What worked: The safe first implementation was to import already-installed Ollama models into a registry and skip provisioning when `gemma-4` already exists, which matches the user's local state without redownloading large files.

What broke: `npm run check` remains unavailable because the repo has no `package.json`; the useful checks are Python compile, JSON validation, JS syntax, API smoke tests, and Playwright rendering.

What surprised me: Local Gemma responded fast enough for end-to-end smoke testing, so the planning harness can demonstrate real local-agent behavior now instead of relying on placeholder text.

Concrete change: Next implementation should wire actual SocratiCode/Axon status and actions into card execution, then add a model provisioning job runner for new downloads/conversions instead of only registry/provision status.

## 2026-05-20 - Protocol Card Wiring

What worked: Each Gemma Forge card now has a concrete backend runner, and the browser shows the resulting artifact in the card while also saving the output into the session context.

What broke: Axon's static dead-code detection flags Flask route handlers and browser event handlers as dead because they are invoked dynamically. Root cause is structural analysis not seeing decorator and DOM-event entry points.

What surprised me: The Axon CLI index was stale even after MCP tools were available, so refreshing `axon analyze` was necessary before trusting harness output.

Concrete change: Add framework-aware suppressions or annotations for dynamic Flask/JS entry points before treating Axon dead-code results as actionable product findings.

## 2026-05-20 - Project Directory Intake Switch

What worked: Asking whether a project directory already exists is the right second intake question because it cleanly switches card state and prevents codebase tools from running against a non-existent project.

What broke: Existing test sessions created before this field do not have `projectMode`, so the UI treats them as the default new-project/no-directory state unless selected sessions carry newer metadata.

What surprised me: The session itself is enough structure to create useful GSD output for blank projects, which means Gemma Forge can support ideation before any files exist.

Concrete change: Add a session migration/default pass later so older sessions receive an explicit `projectMode` instead of relying on UI defaults.

## 2026-05-20 - Plan Runner And Hidden Protocols

What worked: A single Full Forge control fits the work-harness model better than asking users to run each protocol card manually.

What broke: The first resume path would not have continued after Verified because the runner still considered itself active; clearing the runner state before resume fixed it.

What surprised me: Moving pending and inactive cards into a Skipped protocols drawer made the intended workflow much clearer without deleting useful tool context.

Concrete change: Add a future session migration for older card states so legacy sessions can benefit from the hidden-protocol behavior immediately.

## 2026-05-20 - No-Directory Orchestration Smoke Test

What worked: The harness accepted a no-directory project seed, auto-ran with human verification off, and generated a plan containing the requested directory setup, docs, research, HTML/CSS/JS subtasks, reviewer, tester, screenshot validation, final review, and delivery steps.

What broke: The harness stopped at planning artifacts and did not create the directory or website files itself. Root cause: new-project cards are currently planning-only; there is no execution runner that converts a GSD plan into filesystem tasks.

What surprised me: Screenshot validation caught a real integration issue in the delivered test page: the space span initially rendered with zero width even though DOM validation passed.

Concrete change: Add a new-project execution card that can materialize a planned directory, write starter docs/files, and run screenshot validation from inside the harness.

## 2026-05-20 - Real Materialization And Repair Loop

What worked: Adding Project Execution as a protocol card let the harness convert a no-directory session into a real workspace, then continue through Forge Flow, SocratiCode, Axon, Verification, and Handoff without manual intervention.

What broke: The first materialization pass proved execution but did not exercise the repair branch. Root cause: the smoke prompt did not match the narrower repair-probe trigger.

What surprised me: Once the repair probe broadened to orchestration tests, the harness cleanly recorded initial failure, targeted CSS repair, final validation pass, and delivery in `execution.md` and `artifacts/validation.json`.

Concrete change: Next slice should replace the static-site-specific materializer with a planner-driven execution adapter so more project types can be materialized safely.

## 2026-05-20 - Sidebar Session State

What worked: The session list became clearer by deriving row color from card state instead of adding another persisted field.

What broke: No backend state exists for cross-tab "currently running", so the green running indicator is local to the active browser tab.

What surprised me: Selected state and status state both matter visually; keeping selected as the background while status remains a left rail makes both readable.

Concrete change: Add persisted session run state later if multi-window monitoring becomes important.

## 2026-05-20 - Final Forge UI Polish

What worked: The final wording pass made the product read as Gemma Forge instead of a generic challenge demo, while keeping all existing harness functions intact.

What broke: `npm run check` remains unavailable because this repo has no `package.json`; browser, JS, Python, and SVG checks are the useful local verification path.

What surprised me: A small standalone SVG logo was enough to make the left rail feel branded without introducing heavier asset dependencies.

Concrete change: Keep future UI additions in the Forge Harness vocabulary so labels stay productized and do not drift back to implementation terms.

## 2026-05-20 - Session Delete And Scroll

What worked: Testing deletion with a throwaway session verified both the browser control and persisted backend behavior without risking real session data.

What broke: Restarting the harness with system `python3` failed because Flask is only installed in the existing GGUF virtualenv.

What surprised me: The session list already had enough rows to validate overflow naturally, so no fake bulk data was needed.

Concrete change: Restart the harness with `/Users/webot/Projects/gguf/venv/bin/python` whenever server route changes need to go live.

## 2026-05-20 - Help And Archive

What worked: A throwaway session gave a clean end-to-end check for Archive, Restore, Delete, and help popovers without touching real project sessions.

What broke: The Node REPL kept a previous `afterDelete` binding, so the first Playwright script failed before running.

What surprised me: The empty Active/Archived state is useful on its own because it clearly shows users where sessions will go before they create one.

Concrete change: Use unique `var` names or reset the Node REPL before long browser verification scripts.

## 2026-05-20 - Contest Criteria Review

What worked: GSD verify-work mapped cleanly to the judging criteria when each criterion was treated as a user-observable acceptance test.

What broke: The strongest product surface is now the Flask harness, but the public README and launcher still mostly describe the older Tkinter converter.

What surprised me: The core UX is stronger than the publication/package layer, so submission risk is currently more about proof, packaging, and docs than the harness concept.

Concrete change: Before public release, prioritize a README/package pass and fresh-clone install test over adding more harness features.

## 2026-05-20 - Harness Realignment And Model Route Proof

What worked: Moving harness state to `~/.gforge`, keeping Ollama in `~/.ollama`, and adding a model-route endpoint made the product story and runtime evidence line up.

What broke: The first model-route test used the system Python, which lacked Flask. The root cause was running outside the project's Flask-capable venv.

What surprised me: The live harness had already been using `gemma-4`; the missing piece was a visible proof surface, not the actual model path.

Concrete change: For model-use claims, add code-level proof and an in-app status readout before summarizing contest readiness.

## 2026-05-20 - Submission Media And ComfyUI

What worked: Capturing deterministic screenshots first gave ComfyUI useful visual anchors and also produced a clean fallback video path.

What broke: The first LTX workflow assumed the checkpoint carried a text encoder, then the second used placeholder CLIP files. Root cause: local ComfyUI listed placeholder `clip/` files and the LTX checkpoint intentionally had no CLIP weights.

What surprised me: The LTX renders completed locally and created useful atmosphere, but distorted UI text enough that the deterministic screenshot video is the better submission demo base.

Concrete change: For product submissions, use generative video as intro/transition material and keep the main feature proof deterministic and legible.

## 2026-05-20 - Forge Context Naming

What worked: Promoting the hidden harness protocol into `forge.md` made the always-on context concrete while keeping the user-facing UI focused on projects instead of implementation sessions.

What broke: Normal background server launches are cleaned up by the desktop command runner after the command returns. Root cause: child processes from shell commands do not reliably persist across tool calls.

What surprised me: `launchctl submit` cleanly kept the Flask harness alive under the user session and let the browser continue using `http://127.0.0.1:5005/`.

Concrete change: When the harness must stay live for browser review, start it through `launchctl` or the macOS launcher instead of relying on `nohup` from the command runner.

## 2026-05-20 - Clean Browser Demo Recording

What worked: Driving the headed Chrome window through CDP while recording with `screencapture` produced a clean live demo that shows setup, planning, Full Forge execution, and the delivered `Hello World` page.

What broke: Earlier recordings captured Codex in the foreground during part of the run. Root cause: progress updates and polling during capture could shift focus or leave the Codex window visible behind a smaller Chrome window.

What surprised me: Maximizing Chrome with AppleScript before recording and staying silent during capture was enough to keep the final video clean without needing a dedicated recording app.

Concrete change: For future product recordings, front and size the browser first, run one self-contained automation command, avoid commentary while the screen is recording, then validate the output with extracted thumbnails.

## 2026-05-20 - No-Template Agentic Execution Test

What worked: `gemma-4` authored `index.html`, `styles.css`, and `script.js` directly from a file-contract prompt, and the generic writer/validator path produced a rendered page with 11 character nodes, 11 unique colors, preserved spacing, and `data-validation="passed"`.

What broke: The first model output passed its own script validation while failing independent checks: repeated HSL colors and `body.innerHTML = ''` removed the deferred script tag. The first repair response also returned invalid strict JSON because of an unescaped control character in a JavaScript comment.

What surprised me: A second, more explicit repair prompt fixed the real implementation issues, while the remaining failure came from an overly strict validator using `body.innerText.includes("Hello World")` on flex-separated character spans.

Concrete change: Replace the static demo materializer with a generic model-authored file adapter that enforces structured output, robust JSON recovery, independent render validation, and repair prompts with root-cause feedback.

## 2026-05-20 - Small-Model Review Gate

What worked: Moving completion through a server-side finalize step made the extra review real for API, Full Forge, Forge Section, and human verification paths instead of making it a UI-only promise.

What broke: The first live smoke proved the reviewer was too broad and blocked Intake because the full smoke-test outcome was not validated yet. Root cause: the review prompt judged the whole project instead of the current card's responsibility.

What surprised me: The second smoke showed the review gate and research budget clearly in the existing card UI with only small rendering additions.

Concrete change: Future reviewer prompts should always include explicit section responsibility and should distinguish section blockers from non-blocking warnings about later phases.

## 2026-05-20 - Post-Review Repair Loop

What worked: Replaying the user's natural prompt in a unit test exposed the exact failure: `text: "HELLO WORLD! LET'S FORGE!"` was truncated at the apostrophe and validated against the wrong phrase.

What broke: The review stage could flag verification as missing artifacts, but there was no automatic patch/retest stage before `needs-attention`. Root cause: completion review was terminal instead of feeding a repair loop.

What surprised me: The execution review passed because validation data was internally consistent even though it validated the wrong prompt-derived target.

Concrete change: Treat review failures as repair input first, then rerun the review; only stop the user after bounded patch attempts fail.

## 2026-05-20 - Responsive Harness Containment

What worked: Fixing the overflow at the CSS containment layer kept the change focused on layout behavior without touching harness orchestration or model execution.

What broke: The desktop grids used fixed 360px minimum tracks and several output areas lacked long-text wrapping, so narrow browser widths could push the right column beyond the viewport.

What surprised me: The required `npm run check` still resolves outside this repo and fails on missing `/Users/webot/package.json`, so local verification needs explicit syntax and service-health checks until a package manifest exists.

Concrete change: Future harness UI panels should default every grid child, output block, and card container to `min-width: 0` plus deliberate wrapping before adding fixed-width controls.

## 2026-05-20 - Axon And SocratiCode Tool Truth

What worked: Separating tool states into complete, not-needed, host-assisted, unavailable, and degraded prevents the harness from claiming a support tool succeeded when it only skipped or prepared instructions.

What broke: Axon was run against an HTML-only workspace, producing zero graphable files and triggering `max_workers must be greater than 0`; the harness then let model-written repair text blur that real tool failure.

What surprised me: SocratiCode is available through the Codex host/MCP path but not as a harness-executable CLI, so the honest product behavior is a host-assisted command brief unless a direct execution path is added.

Concrete change: Tool cards must show the actual command/tool status in the UI and only stop Full Forge when a selected, applicable tool genuinely needs repair.

## 2026-05-20 - Directory Intake Routing

What worked: Keeping the directory choice explicit in the UI made the product behavior simple: new-project paths can be created, existing-directory paths must already exist.

What broke: Project Execution could be marked `conditional` for an existing-directory session, but Full Forge only ran `active` and `needs-attention`, so the visible execution card was skipped before Verification.

What surprised me: A missing manual path made Forge Flow fall back to the repo root, which hid the bad path until Verification failed against the nonexistent workspace.

Concrete change: Visible conditional cards must be runnable by Full Forge, and missing existing-directory paths must be rejected before a project record is created.

## 2026-05-20 - Product-Owned Code Intelligence

What worked: Installing SocratiCode under `~/.gforge/tools` and calling it through a Flask-owned MCP stdio client made semantic indexing/search real inside the harness instead of depending on Codex host tools.

What broke: The first full validation run stopped at GSD because the small-model reviewer complained about files that Project Execution had not created yet. Root cause: non-execution card reviews still needed deterministic scope normalization when the model judged later implementation responsibilities.

What surprised me: Once the planning-review scope bug was fixed, three separate `gemma-4` app runs completed all cards, including real SocratiCode and Axon passes, without needing task-specific product code.

Concrete change: Tool readiness must be proven by executable probes and full app runs; support-tool claims are not acceptable unless the harness itself ran the tool and captured the artifact.

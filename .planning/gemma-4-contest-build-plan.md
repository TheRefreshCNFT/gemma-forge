# Gemma 4 Contest Build Plan

## Contest Context

The Gemma 4 Challenge submission deadline is May 24 at 11:59 PM PDT. Build submissions are judged on intentional and effective Gemma 4 use, technical implementation and code quality, creativity and originality, and usability/user experience.

## Product Positioning

Gemma Forge should become a local Gemma 4 work harness, not a chat app.

Core pitch: a non-technical user launches one app, the app prepares a local Gemma 4 workspace, installs or uses Ollama, selects the safest compatible model, and guides a planning agent through a structured project protocol with transparent checkpoints.

## Stack Decision

Use a modern local web app served by Flask for the contest build.

Rationale:

- Fastest path from the current code.
- Preserves the existing Python forge pipeline.
- Avoids Electron packaging complexity during the deadline window.
- Still allows a polished HTML/CSS/JS interface.
- Can be wrapped later by Electron or Tauri if packaging becomes the priority.

The existing CustomTkinter app should be treated as legacy launcher/provisioning code while the new work harness UI becomes the primary contest experience.

## Required Experience

### Startup

- Full-screen setup view with "Setting up workspace".
- Scan local CPU/RAM/disk, Ollama presence, Ollama running state, model availability, `llama.cpp` availability, and Hugging Face token availability.
- Present an environment summary after scan.

### Model Selection

- Smallest Gemma 4 model is always selected and cannot be deselected.
- Larger Gemma 4 options appear as selectable only when resources are sufficient.
- Unsupported model cards remain visible but disabled with a clear explanation.
- The app explains whether Ollama will be installed, started, or reused.

### Work Harness

- First prompt for every new session: "What project are we planning?"
- Replace chat framing with planning/orchestration framing.
- Show project sections as cards:
  - Intake
  - Forge Flow
  - GSD Planning
  - Codebase Mapping
  - SocratiCode Search
  - Axon Impact/Dead Code
  - Execution
  - Verification
  - Handoff
- Cards activate/deactivate according to project needs.
- Cards with no planned data collapse or deactivate.

### Skills And Tools

- Rename product-facing `webot-flow` to `forge-flow`.
- Preserve the underlying protocol: orient, verify state, execute with checkpoints, update handoff/map.
- Auto-install or configure SocratiCode and Axon where possible.
- Build skill routing into each card so the agent knows when to apply `forge-flow`, GSD, SocratiCode, and Axon.

### Checkpoints

- Each section header has an auto-run / human-verify control.
- Before start, human-verify mode asks what checkpoint standard should apply.
- In human-verify mode, the agent pauses at checkpoints and provides concrete user instructions.
- Checkpoint actions:
  - Verified: continue to next task.
  - Not Verified: open an issue-resolution dialogue inside the same section.
  - Help: ask "Do you need help with the instructions?" and guide the user.
- Auto-run mode follows protocol without interruption until the section completes.

## Four-Day Build Order

### Day 1: New Harness Shell

- Add Flask-backed workspace scan endpoint.
- Replace chat UI with setup screen and work harness shell.
- Add model/resource cards and default smallest-Gemma lock.
- Keep existing forge pipeline callable.

### Day 2: Workflow Cards

- Build GSD-style card system.
- Add session creation with first prompt: "What project are we planning?"
- Implement card activation/deactivation.
- Add checkpoint state machine.

### Day 3: Agent Protocol Integration

- Add productized `forge-flow` instructions.
- Encode skill routing per card.
- Wire SocratiCode/Axon status checks into the UI.
- Add human verification dialogues and instructions.

### Day 4: Polish And Submission

- Visual polish, copy pass, demo path hardening.
- Add final README contest story.
- Capture screenshots/video.
- Run syntax checks and a lightweight local smoke test.

## Initial Engineering Tasks

1. Add `requirements.txt` for the current Python dependencies.
2. Add a resource scanner module.
3. Replace `chat/` with work-harness terminology and UI while preserving Flask serving.
4. Make model name/port configurable instead of hardcoded.
5. Add card/checkpoint state objects.
6. Add a minimal local protocol prompt for the planning agent.
7. Add final contest-focused README section.

## Implemented On 2026-05-20

- Added local resource scan with CPU, RAM, disk, Ollama, `llama.cpp`, HF token, Gemma model availability, and subagent capacity.
- Added `models.json` model registry.
- Added installed-Ollama-model import into `models.json`.
- Added skip-if-installed provisioning status for `gemma-4`.
- Added active model dropdown.
- Added Settings panel with model import/provision controls, download-only checkbox, and create-interface checkbox.
- Added project-scoped session messages.
- Added per-session `session-context.md`.
- Added session linking with primary `session-bridge.md` and reciprocal shortcut files.
- Added resource-aware planning prompt behavior for subagent capacity and single-agent audit fallback.
- Smoke-tested local Ollama-backed planning with `gemma-4`.
- Wired protocol card run buttons to backend card runners.
- Refreshed the local Axon index and wired the Axon card to `axon status` plus `axon dead-code`.
- Added tool readiness display for Forge Flow, GSD, SocratiCode, and Axon during workspace setup.
- Added intake project-mode switch: new project seed vs existing project directory.
- New-project sessions defer codebase tools until a workspace exists.
- Existing-directory sessions record the path and activate directory-aware planning.
- Added Full Forge orchestration for active cards.
- Added auto-run behavior when human verification is disabled globally or on individual cards.
- Added human-checkpoint resume behavior: Verified continues, Not Verified captures an issue and reruns, Help asks for checkpoint support context.
- Hid inactive/pending protocols from the main stack and moved them into Skipped protocols.
- Added Project Execution card for no-directory sessions.
- Project Execution materializes a session workspace, writes docs/source files, validates the generated project, repairs validation failures, retests, and writes delivery artifacts.
- Verified the full no-directory orchestration path on `session_1779293719873`: Intake, GSD, Project Execution, Forge Flow, SocratiCode, Axon, Verification, and Handoff all completed with human verification off.
- Added final Forge-themed UI polish: SVG logo, Forge Harness naming, Full Forge action text, Forge Section card actions, and collapsible Forge Engine / Forge Intelligence panels.
- Added per-session delete controls with confirmation, persisted DELETE handling, session-data cleanup, bridge pruning, and scrollable sidebar session list.
- Added contextual help popovers on key harness sections, plus archive/restore controls and Active/Archived session groups.

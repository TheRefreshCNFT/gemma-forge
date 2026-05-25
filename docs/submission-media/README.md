# Gemma Forge Submission Media

This directory holds local media assets for the Gemma 4 Challenge submission.

## DEV Cover Image

- `screenshots/current/01-forge-harness-overview.png` - use this as the DEV post cover image. It is the same main product image used at the top of the GitHub README.

## Current Product Screenshots

- `screenshots/current/01-forge-harness-overview.png` - main Forge Harness readiness view with environment checks and Forge Brain model pills.
- `screenshots/current/02-project-intake-protocol-cards.png` - new project seed, Human Verify, protocol cards, and project-context chat.
- `screenshots/current/03-forge-station-evidence-stream.png` - live work/event stream with skill staging, browser fetches, status codes, and screenshot evidence.
- `screenshots/current/04-settings-model-provisioning.png` - Settings model import, Hugging Face search, Ollama naming, and provisioning controls.
- `screenshots/current/05-project-sidebar.png` - compact project rail with active/done states and archive/delete actions.
- `screenshots/current/06-workspace-artifacts.png` - session workspace evidence showing project context, planning, research, execution, verification, handoff files, screenshots, and generated artifacts.

## Earlier Screenshots

- `screenshots/01-setting-up-workspace.png`
- `screenshots/02-forge-harness-ready.png`
- `screenshots/03-forge-engine-panel.png`
- `screenshots/04-forge-intelligence-panel.png`
- `screenshots/05-project-session-protocol-cards.png`
- `screenshots/06-settings-model-route-error-log.png`
- `screenshots/07-mobile-responsive-harness.png`

## Clean Demo Clip

- `video/gemma-forge-screenshot-demo.mp4`

This is a deterministic screenshot-based product clip. It preserves readable UI and is the safer base for the submission video.

## ComfyUI Mood Clips

- `comfy/outputs/video/gemma_forge_intent_i2v_00001_.mp4`
- `comfy/outputs/video/gemma_forge_intent_i2v_subtle_00001_.mp4`

These are local LTX image-to-video generations based on the Forge Harness screenshot. They are useful as atmospheric intro or transition material, not as the main product demo because generated UI text can distort.

## ComfyUI Workflows

- `comfy/gemma-forge-ltx-i2v-api.json`
- `comfy/gemma-forge-ltx-i2v-subtle-api.json`

Both workflows were checked against the running local ComfyUI server and had all required nodes and models available.

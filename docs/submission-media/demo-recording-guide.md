# Gemma Forge Demo Recording Guide

## Goal

Record the real product flow, not a static screenshot reel:

1. Install or launch Gemma Forge.
2. Show `Setting up workspace`.
3. Show Forge Engine readiness.
4. Show Forge Brain defaulting to `gemma-4`.
5. Start a no-directory project.
6. Ask for a Hello World webpage with rainbow or different-colored text.
7. Turn Human verify off for the active cards.
8. Run Full Forge.
9. Show generated project artifacts and validation.
10. Open the delivered Hello World webpage.

## Mac Screen Recording

Use the built-in Screenshot toolbar:

1. Press `Shift` + `Command` + `5`.
2. Choose `Record Selected Portion`.
3. Drag the frame around the browser window.
4. Click `Options`.
5. Set `Save to` to `docs/submission-media/raw-recordings` or Desktop.
6. Turn on microphone only if recording narration live.
7. Click `Record`.
8. Stop with the stop button in the macOS menu bar.

Command-line option:

```bash
mkdir -p docs/submission-media/raw-recordings
screencapture -v -k -V 180 docs/submission-media/raw-recordings/gemma-forge-demo.mov
```

That records up to 180 seconds, includes visible clicks, and saves a `.mov`.

## Recommended Shot Flow

- 0:00-0:08: Launch Gemma Forge and show `Setting up workspace`.
- 0:08-0:20: Show Forge Engine and Forge Intelligence.
- 0:20-0:30: Open Settings briefly and show model-route proof.
- 0:30-0:45: Start a new project plan.
- 0:45-1:05: Enter: `Create a Hello World webpage with each character in a different rainbow color. I do not have a directory yet.`
- 1:05-1:20: Disable Human verify and press Full Forge.
- 1:20-1:50: Let the cards run and show Project Execution / Verification / Handoff.
- 1:50-2:05: Open the generated webpage.
- 2:05-2:15: End on the delivered artifact and project context.

## Editing Notes

Use the deterministic screenshot video and ComfyUI mood clips only as intro/outro or transition material. The main proof should be the live harness recording.

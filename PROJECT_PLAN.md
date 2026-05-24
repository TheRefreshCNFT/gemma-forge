# Gemma Forge Project Plan

## Objective

Ship Gemma Forge as a contest-ready local Gemma 4 work harness that makes free local AI approachable for users who do not want to learn the machinery first.

## Completed

- Forge Harness UI with project-scoped records.
- Startup workspace scan with "Setting up workspace".
- Forge Engine readiness panel.
- Forge Intelligence model lane.
- Forge Brain model selector.
- Initial recommended Gemma 4 model route through `gemma-4-e4b-it`, with user-selected models routed when chosen.
- Full Forge and Forge Section execution paths.
- Human verify checkpoints with Verified, Not Verified, and Help flows.
- Active and Archived project groups.
- Project archive, restore, and delete controls.
- Harness-agent operating guide.
- Project execution smoke test with validation, repair, retest, and delivery artifacts.

## Current Hardening

- Make the Forge Harness the documented and packaged entrypoint.
- Store Gemma Forge state in `~/.gforge` and leave Ollama in `~/.ollama`.
- Add Settings access to meaningful harness errors.
- Add public proof that the default Gemma 4 lane is actually used by model-backed harness calls.
- Make SocratiCode and Axon product-owned working tools, not host-assisted claims.
- Prepare install, demo, and submission materials.

## Final Submission Needs

- Fresh clone install verification.
- Demo video showing first load, model selection, Full Forge, verification, and project management.
- Public repository access.
- Submission write-up with clear model-choice rationale.
- One concise technical note explaining the model route: Forge Brain selection to Flask harness to Ollama `/api/chat`.

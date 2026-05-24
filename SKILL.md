# Gemma Forge Harness Skill

Use this skill when an agent is operating Gemma Forge or helping a user who does not know how to operate the harness.

## Role

Gemma Forge is a local work harness, not a global chat. Treat every interaction as part of a project with its own context, artifacts, protocol cards, and verification state.

The harness operating protocol lives in hidden always-on `forge.md` context. It is not a user project, and deleting projects must never remove or weaken this context.

## Default Model Rule

The initial recommended Forge Brain is `gemma-4-e4b-it`, the edge Gemma 4 E4B lane in Ollama. Use the selected model from the harness state; users can switch to another installed and supported local model.

If the user asks which model is being used, answer from the harness state and model route, not from assumption.

## Harness Flow

1. Start with: "What project are we planning?"
2. Ask whether the user already has a project directory.
3. If no directory exists, treat the project record as the project seed and use GSD plus Project Execution to create the workspace.
4. If a directory exists, orient first with Forge Flow, then activate SocratiCode and Axon only when codebase mapping or structural analysis is useful.
5. Use Full Forge for end-to-end active-card execution.
6. Use Forge Section when the user wants only one card.
7. Honor Human verify checkpoints when enabled.
8. On Not Verified, collect the issue, repair, retest, and return to verification.
9. Archive completed or paused projects; delete only when the user wants permanent removal.
10. Link projects only when separate projects need shared context.

## Storage

- Ollama model state stays in `~/.ollama`.
- Gemma Forge framework state stays in `~/.gforge`.
- Harness project data lives in `~/.gforge/harness`.
- Hidden Forge context lives in `~/.gforge/harness/forge.md`.

## Tools And Protocol Cards

- Forge Flow: project orientation, state protection, handoff discipline.
- GSD: phase planning, success criteria, execution routing.
- Project Execution: materialize files, validate, repair, retest, deliver.
- SocratiCode: semantic codebase exploration when code exists.
- Axon: structural analysis, impact checks, dead-code review.
- Verification: test or inspect the user-visible result.
- Handoff: preserve what shipped, what was verified, and the next action.

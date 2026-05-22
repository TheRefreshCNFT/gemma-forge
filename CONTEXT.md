# Gemma Forge Context

## Core Identity

Gemma Forge is a local Gemma 4 work harness. The product removes the setup wall around local AI by detecting the user's machine, using or preparing Ollama, recommending a compatible Gemma 4 model, and guiding project work through structured protocol cards.

The harness is the main product path.

## Product Intent

The user should not need to know model names, terminal commands, local servers, orchestration patterns, SocratiCode, Axon, or GSD before getting value. Gemma Forge should know the next useful action, explain it in plain language when needed, and keep each project focused.

Each project record is project memory. Projects can be archived, deleted, restored, or linked through bridge files when separate plans need shared context. The hidden `forge.md` context is the always-on operating guide and is not a user project.

## Authenticity Requirement

Gemma Forge must not pre-bake, fake, force, template, or hardcode successful task outputs. Only real verified results are acceptable.

For this product, a real verified result means the selected local Gemma model completes the user's requested task through the harness workflow. Deterministic scripts, validators, screenshots, and packaging steps can verify or present the result, but they cannot replace the selected model doing the work.

If the selected model did not actually complete the requested task, the correct state is unverified or failed. The product must repair orchestration, prompts, tool use, or verification instead of presenting a forced output as success.

Support tools such as Axon and SocratiCode help inspect or map a project, but they are not proof of user-facing task completion by themselves. If a support tool fails because of local environment setup, Gemma Forge should report the degraded state plainly and continue only when execution and verification artifacts prove the requested work.

## Runtime Defaults

- Ollama uses its normal default home: `~/.ollama`.
- Gemma Forge uses its own framework home: `~/.gforge`.
- Harness project data lives under `~/.gforge/harness`.
- Hidden Forge context lives at `~/.gforge/harness/forge.md`.
- The initial recommended Forge Brain is `gemma-4`, but users can switch to another available supported local model.

## Capability Scope

Gemma Forge keeps the earlier model-forging capability as supporting infrastructure, but the contest-facing experience is the Forge Harness:

- local readiness scan
- model selection and provisioning awareness
- project-scoped records
- protocol cards
- auto-run or human verification checkpoints
- verification and handoff artifacts
- error visibility through Settings

## Contest Goal

Optimize for the Gemma 4 Challenge criteria:

- intentional and effective Gemma 4 model use
- technical implementation and code quality
- creativity and originality
- usability and user experience

The strongest story is accessibility: Gemma 4 is not hidden behind a chat box or developer setup. It becomes a local project-planning brain that can guide users through planning, execution, verification, and delivery.

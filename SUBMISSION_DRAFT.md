---
title: Gemma Forge: Local AI Without the Setup Wall
published: false
tags: devchallenge, gemmachallenge, gemma
---

*This is a submission for the [Gemma 4 Challenge: Build with Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06)*

## What I Built

Gemma Forge is a local Gemma 4 work harness for people who want the benefits of local AI without needing to understand model setup, terminal commands, Ollama, or agent orchestration first.

The product starts by scanning the user's machine and showing a plain-language readiness view. It selects the smallest practical Gemma 4 model by default, keeps stronger models available only when the system can support them, and gives the user a project-focused harness instead of a global chat box.

Each project starts with one question: "What project are we planning?" From there, Gemma Forge activates protocol cards for intake, planning, execution, code intelligence, verification, and handoff. Users can run the full workflow with Full Forge, run one card with Forge Section, or enable Human verify checkpoints when they want to test along the way.

The intent is simple: make local, free AI feel usable by anyone at any skill level.

Gemma Forge stores its own project and harness state in `~/.gforge` while leaving Ollama in its standard `~/.ollama` home. That keeps the user's model runtime separate from project memory, error logs, bridges, and Gemma Forge artifacts.

## Demo

TODO: Add video walkthrough link.

Recommended demo path:

1. Launch Gemma Forge and show "Setting up workspace".
2. Show Forge Engine detecting local resources, Ollama, tools, and subagent capacity.
3. Show Forge Brain defaulting to the small Gemma 4 model.
4. Start a no-directory project.
5. Turn Human verify off and run Full Forge.
6. Show generated files, validation, repair/retest, and handoff artifacts.
7. Show Active/Archived projects and linked projects.

## Code

TODO: Add public repository link once the private prep repo is ready to publish.

Planned repository:

https://github.com/TheRefreshCNFT/gemma-forge

Planned install path:

```bash
git clone https://github.com/TheRefreshCNFT/gemma-forge.git
cd gemma-forge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m chat.server
```

Then open:

```text
http://127.0.0.1:5005/
```

## How I Used Gemma 4

Gemma 4 is the planning and orchestration brain inside Gemma Forge.

The default model lane is `gemma-4`, the smallest practical Gemma 4 model available in the harness. That choice is intentional: the project is not trying to prove that only high-end hardware can use local AI. It is trying to make local AI available to people who may not have a workstation, a cloud budget, or confidence with developer tooling.

Gemma 4 is used to:

- turn a raw project idea into a structured project plan
- decide which protocol cards are relevant
- write project-scoped context
- generate GSD-style phase plans
- prepare verification and handoff artifacts
- help users understand what to do next when they do not know the harness
- answer harness-operation questions from the current project

Gemma Forge also stays resource-aware. Larger Gemma 4 options can appear when installed or supported, but the user is not forced to understand model sizing before they can start.

The core idea is that local AI should not begin with a setup wall. Gemma Forge puts the model behind a guided work harness, so the user can focus on the project instead of the machinery.

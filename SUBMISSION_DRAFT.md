---
title: Gemma Forge: Local AI Without the Setup Wall
published: false
tags: devchallenge, gemmachallenge, gemma
---

*This is a submission for the [Gemma 4 Challenge: Build with Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06)*

## What I Built

Gemma Forge is a local Gemma 4 work harness that makes local AI useful before the user has to understand the machinery.

It starts by scanning the user's machine, checking Ollama and model readiness, defaulting to the practical `gemma-4-e4b-it` Forge Brain, and opening a project-focused workspace. From there, the user can describe what they want done in plain language. Gemma Forge turns that request into protocol cards for context, planning, execution, code intelligence, verification, and handoff.

The goal is simple: everyone should be able to use local AI. Gemma Forge opens the door by putting Gemma 4 behind a guided workbench instead of a setup wall.

Most consumers do not need to manage memory systems. They need useful work completed. Most businesses do not need extra ceremony either. They need planning, execution, testing, evaluation, and delivery. Gemma Forge lets the user give the local model a direction, add the skills the project needs, and let the harness keep the work scoped and verifiable.

Gemma Forge also comes pre-fueled with bundled skills for planning, code writing, UI/UX, scraping, PDF work, MCP servers, codebase search, structural analysis, and handoff discipline. Need more fire? Drop in a skill. If the user does not know how to create one, Gemma Forge maintenance mode can help scaffold, stage, and verify a new skill through a controlled allowlist flow.

The project is built in the open-source spirit of Gemma 4: local, inspectable, extensible, and practical for people who want AI they can run and adapt on their own machine.

## Demo

Demo materials are in the repository:

https://github.com/TheRefreshCNFT/gemma-forge/tree/main/docs/submission-media

Recommended video flow:

1. Launch Gemma Forge and show the workspace scan.
2. Show Forge Engine readiness and Forge Brain model route.
3. Start a no-directory project from a plain-language goal.
4. Run Full Forge with Human Verify off.
5. Show Project Context, GSD Planning, Project Execution, Verification, and Handoff.
6. Open the generated artifact.
7. Show Settings with model route proof and local error visibility.

Final DEV post note: embed the live walkthrough video here when the final public video URL is selected.

## Code

Repository:

https://github.com/TheRefreshCNFT/gemma-forge

Quick start:

```bash
git clone https://github.com/TheRefreshCNFT/gemma-forge.git
cd gemma-forge
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
gemma-forge
```

Then open:

```text
http://127.0.0.1:5005/
```

macOS users can also run:

```bash
./launch_forge.command
```

## How I Used Gemma 4

Gemma 4 is the planning and orchestration brain inside Gemma Forge.

The default Forge Brain is `gemma-4-e4b-it`, the Gemma 4 E4B / 4B-class local lane. I chose it as the default because Gemma Forge is trying to be usable on practical local hardware while still giving the model extra reasoning headroom for project planning, tool selection, repair loops, and verification. The harness presents the expected local footprint before provisioning: about 10 GB of disk budget and 8 GB RAM for readiness, with the current quantized Ollama artifact around 5 GB on disk.

Gemma Forge does not lock users into that default. Advanced users can import installed Ollama models or search/provision other compatible Hugging Face repos from Settings when they want a different local model.

Gemma 4 is used to:

- Convert a raw user request into a structured project contract.
- Decide which protocol cards and skills are relevant.
- Write project-scoped context and GSD-style phase plans.
- Generate or repair deliverables through the Project Execution card.
- Evaluate outputs against acceptance criteria and deterministic validation.
- Explain next steps when the user does not know which control to use.
- Produce handoff notes so work can resume cleanly.

Gemma Forge also records the model route: Forge Brain selection to Flask harness to Ollama `/api/chat`. That proof matters because the product's authenticity rule is strict. A valid result means the selected local Gemma model actually did the work through the harness. Deterministic scripts, screenshots, and validators can verify or package the result, but they do not replace Gemma 4 doing the task.

---
title: Gemma Forge: Local AI Without the Setup Wall
published: false
description: A local Gemma 4 work harness that turns local AI into a guided, inspectable project workspace.
tags: devchallenge, gemmachallenge, gemma, localai
cover_image: https://raw.githubusercontent.com/TheRefreshCNFT/gemma-forge/main/docs/submission-media/screenshots/current/01-forge-harness-overview.png
---

*This is a submission for the [Gemma 4 Challenge: Build with Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06)*

![Gemma Forge harness overview](https://raw.githubusercontent.com/TheRefreshCNFT/gemma-forge/main/docs/submission-media/screenshots/current/01-forge-harness-overview.png)

## What I Built

Gemma Forge is a local Gemma 4 work harness that makes local AI useful before the user has to understand the machinery.

The goal is simple: everyone should be able to use local AI. Gemma Forge opens that door by putting Gemma 4 behind a guided workbench instead of a setup wall.

On first launch, Gemma Forge scans the user's machine, checks Ollama and model readiness, installs or verifies the local toolchain, stages bundled skills, and opens a project-focused workspace. From there, the user can describe what they want done in plain language. Gemma Forge turns that request into protocol cards for context, planning, execution, code intelligence, verification, and handoff.

Most consumers do not need to manage elaborate memory systems. They need useful work completed. Most businesses do not need extra ceremony either. They need planning, execution, testing, evaluation, delivery, and a clean handoff. Gemma Forge lets the user give the local model a direction, add the skills the project needs, and let the harness keep the work scoped, observable, and verifiable.

Gemma Forge comes pre-fueled with bundled skills for planning, code writing, UI/UX, scraping, PDF work, MCP servers, codebase search, structural analysis, and handoff discipline. Need more fire? Drop in a skill. If the user does not know how to create one, Gemma Forge maintenance mode can help scaffold, stage, and verify a new skill through a controlled allowlist flow.

The project is built in the open-source spirit of Gemma 4: local, inspectable, extensible, and practical for people who want AI they can run and adapt on their own machine.

## Demo

Demo media and screenshots are available in the repository:

https://github.com/TheRefreshCNFT/gemma-forge/tree/main/docs/submission-media

<!-- When the final hosted video is ready, replace this comment with the DEV embed:
{% embed https://... %}
-->

<!-- Optional: after uploading a Codex or other coding-agent session in DEV, replace this comment with:
{% agent_session ID planning %}
-->

Here is the product flow I would show in the walkthrough:

1. Launch Gemma Forge and show the workspace scan.
2. Show Forge Engine readiness and the selected Forge Brain.
3. Start a no-directory project from a plain-language goal.
4. Run Full Forge with Human Verify off.
5. Watch Project Context, GSD Planning, Project Execution, Verification, and Handoff move through the protocol cards.
6. Open the generated artifact.
7. Show Settings with model route proof and local error visibility.

The main harness screen keeps local readiness, model selection, and workspace status visible in one place.

![Forge Harness readiness view](https://raw.githubusercontent.com/TheRefreshCNFT/gemma-forge/main/docs/submission-media/screenshots/current/01-forge-harness-overview.png)

New work starts with a plain-language project seed, then moves through protocol cards instead of disappearing into a loose chat thread.

![Project intake and protocol cards](https://raw.githubusercontent.com/TheRefreshCNFT/gemma-forge/main/docs/submission-media/screenshots/current/02-project-intake-protocol-cards.png)

Forge Station shows the live evidence stream: card starts, skill selection, staged skills, browser fetches, status codes, character counts, screenshot captures, and other work events.

![Forge Station evidence stream](https://raw.githubusercontent.com/TheRefreshCNFT/gemma-forge/main/docs/submission-media/screenshots/current/03-forge-station-evidence-stream.png)

Gemma Forge also leaves receipts on disk. This workspace screenshot shows the output of a real session: project context, GSD planning, research, execution notes, extra reviews, verification, handoff files, screenshots from browsed sources, and the generated `index.html` artifact.

![Workspace artifacts and generated project files](https://raw.githubusercontent.com/TheRefreshCNFT/gemma-forge/main/docs/submission-media/screenshots/current/06-workspace-artifacts.png)

Settings keeps model management local and explicit. Users can import installed Ollama models, search Hugging Face, name an Ollama model, provision supported repos, and confirm which model the harness actually called last.

![Settings model provisioning](https://raw.githubusercontent.com/TheRefreshCNFT/gemma-forge/main/docs/submission-media/screenshots/current/04-settings-model-provisioning.png)

## Code

Repository:

https://github.com/TheRefreshCNFT/gemma-forge

Quick start on macOS:

```bash
git clone https://github.com/TheRefreshCNFT/gemma-forge.git
cd gemma-forge
./launch_forge.command
```

Then open:

```text
http://127.0.0.1:5005/
```

The macOS launcher is the recommended first-run path. It installs or verifies the local toolchain, starts Ollama, pulls the default source model `gemma4:e4b`, creates the local Forge Brain alias `gemma-4-e4b-it`, stages bundled skills, prepares support tools, and starts the harness.

The first-run install default is fixed so setup is predictable. It does not lock users in. After setup, users can import installed Ollama models, search Hugging Face, provision other compatible repos, and choose a different active local model from Settings.

Manual/development launch:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
gemma-forge
```

## How I Used Gemma 4

Gemma 4 is the planning and orchestration brain inside Gemma Forge.

I chose the E4B / 4B-class lane as the default because Gemma Forge needs more reasoning headroom than a tiny model for project planning, skill routing, repair loops, and verification, while still staying realistic for local hardware. The one-command installer pulls `gemma4:e4b` and aliases it locally as `gemma-4-e4b-it`.

The harness presents the expected local footprint before provisioning: about 10 GB of disk budget and 8 GB RAM for readiness, with the current quantized Ollama artifact around 5 GB on disk.

Gemma Forge uses Gemma 4 to:

- Convert a raw user request into a structured project contract.
- Decide which protocol cards and bundled skills are relevant.
- Write project-scoped context and GSD-style phase plans.
- Generate or repair deliverables through the Project Execution card.
- Evaluate outputs against acceptance criteria and deterministic validation.
- Explain next steps when the user does not know which control to use.
- Produce handoff notes so work can resume cleanly.

Gemma Forge also records model-route proof: Forge Brain selection to Flask harness to Ollama `/api/chat`. That proof matters because the authenticity rule is strict. A valid result means the selected local Gemma model actually did the work through the harness workflow. Deterministic scripts, screenshots, code intelligence, and validators can verify or package the result, but they do not replace Gemma 4 doing the task.

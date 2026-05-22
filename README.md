# Gemma Forge

Gemma Forge is a local Gemma 4 work harness. It helps people use local AI without learning model setup, Ollama commands, agent protocols, or project orchestration first.

The app opens with a workspace scan, recommends a compatible Gemma 4 model, and then keeps each project in its own focused workspace. The user starts with one question: "What project are we planning?"

## What It Does

- Detects local CPU, memory, disk, Ollama, installed models, and tool readiness.
- Lets the user switch the selected local Gemma model from the Forge Brain dropdown.
- Unlocks larger Gemma 4 lanes only when the system can support them.
- Runs project-scoped work instead of one global chat.
- Uses protocol cards for Intake, Forge Flow, GSD Planning, Project Execution, SocratiCode, Axon, Verification, and Handoff.
- Stages installed Forge skills into each project workspace so local Gemma can follow skill instructions without relying on inaccessible absolute paths.
- Runs SocratiCode and Axon as real local project tools: semantic index/search through SocratiCode MCP and structural analysis through Axon CLI.
- Supports Full Forge auto-run or Human verify checkpoints per section.
- Stores Gemma Forge state under `~/.gforge`.
- Uses Ollama's normal local model home under `~/.ollama`.

## Why Gemma 4

Gemma Forge uses Gemma 4 as the local planning and orchestration brain. It recommends `gemma-4` on first run because the product goal is accessibility, then lets the user switch to another available supported local model from the Forge Brain dropdown.

Gemma 4 helps:

- turn an idea into a project plan
- decide which protocol cards are relevant
- create project-scoped memory
- generate phase plans and verification steps
- guide users when they do not know what control to use next
- prepare handoff notes so work can resume cleanly

## Install

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

You can also run the launcher on macOS:

```bash
./launch_forge.command
```

## Local State

Gemma Forge keeps framework state in:

```text
~/.gforge/harness/
```

Ollama keeps models in its normal default home:

```text
~/.ollama/
```

Project artifacts, bridges, logs, and model registry data stay out of the repository.

## Development Checks

```bash
npm run check
python3 -m py_compile chat/server.py chat/workspace_scan.py src/app.py src/config.py src/hf_engine.py src/utils.py tests/integration_test.py
node --check chat/static/js/chat.js
python3 tests/model_route_test.py
```

## License

MIT. See [LICENSE](LICENSE).

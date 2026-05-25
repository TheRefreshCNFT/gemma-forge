# Gemma Forge

<p align="center">
  <img src="chat/static/assets/forge-logo.svg" alt="Gemma Forge logo" width="96">
</p>

<p align="center">
  <strong>Local AI without the setup wall.</strong><br>
  A local Gemma 4 work harness for planning, execution, verification, and handoff.
</p>

<p align="center">
  <a href="https://github.com/TheRefreshCNFT/gemma-forge">Repository</a> |
  <a href="docs/submission-media">Demo Media</a> |
  <a href="CONTEST_READINESS.md">Contest Readiness</a> |
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

![Gemma Forge harness overview](docs/submission-media/screenshots/current/01-forge-harness-overview.png)

## Demo Video

<video src="https://github.com/TheRefreshCNFT/gemma-forge/releases/download/contest-video-20260524-232825/gemma-forge-contest-demo-20260524-232825.mp4" controls width="100%"></video>

[Watch the hosted demo page](https://therefreshcnft.github.io/gemma-forge/) · [Download the MP4](https://github.com/TheRefreshCNFT/gemma-forge/releases/download/contest-video-20260524-232825/gemma-forge-contest-demo-20260524-232825.mp4)

## Why Gemma Forge Exists

Everyone should be able to use local AI. Gemma Forge opens that door by turning Gemma 4 into a guided local workbench instead of leaving users to learn model setup, terminal commands, Ollama internals, prompt formats, and agent protocols before they can get anything done.

Most people do not need to manage elaborate memory systems. They need work completed. Most teams do not need extra ceremony either. They need planning, execution, testing, evaluation, and delivery. Gemma Forge gives the local model a clear direction, adds the skills a task needs, and keeps the work scoped, observable, and verifiable.

Gemma Forge comes pre-fueled and ready for action with bundled protocol skills. Need more fire? Drop in another skill. Do not know how to build one yet? Start a Gemma Forge maintenance project and the harness can help create, stage, and verify a skill through its controlled maintenance flow.

## What It Is

Gemma Forge is a local Gemma 4 work harness built for the [Gemma 4 Challenge: Build with Gemma 4](https://dev.to/challenges/google-gemma-2026-05-06). It is designed for curious users, builders, and small teams who want local AI to help with real project work while keeping model execution, project state, and generated artifacts on their own machine.

The harness:

- Scans local readiness: CPU, memory, disk, Ollama, installed models, tool state, and bundled skills.
- Defaults to `gemma-4-e4b-it`, the Gemma 4 E4B / 4B-class lane chosen for extra reasoning headroom while staying practical for local use.
- Shows users what the default model needs before provisioning: the harness reserves about 10 GB of disk and 8 GB of RAM for this lane, while the current quantized Ollama artifact is about 5 GB on disk.
- Lets users import installed Ollama models or search/provision other compatible Hugging Face repos from Settings when they want a different local model.
- Keeps each project in its own scoped workspace instead of one endless global chat.
- Runs work through protocol cards for context, planning, execution, code intelligence, verification, and handoff.
- Stages Forge skills into each project workspace so the local model can use the right instructions without depending on private absolute paths.
- Records model route evidence so users can verify that local Gemma is doing the work.
- Keeps generated project state out of the repository by default.

## Product Tour

Gemma Forge is organized around visible work surfaces, not hidden agent magic. The user can see the local environment, the default model, optional model provisioning, the active workflow card, project state, and the evidence stream that proves what happened.

The hero screenshot above shows the main Forge Harness view: local readiness, Ollama reuse, bundled tool checks, and the active Forge Brain all in one place. The one-command installer uses a fixed first-run default, `gemma4:e4b` aliased locally as `gemma-4-e4b-it`, so new users are not asked to choose a model size during setup. After install, users can switch the active Forge Brain or provision other compatible Ollama and Hugging Face models from Settings.

<table>
  <tr>
    <td width="50%" valign="top">
      <img src="docs/submission-media/screenshots/current/02-project-intake-protocol-cards.png" alt="Project intake and protocol cards">
      <br>
      <strong>Guided Project Workflow</strong>
      <br>
      New work starts with a project seed. The left side captures the goal, constraints, and project-directory choice. The right side shows protocol cards, the active section, Human Verify controls, and the project-context chat used to continue or audit a specific project.
    </td>
    <td width="50%" valign="top">
      <img src="docs/submission-media/screenshots/current/03-forge-station-evidence-stream.png" alt="Forge Station evidence stream">
      <br>
      <strong>Forge Station</strong>
      <br>
      Forge Station is the live evidence rail. It shows card starts, skill selection, staged skills, browser fetches, HTTP status codes, character counts, screenshot captures, and other work events as they happen.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="docs/submission-media/screenshots/current/04-settings-model-provisioning.png" alt="Settings model provisioning">
      <br>
      <strong>Models And Interfaces</strong>
      <br>
      Settings keeps model management in the app. Users can import installed Ollama models, search Hugging Face, name an Ollama model, provision supported repos, and confirm which model the harness actually called last. The default install target is `gemma-4-e4b-it`; users can still bring in other compatible local models when they want more control.
    </td>
    <td width="50%" valign="top">
      <img src="docs/submission-media/screenshots/current/05-project-sidebar.png" alt="Project sidebar with active and done work">
      <br>
      <strong>Project Rail</strong>
      <br>
      The project rail keeps active and finished work visible without turning the app into one endless chat. Each row shows the project title, state, and compact archive/delete actions so users can keep current work focused.
    </td>
  </tr>
</table>

## Quick Start

### Recommended macOS one-command start

```bash
git clone https://github.com/TheRefreshCNFT/gemma-forge.git
cd gemma-forge
./launch_forge.command
```

Open:

```text
http://127.0.0.1:5005/
```

This is the recommended path for most macOS users. The launcher installs or verifies the local toolchain, starts Ollama, pulls the default Forge Brain source model `gemma4:e4b`, creates the stable local alias `gemma-4-e4b-it`, stages bundled skills, provisions support tools, and starts the Forge Harness.

### What the launcher does

The one-command launcher is intentionally opinionated for first run:

1. Verifies or installs the local tools Gemma Forge depends on.
2. Starts Ollama and checks that it is reachable.
3. Pulls the default source model `gemma4:e4b` and creates the local Forge Brain alias `gemma-4-e4b-it`.
4. Creates the Python environment and installs the harness dependencies.
5. Stages the bundled Forge skills into the local harness runtime.
6. Prepares support tools such as SocratiCode, Axon, Qdrant, and the embedding model where available.
7. Starts the Forge Harness at `http://127.0.0.1:5005/`.

The install default is fixed so the first run is predictable. It does not lock the user in: Settings can still import installed Ollama models, search Hugging Face, provision compatible repos, and let users choose a different active local model after setup.

### Manual or development launch

Use the manual path when you are developing Gemma Forge directly or running outside the macOS one-command installer:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
gemma-forge
```

Then open:

```text
http://127.0.0.1:5005/
```

## Prerequisites

Gemma Forge is local-first. A typical setup should have:

- Python 3.10 or newer.
- Git.
- Ollama installed and running for local model calls.
- Node.js 18 or newer for JavaScript validation checks.
- A local Gemma model available through Ollama. On macOS, the one-command installer pulls `gemma4:e4b` and aliases it to `gemma-4-e4b-it` unless that default model step is explicitly skipped.

The macOS launcher can install or verify the required local tools for a first run. Manual installs should prepare those dependencies before launching the harness.

The harness stores its own runtime state under `~/.gforge` and leaves Ollama in its normal `~/.ollama` home.

## First Run

When the app opens, Gemma Forge shows a workspace scan and readiness view:

- Forge Engine reports local hardware, Ollama state, tool readiness, and support capacity.
- Forge Intelligence shows the default Gemma 4 E4B lane, its readiness, and whether it is installed or runnable.
- Forge Brain selects the active local model used by planning, execution, verification, and project chat.
- Settings can import installed Ollama models, search Hugging Face, provision supported GGUF models, show model-route proof, and open meaningful harness errors.

## Default Model

Gemma Forge defaults to:

```text
gemma-4-e4b-it
```

This is the Gemma 4 E4B / 4B-class local lane. It is the default because it gives the harness more reasoning headroom for planning, skill routing, repair, and verification while still being realistic for local use.

What to expect:

- Approximate readiness budget: 10 GB free disk and 8 GB RAM.
- Current quantized Ollama artifact: about 5 GB on disk.
- The one-command installer uses this fixed first-run default instead of asking users to choose a model size during setup.
- Users can still import installed Ollama models, provision other compatible Hugging Face repos from Settings, and choose what they want to run after setup.

The first useful question is simple:

```text
What project are we planning?
```

Describe what you want built, researched, fixed, planned, or verified. Gemma Forge will turn that into a project-scoped workflow.

## How The Workflow Works

Gemma Forge uses protocol cards instead of a loose chat loop.

| Card | Purpose |
| --- | --- |
| Project Context | Converts the user request into a strict deliverable contract. |
| Forge Flow | Orients on project state and protects existing work. |
| GSD Planning | Breaks work into phases, acceptance criteria, and verification gates. |
| Project Execution | Writes model-authored files, runs allowed workspace commands, validates, repairs, and records artifacts. |
| SocratiCode | Provides semantic codebase discovery when existing code needs exploration. |
| Axon | Provides structural graph and impact analysis for codebase work. |
| Verification | Checks actual artifacts and deterministic validation evidence. |
| Handoff | Captures what happened, what was verified, risks, and next steps. |

Use **Full Forge** to run all active cards in order. Use **Forge Section** to run one card. Turn **Human Verify** on when you want checkpoints, or off when you want the harness to keep moving.

## Skills

Gemma Forge ships with bundled skills so a fresh clone can do useful work without requiring users to assemble an agent toolkit first.

Included skill families:

- `forge-flow` for state, backup, and verification discipline. The bundled source skill lives at `skills/webot-flow/`, but the product surface calls this Forge Flow.
- `gsd` for project planning and phase execution.
- `code-writer` for runnable source-code deliverables.
- `scrapling-official` for web scraping, browsing, and extraction.
- `ui-ux-pro-max` for interface quality, layout, states, accessibility, and polish.
- `socraticode` for semantic codebase search and project discovery.
- `axon` for structural code graph and impact analysis.
- `logo-generator` for SVG logo and brand-mark work.
- `pdf` for PDF, form, and OCR-oriented tasks.
- `mcp-builder` for local MCP server and tool-schema work.

Skills are copied into each project workspace under `.gforge/skills` and injected only when relevant. This keeps projects portable and prevents the model from relying on private host paths.

## Maintenance Mode

Gemma Forge can help maintain itself. If you ask to change the harness, add or update a model, create a skill, adjust routing, repair readiness, or update installer behavior, the harness treats that as a Gemma Forge maintenance project.

Maintenance mode is intentionally controlled:

- The harness snapshots exact allowlisted repo or runtime targets into the project workspace.
- The model writes proposed changes into workspace artifacts.
- Outside-workspace changes must go through `artifacts/maintenance-actions.json`.
- Only validated `copy_file`, `write_file`, or `copy_tree` actions can be applied to allowlisted targets.
- Ollama commands are limited to explicit model-maintenance requests.

That gives the project a practical extension path without turning local AI into unrestricted host access.

## Local State And Privacy

Gemma Forge keeps runtime data local:

```text
~/.gforge/harness/
```

Ollama keeps models in its normal location:

```text
~/.ollama/
```

The repository is intentionally kept clean. These stay out of Git:

- Project records and generated workspaces.
- Local model registries and session data.
- `.gforge/`, `.axon/`, `.venv/`, caches, logs, and raw recordings.
- Model weights such as `.gguf` and `.safetensors`.
- Machine-specific files such as `.DS_Store` and AppleDouble metadata.

## Authenticity And Safety

Gemma Forge has one load-bearing rule: do not fake the result.

A valid run means the selected local Gemma model actually completes the requested task through the harness workflow. Scripts, validators, screenshots, and deterministic checks may verify or package the result, but they must not replace the model doing the work.

Safety boundaries include:

- Verification is read-only against deliverables.
- Workspace commands are bounded and sandboxed.
- Package installs are project-local.
- Deploy, publish, push, global installs, path escapes, shell pipes, and multiline shell are blocked in model-authored command paths.
- GitHub authentication can be used for clone/reference access, but tokens are not printed.
- Archived projects are read-only at the API boundary.

## Demo And Submission Materials

Public demo assets live in:

```text
docs/submission-media/
```

Useful entry points:

- [Demo recording guide](docs/submission-media/demo-recording-guide.md)
- [Screenshots](docs/submission-media/screenshots)
- [Processed demo clips](docs/submission-media/processed)
- [Contest readiness notes](CONTEST_READINESS.md)
- [DEV submission draft](SUBMISSION_DRAFT.md)

## Development Checks

Run the main static and unit checks:

```bash
npm run check
python -m unittest tests.model_route_test
python -m unittest tests.skill_routing_test
python -m unittest tests.maintenance_access_test
```

Clean-install verification for a fresh VM or fresh user account:

```bash
./tools/verify_clean_install.sh
```

The macOS VM orchestration helper is:

```bash
./tools/run_clean_install_test.sh
```

## Troubleshooting

### Ollama is down

Start Ollama and refresh the app:

```bash
ollama serve
```

### No Gemma model is available

Open Settings in Gemma Forge. You can import installed Ollama models, search Hugging Face, or provision a supported model into Ollama from the app.

### Port 5005 is already in use

Use the service helper:

```bash
npm run harness:status
npm run harness:restart
```

### The app launches with degraded tools

Gemma Forge can still run basic project flows when optional tools are unavailable, but SocratiCode, Axon, browser capture, and advanced validation depend on their local runtimes being ready. The launcher and Settings panel report this state plainly.

## Contributing

Gemma Forge is open source, but direct writes to `main` are maintainer-only. Public contributions should come through forks and pull requests for review.

Before opening a PR:

- Keep runtime data, generated sessions, local models, tokens, logs, and caches out of Git.
- Run `npm run check`.
- Explain how the change preserves the authenticity rule.
- Include verification evidence for user-facing behavior.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project contribution policy.

## License

MIT. See [LICENSE](LICENSE).

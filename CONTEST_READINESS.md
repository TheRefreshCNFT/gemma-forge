# Gemma 4 Challenge Readiness Plan

Source reviewed: https://dev.to/devteam/join-the-gemma-4-challenge-3000-prize-pool-for-ten-winners-23in

Template reviewed: the "Build With Gemma 4 Submission Template" opens a DEV post prefill with frontmatter, the challenge submission sentence, and these required sections:

- What I Built
- Demo
- Code
- How I Used Gemma 4

## Rule And Judging Checklist

- Submit under the Build With Gemma 4 prompt.
- Build something useful or creative with Gemma 4 doing real work at the heart of the project.
- Explain which Gemma 4 model is used and why that model is the right fit.
- Include a demo link or video walkthrough.
- Include a code repository link.
- Optimize for the stated judging criteria:
  - intentional and effective Gemma 4 model use
  - technical implementation and code quality
  - creativity and originality
  - usability and user experience
- Submission deadline from the challenge page: May 24, 2026 at 11:59 PM PDT.

## Product Positioning

Gemma Forge makes local free AI usable by people who do not want to learn model hosting, terminals, Ollama setup, or project-agent orchestration first.

The product goal is:

- local AI that feels approachable
- project-based memory instead of one endless global chat
- focused projects for planning and implementation
- project linking only when separate project threads need shared context
- the smallest practical Gemma 4 model as the default brain
- stronger models available when local resources support them
- agent behavior that knows the harness and guides the user through it

## Current Strengths

- Local resource scan on load.
- Default small Gemma 4 model lane.
- Ollama/model readiness detection.
- Project-scoped records.
- Active/Archived project split.
- Archive, restore, delete, and link project controls.
- Protocol cards for Intake, Forge Flow, GSD, Project Execution, SocratiCode, Axon, Verification, and Handoff.
- Full Forge end-to-end card execution.
- Human verify or auto-run mode per visible card.
- Contextual help in key UI areas.
- Harness-agent operating protocol now included in local Gemma prompts.
- Gemma Forge state now defaults to `~/.gforge`; Ollama stays in `~/.ollama`.
- Settings includes a meaningful error log and model-route status.
- `pyproject.toml` exposes a `gemma-forge` CLI entry point.

## Remaining Required Before Submission

1. Record a short demo video.
   - Show first load and "Setting up workspace".
   - Show Forge Engine readiness.
   - Show Forge Brain defaulting to the small model.
   - Start a project with no directory.
   - Run Full Forge.
   - Show generated artifacts and verification.
   - Show archive/restore and project linking.

2. Prepare public code access.
   - Private repo is fine during prep.
   - Make the repo public before posting unless the challenge page or DEV submission rules provide a private-access path for judges.
   - Submission template asks for a repository link, so the final link should be accessible.

3. Package install path.
   - Minimum viable install: GitHub clone plus setup script.
   - Git URL install path exists through `pyproject.toml` and the `gemma-forge` CLI.
   - Better release: GitHub Release zip/tar with launcher scripts after final verification.

4. Final docs.
   - README now centers the Forge Harness.
   - Add screenshots.
   - Add install section for macOS/Linux.
   - Add troubleshooting for Ollama and models.
   - License file exists.

5. Final verification.
   - Fresh clone install test.
   - Start harness on a clean environment.
   - Verify no local user project records, models, tokens, logs, or generated artifacts are committed.
   - Run syntax checks and browser smoke test.

## Private Repo Status

Private prep repository is created:

```text
https://github.com/TheRefreshCNFT/gemma-forge
```

Current visibility: private.

Local git metadata is initialized and `origin` points to the private repo. No commit or push has been made yet.

Initial setup commands used:

```bash
git init -b main
gh repo create TheRefreshCNFT/gemma-forge --private --source=. --remote=origin --description "Gemma Forge local Gemma 4 work harness"
```

Do not commit until the file list is reviewed. The `.gitignore` now excludes local project records, generated project artifacts, Axon indexes, logs, model files, and local environment folders.

Public release switch:

```bash
gh repo edit TheRefreshCNFT/gemma-forge --visibility public
```

Only run this after the submission files, screenshots, README, and install test are ready.

## Download And Install Options

### Immediate GitHub Install

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

### GitHub Release

Create a release zip with:

- source code
- requirements
- launch scripts
- README
- demo screenshots
- no project records, models, tokens, logs, or generated workspaces

### pipx / Git URL Install

Users can install from GitHub:

```bash
pipx install git+https://github.com/TheRefreshCNFT/gemma-forge
gemma-forge
```

This is the cleanest "install it from GitHub" path, but it needs a small packaging pass before submission.

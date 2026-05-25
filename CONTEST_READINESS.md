# Gemma 4 Challenge Readiness

Source reviewed:

- https://dev.to/challenges/google-gemma-2026-05-06
- https://dev.to/page/gemma-4-challenge-2026-05-06-contest-rules

The Build With Gemma 4 submission template asks for:

- What I Built
- Demo
- Code
- How I Used Gemma 4

Judging emphasizes:

- Intentional and effective Gemma 4 use.
- Technical implementation and code quality.
- Creativity and originality.
- Usability and user experience.

## Product Positioning

Gemma Forge is a local Gemma 4 work harness that removes the setup wall around local AI.

Core story:

- Everyone should be able to use local AI.
- Gemma Forge opens the door by turning Gemma 4 into a guided local workbench.
- Users do not need to learn model hosting, terminal setup, Ollama internals, memory systems, or agent protocols before getting value.
- The harness focuses on work: planning, execution, testing, evaluation, delivery, and handoff.
- Gemma Forge ships with bundled skills and can use maintenance mode to create or update skills when the user needs more capability.

## Gemma 4 Use

Default model:

```text
gemma-4-e4b-it
```

Rationale:

- The E4B / 4B-class lane gives extra reasoning headroom for planning, routing, repair, and verification.
- It stays practical for local use compared with large workstation-only models.
- Default readiness budget: about 10 GB free disk and 8 GB RAM, with the current quantized Ollama artifact around 5 GB on disk.
- The one-command installer uses `gemma-4-e4b-it` as a fixed first-run default instead of asking users to choose a model size during setup.
- After install, users can import installed Ollama models or search/provision other compatible Hugging Face repos from Settings.
- Model route proof is visible through the harness: Forge Brain selection -> Flask harness -> Ollama `/api/chat`.

## Repository Status

Repository:

```text
https://github.com/TheRefreshCNFT/gemma-forge
```

Current public-release intent:

- Repo is public.
- `main` should be maintainer-controlled.
- External contributors should use forks and pull requests.
- CODEOWNERS should require `@TheRefreshCNFT` review for repository changes.
- Runtime data, generated sessions, model files, logs, local caches, and private machine artifacts must stay out of Git.

## Submission Assets

Repository assets:

- `README.md` - public project overview and getting-started guide.
- `SUBMISSION_DRAFT.md` - DEV submission draft.
- `docs/submission-media/README.md` - media index.
- `docs/submission-media/demo-recording-guide.md` - live demo recording flow.
- `docs/submission-media/screenshots/` - UI screenshots.
- `docs/submission-media/processed/` - processed live demo clips.
- `docs/model-routing-proof.md` - model-route proof path.

Final post still needs one selected public demo URL or embedded DEV video.

## Readiness Checklist

- [x] Public repository exists.
- [x] README centers the Forge Harness instead of the older model-forging GUI.
- [x] Install path documented.
- [x] Gemma 4 model-choice rationale documented.
- [x] Local state and privacy boundaries documented.
- [x] Maintenance mode documented.
- [x] Contribution policy documented.
- [x] Public repo file hygiene reviewed for local-only runtime paths.
- [x] GitHub branch protection verified on `main`.
- [x] Final validation run recorded after public-doc polish.
- [ ] Final demo video URL selected and inserted into the DEV post.

## GitHub Protection

Verified repository settings:

- Repository visibility is public.
- Only `TheRefreshCNFT` is listed with collaborator/admin access.
- Forking is allowed so outside contributors can submit pull requests.
- `main` has branch protection enabled.
- Pull request reviews are required.
- CODEOWNERS review is required.
- Stale reviews are dismissed after new pushes.
- Force pushes are disabled.
- Branch deletion is disabled.
- Linear history and conversation resolution are required.
- Secret scanning and push protection are enabled.
- Dependabot security updates are enabled.

## Verification Commands

Main local checks:

```bash
npm run check
python -m unittest tests.model_route_test
python -m unittest tests.skill_routing_test
python -m unittest tests.maintenance_access_test
```

Clean install check:

```bash
./tools/verify_clean_install.sh
```

Full VM clean-install orchestration:

```bash
./tools/run_clean_install_test.sh
```

## Public Repo Exclusions

Do not commit:

- `.gforge/`
- `.axon/`
- `chat/session-data/`
- `chat/sessions.json`
- `chat/models.json`
- `crash_log.txt`
- `.venv/`
- caches and bytecode
- raw recordings
- model weights
- `.DS_Store`
- `._*` AppleDouble files

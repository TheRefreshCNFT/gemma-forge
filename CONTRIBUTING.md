# Contributing To Gemma Forge

Thanks for helping make local AI easier to use.

Gemma Forge is open source, but direct writes to `main` are maintainer-only. Public contributions should come through forks and pull requests. Repository ownership is declared in `.github/CODEOWNERS`, and changes should be reviewed by `@TheRefreshCNFT` before merge.

## Before You Open A Pull Request

- Run `npm run check`.
- Keep the change focused.
- Explain how the change was verified.
- Do not commit runtime data, generated sessions, logs, caches, local model files, tokens, or machine-specific files.
- Preserve the authenticity rule: Gemma Forge must not fake task outputs or replace local Gemma model work with hidden generators.

## Good PRs

Good PRs usually include:

- A short problem statement.
- A concise implementation summary.
- Screenshots or artifact links for UI changes.
- Test output or manual verification notes.
- Any remaining risk or follow-up work.

## Security And Local Data

Gemma Forge is local-first, so privacy and filesystem boundaries matter.

Never include:

- API keys or tokens.
- `.gforge/` runtime state.
- `.axon/` indexes.
- `chat/session-data/`, `chat/sessions.json`, or `chat/models.json`.
- `.venv/`, caches, bytecode, logs, raw recordings, or model weights.

For sensitive security issues, avoid posting exploitable details in a public issue. Use GitHub's private vulnerability reporting path if it is available for the repository, or contact the maintainer privately before publishing details.

## Development Checks

```bash
npm run check
python -m unittest tests.model_route_test
python -m unittest tests.skill_routing_test
python -m unittest tests.maintenance_access_test
```

Clean-install verification:

```bash
./tools/verify_clean_install.sh
```

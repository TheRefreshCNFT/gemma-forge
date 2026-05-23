**Project Brief**
- Gemma Forge is local AI harness to make local AI easy to use for curious or advanced users. Validate all your code, security a never be overlooked.

**Starting Point**
- HANDOFF.md
- ACTIVE_STATE.md
- .handoffs/CURRENT_STATE.md

**Required Skills**
- /webot-flow
- /gsd
- /code-exploration

**Goals**
- Get fully acquainted with the project
- Validate the live state backup of what the user requested to be updated prior to making any changes, backup locations will be in the **Starting Point** docs, let the user know the state prior to backing non backed up content
- Once you are fully aligned let the user know
- Handle the user's request as guided by the **Required Skills**
- NEVER perform full code updates unless explicitly asked for
- Updates are pinpointed using /code-exploration, then strategically applied to exact bit of code that required a patch
- Have no negative impact on working live environments

**Backup + GitHub Alignment Rule**
- When Ian asks for a backup, full state backup, state alignment, final push, or anything equivalent, do BOTH:
  1. Back up the full live local working state to the external SSD at `/Volumes/PHIXERO/Backups/gemma-forge/<TIMESTAMP>-full-live-local-working-state/`, including ignored runtime files and a restore archive.
  2. Align GitHub with the installable repo state by committing and pushing every file needed for a fresh clone/install to work.
- Do not push local-only runtime data or machine artifacts: `.gforge/`, `.axon/`, `chat/session-data/`, `chat/sessions.json`, `chat/models.json`, `crash_log.txt`, `.venv/`, caches, raw recordings, model weights, `.DS_Store`, or `._*` AppleDouble files.
- The repo should contain the launcher, harness code, docs, tests, clean-install tools, and bundled protocol skills required for one-package installation.
- Treat "backup complete" as incomplete until the external SSD backup is verified AND GitHub is aligned or the blocker is explicitly reported.

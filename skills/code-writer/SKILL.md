---
name: code-writer
description: Build, modify, and verify local code deliverables in common languages, especially Python, JavaScript, TypeScript, HTML/CSS, SQL, and shell scripts. Use when the user asks to write a script, CLI, module, web app, API client, parser, test, automation, or other executable/source-code artifact. Do not use as a substitute for SocratiCode/Axon when the task is primarily codebase discovery, semantic search, call graph, dependency impact, or dead-code analysis.
keywords:
  - code writer
  - code generation
  - write code
  - implement code
  - build script
  - python script
  - python cli
  - javascript module
  - typescript module
  - html css js
  - web app
  - single page app
  - api client
  - parser
  - automation script
  - unit tests
  - sql query
  - shell script
---

# Code Writer

Use this skill when the primary deliverable is source code or an executable
local artifact.

## Routing

- Fresh code, scripts, CLIs, modules, utilities, tests, parsers, small web apps,
  API clients, SQL, shell scripts: use this skill.
- Existing-codebase discovery, architecture mapping, "where does this live",
  semantic search, dependency context: use SocratiCode first.
- Structural graph, call graph, blast radius, circular dependencies, dead code:
  use Axon.
- UI, dashboard, layout, component states, visual hierarchy, accessibility:
  pair with UI/UX Pro Max. UI/UX owns design direction; Code Writer owns the
  concrete implementation.
- Web scraping/crawling/browser extraction: pair with Scrapling. Scrapling owns
  source acquisition; Code Writer owns parsing, transformation, and packaging.

## Core Workflow

1. Identify the runnable unit: script, CLI, module, webpage, test, SQL, or config.
2. Choose the smallest conventional structure for the language and task.
3. Write complete files, not patches or placeholders.
4. Add error handling for expected bad inputs and missing files.
5. Keep dependencies minimal. Prefer the standard library unless a package is
   clearly justified and installable in the workspace.
6. Include a simple validation path: unit test, smoke command, syntax check,
   sample input/output, or deterministic assertion.
7. If workspace exec is available, request a simple command in `COMMANDS` and
   do not claim it ran until the harness records the command run.

## Language Defaults

- Python: prefer standard-library CLIs with `argparse`, clear functions, and
  `if __name__ == "__main__": main()`. Use `pathlib`, structured exceptions,
  and tests or sample commands.
- JavaScript/TypeScript: prefer small ES modules or browser-safe scripts.
  Avoid framework scaffolds unless the user asks for a framework.
- HTML/CSS/JS: produce a complete runnable page. Keep links/assets
  workspace-relative and emit every referenced local file.
- SQL: write explicit schema/query files with comments only where they clarify
  intent. Do not claim execution unless a database command actually ran.
- Shell: keep scripts POSIX-ish when possible, quote variables, use `set -euo
  pipefail` for Bash/Zsh scripts, and avoid destructive commands.

## Verification Rules

- Syntax checks are not enough for user-facing behavior; include a behavioral
  smoke check when possible.
- For generated files, verify paths and referenced assets exist.
- For parsing/transforms, include a sample input and expected output or a small
  assertion.
- For UI code, pair with screenshots when the harness/browser path supports it.

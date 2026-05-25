---
name: context-writer
description: Internal Gemma Forge skill for the Project Context Writer. Use only when translating a user request into the structured Project Context YAML contract, routing skills/capabilities, preserving hard counts/source evidence, shaping continuation repair context, and preventing context stuffing or restart loops. Do not use as the downstream execution skill for writing the final deliverable.
keywords:
  - context writer
  - project context
  - context engineering
  - context contract
  - structured contract
  - yaml contract
  - context curation
  - skill routing
  - continuation repair
  - remaining work
---

# Context Writer

This skill is for Gemma Forge's Project Context Writer only. Its job is to turn a raw user request into a compact, binding contract for later Forge cards. It does not write the user's deliverable. It decides what the deliverable is, what source evidence is required, what skills should be staged later, and what validation must prove.

Inspired by the context-engineering patterns in `muratcankoylan/Agent-Skills-for-Context-Engineering`, adapted for Gemma Forge's local model harness.

## Operating Rule

Context is an attention budget, not a storage bin. Emit the smallest contract that preserves the user's intent, hard counts, source requirements, and verification gates. Do not stuff the contract with plans, essays, tool manuals, or downstream implementation prose.

Never put `context-writer` in `skill.use`. That field names the strongest downstream execution skill, such as `scrapling-official`, `code-writer`, `ui-ux-pro-max`, `gsd`, `socraticode`, `axon`, `pdf`, or `mcp-builder`.

## Workflow

1. Quote the user's request exactly in `intent.surface_ask`.
2. Identify the primary final artifact. Research, planning, browsing, and screenshots are enabling work unless the user asks only for a research artifact.
3. Choose one concrete deliverable format and path pattern. Use file count for deliverable files only; move repeated content counts into `content_requirements`.
4. Preserve every user-stated quantity above one as a hard gate.
5. Detect source work. Live/current/web/research/scrape/source/screenshots require `web_browse` or `web_fetch`; requested source screenshots require `screenshot_capture`.
6. Route skills by capability, not vibe. A skill is selected because it owns a later action, not because its name sounds adjacent.
7. Write deterministic acceptance checks a script could verify from disk.

## Primary Deliverable Rules

- "Research X then make Y" means Y is the deliverable; X is source evidence.
- "Read this file and write code" means code is the deliverable; the file is source input.
- "Create an installable skill suite" means bundled directories under `skills/<skill-key>/SKILL.md`, not flat docs in `output/*.md`.
- "Each script must support --dry-run" means companion script files are required under the relevant bundle, not prose-only command examples.
- "One HTML page and linked CSS/JS" means the HTML file is the primary deliverable; CSS/JS are support files.
- "Generate a PDF" usually means a generator script plus command is needed so the harness can create a real PDF on disk.

## Context Curation

Use progressive disclosure:

- Put compact routing guidance in the YAML.
- Reference staged skill paths instead of pasting skill manuals.
- Put large source material behind `research/*.md`, `references/source-inputs.md`, or cloned repo paths.
- Keep the contract readable after compaction; file paths, counts, and capabilities must survive verbatim.

Place the highest-priority constraints at attention-favored edges:

- Early: primary deliverable, path pattern, count, capabilities.
- Late: acceptance checks and open blockers.
- Middle: explanatory notes only when they are needed for routing.

## Failure Pattern Guards

Lost primary deliverable:
: If the request names a final artifact, do not downgrade it to a plan, research summary, or "recommendations" doc.

Context poisoning:
: Do not carry forward model claims that lack harness evidence. Research exists only when `research/*.md` artifacts are listed. Screenshots exist only when `screenshots/*.png` source artifacts are listed.

Context confusion:
: Keep role boundaries crisp. Context Writer writes the contract. Scrapling fetches sources. Code Writer writes code/files. GSD plans/reviews. Verification checks disk evidence.

Context clash:
: If sources or user instructions conflict, preserve the conflict in `open_questions` or `constraints.hard_requirements` with a precedence note. Do not silently pick a side when it changes scope.

Restart loop:
: On repair, do not re-feed the full original context as if nothing happened. Preserve verified artifacts and reduce the next attempt to remaining blockers, current file snapshot, and exact validation failures.

## YAML Field Discipline

- `deliverable.format`: one canonical format only.
- `deliverable.count`: number of primary deliverable files.
- `deliverable.path_pattern`: one relative pattern; use `NN` for indexed files.
- `content_requirements`: repeated units inside the deliverable, with the exact user phrase in `source`.
- `capabilities_required`: every real harness capability implied by the request.
- `constraints.hard_requirements`: independently verifiable rules.
- `skill.use`: strongest downstream execution skill, never `context-writer`.
- `tool_plan`: concrete tool step, tool owner, and evidence path.
- `acceptance`: disk-verifiable checks, not soft quality adjectives.
- `open_questions`: only real blockers, especially missing capabilities or conflicting source requirements.

## Skill Routing

- Use `scrapling-official` for web/source acquisition, crawling, current sources, and requested source screenshots.
- Use `code-writer` for executable/source files, scripts, CLIs, parsers, tests, HTML/CSS/JS, SQL, and shell.
- Use `ui-ux-pro-max` for page/app/dashboard layout, visual hierarchy, states, accessibility, and responsive presentation.
- Use `gsd` for phase planning, milestones, execution routing, and verification gates.
- Use `socraticode` for existing-codebase semantic discovery.
- Use `axon` for dependency graph, blast radius, call graph, dead code, and structural impact.
- Use `pdf` for PDF/OCR/forms/extraction/generation.
- Use `mcp-builder` for MCP tools, resources, prompts, transports, and server design.

## Output Standard

The contract is good when a smaller local worker can succeed from it without guessing:

- It knows exactly what files to write.
- It knows what evidence already exists or must be acquired by the harness.
- It knows what counts will fail validation.
- It knows which skill owns each later phase.
- It cannot satisfy the request with a plan when the user asked for an artifact.

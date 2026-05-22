# Model capability notes

> Verified once on 2026-05-21. Update if model family changes.

## Default model: gemma-4

**Verified official Google release.** gguf metadata reads:

```
general.name: Google_Gemma 4 E2B It
general.size_label: 4.6B
general.license: apache-2.0
general.license.link: https://ai.google.dev/gemma/docs/gemma_4_license
general.base_model.0.organization: Google
general.base_model.0.repo_url: https://huggingface.co/google/gemma-4-E2B
general.sampling.temp: 1.0
```

601 tensors, Q4_K_M, native temp 1, 131K context. Source gguf at
`Projects/gguf/models/google_gemma-4-E2B-it.gguf` (3.43 GB).
Not a fork, not a merge, not a quirky community quant.

## Honest capability profile by model size

| Size class | Good at | Struggles with |
|---|---|---|
| **2–5B** (gemma-4 E2B, UnCenOr) | Structured emission (JSON/YAML/SVG), code scaffolding, single-file pages, README/spec writing, pattern-matched output, tool calls with tight schemas | Aesthetic judgment, multi-step reasoning under ambiguity, long-form coherence, novel problem solving |
| **8–13B** (gempus4:tuned at 13B-ish) | Multi-file projects, design-with-taste hints, longer coherent writing, refactors with context | Top-tier aesthetics, expert-domain nuance, very long horizons |
| **30B+** (gemma4:31b-max) | Real design taste, complex reasoning, multi-file refactors, novel solutions | Cold-start latency, RAM footprint |

## What gemma-4 (4.6B) wins at in the harness

- Project Context Writer (deterministic schema emission). **Confirmed in production.**
- Code scaffolding: index.html, style.css, app.py, requirements.txt, Dockerfile, .github/workflows/*.yml, package.json.
- READMEs, changelogs, install guides, API briefs.
- Pattern-matched SVG (geometric primitives, concentric circles, node graphs, monograms).
- Phase plans, acceptance criteria, verification checklists.
- Single-file CLIs (Python / shell / Node) under ~200 lines.
- Validators, parsers, small data-transformation scripts.

## What gemma-4 struggles with

- "Make it look cool/modern/sleek" — aesthetic judgment requires more params.
- Multi-page projects with cross-file consistency.
- Highly varied creative output without worked examples to riff on.
- Long-form content where coherence matters past ~500 lines.
- Style mimicry of specific brands / authors / personalities.

## Suggested contest demo tasks (gemma-4 looks good)

1. *"Build me a landing page for a coffee shop called Crema."* — index.html + style.css, gemma-4 strength.
2. *"Write a Python CLI that summarizes a CSV."* — pure scaffolding win.
3. *"Generate 6 SVG favicons for X."* — small, structured, pattern-y.
4. *"Create a README for a new open-source tool that does Y."* — pure 4.6B strength.
5. *"Write a phase plan for shipping a chrome-extension."* — exactly the planning lane.

## Logo demo specifically

Possible but it's near the hard edge of what 4.6B can do. Boost via:

1. **Few-shot examples** in logo-generator's OUTPUT.md (P0.4).
2. **Variant-generation mode** when `deliverable.count > 1` — explicit "produce N distinct variants" in the prompt.
3. **Per-task model recommendation** — design_deliverable tasks recommend gempus4 or gemma4:31b-max if installed.

## What we learned debugging

- Forcing `temperature 0.2` globally hurt every model whose Modelfile
  was tuned at 1. Removed.
- Forcing `num_ctx 8192` capped gempus4:tuned (its Modelfile is 65536).
  Removed. Both fixed in `OLLAMA_DEFAULT_OPTIONS = {}`.
- Small models pattern-match every literal string near "format" or
  "encoding". `encoding: gforge_file_block` looked like a markdown
  code-fence language tag — the model emitted ```gforge_file_block
  instead of the literal delimiters. Fixed by showing the explicit
  delimiter syntax in the contract block with anti-pattern callouts.
- Substring matching against agent message content marked unrelated
  skills (`gsd`, `socraticode`) as "requested" and stuffed their
  SKILL.md into the prompt. Fixed by gating staging on
  `projectContext.skill.use` from the Context Writer.

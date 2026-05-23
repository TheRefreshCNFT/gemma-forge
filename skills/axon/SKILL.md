---
name: axon
description: Build a knowledge graph from any codebase, then query it. Use this skill when asked to analyze a repo's structure, find dead code, trace call graphs, see what breaks if a symbol changes, discover code clusters, run Cypher against a code graph, or expose codebase context to an AI agent via MCP. Trigger phrases include "dead code", "what calls this", "blast radius", "impact analysis", "code coupling", "knowledge graph", "MCP server for code", "explain this codebase", or "find circular dependencies".
version: "1.0.1"
license: Complete terms in LICENSE.txt
metadata:
  homepage: "https://github.com/harshkedia177/axon"
  openclaw:
    emoji: "🧠"
    homepage: "https://github.com/harshkedia177/axon"
    requires:
      bins:
        - python3
      anyBins:
        - pip
        - pip3
---

# Axon

Axon indexes a codebase into a structural knowledge graph. Every dependency, call chain, type reference, community cluster, and execution flow ends up in a local graph database. You query it from the CLI, a web UI, or an MCP server.

The PyPI package is named **`axoniq`**. The CLI is named **`axon`**. Internal Python imports use `axon`.

**Requires: Python 3.11+**

**Local-only.** Parsing, graph storage, embeddings, and search all run on disk. No external APIs.

**Supported languages:** Python (`.py`), TypeScript (`.ts`, `.tsx`), JavaScript (`.js`, `.jsx`, `.mjs`, `.cjs`). Other languages are ignored.


## Setup (once)

Inside a Python 3.11+ environment:

```bash
pip install axoniq
```

The web UI (FastAPI backend + React frontend) ships inside the wheel, so no Node.js install is needed.

Optional Neo4j backend:

```bash
pip install "axoniq[neo4j]"
```

## When to use Axon

Use Axon whenever a question is about **structure**, not text:

- "What functions call `validate_user`?"
- "What breaks if I change the return type of `User.save`?"
- "Show me the dead code in this repo."
- "Which files always change together with `auth.py`?"
- "Are there circular dependencies between these modules?"
- "What community does `UserService` belong to?"
- "Find the shortest call chain from `cli.main` to `KuzuBackend.execute_raw`."
- "What tests are likely affected by this git diff?"

For plain text search use grep. For structural questions, run `axon analyze .` then query.

## Workflow

There are exactly three steps:

1. **Index.** `cd` into the repo, then `axon analyze .`. Writes `.axon/kuzu/` and `.axon/meta.json`. Takes a few seconds for most repos.
2. **Query.** Use the CLI (`axon query`, `axon context`, `axon impact`, `axon dead-code`, `axon cypher`) or the MCP server.
3. **Optional: live updates.** `axon watch` re-indexes on save. `axon serve --watch` does the same while exposing MCP.

The index lives entirely under `<repo>/.axon/`. Add `.axon/` to `.gitignore`.

## CLI reference (short form)

```
axon analyze [PATH]          Index the repo at PATH (default: .)
    --no-embeddings          Skip vector embeddings (faster, semantic search off)

axon status                  Print stats for the current repo's index
axon list                    List every indexed repo on this machine
axon clean                   Delete .axon/ for the current repo
    --force / -f             Skip confirmation

axon query QUERY             Hybrid search (BM25 + vector + fuzzy)
    --limit / -n N           Max results (default 20)

axon context SYMBOL          360-degree view: callers, callees, types, community
axon impact SYMBOL           Blast radius — what changes if SYMBOL changes
    --depth / -d N           BFS depth 1..10 (default 3)

axon dead-code               List unreachable symbols
axon cypher QUERY            Run a read-only Cypher query against the graph

axon watch                   Re-index on file changes (Ctrl+C to stop)
axon diff BASE..HEAD         Symbol-level diff between two git refs

axon mcp                     Start MCP server over stdio (no watcher)
axon serve --watch           Start MCP server with live re-indexing
axon host                    Shared host: web UI + multi-client HTTP MCP
    --port / -p PORT         Port (default 8420)
    --bind HOST              Interface to bind (default 127.0.0.1)
    --watch / --no-watch     Live re-indexing (default on)
    --no-open                Don't auto-open browser

axon ui                      Web dashboard at localhost:8420
    --port / -p PORT         Port (default 8420)
    --watch / -w             Live re-indexing
    --no-open                Don't auto-open browser
    --direct                 Force standalone mode even if a host is running

axon setup --claude          Print MCP config for Claude Code
axon setup --cursor          Print MCP config for Cursor

axon --version               Print version
```

Every output is plain text. No JSON unless you go through the HTTP API.

## Worked examples

### 1. Index, then ask what calls a function

```bash
cd ~/Projects/my-repo
axon analyze .
axon context validate_user
```

`axon context` prints the symbol's file, the callers (with confidence), the callees, the type references, and the community it sits in.

### 2. Find dead code, then check what (if anything) still calls one of the entries

```bash
axon dead-code
axon context some_unreachable_function
```

If `context` shows zero callers, the dead-code report is correct. If it shows callers, the dead-code pass exempted them (constructor, protocol stub, framework entry point).

### 3. Use Axon as an MCP server from inside another AI agent

Create `.mcp.json` in the repo root:

```json
{
  "mcpServers": {
    "axon": {
      "command": "axon",
      "args": ["serve", "--watch"]
    }
  }
}
```

The agent gets 15 tools: `axon_query`, `axon_context`, `axon_impact`, `axon_dead_code`, `axon_detect_changes`, `axon_cypher`, `axon_coupling`, `axon_communities`, `axon_explain`, `axon_review_risk`, `axon_call_path`, `axon_file_context`, `axon_test_impact`, `axon_cycles`, `axon_list_repos`.

### 4. Run a Cypher query directly

```bash
axon cypher "MATCH (n:Function) WHERE n.is_dead = true RETURN n.name, n.file_path LIMIT 20"
```

Write keywords (`CREATE`, `DELETE`, `DROP`, `SET`, `MERGE`, `REMOVE`) are rejected — the graph is read-only from outside.

## Storage layout

```
<repo>/
  .axon/
    kuzu/            KuzuDB graph database (graph + FTS + vectors)
    meta.json        Stats and last_indexed_at timestamp
~/.axon/
  repos/<slug>/      Global registry, populated automatically on analyze
```

## References

When you need more detail than this file:

- `references/commands.md` — every CLI subcommand with every flag, copied from the source
- `references/mcp-server.md` — all 15 MCP tools with input schemas and the 3 resources
- `references/dashboard.md` — the `axon ui` web dashboard (Explorer / Analysis / Cypher Console)
- `references/graph-model.md` — nodes, edges, ID format, properties
- `references/cypher-queries.md` — ready-to-run Cypher queries for common questions

## Rules

- Always run `axon analyze .` once before any query command. If the user asks a structural question without an index, run analyze first.
- Treat `axon cypher` as read-only. Don't generate write queries — they'll be rejected.
- Don't index outside the user's repo. The index writes to `.axon/` in the current directory only.
- Don't invent flag names. If a flag isn't in this file or in `references/commands.md`, it doesn't exist.

# Axon CLI Reference

Every command, every flag. Pulled from `src/axon/cli/main.py` in the upstream repo.

The CLI is built with [Typer](https://typer.tiangolo.com/). The binary is named `axon`. Run `axon --help` for the Typer-rendered version.

## Top-level options

| Flag             | Description                       |
| ---------------- | --------------------------------- |
| `--version, -v`  | Print version and exit.           |
| `--help`         | Print Typer help and exit.        |

## `axon analyze [PATH]`

Index a repository into a knowledge graph. Writes `<PATH>/.axon/kuzu/` (graph DB) and `<PATH>/.axon/meta.json` (stats).

| Argument / Flag             | Type     | Default | Description                                                                                  |
| --------------------------- | -------- | ------- | -------------------------------------------------------------------------------------------- |
| `PATH`                      | Path     | `.`     | Path to the repository.                                                                      |
| `--no-embeddings`           | bool     | false   | Skip vector embedding generation. Faster, but semantic search is disabled.                   |
| `--foreground-embeddings`   | bool     | false   | Generate embeddings synchronously instead of in a background thread.                         |

After indexing, the repo is auto-registered in `~/.axon/repos/<slug>/` so `axon list` can find it.

## `axon status`

Print index status for the current repo. Reads `./.axon/meta.json`. Exits non-zero if there's no index.

No flags.

## `axon list`

List every indexed repo on this machine. Scans `~/.axon/repos/*/meta.json`. Falls back to the current `./.axon/meta.json` if the registry is empty.

No flags.

## `axon clean`

Delete `./.axon/` for the current repo.

| Flag           | Type | Default | Description                |
| -------------- | ---- | ------- | -------------------------- |
| `--force, -f`  | bool | false   | Skip confirmation prompt.  |

## `axon query QUERY`

Hybrid search (BM25 full-text + 384-dim vector + fuzzy Levenshtein). Same handler as the `axon_query` MCP tool.

| Argument / Flag    | Type    | Default | Description                  |
| ------------------ | ------- | ------- | ---------------------------- |
| `QUERY`            | string  | (required) | Search query text.        |
| `--limit, -n`      | int     | 20      | Maximum number of results.   |

## `axon context SYMBOL`

360-degree view of a symbol: file, signature, callers (with confidence), callees, type references, community membership, dead-code status.

| Argument | Type   | Default | Description                  |
| -------- | ------ | ------- | ---------------------------- |
| `SYMBOL` | string | (required) | Name of the symbol to inspect. |

## `axon impact SYMBOL`

Blast-radius analysis — every symbol affected by changing `SYMBOL`. Results are grouped by BFS depth:

- Depth 1: direct callers (will break)
- Depth 2: indirect callers (may break)
- Depth 3+: transitive (review)

| Argument / Flag   | Type    | Default | Description                                |
| ----------------- | ------- | ------- | ------------------------------------------ |
| `SYMBOL`          | string  | (required) | Symbol to analyse.                      |
| `--depth, -d`     | int     | 3       | BFS traversal depth. Range: 1..10.         |

## `axon dead-code`

List every symbol with no incoming calls, after exemptions for entry points, exports, constructors, test code, dunder methods, `__init__.py` symbols, decorated functions, `@property` methods, overrides of non-dead base methods, Protocol conformance, and Protocol class methods.

No flags.

## `axon cypher QUERY`

Execute a raw Cypher query against the KuzuDB graph. Read-only — write keywords (`CREATE`, `DELETE`, `DROP`, `SET`, `MERGE`, `REMOVE`) are rejected after comment stripping.

| Argument | Type   | Default | Description                |
| -------- | ------ | ------- | -------------------------- |
| `QUERY`  | string | (required) | The Cypher query.       |

See `references/cypher-queries.md` for ready-to-run queries and `references/graph-model.md` for the schema.

## `axon watch`

Live re-indexing. Runs the file walker, parser, calls/imports/types phases on each save, and re-runs global phases (communities, processes, dead code) every 30 seconds. Backed by the Rust [watchfiles](https://github.com/samuelcolvin/watchfiles) crate.

Ctrl+C to stop.

No flags.

## `axon diff BASE..HEAD`

Symbol-level diff between two git refs. Uses `git worktree` so it doesn't stash. Prints symbols added, modified, and removed.

| Argument        | Type   | Default | Description                                  |
| --------------- | ------ | ------- | -------------------------------------------- |
| `BRANCH_RANGE`  | string | (required) | Two git refs joined by `..` (e.g. `main..feature`). |

## `axon mcp`

Start the MCP server over stdio transport. No file watching. The current working directory must contain a `.axon/kuzu/` index. Exits when the client disconnects.

No flags.

## `axon serve`

Start the MCP server. Optionally enable live re-indexing.

| Flag             | Type | Default | Description                                                                            |
| ---------------- | ---- | ------- | -------------------------------------------------------------------------------------- |
| `--watch, -w`    | bool | false   | Enable live file watching with auto-reindex. Spawns a shared host in the background. |

With `--watch`, `serve` doesn't run the MCP server directly. It starts a shared host (managed, listening on port 8421 by default) and proxies the stdio MCP session through it. Multiple clients can attach to the same host.

## `axon host`

Run the shared Axon host: web UI **plus** multi-session HTTP MCP. Default URL `http://127.0.0.1:8420`. The MCP endpoint is `<host>/mcp`. Auto-opens the browser.

| Flag                  | Type   | Default      | Description                                                |
| --------------------- | ------ | ------------ | ---------------------------------------------------------- |
| `--port, -p`          | int    | 8420         | Port for UI and HTTP MCP.                                  |
| `--bind`              | string | `127.0.0.1`  | Host interface to bind.                                    |
| `--no-open`           | bool   | false        | Don't auto-open the browser.                               |
| `--watch / --no-watch`| bool   | watch on     | Enable file watching with auto-reindex.                    |
| `--dev`               | bool   | false        | Dev mode: proxy frontend to a Vite dev server on `:5173`.  |

## `axon ui`

Launch the web UI. Default `http://127.0.0.1:8420`.

If a host is already running for this repo, `axon ui` attaches to it; if not, it starts one. `--direct` forces standalone mode.

| Flag           | Type | Default | Description                                                      |
| -------------- | ---- | ------- | ---------------------------------------------------------------- |
| `--port, -p`   | int  | 8420    | Port to serve on.                                                |
| `--no-open`    | bool | false   | Don't auto-open the browser.                                     |
| `--watch, -w`  | bool | false   | Enable live file watching with auto-reindex.                     |
| `--dev`        | bool | false   | Dev mode: proxy to Vite dev server on `:5173` for HMR.          |
| `--direct`     | bool | false   | Force standalone UI mode even if a shared Axon host is running. |

## `axon setup`

Print MCP configuration JSON for popular AI agents. Doesn't write any files.

| Flag        | Type | Default | Description                              |
| ----------- | ---- | ------- | ---------------------------------------- |
| `--claude`  | bool | false   | Print Claude Code `.mcp.json` snippet.   |
| `--cursor`  | bool | false   | Print Cursor MCP config snippet.         |

With no flag, prints both. The snippet always launches `axon serve --watch`.

## Exit codes

- `0` — Success.
- `1` — User error: no index, target path is not a directory, invalid diff range, no live host on a managed connection, etc.
- Other non-zero — Unhandled exception. Look at stderr.

## Update notification

On every command except `mcp`, `serve`, and `host`, the CLI may print:

```
Update available: Axon <new> (current <old>). Run `pip install -U axoniq`.
```

It checks PyPI at most once every 24 hours and caches the result in `~/.axon/update-check.json`.

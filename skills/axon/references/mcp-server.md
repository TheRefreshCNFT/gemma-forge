# Axon MCP Server

Axon exposes its full intelligence as an MCP server with 15 tools and 3 resources. The server is implemented in `src/axon/mcp/server.py` and `src/axon/mcp/tools.py` in the upstream repo.

The MCP server name is `axon`. Transports:

- **stdio** — default. `axon mcp` or `axon serve`.
- **streamable HTTP** — enabled when the shared host runs. Endpoint `<host>/mcp`. Started by `axon host` or `axon serve --watch`.

## Setup

### Claude Code

Add to `.mcp.json` in the project root:

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

Or run `claude mcp add axon -- axon serve --watch`.

### Cursor

```json
{
  "axon": {
    "command": "axon",
    "args": ["serve", "--watch"]
  }
}
```

### Manual

```bash
axon setup --claude    # Print Claude Code snippet
axon setup --cursor    # Print Cursor snippet
```

The server always operates on the current working directory's `.axon/kuzu/` index. Run `axon analyze .` once before connecting.

## Tools

All 15 tools return a single `TextContent` block. Every response includes a next-step hint like:

```
query   -> "Next: Use context() on a specific symbol for the full picture."
context -> "Next: Use impact() if planning changes to this symbol."
impact  -> "Tip: Review each affected symbol before making changes."
```

### `axon_list_repos`

List all indexed repositories with their stats.

| Parameter | Type | Default | Description |
| --------- | ---- | ------- | ----------- |
| _(none)_  |      |         |             |

### `axon_query`

Search the knowledge graph using hybrid (keyword + vector) search. Returns ranked symbols matching the query.

| Parameter | Type    | Default  | Description                              |
| --------- | ------- | -------- | ---------------------------------------- |
| `query`   | string  | required | Search query text.                       |
| `limit`   | integer | 20       | Maximum number of results.               |

### `axon_context`

Get a 360-degree view of a symbol: callers, callees, type references, and community membership.

| Parameter | Type   | Default  | Description                       |
| --------- | ------ | -------- | --------------------------------- |
| `symbol`  | string | required | Name of the symbol to look up.    |

### `axon_impact`

Blast radius analysis: find all symbols affected by changing a given symbol.

| Parameter | Type    | Default  | Description                                                  |
| --------- | ------- | -------- | ------------------------------------------------------------ |
| `symbol`  | string  | required | Name of the symbol to analyse.                               |
| `depth`   | integer | 3        | Maximum traversal depth. Range 1..10.                        |

### `axon_dead_code`

List all symbols detected as dead (unreachable) code.

| Parameter | Type | Default | Description |
| --------- | ---- | ------- | ----------- |
| _(none)_  |      |         |             |

### `axon_detect_changes`

Parse a git diff and map changed files/lines to affected symbols in the knowledge graph.

| Parameter | Type   | Default  | Description           |
| --------- | ------ | -------- | --------------------- |
| `diff`    | string | required | Raw git diff output.  |

### `axon_cypher`

Execute a raw Cypher query against the knowledge graph. Read-only — write keywords are rejected.

| Parameter | Type   | Default  | Description           |
| --------- | ------ | -------- | --------------------- |
| `query`   | string | required | Cypher query string.  |

### `axon_coupling`

Show files temporally coupled with a given file. Reveals hidden dependencies from git co-change patterns.

| Parameter      | Type    | Default  | Description                                            |
| -------------- | ------- | -------- | ------------------------------------------------------ |
| `file_path`    | string  | required | Path to the file to analyze coupling for.              |
| `min_strength` | number  | 0.3      | Minimum coupling strength threshold. Range 0.0..1.0.   |

### `axon_communities`

List detected code communities (Leiden clusters) or drill into a specific community to see its members.

| Parameter   | Type   | Default | Description                                                  |
| ----------- | ------ | ------- | ------------------------------------------------------------ |
| `community` | string | null    | Optional community name to drill into. Omit to list all.     |

### `axon_explain`

Get a narrative explanation of a symbol: its role, community, process flows, and relationships summarized for onboarding.

| Parameter | Type   | Default  | Description                       |
| --------- | ------ | -------- | --------------------------------- |
| `symbol`  | string | required | Name of the symbol to explain.    |

### `axon_review_risk`

PR risk assessment: analyzes a git diff to find affected symbols, missing co-change files, community boundary crossings, and downstream blast radius. Returns a risk score.

| Parameter | Type   | Default  | Description           |
| --------- | ------ | -------- | --------------------- |
| `diff`    | string | required | Raw git diff output.  |

### `axon_call_path`

Find the shortest call chain between two symbols. Uses BFS over `CALLS` edges.

| Parameter     | Type    | Default  | Description                                            |
| ------------- | ------- | -------- | ------------------------------------------------------ |
| `from_symbol` | string  | required | Name of the source symbol.                             |
| `to_symbol`   | string  | required | Name of the target symbol.                             |
| `max_depth`   | integer | 10       | Maximum hops. Range 1..10.                             |

### `axon_file_context`

Get comprehensive context for a file: symbols, imports, coupling, dead code, and community membership in one call.

| Parameter   | Type   | Default  | Description                       |
| ----------- | ------ | -------- | --------------------------------- |
| `file_path` | string | required | Path to the file to analyze.      |

### `axon_test_impact`

Find tests likely affected by code changes. Accepts a git diff or symbol names, traces callers to find test files.

| Parameter | Type           | Default | Description                          |
| --------- | -------------- | ------- | ------------------------------------ |
| `diff`    | string         | (one of `diff` or `symbols` required) | Raw git diff output. |
| `symbols` | array<string>  | (one of `diff` or `symbols` required) | List of symbol names to check. |

### `axon_cycles`

Detect circular dependencies using strongly connected component analysis. Returns cycle groups sorted by size.

| Parameter   | Type    | Default | Description                                                  |
| ----------- | ------- | ------- | ------------------------------------------------------------ |
| `min_size`  | integer | 2       | Minimum cycle size to report. Must be >= 2.                  |

## Resources

Three text resources, all read-only. Fetched via standard MCP `resources/read`.

| URI                   | Description                                              |
| --------------------- | -------------------------------------------------------- |
| `axon://overview`     | Node and relationship counts grouped by type.            |
| `axon://dead-code`    | Full dead code report, grouped by file.                  |
| `axon://schema`       | Description of node labels, relationship types, properties, ID format. |

## Calling tools — JSON-RPC example

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "axon_context",
    "arguments": {
      "symbol": "validate_user"
    }
  }
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {"type": "text", "text": "<formatted symbol context>"}
    ],
    "isError": false
  }
}
```

## Read-only mode and locking

When the MCP server runs without a watcher (`axon mcp`), each tool call opens a short-lived read-only KuzuBackend connection. When the watcher is on (`axon serve --watch` or attached to a host), the server holds one shared backend and serialises tool calls behind an `asyncio.Lock` so reads see consistent state during re-index batches.

## When to pick which tool

| Question                                                    | Tool                  |
| ----------------------------------------------------------- | --------------------- |
| "Find something by name or concept"                         | `axon_query`          |
| "Tell me everything about symbol X"                         | `axon_context`        |
| "Walk me through symbol X for onboarding"                   | `axon_explain`        |
| "What breaks if I change X?"                                | `axon_impact`         |
| "Where's the dead code?"                                    | `axon_dead_code`      |
| "What does this git diff touch?"                            | `axon_detect_changes` |
| "How risky is this PR?"                                     | `axon_review_risk`    |
| "Which tests should I run for this diff?"                   | `axon_test_impact`    |
| "Does A end up calling B somewhere?"                        | `axon_call_path`      |
| "Tell me everything about file F"                           | `axon_file_context`   |
| "Which files always change with file F?"                    | `axon_coupling`       |
| "What are the architectural clusters?"                      | `axon_communities`    |
| "Are there circular dependencies?"                          | `axon_cycles`         |
| "I need raw graph access"                                   | `axon_cypher`         |
| "Which repos are indexed on this machine?"                  | `axon_list_repos`     |

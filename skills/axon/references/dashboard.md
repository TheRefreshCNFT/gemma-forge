# Axon Web Dashboard

Launch with:

```bash
axon ui                     # http://127.0.0.1:8420 (auto-opens browser)
axon ui --watch             # live re-indexing on save
axon ui --port 9000         # custom port
axon ui --no-open           # don't auto-open
axon ui --direct            # standalone (don't attach to existing host)
axon host                   # shared host: UI + multi-session HTTP MCP
```

The frontend is a React + TypeScript + Vite app served by FastAPI + Uvicorn. The graph renderer is Sigma.js + Graphology with WebGL and the ForceAtlas2 layout. Tailwind CSS handles styling.

If a shared host is already running for the repo, `axon ui` attaches to it instead of starting a second server. Pass `--direct` to override.

## Three views

### Explorer

The default view. A force-directed graph of every node in the index.

- Click any node to open its detail panel: code preview, callers, callees, impact analysis, process memberships.
- The file tree sidebar lets you scope the graph to one directory or file.
- Community hull overlays draw a tinted polygon around each Leiden cluster so architectural groups are visible at a glance.
- Flow trace animation: pick a process and watch it light up step by step.
- Impact ripple animation: pick a symbol and watch the blast radius expand depth by depth.
- Graph minimap for navigation.
- Keyboard shortcuts and a command palette (`Cmd+K`).

### Analysis

Codebase health in one screen:

- **Health score** — aggregate metric.
- **Coupling heatmap** — file × file matrix of co-change strength.
- **Dead code report** — same data as `axon dead-code` and `axon://dead-code`.
- **Inheritance tree** — class/interface hierarchies.
- **Branch diff** — symbol-level diff between two git refs (same data as `axon diff`).
- **Aggregate stats** — node and edge counts by type.

### Cypher Console

A query editor for the graph:

- Syntax highlighting.
- Preset query library (common patterns like "list dead code", "find tight coupling").
- Results table.
- Query history.
- Read-only — write keywords are rejected server-side after comment stripping. Same guard as the CLI `axon cypher` command.

## Live reload

When `--watch` is on, the backend pushes Server-Sent Events on `/api/events`. The frontend listens and re-fetches the graph whenever the watcher re-indexes a file. No manual refresh needed.

## REST API

The UI is backed by a FastAPI server. Every endpoint is under `/api`:

| Method | Endpoint                | Description                                                |
| ------ | ----------------------- | ---------------------------------------------------------- |
| GET    | `/api/graph`            | Full knowledge graph, paginated.                           |
| GET    | `/api/node/{id}`        | Node detail with callers, callees, type refs.              |
| GET    | `/api/overview`         | Aggregate node and edge counts.                            |
| GET    | `/api/search`           | Hybrid search (BM25 + vector + fuzzy).                     |
| GET    | `/api/impact/{id}`      | Blast radius analysis by depth.                            |
| GET    | `/api/dead-code`        | Dead code report.                                          |
| GET    | `/api/communities`      | Community listing with members.                            |
| GET    | `/api/coupling`         | Change coupling heatmap data.                              |
| GET    | `/api/files/{path}`     | Source file content with syntax context.                   |
| POST   | `/api/cypher`           | Execute a read-only Cypher query.                          |
| GET    | `/api/diff`             | Structural branch comparison.                              |
| GET    | `/api/processes`        | Execution flow listing.                                    |
| GET    | `/api/events`           | Server-Sent Events stream for live reload.                 |
| POST   | `/api/reindex`          | Trigger a full re-index (only available in watch mode).    |
| GET    | `/api/host`             | Returns `{ "repoPath": "<abs-path>" }` so attachers can verify the host is the right one. |

## Dev mode

```bash
cd src/axon/web/frontend
npm install
npm run dev                  # Vite dev server on :5173

# In another terminal:
axon ui --dev                # Backend on :8420, proxies to Vite for HMR
```

For end users of the published wheel, this isn't needed — the dashboard is pre-built and embedded in the package.

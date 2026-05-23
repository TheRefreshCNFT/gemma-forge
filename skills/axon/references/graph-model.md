# Axon Knowledge Graph Model

Axon stores the codebase as a labelled property graph in KuzuDB. The schema is fixed — Axon writes it at index time and the MCP server's `axon://schema` resource emits the same description below.

## Node labels

| Label       | Description                                |
| ----------- | ------------------------------------------ |
| `File`      | Source file in the repository.             |
| `Folder`    | Directory in the repository.               |
| `Function`  | Top-level function definition.             |
| `Class`     | Class definition.                          |
| `Method`    | Method within a class.                     |
| `Interface` | Interface / protocol definition.           |
| `TypeAlias` | Type alias definition.                     |
| `Enum`      | Enumeration definition.                    |
| `Community` | Detected community cluster (Leiden algorithm). |
| `Process`   | Execution flow / business process.         |

## Common node properties

Available on most symbol nodes:

```
id              string  — globally unique node ID
name            string  — short symbol name
file_path       string  — repo-relative path
start_line      int     — 1-indexed
end_line        int     — 1-indexed
content         string  — source text of the symbol
signature       string  — function/method signature, where applicable
language        string  — "python" / "typescript" / "javascript"
class_name      string  — for Method nodes, the parent class name
is_dead         bool    — flagged by the dead-code pass
is_entry_point  bool    — framework-detected entry (route, handler, test_*, __main__, ...)
is_exported     bool    — appears in an EXPORTS edge
```

## Relationship types

| Type               | Direction                    | Description                              |
| ------------------ | ---------------------------- | ---------------------------------------- |
| `CONTAINS`         | Folder/File -> Symbol        | Hierarchy.                               |
| `DEFINES`          | File -> Symbol               | The file that defines the symbol.        |
| `CALLS`            | Symbol -> Symbol             | A function/method call.                  |
| `IMPORTS`          | File -> File                 | One file imports from another.           |
| `EXTENDS`          | Class -> Class               | Inheritance.                             |
| `IMPLEMENTS`       | Class -> Interface           | Interface / protocol conformance.        |
| `USES_TYPE`        | Symbol -> Type               | Type reference in params / returns / vars. |
| `EXPORTS`          | File -> Symbol               | Public export.                           |
| `MEMBER_OF`        | Symbol -> Community          | Leiden cluster membership.               |
| `STEP_IN_PROCESS`  | Symbol -> Process            | A step inside an execution flow.         |
| `COUPLED_WITH`     | File -> File                 | Temporal coupling from git history.      |

## Relationship properties

All edges carry a `rel_type` string (the same as the type above). Other properties depend on the edge:

| Property      | Edge types                | Description                                                       |
| ------------- | ------------------------- | ----------------------------------------------------------------- |
| `confidence`  | `CALLS`                   | 0.0..1.0. 1.0 = exact match, 0.8 = receiver method, 0.5 = fuzzy.  |
| `role`        | `USES_TYPE`               | `"param"` / `"return"` / `"variable"`.                            |
| `step_number` | `STEP_IN_PROCESS`         | Position in the flow (1-indexed).                                 |
| `strength`    | `COUPLED_WITH`            | 0.0..1.0. `co_changes(A,B) / max(changes(A), changes(B))`.        |
| `co_changes`  | `COUPLED_WITH`            | Integer count of co-changing commits.                             |
| `symbols`     | `IMPORTS`                 | List of imported symbol names.                                    |

## Node ID format

```
{label}:{relative_path}:{symbol_name}
```

Examples:

```
function:src/auth/validate.py:validate_user
class:src/models/user.py:User
method:src/models/user.py:User.save
file:src/auth/validate.py:
folder:src/auth:
```

For `File` and `Folder` nodes, the symbol name slot is empty.

## How the graph is built — the 12-phase pipeline

Each `axon analyze` run executes these phases in order:

| # | Phase                | What it produces                                                       |
| - | -------------------- | ---------------------------------------------------------------------- |
| 1 | File walking        | Respects `.gitignore`, filters supported languages.                   |
| 2 | Structure            | Creates `File`/`Folder` nodes with `CONTAINS` edges.                  |
| 3 | Parsing              | tree-sitter ASTs — functions, classes, methods, interfaces, enums, type aliases. |
| 4 | Import resolution    | Resolves relative, absolute, and bare specifiers to actual files.     |
| 5 | Call tracing         | `CALLS` edges with confidence. 138 language builtins are filtered.    |
| 6 | Heritage             | `EXTENDS` and `IMPLEMENTS` edges.                                     |
| 7 | Type analysis        | `USES_TYPE` edges with `role`.                                        |
| 8 | Community detection  | Leiden algorithm via `igraph + leidenalg` -> `Community` nodes.       |
| 9 | Process detection    | Framework-aware entry points + BFS flow tracing -> `Process` nodes.   |
| 10| Dead code detection  | Multi-pass: scan -> exemptions -> override -> protocol conformance.   |
| 11| Change coupling      | 6 months of git history -> `COUPLED_WITH` edges (strength >= 0.3, 3+ co-changes). |
| 12| Embeddings           | 384-dim vectors via fastembed (`BAAI/bge-small-en-v1.5`). Skip with `--no-embeddings`. |

## What gets exempted from dead code

The dead-code pass starts by flagging every symbol with no incoming `CALLS`. It then un-flags:

- Framework entry points: `@app.route`, `@router.get`, `@click.command`, `test_*` functions, `__main__` blocks, Express handlers, exported functions, `handler` / `middleware` patterns.
- Exports.
- Constructors.
- Test code (functions inside files matching `_is_test_file`).
- Dunder methods (`__init__`, `__repr__`, etc.).
- All symbols defined in `__init__.py`.
- Decorated functions.
- `@property` methods.
- Methods that override a non-dead base class method (override pass).
- Methods on classes that conform to a `Protocol` (protocol conformance pass).
- All methods on `Protocol` classes themselves (protocol stub pass).

## Storage backend

KuzuDB is the default — an embedded graph database that also provides full-text search (BM25) and vector indexes (HNSW). Everything lives under `.axon/kuzu/`.

A Neo4j backend is available behind `pip install "axoniq[neo4j]"`. The same `StorageBackend` Protocol is used either way; tools and the UI don't care which backend you pick.

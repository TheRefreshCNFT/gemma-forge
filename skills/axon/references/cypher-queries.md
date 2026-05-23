# Cypher Queries Against the Axon Graph

Axon stores everything in KuzuDB and exposes it through `axon cypher QUERY`, the `axon_cypher` MCP tool, and the `/api/cypher` HTTP endpoint. All three are read-only — write keywords (`CREATE`, `DELETE`, `DROP`, `SET`, `MERGE`, `REMOVE`) are rejected after comment stripping.

See `references/graph-model.md` for the full schema. The shorthand:

- Nodes: `File`, `Folder`, `Function`, `Class`, `Method`, `Interface`, `TypeAlias`, `Enum`, `Community`, `Process`.
- Edges: every edge type is stored in a `CodeRelation` table, with `rel_type` distinguishing `CALLS` / `IMPORTS` / `EXTENDS` / `IMPLEMENTS` / `USES_TYPE` / `EXPORTS` / `MEMBER_OF` / `STEP_IN_PROCESS` / `COUPLED_WITH` / `CONTAINS` / `DEFINES`.

## Queries from the upstream README

These are pulled verbatim from the project's documented example workflows.

### Files most tightly coupled to `user.py`

```cypher
MATCH (a:File)-[r:CodeRelation]->(b:File)
WHERE a.name = 'user.py' AND r.rel_type = 'coupled_with'
RETURN b.name, r.strength
ORDER BY r.strength DESC
```

### List all detected execution flows

```cypher
MATCH (p:Process)
RETURN p.name, p.properties
ORDER BY p.name
```

### Top 20 file pairs by coupling strength

```cypher
MATCH (a:File)-[r:CodeRelation]->(b:File)
WHERE r.rel_type = 'coupled_with'
RETURN a.name, b.name, r.strength
ORDER BY r.strength DESC
LIMIT 20
```

## Useful patterns

### Every dead function

```cypher
MATCH (n:Function)
WHERE n.is_dead = true
RETURN n.name, n.file_path, n.start_line
ORDER BY n.file_path
```

### Direct callers of a symbol

```cypher
MATCH (caller)-[r:CodeRelation]->(target)
WHERE r.rel_type = 'calls' AND target.name = 'validate_user'
RETURN caller.name, caller.file_path, r.confidence
ORDER BY r.confidence DESC
```

### Classes implementing a given interface

```cypher
MATCH (c:Class)-[r:CodeRelation]->(i:Interface)
WHERE r.rel_type = 'implements' AND i.name = 'StorageBackend'
RETURN c.name, c.file_path
```

### Members of a community

```cypher
MATCH (n)-[r:CodeRelation]->(c:Community)
WHERE r.rel_type = 'member_of' AND c.name = 'auth_cluster'
RETURN n.name, n.file_path
```

### Cross-community calls (architectural seams)

```cypher
MATCH (a)-[ca:CodeRelation]->(b),
      (a)-[ma:CodeRelation]->(cA:Community),
      (b)-[mb:CodeRelation]->(cB:Community)
WHERE ca.rel_type = 'calls'
  AND ma.rel_type = 'member_of'
  AND mb.rel_type = 'member_of'
  AND cA.name <> cB.name
RETURN cA.name, cB.name, count(*) AS call_count
ORDER BY call_count DESC
```

### Symbols with the most callers (entry-like hubs)

```cypher
MATCH (caller)-[r:CodeRelation]->(target)
WHERE r.rel_type = 'calls'
RETURN target.name, target.file_path, count(caller) AS in_degree
ORDER BY in_degree DESC
LIMIT 20
```

### Steps of a specific process, in order

```cypher
MATCH (s)-[r:CodeRelation]->(p:Process)
WHERE r.rel_type = 'step_in_process' AND p.name = 'checkout_flow'
RETURN s.name, s.file_path, r.step_number
ORDER BY r.step_number
```

### All entry points

```cypher
MATCH (n)
WHERE n.is_entry_point = true
RETURN n.name, n.file_path, label(n)
ORDER BY n.file_path
```

## Where to run them

Pick whichever you prefer:

```bash
# CLI
axon cypher "MATCH (n:Function) WHERE n.is_dead = true RETURN n.name LIMIT 10"

# Web UI (Cypher Console view)
axon ui

# MCP
# Tool name: axon_cypher
# Arguments: { "query": "MATCH ... RETURN ..." }

# HTTP
curl -X POST http://127.0.0.1:8420/api/cypher \
     -H "Content-Type: application/json" \
     -d '{"query": "MATCH (n:Function) RETURN count(n)"}'
```

## Gotchas

- KuzuDB is Cypher-compatible but not 100% identical to Neo4j. Stick to the patterns above and you'll be fine.
- All edges go through a single `CodeRelation` table. Always filter on `r.rel_type` when you want a specific edge type. Lowercase values: `'calls'`, `'imports'`, `'coupled_with'`, etc.
- Write queries are rejected even if they look harmless — `RETURN 1` is fine but `RETURN 1 // CREATE foo` will be blocked after comment stripping.
- For huge graphs, always include `LIMIT`. The full `/api/graph` is paginated for the same reason.

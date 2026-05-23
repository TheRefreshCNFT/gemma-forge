#!/usr/bin/env bash
# Example 3: run Cypher queries against the Axon knowledge graph.
#
# All queries are read-only — write keywords (CREATE/DELETE/DROP/SET/MERGE/REMOVE)
# are rejected after comment stripping.
#
# Usage:
#   cd /path/to/your/indexed/repo
#   ./03_cypher_query.sh
#
# Requires: `axon analyze .` already run in this directory.

set -euo pipefail

echo "==> 1. Count every node by label"
axon cypher "MATCH (n) RETURN label(n) AS label, count(n) AS count ORDER BY count DESC"

echo
echo "==> 2. Top 10 functions by number of incoming calls (call hubs)"
axon cypher "MATCH (caller)-[r:CodeRelation]->(target:Function) WHERE r.rel_type = 'calls' RETURN target.name, target.file_path, count(caller) AS callers ORDER BY callers DESC LIMIT 10"

echo
echo "==> 3. Files tightly coupled in git history (top 20 pairs)"
axon cypher "MATCH (a:File)-[r:CodeRelation]->(b:File) WHERE r.rel_type = 'coupled_with' RETURN a.name, b.name, r.strength ORDER BY r.strength DESC LIMIT 20"

echo
echo "==> 4. All detected execution flows"
axon cypher "MATCH (p:Process) RETURN p.name, p.properties ORDER BY p.name"

echo
echo "==> 5. Dead functions, file-grouped"
axon cypher "MATCH (n:Function) WHERE n.is_dead = true RETURN n.file_path, n.name ORDER BY n.file_path"

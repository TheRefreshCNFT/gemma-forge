#!/usr/bin/env bash
# Example 1: index a repo, then run a few queries against the knowledge graph.
#
# Usage:
#   ./01_analyze_and_search.sh /path/to/your/repo
#
# Requires: axoniq installed (`pip install axoniq`).

set -euo pipefail

REPO_PATH="${1:-.}"
cd "$REPO_PATH"

echo "==> Indexing $(pwd)"
axon analyze .

echo
echo "==> Index status"
axon status

echo
echo "==> Hybrid search for 'validate' (top 5)"
axon query "validate" --limit 5

echo
echo "==> 360-degree context for the first matching symbol"
# Pick a symbol you actually have. Replace 'main' with whatever shows up above.
axon context main || true

echo
echo "==> Blast radius for the same symbol (depth 2)"
axon impact main --depth 2 || true

echo
echo "==> Dead code report"
axon dead-code

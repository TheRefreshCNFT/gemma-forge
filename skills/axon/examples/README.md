# Axon Examples

Short, runnable snippets covering the three ways to use Axon: CLI, MCP, and Cypher.

## Prerequisites

```bash
pip install axoniq
```

Every example assumes you're sitting in a directory that contains code Axon can index (Python, TypeScript, or JavaScript). For the CLI and Cypher examples, run `axon analyze .` once before doing anything else.

## Examples

| File                          | Type   | What it does                                                              |
| ----------------------------- | ------ | ------------------------------------------------------------------------- |
| `01_analyze_and_search.sh`    | bash   | Index a repo, then query it (status, hybrid search, context, impact, dead code). |
| `02_mcp_tools_call.py`        | Python | Spawn `axon mcp` over stdio, list its tools, call a few of them, read a resource. |
| `03_cypher_query.sh`          | bash   | Run useful Cypher queries via `axon cypher`.                              |

## Running

```bash
# 1. CLI walk-through
chmod +x 01_analyze_and_search.sh
./01_analyze_and_search.sh /path/to/your/repo

# 2. MCP from Python
cd /path/to/your/repo
axon analyze .
python /path/to/skills/axon/examples/02_mcp_tools_call.py

# 3. Cypher queries
cd /path/to/your/repo
chmod +x 03_cypher_query.sh
./03_cypher_query.sh
```

## Decision tree

```
Want to ask one question?       -> axon query / axon context / axon impact / axon dead-code
Want to drive Axon from code?   -> MCP server (02_mcp_tools_call.py)
Want to write your own query?   -> axon cypher (03_cypher_query.sh)
Want a visual explorer?         -> axon ui
```

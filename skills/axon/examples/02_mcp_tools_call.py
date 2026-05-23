"""Example 2: call Axon's MCP tools from Python over stdio.

Spawns `axon mcp` as a subprocess, performs the MCP handshake, lists the
available tools, then calls a few of them. Works against any repo that
already has a `.axon/kuzu/` index (run `axon analyze .` first).

Usage:
    cd /path/to/repo-with-axon-index
    python /path/to/this/02_mcp_tools_call.py

Requires the official MCP Python SDK (it ships as a dependency of axoniq, so
if you have axoniq installed you already have it):
    pip install mcp
"""

from __future__ import annotations

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command="axon", args=["mcp"])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Discover tools.
            tool_list = await session.list_tools()
            print(f"Discovered {len(tool_list.tools)} tools:")
            for tool in tool_list.tools:
                print(f"  - {tool.name}")
            print()

            # 2. Call axon_query.
            print("== axon_query('storage backend') ==")
            result = await session.call_tool(
                "axon_query",
                arguments={"query": "storage backend", "limit": 5},
            )
            for block in result.content:
                if block.type == "text":
                    print(block.text)
            print()

            # 3. Call axon_dead_code.
            print("== axon_dead_code() ==")
            result = await session.call_tool("axon_dead_code", arguments={})
            for block in result.content:
                if block.type == "text":
                    print(block.text)
            print()

            # 4. Read a resource.
            print("== axon://overview ==")
            res = await session.read_resource("axon://overview")
            for content in res.contents:
                if hasattr(content, "text"):
                    print(content.text)


if __name__ == "__main__":
    asyncio.run(main())

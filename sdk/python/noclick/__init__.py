"""
NoClick SDK for Python.

Usage:
    import asyncio
    import noclick

    async def main():
        client = noclick.Client(api_key="nk_live_...")
        await client.connect()

        output = await client.nodes.get_output("node-id")
        await client.execution.run_nodes_in_background(["node-id"])
        await client.state.set("counter", 42)

        await client.disconnect()

    asyncio.run(main())
"""

from noclick.client import Client

__all__ = ["Client"]
__version__ = "0.1.0"

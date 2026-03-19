"""
Test: run a node and get streaming output via Socket.IO transport.

Usage:
    python test_streaming.py <api-key> <workflow-id> <node-id>

Example:
    python test_streaming.py nk_live_... 377a8f23-... automation-serverless-function-...
"""

import asyncio
import json
import sys

sys.path.insert(0, ".")

from noclick import Client


async def main():
    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    workflow_id = sys.argv[2] if len(sys.argv) > 2 else None
    node_id = sys.argv[3] if len(sys.argv) > 3 else None

    if not all([api_key, workflow_id, node_id]):
        print("Usage: python test_streaming.py <api-key> <workflow-id> <node-id>")
        sys.exit(1)

    print("Connecting...")
    sdk = Client(
        api_key=api_key,
        url="http://localhost:8005",  # local dev
        workflow_id=workflow_id,
    )
    await sdk.connect()
    print("✓ Connected\n")

    # Read existing output
    print("--- Reading existing output ---")
    before = await sdk.nodes.get_output(node_id)
    before_ts = None
    if before and isinstance(before, dict):
        before_ts = before.get("result", {}).get("generated_at")
    print(f"  Existing timestamp: {before_ts or 'none'}")

    # Run and get output with streaming
    print("\n--- execution.run_nodes_and_get_output ---")
    print(f"  Running node: {node_id}")
    print("  Waiting for output...")

    try:
        results = await sdk.execution.run_nodes_and_get_output(
            [node_id], [node_id], timeout=30
        )
        print("\n--- Results ---")
        for nid, data in results.items():
            print(f"  {nid}: {json.dumps(data)[:200]}")
    except Exception as e:
        print(f"  Error: {e}")

    # Verify fresh output
    print("\n--- Verifying fresh output ---")
    after = await sdk.nodes.get_output(node_id)
    after_ts = None
    if after and isinstance(after, dict):
        after_ts = after.get("result", {}).get("generated_at")
    print(f"  New timestamp: {after_ts or 'none'}")
    print(f"  Is different from before: {before_ts != after_ts}")

    print("\n✓ Streaming test complete")
    await sdk.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

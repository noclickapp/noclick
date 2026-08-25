"""
End-to-end test for the Python SDK.

Prerequisites:
    1. Backend running on localhost:8005
    2. API key created:
       cd backend && python scripts/create_api_key.py --user-id <uuid> --name "Test"
    3. Dependencies installed:
       pip install python-socketio[asyncio_client] aiohttp

Usage:
    python test_external.py <api-key> [workflow-id]
"""

import asyncio
import json
import sys

sys.path.insert(0, ".")

from noclick import Client


async def main():
    api_key = sys.argv[1] if len(sys.argv) > 1 else None
    workflow_id = sys.argv[2] if len(sys.argv) > 2 else None

    if not api_key:
        print("Usage: python test_external.py <api-key> [workflow-id]")
        sys.exit(1)

    print(f"Connecting to NoClick backend...")
    print("  API Key: configured")
    print(f"  Workflow: {workflow_id or '(all)'}")

    sdk = Client(
        api_key=api_key,
        url="http://localhost:8005",  # local dev
        workflow_id=workflow_id,
    )

    try:
        await sdk.connect()
        print("✓ Connected!\n")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        sys.exit(1)

    # --- Test: workflow.get_info ---
    print("--- workflow.get_info ---")
    try:
        info = await sdk.workflow.get_info()
        print(f"  Name: {info['name']}, Nodes: {info['node_count']}")
    except Exception as e:
        print(f"  Error: {e}")

    # --- Test: nodes.list ---
    print("\n--- nodes.list ---")
    try:
        nodes = await sdk.nodes.list()
        print(f"  Found {len(nodes)} nodes:")
        for n in nodes:
            print(f"    {n['id']} ({n['type']}) — {n['label']}")
    except Exception as e:
        print(f"  Error: {e}")

    # --- Test: auth.list_credentials ---
    print("\n--- auth.list_credentials ---")
    try:
        creds = await sdk.auth.list_credentials()
        print(f"  Found {len(creds)} credentials")
        for c in creds[:3]:
            print(f"    {c['name']} ({c['type']})")
    except Exception as e:
        print(f"  Error: {e}")

    # --- Test: resources.list ---
    print("\n--- resources.list ---")
    try:
        resources = await sdk.resources.list()
        print(f"  Found {len(resources)} resources")
        for r in resources[:3]:
            print(f"    {r['name']} ({r['resource_type']})")
    except Exception as e:
        print(f"  Error: {e}")

    # --- Test: dataset CRUD ---
    print("\n--- dataset CRUD ---")
    try:
        ds_id = await sdk.dataset.create("Python SDK Test")
        print(f"  Created dataset: {ds_id}")

        count = await sdk.dataset.append_rows(ds_id, [
            {"name": "Alice", "score": 95},
            {"name": "Bob", "score": 87},
        ])
        print(f"  Appended {count} rows")

        page = await sdk.dataset.get_rows(ds_id, limit=10)
        print(f"  Read {len(page['rows'])} rows (total: {page['total_count']})")
        for r in page["rows"]:
            print(f"    {r['id']}: {json.dumps(r.get('data', {}))}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n✓ All tests complete")
    await sdk.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

# noclick-sdk

Python SDK for [NoClick](https://noclick.com) workflow automation. Build external applications that interact with NoClick workflows — read node outputs, trigger execution, manage state, and work with files and datasets.

The client intentionally defaults to the managed `https://api.noclick.io`
service. When connecting to a self-hosted instance, pass its backend URL as the
`url=` argument.

## Installation

```bash
pip install noclick
```

## Quick Start

```python
import asyncio
import noclick

async def main():
    sdk = noclick.Client(
        api_key="nk_live_...",
        workflow_id="your-workflow-id",
    )
    await sdk.connect()

    # List nodes
    nodes = await sdk.nodes.list()
    for node in nodes:
        print(f"{node['label']} ({node['type']})")

    # Read node output
    output = await sdk.nodes.get_output("gmail-node-id")

    # Run a node and get results
    results = await sdk.execution.run_nodes_and_get_output(
        ["data-fetcher"], ["formatter"]
    )

    # State management
    await sdk.state.set("counter", 42)
    val = await sdk.state.get("counter")

    # Dataset CRUD
    ds_id = await sdk.dataset.create("My Data")
    await sdk.dataset.append_rows(ds_id, [{"name": "Alice", "score": 95}])

    await sdk.disconnect()

asyncio.run(main())
```

## API

| Namespace | Methods |
|-----------|---------|
| `sdk.nodes` | `get_output`, `get_config`, `list` |
| `sdk.execution` | `run_nodes_and_get_output`, `run_nodes_in_background`, `on_node_output`, `on_node_state` |
| `sdk.state` | `get`, `set`, `delete`, `update`, `keys` |
| `sdk.auth` | `list_credentials`, `has_credential`, `create_credential` |
| `sdk.resources` | `upload`, `get_url`, `remove`, `list` |
| `sdk.dataset` | `create`, `list`, `get_rows`, `append_rows`, `update_row`, `delete_rows` |
| `sdk.workflow` | `get_info` |

## Documentation

Full documentation at [docs.noclick.com/sdk](https://docs.noclick.com/sdk/overview).

## License

[Sustainable Use License 1.0](./LICENSE.md) — use it for your own internal
business purposes, or non-commercially. Source-available rather than open
source, and it does not convert to a permissive licence over time.

"""
SDK namespace classes — thin wrappers that map to socket events.
Each method mirrors the TypeScript SDK API.
"""

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from noclick.client import Client


class NodesNamespace:
    def __init__(self, sdk: "Client"):
        self._sdk = sdk

    async def get_output(self, node_id: str) -> Any:
        """Read a node's last output."""
        resp = await self._sdk.send_event("workflow:get_node_outputs", {
            "workflow_id": self._sdk.workflow_id,
            "node_ids": [node_id],
        })
        outputs = resp.get("outputs", {})
        node_output = outputs.get(node_id, {})
        return node_output.get("output")

    async def get_config(self, node_id: str) -> Dict[str, Any]:
        """Read a node's config."""
        resp = await self._sdk.send_event("workflow:get", {
            "workflow_id": self._sdk.workflow_id,
        })
        workflow_data = resp.get("workflow", {}).get("workflow_data", {})
        for node in workflow_data.get("nodes", []):
            if node.get("id") == node_id:
                return node.get("config", {})
        raise ValueError(f"Node not found: {node_id}")

    async def list(self) -> List[Dict[str, Any]]:
        """List all nodes in the workflow."""
        resp = await self._sdk.send_event("workflow:get", {
            "workflow_id": self._sdk.workflow_id,
        })
        workflow_data = resp.get("workflow", {}).get("workflow_data", {})
        return [
            {
                "id": n.get("id"),
                "type": n.get("type"),
                "label": n.get("config", {}).get("label", n.get("type", "")),
                "hasOutput": False,  # Would need separate output check
            }
            for n in workflow_data.get("nodes", [])
        ]


class ExecutionNamespace:
    def __init__(self, sdk: "Client"):
        self._sdk = sdk

    async def run_nodes_in_background(self, node_ids: List[str]) -> None:
        """Run nodes without waiting for output."""
        await self._sdk.send_event_no_wait("workflow:execute", {
            "workflow_id": self._sdk.workflow_id,
            "start_node_id": node_ids[0] if node_ids else None,
        })

    async def run_nodes_and_get_output(
        self, run_nodes: List[str], target_nodes: List[str], timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """Run nodes and wait for target outputs."""
        import asyncio

        # Start execution
        await self._sdk.send_event_no_wait("workflow:execute", {
            "workflow_id": self._sdk.workflow_id,
            "start_node_id": run_nodes[0] if run_nodes else None,
        })

        # Collect outputs via node:output events
        results: Dict[str, Any] = {}
        remaining = set(target_nodes)
        done_event = asyncio.Event()

        def on_output(node_id: str, output: Any):
            if node_id in remaining:
                results[node_id] = output
                remaining.discard(node_id)
                if not remaining:
                    done_event.set()

        self._sdk.on_event("node:output", on_output)
        try:
            await asyncio.wait_for(done_event.wait(), timeout=timeout or self._sdk.timeout)
        finally:
            if on_output in self._sdk._event_handlers.get("node:output", []):
                self._sdk._event_handlers["node:output"].remove(on_output)

        return results

    def stop(self) -> None:
        """Stop the current execution."""
        # Fire and forget
        import asyncio
        asyncio.create_task(self._sdk.send_event_no_wait("workflow:stop", {
            "workflow_id": self._sdk.workflow_id,
        }))

    def on_node_state(self, node_id: str, handler: Callable) -> None:
        """Subscribe to a node's state changes."""
        def filtered_handler(nid: str, state: str):
            if nid == node_id:
                handler(state)
        self._sdk.on_event("node:state", filtered_handler)

    def on_node_output(self, node_id: str, handler: Callable) -> None:
        """Subscribe to a node's output changes."""
        def filtered_handler(nid: str, output: Any):
            if nid == node_id:
                handler(output)
        self._sdk.on_event("node:output", filtered_handler)


class StateNamespace:
    def __init__(self, sdk: "Client"):
        self._sdk = sdk

    async def get(self, key: str, node_id: Optional[str] = None) -> Any:
        """Read a state value."""
        resp = await self._sdk.send_event("workflow:load_node_state", {
            "workflow_id": self._sdk.workflow_id,
            "node_id": node_id,  # Handler resolves state-manager if None
            "key": key,
        })
        return resp.get("state", {}).get(key)

    async def set(self, key: str, value: Any, node_id: Optional[str] = None) -> None:
        """Set a state value."""
        await self._sdk.send_event("workflow:save_node_state", {
            "workflow_id": self._sdk.workflow_id,
            "node_id": node_id,
            "state": {key: value},
        })

    async def delete(self, key: str, node_id: Optional[str] = None) -> None:
        """Delete a state key."""
        # Read current, remove key, write back
        current = await self.get(key, node_id)
        if current is not None:
            await self._sdk.send_event("workflow:save_node_state", {
                "workflow_id": self._sdk.workflow_id,
                "node_id": node_id,
                "state": {key: None},  # Convention: None = delete
            })

    async def update(self, key: str, updater: Callable, node_id: Optional[str] = None) -> None:
        """Update a state value with a function."""
        current = await self.get(key, node_id)
        new_value = updater(current)
        await self.set(key, new_value, node_id)

    async def keys(self, node_id: Optional[str] = None) -> List[str]:
        """List available state keys."""
        resp = await self._sdk.send_event("workflow:load_node_state", {
            "workflow_id": self._sdk.workflow_id,
            "node_id": node_id,
        })
        state_data = resp.get("state", {})
        return list(state_data.keys()) if isinstance(state_data, dict) else []


class AuthNamespace:
    def __init__(self, sdk: "Client"):
        self._sdk = sdk

    async def list_credentials(self) -> List[Dict[str, str]]:
        """List available credentials."""
        resp = await self._sdk.send_event("credential:list", {})
        return [
            {"id": c["id"], "type": c.get("credential_type", ""), "name": c.get("name", "")}
            for c in resp.get("credentials", [])
        ]

    async def has_credential(self, credential_type: str) -> bool:
        """Check if a credential of the given type exists."""
        creds = await self.list_credentials()
        return any(c["type"] == credential_type for c in creds)

    async def create_credential(
        self, credential_type: str, data: Dict[str, Any], name: Optional[str] = None
    ) -> Dict[str, str]:
        """Create a non-OAuth credential (API key, token, etc)."""
        resp = await self._sdk.send_event("credential:create", {
            "name": name or credential_type,
            "credential_type": credential_type,
            "credential_data": data,
            "metadata": {},
        })
        cred = resp.get("credential", {})
        return {"id": cred.get("id", ""), "type": credential_type, "name": cred.get("name", "")}


class ResourcesNamespace:
    def __init__(self, sdk: "Client"):
        self._sdk = sdk

    async def upload(self, name: str, mime_type: str, size_bytes: int, resource_type: str = "file"):
        """Create a resource and get a presigned upload URL."""
        create_resp = await self._sdk.send_event("resource:create", {
            "workflow_id": self._sdk.workflow_id,
            "resource_type": resource_type,
            "name": name,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
        })
        resource = create_resp.get("resource", {})
        resource_id = resource.get("id")
        if not resource_id:
            raise ValueError("Failed to create resource")

        upload_resp = await self._sdk.send_event("resource:upload_url", {
            "resource_id": resource_id,
            "filename": name,
            "content_type": mime_type,
        })
        return {
            "resource_id": resource_id,
            "upload_url": upload_resp.get("upload_url", ""),
        }

    async def get_url(self, resource_id: str) -> str:
        """Get a presigned download URL."""
        resp = await self._sdk.send_event("resource:download_url", {
            "resource_id": resource_id,
        })
        return resp.get("download_url", "")

    async def remove(self, resource_id: str) -> None:
        """Delete a resource."""
        await self._sdk.send_event("resource:delete", {
            "resource_id": resource_id,
        })

    async def list(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List resources in the workflow."""
        resp = await self._sdk.send_event("resource:list", {
            "workflow_id": self._sdk.workflow_id,
            "resource_type": resource_type,
        })
        return [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "resource_type": r.get("resource_type"),
                "mime_type": r.get("mime_type"),
                "size_bytes": r.get("size_bytes"),
            }
            for r in resp.get("resources", [])
        ]


class DatasetNamespace:
    def __init__(self, sdk: "Client"):
        self._sdk = sdk

    async def create(self, name: str) -> str:
        """Create a new dataset. Returns resource_id."""
        resp = await self._sdk.send_event("resource:create", {
            "workflow_id": self._sdk.workflow_id,
            "resource_type": "dataset",
            "name": name,
        })
        resource = resp.get("resource", {})
        resource_id = resource.get("id")
        if not resource_id:
            raise ValueError("Failed to create dataset")
        return resource_id

    async def list(self) -> List[Dict[str, Any]]:
        """List all datasets in the workflow."""
        resp = await self._sdk.send_event("resource:list", {
            "workflow_id": self._sdk.workflow_id,
            "resource_type": "dataset",
        })
        return [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "row_count": r.get("metadata", {}).get("row_count", 0),
            }
            for r in resp.get("resources", [])
        ]

    async def get_rows(
        self, resource_id: str, limit: int = 100, offset: int = 0
    ) -> Dict[str, Any]:
        """Get paginated rows from a dataset."""
        resp = await self._sdk.send_event("resource:dataset:rows", {
            "resource_id": resource_id,
            "limit": limit,
            "offset": offset,
        })
        return {
            "rows": resp.get("rows", []),
            "total_count": resp.get("total_count", 0),
        }

    async def append_rows(self, resource_id: str, rows: List[Dict[str, Any]]) -> int:
        """Append rows to a dataset. Returns inserted count."""
        resp = await self._sdk.send_event("resource:dataset:append", {
            "resource_id": resource_id,
            "rows": rows,
        })
        return resp.get("inserted_count", 0)

    async def update_row(self, resource_id: str, row_id: str, data: Dict[str, Any]) -> None:
        """Update a single row."""
        await self._sdk.send_event("resource:dataset:update_row", {
            "resource_id": resource_id,
            "row_id": row_id,
            "data": data,
        })

    async def delete_rows(self, resource_id: str, row_ids: List[str]) -> int:
        """Delete rows. Returns deleted count."""
        resp = await self._sdk.send_event("resource:dataset:delete_rows", {
            "resource_id": resource_id,
            "row_ids": row_ids,
        })
        return resp.get("deleted_count", 0)


class WorkflowNamespace:
    def __init__(self, sdk: "Client"):
        self._sdk = sdk

    async def get_info(self) -> Dict[str, Any]:
        """Get workflow info."""
        resp = await self._sdk.send_event("workflow:get", {
            "workflow_id": self._sdk.workflow_id,
        })
        wf = resp.get("workflow", {})
        nodes = wf.get("workflow_data", {}).get("nodes", [])
        return {
            "id": wf.get("id", ""),
            "name": wf.get("name", ""),
            "node_count": len(nodes),
        }

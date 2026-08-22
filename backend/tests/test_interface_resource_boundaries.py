"""Execution-time access checks for interface resource UUIDs."""

import pytest

from nodes.interface.dataframe_node import (
    DataframeConfig,
    DataframeInterfaceNode,
    DataframeInterfaceNodeConfig,
)
from nodes.interface.file_node import FileConfig, FileInterfaceNode, FileInterfaceNodeConfig
from nodes.interface.file_upload_node import (
    FileUploadConfig,
    FileUploadInterfaceNode,
    FileUploadInterfaceNodeConfig,
)


class _BoundaryPool:
    def __init__(self, *, accessible_user: str | None = None):
        self.accessible_user = accessible_user
        self.calls = []

    async def fetchrow(self, query, resource_id, workflow_id):
        self.calls.append((query, resource_id, workflow_id))
        assert "workflow_id = $2" in query
        # The configured resource belongs to workflow-a. A workflow-b lookup
        # must behave exactly like a missing row.
        if workflow_id != "workflow-a":
            return None
        return {
            "storage_ref": "owner/workflow-a/secret.pdf",
            "name": "secret.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 42,
        }

    async def fetch(self, query, resource_id, workflow_id, user_id):
        self.calls.append((query, resource_id, workflow_id, user_id))
        assert "JOIN workflow_resources" in query
        assert "resource_shares" in query
        assert "wr.workflow_id = $2" in query
        if workflow_id == "workflow-a" or user_id == self.accessible_user:
            return [{"data": {"secret": "allowed"}}]
        return []


@pytest.mark.asyncio
async def test_file_uuid_from_another_workflow_does_not_return_url(monkeypatch):
    pool = _BoundaryPool()
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    node = FileInterfaceNode(
        "file",
        "interface-file",
        {},
        config=FileInterfaceNodeConfig(config=FileConfig(resource_id="resource-a")),
        workflow_id="workflow-b",
        user_id="user-b",
    )

    result = await node.execute({})

    assert result["url"] == ""
    assert "secret.pdf" not in str(result)


@pytest.mark.asyncio
async def test_file_upload_uuid_from_another_workflow_is_omitted(monkeypatch):
    pool = _BoundaryPool()
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    node = FileUploadInterfaceNode(
        "upload",
        "interface-file-upload",
        {},
        config=FileUploadInterfaceNodeConfig(
            config=FileUploadConfig(resource_ids="resource-a")
        ),
        workflow_id="workflow-b",
        user_id="user-b",
    )

    result = await node.execute({})

    assert result["files"] == []


@pytest.mark.asyncio
async def test_dataframe_uuid_requires_workflow_view_access(monkeypatch):
    pool = _BoundaryPool(accessible_user="user-a")
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    node = DataframeInterfaceNode(
        "dataframe",
        "interface-dataframe",
        {},
        config=DataframeInterfaceNodeConfig(
            config=DataframeConfig(resource_id="dataset-a")
        ),
        workflow_id="workflow-b",
        user_id="user-b",
    )

    result = await node.execute({})

    assert result["data"] == []


@pytest.mark.asyncio
async def test_dataframe_keeps_intended_shared_workflow_reuse(monkeypatch):
    pool = _BoundaryPool(accessible_user="shared-user")
    monkeypatch.setattr("utils.database_pool.get_native_pool", lambda: pool)
    node = DataframeInterfaceNode(
        "dataframe",
        "interface-dataframe",
        {},
        config=DataframeInterfaceNodeConfig(
            config=DataframeConfig(resource_id="dataset-a")
        ),
        workflow_id="workflow-b",
        user_id="shared-user",
    )

    result = await node.execute({})

    assert result["data"] == [{"secret": "allowed"}]

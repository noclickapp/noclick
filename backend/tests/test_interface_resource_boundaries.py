"""Execution-time access checks for interface resource UUIDs."""

import uuid

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
from tests.fixtures.real_db_fixture import real_database  # noqa: F401


class _BoundaryPool:
    def __init__(self):
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


async def _dataset_of_another_workflow(db):
    """A table in workflow A (its owner's), and workflow B of another user, who runs the node."""
    from repositories.resources import ResourceRepo
    from utils import dataset_store

    owner, runner = str(uuid.uuid4()), str(uuid.uuid4())
    for user in (owner, runner):
        await db.execute("INSERT INTO auth.users (id, email) VALUES ($1, $2)", user, f"{user}@example.com")
    workflow_a = await db.fetchval("INSERT INTO workflows (owner_id, name) VALUES ($1, 'A') RETURNING id", owner)
    workflow_b = await db.fetchval("INSERT INTO workflows (owner_id, name) VALUES ($1, 'B') RETURNING id", runner)
    made = await ResourceRepo(db.pool).create_resource(
        owner_id=owner, organization_id=None, workflow_id=str(workflow_a), node_id=None, resource_type="dataset",
        name="Secrets", mime_type=None, size_bytes=0, storage_ref=None, metadata={})
    await dataset_store.create_dataset(db.pool, made)
    made = await ResourceRepo(db.pool).get_resource(str(made["id"]))
    await dataset_store.append_rows(db.pool, made, [{"secret": "allowed"}])
    return owner, runner, str(workflow_a), str(workflow_b), str(made["id"])


async def _run_table(resource_id, workflow_id, user_id):
    node = DataframeInterfaceNode(
        "dataframe",
        "interface-dataframe",
        {},
        config=DataframeInterfaceNodeConfig(config=DataframeConfig(resource_id=resource_id)),
        workflow_id=workflow_id,
        user_id=user_id,
    )

    async def emit(_):
        return None

    node.emit = emit
    return await node.execute({})


@pytest.mark.asyncio
async def test_dataframe_uuid_requires_workflow_view_access(real_database):
    _, runner, _, workflow_b, resource_id = await _dataset_of_another_workflow(real_database)

    result = await _run_table(resource_id, workflow_b, runner)

    assert result["data"] == []


@pytest.mark.asyncio
async def test_dataframe_keeps_intended_shared_workflow_reuse(real_database):
    owner, runner, workflow_a, workflow_b, resource_id = await _dataset_of_another_workflow(real_database)
    await real_database.execute(
        "INSERT INTO resource_shares (resource_type, resource_id, target_type, target_user_id, permission, shared_by) "
        "VALUES ('workflow', $1, 'user', $2, 'view', $3)", workflow_a, runner, owner)

    result = await _run_table(resource_id, workflow_b, runner)

    assert result["data"] == [{"secret": "allowed"}]
    # Its own workflow reads it as well.
    assert (await _run_table(resource_id, workflow_a, owner))["data"] == [{"secret": "allowed"}]

"""Durable workflow media references are renewed immediately before execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode
from nodes.core.media_resolver import renewable_media_urls
from nodes.core.media_resolver import resolve_media_input


RESOURCE_ID = "12345678-1234-1234-1234-1234567890ab"
WORKFLOW_ID = "87654321-4321-4321-4321-ba0987654321"


class MediaConfig(BaseModel):
    media: str = Field(
        ..., json_schema_extra={"ui:widget": "media_upload"}
    )
    ordinary_uuid: str


class WrappedConfig(BaseModel):
    config: MediaConfig


class EchoNode(WorkflowNode):
    async def execute(self, inputs):
        del inputs
        return {"media": self._config.config.media}


def _pool(storage_ref: str = "owner/workflow/resource/file.png") -> AsyncMock:
    pool = AsyncMock()
    pool.fetchrow.return_value = {"storage_ref": storage_ref}
    return pool


@pytest.mark.asyncio
async def test_run_renews_media_resource_id_and_restores_config() -> None:
    config = WrappedConfig(
        config=MediaConfig(media=RESOURCE_ID, ordinary_uuid=RESOURCE_ID)
    )
    node = EchoNode(
        "node-1",
        "echo",
        {},
        config=config,
        workflow_id=WORKFLOW_ID,
    )
    pool = _pool()

    with (
        patch("utils.database_pool.get_native_pool", return_value=pool),
        patch(
            "utils.r2_cloudflare.get_public_download_url",
            return_value="https://storage.example/fresh",
        ),
    ):
        result = await node.run({})

    assert result == {"media": "https://storage.example/fresh"}
    assert config.config.media == RESOURCE_ID
    assert config.config.ordinary_uuid == RESOURCE_ID
    query, resource_id, workflow_id = pool.fetchrow.await_args.args
    assert "workflow_id = $2" in query
    assert (resource_id, workflow_id) == (RESOURCE_ID, WORKFLOW_ID)


@pytest.mark.asyncio
async def test_duplicate_ids_share_one_lookup_and_are_always_restored() -> None:
    class Pair(BaseModel):
        first: str = Field(..., json_schema_extra={"ui:widget": "media_upload"})
        second: str = Field(..., json_schema_extra={"ui:widget": "media_upload"})

    config = Pair(first=RESOURCE_ID, second=RESOURCE_ID)
    pool = _pool()

    with (
        patch("utils.database_pool.get_native_pool", return_value=pool),
        patch(
            "utils.r2_cloudflare.get_public_download_url",
            return_value="https://storage.example/fresh",
        ),
    ):
        with pytest.raises(RuntimeError, match="handler failed"):
            async with renewable_media_urls(config, WORKFLOW_ID):
                assert config.first == config.second == "https://storage.example/fresh"
                raise RuntimeError("handler failed")

    assert config.first == config.second == RESOURCE_ID
    pool.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_workflow_or_missing_resource_fails_closed() -> None:
    config = MediaConfig(media=RESOURCE_ID, ordinary_uuid="not-a-resource")
    pool = AsyncMock()
    pool.fetchrow.return_value = None

    with patch("utils.database_pool.get_native_pool", return_value=pool):
        with pytest.raises(ValueError, match="does not belong"):
            async with renewable_media_urls(config, WORKFLOW_ID):
                pass

    assert config.media == RESOURCE_ID


@pytest.mark.asyncio
async def test_run_scopes_resource_ids_resolved_from_dynamic_inputs() -> None:
    class InputMediaNode(WorkflowNode):
        async def execute(self, inputs):
            media = await resolve_media_input(inputs["media"])
            return {"filename": media.filename}

    class _Pool:
        async def fetchrow(self, query, resource_id, workflow_id):
            assert "workflow_id = $2" in query
            assert (resource_id, workflow_id) == (RESOURCE_ID, WORKFLOW_ID)
            return {
                "storage_ref": "owner/workflow/resource/file.png",
                "mime_type": "image/png",
                "name": "file.png",
                "size_bytes": 3,
            }

    node = InputMediaNode(
        "node-1",
        "input-media",
        {},
        config=None,
        workflow_id=WORKFLOW_ID,
    )
    with (
        patch("utils.database_pool.get_native_pool", return_value=_Pool()),
        patch(
            "utils.r2_cloudflare.generate_presigned_download_url",
            return_value="https://storage.example/fresh",
        ),
        patch(
            "nodes.core.media_resolver._stream_to_bytes",
            new=AsyncMock(return_value=(b"img", "image/png")),
        ),
    ):
        result = await node.run({"media": RESOURCE_ID})

    assert result == {"filename": "file.png"}

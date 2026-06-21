"""
Unit tests for the central binary-media seam: BinaryOutput markers are resolved
to {url, mime_type, name, size_bytes} file references (or a base64 dict with no
workflow context), and WorkflowNode.run() applies that to a node's output.
"""
import base64
from unittest.mock import AsyncMock, patch

import pytest

from nodes.core.binary_output import BinaryOutput, resolve_binary_outputs
from nodes.core.base import WorkflowNode


async def _fake_store(**kw):
    return {
        "resource_id": "res-1",
        "name": kw["filename"],
        "mime_type": kw["content_type"],
        "size_bytes": len(kw["body"]),
        "storage_ref": f"u/w/res-1/{kw['filename']}",
        "download_url": f"https://assets.test/{kw['filename']}",
    }


CTX = dict(user_id="u1", workflow_id="w1", node_id="n1", organization_id=None)


@pytest.mark.asyncio
async def test_resolves_top_level_marker():
    out = {"audio": BinaryOutput(b"hello", "audio/mpeg", "clip.mp3"), "ok": True}
    with patch("nodes.core.binary_output.create_resource_from_bytes", new=AsyncMock(side_effect=_fake_store)):
        resolved = await resolve_binary_outputs(out, **CTX)
    assert resolved["ok"] is True
    assert resolved["audio"] == {
        "url": "https://assets.test/clip.mp3",
        "mime_type": "audio/mpeg",
        "name": "clip.mp3",
        "size_bytes": 5,
    }
    assert not isinstance(resolved["audio"], BinaryOutput)


@pytest.mark.asyncio
async def test_no_context_falls_back_to_base64():
    out = {"audio": BinaryOutput(b"hello", "audio/mpeg", "clip.mp3")}
    # no workflow context -> base64 dict, never touches R2
    store = AsyncMock(side_effect=_fake_store)
    with patch("nodes.core.binary_output.create_resource_from_bytes", new=store):
        resolved = await resolve_binary_outputs(out, user_id=None, workflow_id=None)
    store.assert_not_called()
    assert resolved["audio"]["is_base64"] is True
    assert resolved["audio"]["base64"] == base64.b64encode(b"hello").decode()
    assert resolved["audio"]["mime_type"] == "audio/mpeg"
    assert "url" not in resolved["audio"]


@pytest.mark.asyncio
async def test_nested_markers_in_list_and_dict():
    out = {
        "items": [
            {"file": BinaryOutput(b"a", "image/png", "a.png")},
            {"file": BinaryOutput(b"bb", "image/png", "b.png")},
        ],
        "meta": {"deep": {"thumb": BinaryOutput(b"ccc", "image/jpeg", "c.jpg")}},
    }
    with patch("nodes.core.binary_output.create_resource_from_bytes", new=AsyncMock(side_effect=_fake_store)):
        resolved = await resolve_binary_outputs(out, **CTX)
    assert resolved["items"][0]["file"]["url"] == "https://assets.test/a.png"
    assert resolved["items"][1]["file"]["size_bytes"] == 2
    assert resolved["meta"]["deep"]["thumb"]["url"] == "https://assets.test/c.jpg"


@pytest.mark.asyncio
async def test_no_marker_passthrough_returns_same_object():
    out = {"data": {"a": 1, "b": ["x", "y"]}, "text": "z" * 10000}
    # cheap pre-scan: no marker -> returned untouched (same identity, no rebuild)
    resolved = await resolve_binary_outputs(out, **CTX)
    assert resolved is out


@pytest.mark.asyncio
async def test_metadata_merged_alongside_ref():
    out = {"audio": BinaryOutput(b"x", "audio/mpeg", "c.mp3", metadata={"duration_ms": 1200})}
    with patch("nodes.core.binary_output.create_resource_from_bytes", new=AsyncMock(side_effect=_fake_store)):
        resolved = await resolve_binary_outputs(out, **CTX)
    assert resolved["audio"]["url"] == "https://assets.test/c.mp3"
    assert resolved["audio"]["duration_ms"] == 1200


class _FakeMediaNode(WorkflowNode):
    @classmethod
    def get_config_model(cls):
        return None

    async def execute(self, inputs):
        return {"file": BinaryOutput(b"payload", "video/mp4", "v.mp4"), "status": "success"}


@pytest.mark.asyncio
async def test_run_wrapper_resolves_node_output():
    node = _FakeMediaNode(
        node_id="n1", node_type="automation-fake", node_data={},
        workflow_id="w1", user_id="u1",
    )
    with patch("nodes.core.binary_output.create_resource_from_bytes", new=AsyncMock(side_effect=_fake_store)):
        out = await node.run({})
    assert out["status"] == "success"
    assert out["file"] == {
        "url": "https://assets.test/v.mp4",
        "mime_type": "video/mp4",
        "name": "v.mp4",
        "size_bytes": 7,
    }


@pytest.mark.asyncio
async def test_snapshot_safe_redacts_markers_without_bytes():
    from nodes.core.binary_output import snapshot_safe

    out = {"file": BinaryOutput(b"rawbytes", "video/mp4", "v.mp4"), "ok": True}
    safe = snapshot_safe(out)
    assert safe["ok"] is True
    assert safe["file"] == {
        "name": "v.mp4",
        "mime_type": "video/mp4",
        "size_bytes": 8,
        "pending": True,
    }
    # no raw bytes leak into the snapshot
    assert "rawbytes" not in str(safe)
    assert not isinstance(safe["file"], BinaryOutput)


def test_snapshot_safe_passthrough_when_no_marker():
    from nodes.core.binary_output import snapshot_safe

    out = {"a": 1, "b": ["x"]}
    assert snapshot_safe(out) is out

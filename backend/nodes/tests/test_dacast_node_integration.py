"""Regressions using Dacast's unmodified official response examples."""
from pathlib import Path
import json
from unittest.mock import AsyncMock
import pytest
from nodes import dacast_node as p
from nodes.core.registry import NodeFactory
from nodes.tests.test_dacast_node_mock import wire, blob, USER

FIXTURES = Path(__file__).parent / "fixtures" / "dacast"


@pytest.mark.asyncio
async def test_current_documented_video_list(wire):
    payload = json.loads((FIXTURES / "list_videos.json").read_text())
    vid = payload["data"][0]["id"]
    data = blob(approved_resources_json=json.dumps({"channels": [], "videos": [vid], "folders": [], "playlists": []}))
    wire.queue = [payload]
    node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": {"operation": "list_videos", "per_page": 2}, "credentials": data}, user_id=USER)
    result = await node.execute({})
    assert result["results"][0]["id"] == vid
    assert result["has_more"] and result["provider_total_count"] == 43


@pytest.mark.asyncio
async def test_documented_folder_poll_runs_new_item_detection(wire):
    payload = json.loads((FIXTURES / "list_folders.json").read_text())
    ids = [row["id"] for row in payload["data"]]
    data = blob(approved_resources_json=json.dumps({"channels": [], "videos": [], "folders": ids, "playlists": []}))
    node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": {"operation": "on_new_folder"}, "credentials": data}, user_id=USER)
    node._filter_unseen = AsyncMock(side_effect=lambda rows, key: rows)
    wire.queue = [payload]
    result = await node.execute({})
    assert [row["id"] for row in result["folders"]] == ids
    assert result["new_folder_count"] == len(ids)
    assert wire.calls[0][2]["params"] == {"page": 1, "per_page": 50, "sort": "id", "order": "desc"}
    node._filter_unseen.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_poll_page_does_not_advance_baseline(wire):
    payload = json.loads((FIXTURES / "list_folders.json").read_text())
    payload["paging"]["next"] = "/v2/folder?page=2&per_page=50"
    payload["total_count"] = "101"
    data = blob(approved_resources_json=json.dumps({"channels": [], "videos": [], "folders": [row["id"] for row in payload["data"]], "playlists": []}))
    node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": {"operation": "on_new_folder"}, "credentials": data}, user_id=USER)
    node._filter_unseen = AsyncMock()
    wire.queue = [payload, payload]
    with pytest.raises(RuntimeError, match="repeated a folder"):
        await node.execute({})
    node._filter_unseen.assert_not_awaited()


@pytest.mark.asyncio
async def test_monitor_all_folders_requires_explicit_credential_opt_in(wire):
    payload = json.loads((FIXTURES / "list_folders.json").read_text())
    empty = json.dumps({"channels": [], "videos": [], "folders": [], "playlists": []})
    for monitor_all in (False, True):
        data = blob(approved_resources_json=empty, monitor_all_folders=monitor_all)
        node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": {"operation": "on_new_folder"}, "credentials": data}, user_id=USER)
        node._filter_unseen = AsyncMock(side_effect=lambda rows, key: rows)
        if not monitor_all:
            with pytest.raises(ValueError, match="Approve existing"):
                await node.execute({})
            assert not wire.calls
        else:
            wire.queue = [payload]
            result = await node.execute({})
            assert result["new_folder_count"] == len(payload["data"])
            event = p.DacastNode.resolve_agent_event(result)
            assert "Dacast" in event["text"]
            assert all(row["id"] in event["text"] for row in payload["data"])
            assert p.DacastNode.resolve_agent_event({"folders": []}) is None

"""Brightcove node contracts through real models and mock HTTP responses."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import brightcove_node as bc
from nodes.core.registry import NODE_REGISTRY, NodeFactory
USER = "test-user"

NODE = "automation-brightcove"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(fresh=True, **updates):
    return {"credential_type": "brightcove_client_credentials", "account_id": "123",
        "client_id": "fixture-client", "client_secret": "fixture-secret",
        "permissions": ["video-cloud/video/read", "video-cloud/playlist/read"],
        "access_token": "fixture-access", "token_type": "Bearer",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1 if fresh else -1)).isoformat(),
        **updates}


def make_node(operation, data=None, **config):
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **config},
        "credentials": credential() if data is None else data}, user_id=USER)


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[], callback=None)
    async def respond(request):
        state.calls.append(request)
        if state.callback:
            return await state.callback(request)
        assert state.responses, "Unexpected HTTP request"
        status, payload = state.responses.pop(0)
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        state.client_options.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(bc, "guarded_async_client", client)
    return state


@pytest.mark.parametrize("extra", [
    {"refresh_token": "not-supported"}, {"account_id": "https://evil.example"},
    {"client_id": "invalid:basic"}, {"token_type": "Token"}, {"expires_at": None},
])
def test_credential_family_binding_and_real_finite_token(extra):
    with pytest.raises(ValueError):
        bc._credential(credential(**extra))


def test_actual_factory_has_25_operations_and_no_global_callback():
    assert NODE_REGISTRY[NODE] is bc.BrightcoveNode
    schema = bc.BrightcoveNode.get_config_schema()
    refs = schema["properties"]["config"]["oneOf"]
    assert len({schema["$defs"][ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in refs}) == 25
    fields = schema["$defs"]["BrightcoveClientCredential"]
    assert "x-oauth-provider" not in fields
    node = make_node("create_video_draft", name="Fixture")
    assert isinstance(node.config.config, bc.BrightcoveCreateVideoConfig)
    with pytest.raises(ValidationError):
        bc.BrightcoveCreateVideoConfig()
    with pytest.raises(ValidationError):
        bc.BrightcoveCreateVideoConfig(name="x", state="ACTIVE")


@pytest.mark.asyncio
async def test_token_uses_basic_body_and_actual_expiry_not_refresh(http):
    http.responses = [(200, {"access_token": "new-access", "token_type": "Bearer", "expires_in": 120})]
    before = datetime.now(timezone.utc)
    minted = await bc._mint(credential(fresh=False))
    request = http.calls[0]
    assert str(request.url) == bc.TOKEN_URL and request.method == "POST"
    assert request.headers["authorization"] == "Basic Zml4dHVyZS1jbGllbnQ6Zml4dHVyZS1zZWNyZXQ="
    assert request.content == b"grant_type=client_credentials" and not request.url.query
    assert 119 <= (datetime.fromisoformat(minted["expires_at"]) - before).total_seconds() <= 121
    assert "refresh_token" not in minted


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"access_token": "x", "token_type": "Bearer"}, {"access_token": "x", "token_type": "Bearer", "expires_in": 0},
    {"access_token": "x", "token_type": "Bearer", "expires_in": True},
    {"access_token": "x", "token_type": "Token", "expires_in": 300},
    {"access_token": "x", "token_type": "Bearer", "expires_in": 300, "refresh_token": "unexpected"},
])
async def test_incomplete_token_never_becomes_infinite_or_assumed_refresh(http, payload):
    http.responses = [(200, payload)]
    with pytest.raises(RuntimeError, match="incomplete finite"):
        await bc._mint(credential(fresh=False))


@pytest.mark.asyncio
async def test_draft_inactive_projection_and_nullable_custom_fields(http):
    http.responses = [(201, {"id": "456", "name": "Fixture", "state": "INACTIVE",
        "custom_fields": {"topic": None}, "sources": [{"src": "https://secret.example"}],
        "images": {"poster": {"src": "https://private.example"}}, "download_url": "hidden"})]
    out = await make_node("create_video_draft", credential(permissions=["video-cloud/video/create"]),
        name="Fixture", custom_fields={"topic": None}).execute({})
    assert json.loads(http.calls[0].content)["state"] == "INACTIVE"
    assert out["video"]["custom_fields"] == {"topic": None}
    assert set(out["video"]) == {"id", "name", "state", "custom_fields"}


@pytest.mark.asyncio
async def test_write_ceiling_denies_before_token_or_provider(http):
    with pytest.raises(ValueError, match="local ceiling"):
        await make_node("delete_video", credential(fresh=False), video_id="456").execute({})
    assert http.calls == []


@pytest.mark.asyncio
async def test_manual_membership_clear_and_false_are_preserved(http):
    http.responses = [(200, {"id": "789", "type": "EXPLICIT"}), (200, {"id": "789", "favorite": False, "video_ids": []})]
    out = await make_node("update_playlist", credential(permissions=["video-cloud/playlist/update"]),
        playlist_id="789", favorite=False, video_ids=[]).execute({})
    assert json.loads(http.calls[-1].content) == {"favorite": False, "video_ids": []}
    assert out["playlist"]["favorite"] is False


@pytest.mark.asyncio
async def test_smart_playlist_replacement_and_foreign_account_stop_before_write(http):
    http.responses = [(200, {"id": "789", "type": "ACTIVATED_OLDEST"})]
    with pytest.raises(ValueError, match="manual"):
        await make_node("update_playlist", credential(permissions=["video-cloud/playlist/update"]),
            playlist_id="789", video_ids=[]).execute({})
    assert len(http.calls) == 1
    http.responses = [(200, {"id": "456", "account_id": "999"})]
    with pytest.raises(RuntimeError, match="unexpected account"):
        await make_node("delete_video", credential(permissions=["video-cloud/video/delete"]), video_id="456").execute({})
    assert all(request.method == "GET" for request in http.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 204])
async def test_empty_folder_delete_matches_current_name_and_preserves_status(http, status):
    http.responses = [(200, {"id": "folder-a", "name": "Fixture", "video_count": 0}), (status, None)]
    out = await make_node("delete_empty_folder", credential(permissions=["video-cloud/video/delete"]),
        folder_id="folder-a", name="Fixture").execute({})
    assert out == {"deleted": True, "http_status": status}
    assert http.calls[-1].url.params["name"] == "Fixture"


@pytest.mark.asyncio
async def test_remove_checks_actual_folder_membership(http):
    http.responses = [(200, {"id": "folder-a", "name": "Fixture", "video_count": 1}),
        (200, {"id": "456", "folder_id": "folder-b"})]
    with pytest.raises(ValueError, match="not in"):
        await make_node("remove_video_from_folder", credential(permissions=["video-cloud/video/update"]),
            folder_id="folder-a", video_id="456").execute({})
    assert all(request.method == "GET" for request in http.calls)


@pytest.mark.asyncio
async def test_zero_match_page_keeps_continuation_and_cursor_is_scope_bound(http):
    http.responses = [(200, [{"id": "456", "name": "Unmatched"}]), (200, {"count": 60})]
    result = await bc.BrightcoveNode.load_field_options("video_id", credential(), search="wanted")
    assert result["options"] == [] and result["next_page_token"]
    for data, search in [(credential(account_id="999"), "wanted"), (credential(), "different")]:
        with pytest.raises(ValueError, match="page token"):
            await bc.BrightcoveNode.load_field_options("video_id", data, search=search, page_token=result["next_page_token"])
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_parent_cursor_is_bound_and_label_reads_do_not_allow_writes(http):
    http.responses = [(200, {"id": "folder-a", "name": "A", "video_count": 51}), (200, [])]
    page = await bc.BrightcoveNode.load_field_options("folder_video_id", credential(), context={"folder_id": "folder-a"})
    assert page["next_page_token"]
    http.responses = [(200, {"id": "folder-b", "name": "B", "video_count": 51})]
    with pytest.raises(ValueError, match="page token"):
        await bc.BrightcoveNode.load_field_options("folder_video_id", credential(),
            context={"folder_id": "folder-b"}, page_token=page["next_page_token"])
    assert len(http.calls) == 3
    with pytest.raises(ValueError, match="local ceiling"):
        await make_node("delete_label", label_path="/Fixture").execute({})
    assert len(http.calls) == 3


@pytest.mark.asyncio
async def test_freshen_client_grant_uses_current_token_or_mints_without_persistence(http):
    current = credential()
    assert await bc.BrightcoveNode.freshen_credential(current) == bc._credential(current)
    assert http.calls == []
    http.responses = [(200, {"access_token": "minted", "token_type": "Bearer", "expires_in": 300})]
    result = await bc.BrightcoveNode.freshen_credential(credential(fresh=False))
    assert result["access_token"] == "minted"
    assert result["account_id"] == current["account_id"]
    assert "refresh_token" not in result


@pytest.mark.asyncio
async def test_access_validation_and_picker_mint_expired_client_tokens(http):
    http.responses = [(200, {"access_token": "minted", "token_type": "Bearer", "expires_in": 300}),
        (200, [{"id": "456", "name": "Fixture"}])]
    assert await bc.BrightcoveNode.validate_credential_access(credential(fresh=False)) == {"valid": True}
    http.responses = [(200, {"access_token": "minted", "token_type": "Bearer", "expires_in": 300}),
        (200, [{"id": "456", "name": "Fixture"}]), (200, {"count": 1})]
    result = await bc.BrightcoveNode.load_field_options("video_id", credential(fresh=False))
    assert result["options"] == [{"value": "456", "label": "Fixture"}]


@pytest.mark.asyncio
async def test_actual_unsaved_collector_proves_account_without_identity(http):
    from nodes.core.connection_evidence import collect_evidence
    http.responses = [(200, [{"id": "456", "name": "Private fixture"}]), (200, {"count": 1})]
    result = await collect_evidence(node_type=NODE, user_id=USER, credential_data=credential())
    assert result.reachable is True and result.noun == "videos"
    assert result.samples[0].label == "Private fixture" and result.account_label is None
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_actual_manual_connect_shapes_before_probe_and_preserves_account_proof(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    invalid = await credential_connect.validate_for_connect(credential_type="brightcove_client_credentials",
        credential_data=credential(account_id="https://wrong.example"), user_id=USER)
    assert not invalid.ok and "account_id" in invalid.field_errors and http.calls == []
    http.responses = [(200, [{"id": "456", "name": "Private fixture"}]), (200, {"count": 1})]
    valid = await credential_connect.validate_for_connect(credential_type="brightcove_client_credentials",
        credential_data=credential(), user_id=USER)
    assert valid.ok and valid.node_type == NODE and valid.evidence.reachable is True
    assert valid.verified_metadata()["verified_with"] == "Private fixture"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_error_projection_never_exports_auth_or_body(http, status):
    http.responses = [(status, {"error": "fixture-secret https://signed.example"})]
    with pytest.raises(RuntimeError) as failure:
        await make_node("get_video", video_id="456").execute({})
    assert "fixture-secret" not in str(failure.value) and "signed.example" not in str(failure.value)



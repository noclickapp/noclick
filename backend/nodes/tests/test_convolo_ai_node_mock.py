"""Test the Convolo Ai factory against a fake provider transport.

Pin write semantics, credential handling and pagination without accessing
any provider account or replacing the shared workflow execution path.
"""
import json
import httpx
import pytest
from nodes import convolo_ai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "convolo-test-secret-67"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="convolo-test", node_type=native.NODE_TYPE,
        node_data={"config": config, "credentials": {"credential_type": "convolo_ai_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
async def test_project_evidence_uses_own_account_and_keeps_page(monkeypatch):
    calls = transport(monkeypatch, {"success": True, "projects": [{"id": 12345, "name": "Sales"}], "totalCount": 51})
    result = await node({"operation": "list_projects", "page": 2, "items_per_page": 50, "archive": "nonArchived"}).execute({})
    assert len(calls) == 1 and calls[0].url.host == "api.dialer.brightcall.ai"
    assert calls[0].url.path == "/api/v3/projects"
    assert dict(calls[0].url.params) == {"page": "2", "itemsPerPage": "50", "archive": "nonArchived"}
    assert calls[0].headers["api-key"] == TOKEN
    assert result["data"]["projects"][0]["name"] == "Sales" and result["data"]["totalCount"] == 51


@pytest.mark.asyncio
async def test_contact_names_and_zero_saved_are_preserved(monkeypatch):
    calls = transport(monkeypatch, {"success": True, "savedContactsCount": 0, "duplicates": ["14155550123"]}, 201)
    result = await node({"operation": "add_contact", "project_id": 12345,
        "contact": {"Phone": "+14155550123", "First name": "Jane", "Company": "Acme Inc"}}).execute({})
    assert calls[0].method == "POST" and calls[0].url.path == "/api/v1/project-contacts/12345/add"
    assert dict(calls[0].url.params) == {"addDuplicates": "false"}
    assert json.loads(calls[0].content)["Phone"] == "+14155550123"
    assert result["contact_added"] is False


@pytest.mark.asyncio
async def test_partial_contact_edit_uses_column_ids(monkeypatch):
    calls = transport(monkeypatch, {"success": True})
    await node({"operation": "update_contact", "project_id": 12345, "contact_id": 678,
        "contact_data": [{"columnId": 42, "value": "Alice"}]}).execute({})
    assert calls[0].method == "PATCH" and calls[0].url.path.endswith("/12345/678")
    assert json.loads(calls[0].content) == {"contactData": [{"columnId": 42, "value": "Alice"}]}


@pytest.mark.asyncio
async def test_agent_edit_requires_version_and_preserves_omission_vs_clear(monkeypatch):
    calls = transport(monkeypatch, {"success": True, "dryRun": True, "changed": ["voice"], "agent": {"version": "v2"}})
    await node({"operation": "update_ai_agent", "project_id": 12345, "version": "v1", "dry_run": True,
        "voice": None, "prompt": {"instructions": "Ask for a meeting"}}).execute({})
    assert json.loads(calls[0].content) == {"version": "v1", "dryRun": True, "voice": None, "prompt": {"instructions": "Ask for a meeting"}}
    with pytest.raises(ValueError):
        node({"operation": "update_ai_agent", "project_id": 12345, "voice": "Alice"})


@pytest.mark.asyncio
async def test_call_cursor_and_safe_identifiers(monkeypatch):
    calls = transport(monkeypatch, {"success": True, "calls": [], "hasMore": True, "nextCursor": "next+cursor"})
    result = await node({"operation": "list_ai_agent_calls", "project_id": 12345, "cursor": "first+cursor", "limit": 3}).execute({})
    assert dict(calls[0].url.params) == {"limit": "3", "cursor": "first+cursor"}
    assert result["data"]["nextCursor"] == "next+cursor"
    for bad in ["..", "../../openapi", "x/y", "https://evil.test"]:
        with pytest.raises(ValueError):
            node({"operation": "get_ai_agent_call", "project_id": 12345, "call_id": bad})


@pytest.mark.asyncio
async def test_revert_is_versioned_and_autoplay_is_explicit(monkeypatch):
    calls = transport(monkeypatch, {"success": True})
    await node({"operation": "revert_ai_agent", "project_id": 12345, "version": "v2", "version_id": "old-id", "before": True}).execute({})
    assert calls[0].method == "POST" and calls[0].url.path.endswith("/revert/old-id")
    assert json.loads(calls[0].content) == {"version": "v2", "dryRun": False, "before": True}
    await node({"operation": "set_project_autoplay", "project_id": 12345, "enabled": False}).execute({})
    assert calls[1].method == "PUT" and calls[1].url.path == "/api/v1/projects/autoplay/12345/0"
    assert not calls[1].content


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Rejected " + TOKEN}), (200, {"success": False, "debug": TOKEN})])
async def test_provider_errors_and_secret_redaction(monkeypatch, status, body):
    transport(monkeypatch, body, status)
    result = await node({"operation": "list_ai_agents"}).execute({})
    assert result["success"] is False and result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_unexpected_envelope_is_not_success(monkeypatch):
    transport(monkeypatch, {"projects": []})
    with pytest.raises(ValueError, match="unexpected response"):
        await node({"operation": "list_projects"}).execute({})


@pytest.mark.parametrize("key", ["https://api.example.test", "<token>", "one\ntwo"])
def test_credential_rejects_bad_keys(key):
    with pytest.raises(ValueError):
        native.ConvoloAiAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
async def test_project_payload_keeps_documented_numeric_enum_value(monkeypatch):
    # Synthetic response: numeric type follows the provider's enum and prose.
    calls = transport(monkeypatch, {"success": True, "project": {"id": 12345, "name": "Sales", "type": 4}})
    result = await node({"operation": "get_project", "project_id": 12345}).execute({})
    assert calls[0].url.path == "/api/v3/project/12345"
    assert result["data"]["project"]["type"] == 4

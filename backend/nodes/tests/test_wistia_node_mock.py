"""Offline request/response regressions; fixtures are synthetic, not live evidence."""
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import wistia_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "wistia-synthetic-test-token"
CASES = json.loads((Path(__file__).parent / "fixtures/wistia/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="wistia-test", node_type="automation-wistia", node_data={
        "config": config, "credentials": {"credential_type": "wistia_api_token", "api_token": TOKEN}})


def transport(monkeypatch, reply):
    calls = []
    def handler(request):
        calls.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["config"]["operation"])
async def test_contract_request_and_documented_envelope(monkeypatch, case):
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json=case["response"]) if case["response"] is not None else httpx.Response(200))
    result = await node(case["config"]).execute({})
    assert NODE_REGISTRY["automation-wistia"] is native.WistiaNode
    assert result["status"] == "success" and result["data"] == case["response"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.host == "api.wistia.com"
    assert request.url.raw_path.split(b"?")[0].decode() == "/modern" + case["path"]
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["x-wistia-api-version"] == "2026-09"
    assert (json.loads(request.content) if request.content else None) == case["body"]
    if case["config"]["operation"] == "list_media":
        assert dict(request.url.params) == {"page": "1", "per_page": "25", "name": "Launch + café", "archived": "false"}
    if case["config"]["operation"] == "list_folders":
        assert dict(request.url.params) == {"page": "2", "per_page": "1"}
        assert result["has_more"] and result["next_page"] == 3
    if case["config"]["operation"] == "import_media":
        assert result["import_completed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302])
async def test_errors_redact_secret_and_do_not_retry_or_follow(monkeypatch, status):
    calls = transport(monkeypatch, lambda _: httpx.Response(status, text="Denied " + TOKEN, headers={"Location": "https://example.com"}))
    result = await node({"operation": "get_account"}).execute({})
    assert len(calls) == 1 and result["status"] == "error"
    assert result["http_status"] == status and TOKEN not in str(result)
    assert result["message"] == "Denied [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>oops</html>"), httpx.Response(200, json=[]), httpx.Response(200, json={"error": "denied"}), httpx.Response(200, content=b"{", headers={"content-type": "application/json"})])
async def test_malformed_success_is_not_connection_proof(monkeypatch, response):
    transport(monkeypatch, lambda _: response)
    with pytest.raises(ValueError):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.asyncio
async def test_empty_page_and_nested_secret_redaction(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json=[]))
    result = await node({"operation": "list_media"}).execute({})
    assert result["data"] == [] and result["next_page"] is None
    transport(monkeypatch, lambda _: httpx.Response(200, json={"id": 123, "name": "Acme", "nested": [TOKEN]}))
    assert TOKEN not in str(await node({"operation": "get_account"}).execute({}))


@pytest.mark.asyncio
async def test_write_timeout_does_not_retry(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("private " + TOKEN, request=request)
    calls = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="inspect write outcomes") as exc:
        await node({"operation": "create_tag", "name": "launch"}).execute({})
    assert TOKEN not in str(exc.value) and len(calls) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_media", "media_id": "../other"},
    {"operation": "get_folder", "folder_id": "x/y"},
    {"operation": "update_media", "media_id": "abc"},
    {"operation": "update_folder", "folder_id": "abc"},
    {"operation": "list_media", "per_page": 101},
    {"operation": "list_media", "page": 0},
    {"operation": "import_media", "url": "https://user:secret@example.com/a"},
    {"operation": "import_media", "url": "file:///etc/passwd"},
    {"operation": "create_captions", "media_id": "abc", "caption_file": "captions", "language": "english"},
])
def test_invalid_inputs_rejected_before_network(config):
    assert not native.WistiaNode.validate_config({"config": config})["valid"]


def test_token_cleaning_and_account_specific_connection_evidence():
    credential = native.WistiaAPITokenCredential(api_token=" " + TOKEN + " ")
    assert credential.api_token == TOKEN
    for value in ["https://example.com/token", "Bearer " + TOKEN, "<token>"]:
        with pytest.raises(ValidationError):
            native.WistiaAPITokenCredential(api_token=value)
    evidence = native.WistiaNode.connection_evidence
    assert evidence.operation == "list_media" and evidence.identity_operation == "get_account"
    assert evidence.proves == "account"


DOCUMENTED_MEDIA = json.loads((Path(__file__).parent / "fixtures/wistia/media-list-documented.json").read_text())["body"]


def poll_state(monkeypatch, instance, state):
    """Exercise real dedup and scope logic with an in-memory CAS state seam."""
    async def update(mutator, **kwargs):
        replacement, result = mutator(deepcopy(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_media", "on_updated_media"])
async def test_poll_baseline_new_update_dedup_and_agent_event(monkeypatch, operation):
    rows = deepcopy(DOCUMENTED_MEDIA)
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json=rows))
    instance = node({"operation": operation, "folder_id": "5cb193e92c"})
    state = {}
    poll_state(monkeypatch, instance, state)
    baseline = await instance.execute({})
    assert baseline["media"] == []
    assert instance.trigger_produced_no_event(baseline)
    assert not instance.should_propagate_output(baseline, {"operation": operation})
    assert instance.resolve_agent_event(baseline) is None
    # Deliberate mutations of the documented example model later deliveries.
    rows[0]["updated"] = "2011-05-27T00:04:25+00:00"
    updated = await instance.execute({})
    assert updated["media_count"] == (1 if operation == "on_updated_media" else 0)
    rows.append({**rows[0], "hashed_id": "newmedia123", "name": "New video"})
    output = await instance.execute({})
    assert output["media_count"] == 1 and output["media"][0]["hashed_id"] == "newmedia123"
    assert instance.trigger_emitted_event(output)
    assert instance.should_propagate_output(output, {"operation": operation})
    event = instance.resolve_agent_event(output)
    assert all(value in event["text"] for value in ["Wistia", "New video", "newmedia123", "5cb193e92c"])
    assert (await instance.execute({}))["media_count"] == 0
    for request in calls:
        assert request.method == "GET" and request.url.path == "/modern/medias"
        assert dict(request.url.params) == {"page": "1", "per_page": "100", "folder_id": "5cb193e92c",
            "sort_by": "updated" if operation == "on_updated_media" else "created", "sort_direction": "0"}


@pytest.mark.asyncio
async def test_poll_paginates_and_rebaselines_on_scope_change(monkeypatch):
    rows = [{**DOCUMENTED_MEDIA[0], "hashed_id": str(i)} for i in range(101)]
    def reply(request):
        start = (int(request.url.params["page"]) - 1) * 100
        return httpx.Response(200, json=rows[start:start + 100])
    calls = transport(monkeypatch, reply)
    state = {}
    instance = node({"operation": "on_new_media", "folder_id": "first"})
    poll_state(monkeypatch, instance, state)
    assert (await instance.execute({}))["media_count"] == 0
    assert len(state["seen_ids"]) == 101 and len(calls) == 2
    old_scope = state["scope"]
    instance = node({"operation": "on_new_media", "folder_id": "second"})
    poll_state(monkeypatch, instance, state)
    rows.append({**DOCUMENTED_MEDIA[0], "hashed_id": "different"})
    assert (await instance.execute({}))["media_count"] == 0
    assert state["scope"] != old_scope and len(state["seen_ids"]) == 102


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(401), httpx.Response(200, json=[{}]),
    httpx.Response(200, json=[{"hashed_id": "abc"}]), httpx.Response(200, json={"bad": "shape"})])
async def test_poll_failure_never_advances_state(monkeypatch, response):
    transport(monkeypatch, lambda _: response)
    instance = node({"operation": "on_updated_media"})
    state = {"seen_ids": ["previous"]}
    poll_state(monkeypatch, instance, state)
    with pytest.raises(ValueError):
        await instance.execute({})
    assert state == {"seen_ids": ["previous"]}


@pytest.mark.asyncio
async def test_poll_limit_fails_before_recording_a_partial_baseline(monkeypatch):
    calls = transport(monkeypatch, lambda _: httpx.Response(200, json=DOCUMENTED_MEDIA * 100))
    instance = node({"operation": "on_new_media"})
    state = {}
    poll_state(monkeypatch, instance, state)
    with pytest.raises(ValueError, match="2,000 media"):
        await instance.execute({})
    assert len(calls) == 21 and state == {}

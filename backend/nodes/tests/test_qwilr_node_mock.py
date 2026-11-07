"""Native Qwilr contracts through parsed execute and HTTP fixtures."""
from copy import deepcopy
import json
import logging
from types import SimpleNamespace
import httpx
import pytest
from pydantic import TypeAdapter
from nodes import qwilr_node as Q

USER = "00000000-0000-4000-8000-000000000001"
PAGE = "6ee0f841f3cc8900090d82dc"
OWNER_ID = "6ee0f841f3cc8900090d82dd"
BLOCK = "uCHq6B6_S1EqZ2pyam8YVfUldvoF-Q"
AUTH = {"credential_type": Q.FAMILY, "api_token": "synthetic-qwilr-token-only"}


def page(**changes):
    return {"id": PAGE, "name": "Owned fixture draft", "status": "draft", "tags": ["fixture"],
        "createdAt": "2026-10-06T00:00:00Z", "folderId": None, "ownerId": OWNER_ID,
        "expiry": {"enabled": False}, "paymentSettings": {"enabled": True, "gatewayId": "private-gateway"},
        "links": {"publicUrl": "https://private.invalid/link", "collaboratorUrl": "private-link"},
        "metadata": {"private": "private-data"}, "acceptance": {"acceptersCount": 1, "acceptersTotal": 2,
            "accepters": [{"email": "private@example.invalid", "name": "Private signer", "esigned": True}], "quote": {"amount": 999}}, **changes}


class Context:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *_): return False


@pytest.fixture
def world(monkeypatch):
    state = SimpleNamespace(calls=[], current=page(), next_cursor=None, status=None, raw=None, after_request=None, kwargs=[])
    def respond(req):
        state.calls.append(req)
        if state.after_request: state.after_request(req)
        if state.status: return httpx.Response(state.status, json={"message": "private provider text", "api_token": AUTH["api_token"]})
        if state.raw is not None: return httpx.Response(200, content=state.raw, headers={"content-type": "application/json"})
        path = req.url.path
        if path == "/v1/users": data = [{"id": OWNER_ID, "email": "private@example.invalid", "firstName": "Fixture", "lastName": "Owner", "createdAt": "2026-10-06T00:00:00Z", "roles": [{"name": "admin"}], "teams": [{"name": "Fixture team"}]}]
        elif path == "/v1/blocks/saved": data = [{"id": BLOCK, "name": "Owned saved block", "type": "text", "content": "private-content"}]
        elif req.method == "POST":
            body = json.loads(req.content); assert body["published"] is False
            state.current = page(name=body["name"], tags=body["tags"])
            data = state.current
        elif req.method == "PUT":
            body = json.loads(req.content); assert body["published"] is False
            if "expiry" in body: state.current["expiry"] = body["expiry"]
            data = state.current
        elif path == "/v1/pages": data = {"data": [state.current], "nextCursor": state.next_cursor}
        else: data = state.current
        return httpx.Response(201 if req.method == "POST" else 200, json=data)
    def client(**kwargs):
        state.kwargs.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False)
    monkeypatch.setattr(Q, "guarded_async_client", client)
    return state


def args(op):
    result = {"operation": op}
    if op in {"get_page", "get_acceptance_summary", "replace_draft_blocks", "update_draft_expiry"}: result["page_id"] = PAGE
    if op.startswith("create_draft_"):
        result.update(name="New fixture", tags=["fixture"], acknowledge_live_account_effects=True,
            substitutions={"company": "Synthetic Ltd", "rows": [{"item": "fixture"}]}, metadata={"external_id": "synthetic"}, owner_id=OWNER_ID)
        if op.endswith("template"): result["template_id"] = PAGE
    if op in {"create_draft_from_blocks", "replace_draft_blocks"}: result["saved_block_id"] = BLOCK
    if op in {"replace_draft_blocks", "update_draft_expiry"}: result["acknowledge_live_account_effects"] = True
    if op == "replace_draft_blocks": result["saved_block_page_confirmed"] = True
    if op == "update_draft_expiry": result["expire_after_days"] = 7
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("op", Q.OPS)
async def test_every_native_operation_discriminates_generates_and_executes(world, op):
    cfg = args(op)
    parsed = TypeAdapter(Q.QwilrOperation).validate_python(cfg)
    assert parsed.operation == op
    schema = TypeAdapter(Q.QwilrOperation).json_schema()
    assert set(schema["discriminator"]["mapping"]) == set(Q.OPS)
    node = Q.QwilrNode("fixture", Q.NODE_TYPE, {"credentials": AUTH, "config": cfg}, Q.QwilrNode.parse_config({"credentials": AUTH, "config": cfg}), None, "sid", None, USER)
    result = await node.execute({})
    assert world.calls and all(str(req.url).startswith(Q.BASE + "/") and req.headers["authorization"] == "Bearer " + AUTH["api_token"] for req in world.calls)
    serialized = json.dumps(result)
    assert not any(secret in serialized for secret in (AUTH["api_token"], "private@example.invalid", "Private signer", "private-link", "private-data", "private-gateway", "private-content"))
    if op.startswith("create_draft_") or op in {"replace_draft_blocks", "update_draft_expiry"}:
        assert result["readback_verified"] is True and result["content_verified"] is False
        writes = [r for r in world.calls if r.method in {"POST", "PUT"}]
        assert len(writes) == 1 and json.loads(writes[0].content)["published"] is False
        assert not any(key in json.loads(writes[0].content) for key in ("paymentSettings", "acceptSettings", "gatewayId"))
    if op == "get_acceptance_summary": assert result["acceptance_counts"] == {"acceptersCount": 1, "acceptersTotal": 2}


@pytest.mark.asyncio
async def test_real_cursor_filter_wire_and_picker_boundaries(world):
    world.next_cursor = "provider-cursor"
    result = await Q.records(AUTH, {"operation": "list_pages", "statuses": ["draft", "accepted"], "tags": ["fixture"], "owner_id": OWNER_ID, "folder_id": PAGE, "sort_direction": "asc", "cursor": "old", "limit": 10})
    assert result["next_cursor"] == "provider-cursor"
    assert dict(world.calls[-1].url.params) == {"limit": "10", "sortDirection": "asc", "cursor": "old", "folderId": PAGE, "ownerId": OWNER_ID, "status": "draft,accepted", "tags": "fixture"}
    first = await Q.QwilrNode.load_field_options("page_id", AUTH, search="Owned")
    second = await Q.QwilrNode.load_field_options("page_id", AUTH, page_token=first["next_page_token"], search="Owned")
    assert second["options"] == [{"value": PAGE, "label": "Owned fixture draft"}] and world.calls[-1].url.params["cursor"] == "provider-cursor"
    count = len(world.calls)
    for data, field, search in (({**AUTH, "api_token": "synthetic-other-token"}, "page_id", "Owned"), (AUTH, "owner_id", "Owned"), (AUTH, "page_id", "Different")):
        with pytest.raises(ValueError): await Q.QwilrNode.load_field_options(field, data, page_token=first["next_page_token"], search=search)
    assert len(world.calls) == count and AUTH["api_token"] not in first["next_page_token"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 301, 400, 401, 403, 404, 409, 422, 429, 503])
async def test_status_refusals_are_static_without_retry_or_provider_body(world, status):
    world.status = status
    with pytest.raises((ValueError, RuntimeError)) as caught: await Q.records(AUTH, {"operation": "list_pages"})
    assert len(world.calls) == 1 and AUTH["api_token"] not in str(caught.value) and "private provider" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b'{}', b'[]', b'{"data":[],"nextCursor":null,"nextCursor":"dup"}', b'{"data":[],"nextCursor":NaN}', b'{"statusCode":400,"message":"private"}', b'{"data":[],"nextCursor":1}'])
async def test_malformed_success_cannot_claim_read_completion(world, raw):
    world.raw = raw
    with pytest.raises((ValueError, RuntimeError)): await Q.records(AUTH, {"operation": "list_pages"})
    assert len(world.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", "https://private.invalid/token", "your-api-key", "Bearer secret", 123, True, "a b", "a\nb"])
async def test_bad_manual_token_never_reaches_transport(world, bad):
    with pytest.raises(ValueError): await Q.records({**AUTH, "api_token": bad}, {"operation": "list_pages"})
    assert world.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["foreign", "dual", "host"])
async def test_foreign_raw_family_and_saved_marker_refuse(world, changed):
    data = deepcopy(AUTH)
    if changed == "foreign": data["credential_type"] = "slack_oauth"
    if changed == "dual": data["access_token"] = "synthetic-other"
    if changed == "host": data["server_url"] = "https://other.invalid"
    with pytest.raises(ValueError): await Q.records(data, {"operation": "list_pages"})
    assert world.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("op", ["replace_draft_blocks", "update_draft_expiry"])
async def test_live_page_never_enters_draft_write(world, op):
    world.current["status"] = "live"
    with pytest.raises(ValueError): await Q.records(AUTH, args(op))
    assert [r.method for r in world.calls] == ["GET"]


@pytest.mark.asyncio
async def test_foreign_owner_and_block_never_start_creation(world):
    cfg = args("create_draft_from_blocks"); cfg["owner_id"] = "z" * 24
    with pytest.raises(ValueError): await Q.records(AUTH, cfg)
    cfg["owner_id"] = OWNER_ID; cfg["saved_block_id"] = "x" * 30
    with pytest.raises(ValueError): await Q.records(AUTH, cfg)
    assert all(r.method == "GET" for r in world.calls)


@pytest.mark.asyncio
async def test_postwrite_readback_failure_does_not_repeat_creation(world):
    def change_readback(req):
        if req.url.path == "/v1/pages/" + PAGE and any(r.method == "POST" for r in world.calls):
            world.current["name"] = "Concurrent edit"
    world.after_request = change_readback
    with pytest.raises(RuntimeError, match="may have applied"):
        await Q.records(AUTH, args("create_draft_from_template"))
    assert len([r for r in world.calls if r.method == "POST"]) == 1


@pytest.mark.parametrize("field,value", [("substitutions", {"count": 3}), ("metadata", {"key": {"nested": "value"}}), ("template_id", 123), ("tags", ["tag,other"]), ("saved_block_id", "wrong-id")])
def test_closed_native_fields_refuse_arbitrary_payload_shapes(field, value):
    cfg = args("create_draft_from_blocks" if field == "saved_block_id" else "create_draft_from_template")
    cfg[field] = value
    with pytest.raises(ValueError): TypeAdapter(Q.QwilrOperation).validate_python(cfg)


@pytest.mark.parametrize("value", [False, None, 1, "true", "yes"])
def test_acknowledgement_is_deliberate_boolean_without_schema_autoselection(value):
    cfg = args("create_draft_from_template"); cfg["acknowledge_live_account_effects"] = value
    with pytest.raises(ValueError): TypeAdapter(Q.QwilrOperation).validate_python(cfg)
    field = Q.CreateDraftFromTemplate.model_json_schema()["properties"]["acknowledge_live_account_effects"]
    assert field["type"] == "boolean" and "const" not in field and "default" not in field


@pytest.mark.asyncio
async def test_private_transport_logging_is_scoped(world, caplog):
    def log(req): logging.getLogger("httpcore.http11").warning("private header %s", req.headers["authorization"])
    world.after_request = log
    with caplog.at_level(logging.WARNING): await Q.records(AUTH, {"operation": "list_pages"})
    assert AUTH["api_token"] not in caplog.text
    logging.getLogger("httpcore.http11").warning("normal nonprovider event")
    assert "normal nonprovider event" in caplog.text

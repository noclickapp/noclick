"""UNRUN native Stream Chat regressions using synthetic storage and HTTP only."""
import asyncio
import base64
from copy import deepcopy
import hashlib
import hmac
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.stream_chat_node import (
    BASE, FAMILY, NODE, StreamChatNode, StreamChatNodeConfig, StreamChatServerCredential,
    _Client, _PRIVATE_REQUEST, _PRIVACY,
)
from nodes.core.credential_validation import CredentialValidationUnavailable
from nodes.core.registry import NODE_REGISTRY
from nodes.core.run_op import run_node_lookup, run_node_operation
from repositories.credentials import credential_access_predicate
from tests.test_post_connect_validation_context import (
    CID, USER, ORG, OWNER, _Storage as ContextStorage, native as context_native, _validate,
)

CREDENTIAL = {"credential_type": FAMILY, "api_key": "fixture-stream-key", "api_secret": "fixture-stream-secret"}
TYPE = "messaging"
CHANNEL = "owned-fixture"
MESSAGE = "message-fixture"
CID_VALUE = TYPE + ":" + CHANNEL
DURATION = {"duration": "0.01ms"}


def user(ident="alice", name="Alice"):
    return {"id": ident, "name": name, "created_at": "2026-10-06T00:00:00Z", "role": "admin", "custom": {"private": "omit-me"}}


def channel():
    return {"id": CHANNEL, "type": TYPE, "cid": CID_VALUE, "name": "Fixture", "created_by": {"id": "alice"},
            "member_count": 1, "custom": {"private": "omit-me"}, "frozen": False, "message_count": 0}


def message():
    return {"id": MESSAGE, "cid": CID_VALUE, "channel": channel(), "user": user(), "type": "regular",
        "created_at": "2026-10-06T00:00:00Z", "reply_count": 0, "pinned": False,
        "text": "PRIVATE_MESSAGE", "html": "PRIVATE_HTML", "attachments": [{"url": "https://private.invalid/signed"}]}


class Storage(ContextStorage):
    def __init__(self):
        super().__init__()
        self.row["credential_type"] = FAMILY

    async def fetchrow(self, sql, *args):
        if "SELECT c.credential, c.owner_id, c.credential_type, c.token_version" in sql:
            assert credential_access_predicate() in sql
            assert "workflow_authorized_credentials" in sql
            assert args == (CID, USER, ORG, USER, False, None)
            self.timeline.append("authority")
            return deepcopy(self.row) if (USER, ORG) in self.allowed else None
        return await super().fetchrow(sql, *args)


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def api(monkeypatch):
    state = SimpleNamespace(requests=[], status=None, body=None, callback=None, failure=None, channel_name="Fixture", absent=False)
    async def respond(request):
        state.requests.append(request)
        assert request.url.host == "chat.stream-io-api.com" and request.url.scheme == "https"
        assert request.url.params["api_key"] == CREDENTIAL["api_key"]
        assert request.headers["Stream-Auth-Type"] == "jwt"
        token = request.headers["Authorization"]
        assert not token.startswith("Bearer ")
        head, claim, signature = token.split(".")
        decode = lambda part: json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        assert decode(head) == {"alg": "HS256", "typ": "JWT"} and decode(claim) == {"server": True}
        expected = base64.urlsafe_b64encode(hmac.new(CREDENTIAL["api_secret"].encode(), f"{head}.{claim}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        assert hmac.compare_digest(signature, expected)
        if state.callback:
            state.callback(request)
        if state.failure:
            raise state.failure(request)
        path, method = request.url.path, request.method
        status = 200
        row = channel(); row["name"] = state.channel_name
        if path == "/channeltypes":
            body = {"channel_types": {TYPE: {"name": TYPE, "permissions": [{"private": "omit-me"}]}}}
        elif path == "/channeltypes/" + TYPE:
            body = {"name": TYPE, "grants": {"admin": ["all"]}}
        elif path == "/users" and method == "GET":
            payload = json.loads(request.url.params["payload"])
            assert payload["presence"] is False
            ids = payload["filter_conditions"].get("id", {}).get("$in", ["alice"])
            body = {"users": [user(i, state.user_name if hasattr(state, "user_name") else "Alice") for i in ids]}
        elif path == "/users":
            payload = json.loads(request.content)
            assert set(payload) == {"users"} and set(payload["users"]) == {"alice"}
            assert set(payload["users"]["alice"]) == {"id", "name"}
            state.user_name = payload["users"]["alice"]["name"]
            body, status = {"users": {"alice": user(name=state.user_name)}}, 201
        elif path == "/channels":
            payload = json.loads(request.content)
            assert payload["filter_conditions"]["type"] == TYPE and payload["state"] is False
            assert payload["member_limit"] == payload["message_limit"] == 0
            body, status = {"channels": [{"channel": row, "messages": [message()]}]}, 201
        elif path.endswith("/query"):
            payload = json.loads(request.content)
            assert payload["data"] == {"created_by_id": "alice", "members": [{"user_id": "alice"}], "name": "Fixture"}
            assert payload["state"] is False and payload["messages"]["limit"] == payload["watchers"]["limit"] == 0
            state.absent = False
            body, status = {"channel": row}, 201
        elif path == f"/channels/{TYPE}/{CHANNEL}" and method == "PATCH":
            payload = json.loads(request.content)
            assert payload == {"set": {"name": "Renamed"}}
            state.channel_name = "Renamed"; row["name"] = state.channel_name
            body = {"channel": row}
        elif path == f"/channels/{TYPE}/{CHANNEL}":
            if state.absent:
                return httpx.Response(404, json={"message": "No channel"})
            assert request.url.params["watchers_limit"] == "0"
            body = {"channel": row, "members": [{"user": user()}], "messages": [message()] if int(request.url.params["messages_limit"]) else []}
        elif path == "/messages/" + MESSAGE:
            body = {"message": message()}
        elif path == "/messages/history":
            payload = json.loads(request.content)
            assert payload["filter"] == {"message_id": {"$eq": MESSAGE}}
            body, status = {"message_history": [{"message_id": MESSAGE, "message_updated_at": "2026-10-06T00:00:00Z",
                "message_updated_by_id": "alice", "is_deleted": False, "text": "PRIVATE_OLD_TEXT", "attachments": []}]}, 201
        else:
            raise AssertionError("Unexpected fixture route")
        return httpx.Response(state.status or status, json=state.body if state.body is not None else {**DURATION, **body})
    original = httpx.AsyncClient
    def transport(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", transport)
    state.transport = transport
    return state


@pytest.fixture
def stored(monkeypatch):
    storage = Storage()
    crypto = MagicMock(); crypto.decrypt_credential.side_effect = lambda _: deepcopy(CREDENTIAL)
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.credentials.get_encryption", lambda: crypto)
    monkeypatch.setattr("wss.handlers.workflow_handler.get_user_org_context", AsyncMock(return_value=ORG))
    return storage, crypto


async def run(op, arguments=None, **kwargs):
    return await run_node_operation(node_type=NODE, operation=op, arguments=arguments or {}, user_id=USER,
                                    organization_id=ORG, **kwargs)


OPERATIONS = [
    ("list_users", {}, "GET", "/users"),
    ("get_user", {"user_id": "alice"}, "GET", "/users"),
    ("upsert_user", {"user_id": "alice", "name": "Alice Changed"}, "POST", "/users"),
    ("list_channel_types", {}, "GET", "/channeltypes"),
    ("get_channel_type", {"channel_type": TYPE}, "GET", "/channeltypes/" + TYPE),
    ("list_channels", {"channel_type": TYPE}, "POST", "/channels"),
    ("get_channel", {"channel_type": TYPE, "channel_id": CHANNEL}, "GET", f"/channels/{TYPE}/{CHANNEL}"),
    ("list_channel_members", {"channel_type": TYPE, "channel_id": CHANNEL}, "GET", f"/channels/{TYPE}/{CHANNEL}"),
    ("get_or_create_private_channel", {"channel_type": TYPE, "channel_id": CHANNEL, "created_by_id": "alice",
        "member_user_ids": ["alice"], "name": "Fixture", "member_restricted_type_confirmed": True}, "GET", f"/channels/{TYPE}/{CHANNEL}"),
    ("rename_channel", {"channel_type": TYPE, "channel_id": CHANNEL, "name": "Renamed"}, "PATCH", f"/channels/{TYPE}/{CHANNEL}"),
    ("list_messages", {"channel_type": TYPE, "channel_id": CHANNEL}, "GET", f"/channels/{TYPE}/{CHANNEL}"),
    ("get_message", {"channel_type": TYPE, "channel_id": CHANNEL, "message_id": MESSAGE}, "GET", "/messages/" + MESSAGE),
    ("list_message_history", {"channel_type": TYPE, "channel_id": CHANNEL, "message_id": MESSAGE}, "POST", "/messages/history"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,method,path", OPERATIONS)
async def test_real_factory_dispatcher_catalog_and_wire_projection(api, op, args, method, path):
    assert NODE_REGISTRY[NODE] is StreamChatNode
    result = await run(op, args, credential_data=CREDENTIAL)
    assert result["status"] == "success" and result["identity_verified"] is False
    assert any(r.method == method and r.url.path == path for r in api.requests)
    for forbidden in ("PRIVATE_", "omit-me", "permissions", "attachments", CREDENTIAL["api_key"], CREDENTIAL["api_secret"], "Authorization"):
        assert forbidden not in repr(result)
    if op == "get_or_create_private_channel":
        assert result["data"]["creation_request_sent"] is False
        assert all(r.method == "GET" for r in api.requests)


@pytest.mark.asyncio
async def test_typed_config_credentials_reach_provider_without_raw_node_data(api):
    config = StreamChatNodeConfig.model_validate({
        "config": {"operation": "list_channel_types"}, "credentials": CREDENTIAL,
    })
    node = StreamChatNode(node_id="typed", node_type=NODE, node_data={}, config=config, sio=None)
    result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["items"] == [{"id": TYPE, "name": TYPE}]
    assert [(r.method, r.url.path) for r in api.requests] == [("GET", "/channeltypes")]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, {**CREDENTIAL, "credential_type": "unrelated_provider"}])
async def test_present_invalid_raw_credentials_cannot_use_valid_typed_credentials(api, raw):
    config = StreamChatNodeConfig.model_validate({
        "config": {"operation": "list_channel_types"}, "credentials": CREDENTIAL,
    })
    node = StreamChatNode(node_id="typed", node_type=NODE, node_data={"credentials": raw}, config=config, sio=None)
    with pytest.raises(ValueError, match="Stream Chat Server Key"):
        await node.execute({})
    assert api.requests == []


@pytest.mark.asyncio
async def test_missing_read_does_not_create_and_missing_explicit_create_reads_back(api):
    api.absent = True
    with pytest.raises(ValueError, match="HTTP 404"):
        await run("get_channel", {"channel_type": TYPE, "channel_id": CHANNEL}, credential_data=CREDENTIAL)
    assert [r.method for r in api.requests] == ["GET"]
    api.requests.clear()
    args = dict(OPERATIONS[8][1])
    result = await run("get_or_create_private_channel", args, credential_data=CREDENTIAL)
    assert result["data"]["creation_request_sent"] is True
    assert result["data"]["readback_confirmed"] is True
    assert [r.method for r in api.requests] == ["GET", "GET", "GET", "POST", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["credential_type", "token_version", "revoked_at", "owner_id", "updated_at", "acl"])
async def test_actual_current_row_denial_or_change_stops_network_or_output(api, stored, changed):
    storage, crypto = stored
    if changed == "credential_type": storage.row[changed] = "other_key"
    elif changed == "token_version": storage.row[changed] = 0
    elif changed == "revoked_at": storage.row[changed] = storage.row["updated_at"]
    elif changed == "acl": storage.allowed.clear()
    elif changed == "owner_id": api.callback = lambda _: storage.row.update(owner_id=USER)
    else: api.callback = lambda _: storage.row.update(updated_at=storage.row["updated_at"].replace(day=6))
    with pytest.raises(ValueError):
        await run("list_channel_types", credential_id=CID, pool=storage)
    if changed in ("owner_id", "updated_at"):
        assert len(api.requests) == 1
    else:
        assert api.requests == []
        assert crypto.decrypt_credential.call_count <= 1


@pytest.mark.asyncio
async def test_actual_saved_row_picker_keeps_parent_and_missing_parent_refuses(api, stored):
    storage, _ = stored
    result = await run_node_lookup(node_type=NODE, field_name="message_id", credential_id=CID,
        user_id=USER, organization_id=ORG, pool=storage, context={"channel_type": TYPE, "channel_id": CHANNEL})
    assert result["options"] == [{"value": MESSAGE, "label": MESSAGE}]
    assert "authority" in storage.timeline
    api.requests.clear()
    with pytest.raises(ValueError):
        await run_node_lookup(node_type=NODE, field_name="message_id", credential_id=CID,
            user_id=USER, organization_id=ORG, pool=storage, context={"channel_type": TYPE})
    assert api.requests == []


@pytest.mark.asyncio
async def test_actual_connect_empty_reachability_and_malformed_is_unknown(api, monkeypatch):
    from nodes.core.credential_connect import validate_for_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr("nodes.core.credential_connect._collect_evidence", collect_evidence)
    api.body = {**DURATION, "channel_types": {}}
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDENTIAL, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert verdict.evidence.account_label is None and verdict.evidence.samples == []
    api.body = {"channel_types": {}}
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=CREDENTIAL, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(401, False), (403, False), (429, None), (503, None)])
async def test_actual_registered_socket_current_context_tristate(api, monkeypatch, status, valid):
    state = context_native.__wrapped__(monkeypatch)
    state.blob = deepcopy(CREDENTIAL)
    state.storage = Storage()
    state.handler.get_pool = AsyncMock(return_value=state.storage)
    monkeypatch.setattr(httpx, "AsyncClient", api.transport)
    api.status = status
    result = await _validate(state, node_type=NODE)
    assert result["valid"] is valid
    assert result.get("identity_verified", False) is False


@pytest.mark.asyncio
async def test_actual_native_admission_pending_and_rejected_before_provider(api, stored, monkeypatch):
    storage, _ = stored
    storage.row["approval_operations"] = [NODE + ".list_channel_types"]
    monkeypatch.setattr("wss.sender.send_event", AsyncMock())
    pending = await run("list_channel_types", credential_id=CID, pool=storage)
    assert pending["status"] == "pending_approval" and api.requests == []
    next(iter(storage.grants.values()))["status"] = "rejected"
    rejected = await run("list_channel_types", credential_id=CID, pool=storage)
    assert rejected["status"] != "success" and api.requests == []


@pytest.mark.asyncio
async def test_parent_mismatch_and_history_cursor_are_fail_closed(api):
    api.body = {**DURATION, "message": {**message(), "cid": "messaging:another"}}
    with pytest.raises(ValueError, match="selected channel"):
        await run("get_message", OPERATIONS[11][1], credential_data=CREDENTIAL)
    client = _Client(CREDENTIAL)
    scope = ["list_message_history", TYPE, CHANNEL, MESSAGE, 25]
    token = client.cursor("opaque-provider-next", scope)
    api.requests.clear()
    with pytest.raises(ValueError, match="original scope"):
        await run("list_message_history", {**OPERATIONS[12][1], "limit": 26, "page_token": token}, credential_data=CREDENTIAL)
    assert api.requests == []
    assert CREDENTIAL["api_key"] not in token


@pytest.mark.asyncio
async def test_malformed_nested_scalar_and_echoed_secret_are_not_exposed(api):
    api.body = {**DURATION, "users": [{"id": "alice", "name": {"secret": CREDENTIAL["api_secret"]}}]}
    with pytest.raises(ValueError, match="invalid metadata") as caught:
        await run("list_users", credential_data=CREDENTIAL)
    assert CREDENTIAL["api_secret"] not in str(caught.value)
    api.body = {**DURATION, "users": [user(name=CREDENTIAL["api_secret"])]}
    assert (await run("list_users", credential_data=CREDENTIAL))["data"]["items"][0]["name"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_write_timeout_is_fixed_private_and_never_replayed(api):
    api.failure = lambda request: httpx.ReadTimeout(str(request.url) + request.headers["Authorization"], request=request)
    with pytest.raises(ValueError, match="No automatic replay") as caught:
        await run("upsert_user", {"user_id": "alice", "name": "Changed"}, credential_data=CREDENTIAL)
    assert len(api.requests) == 1 and caught.value.__cause__ is None
    assert CREDENTIAL["api_key"] not in str(caught.value)


@pytest.mark.asyncio
async def test_request_logging_is_private_and_unrelated_concurrent_logging_survives(api, caplog):
    entered, release = asyncio.Event(), asyncio.Event()
    transport = logging.getLogger("httpx")
    transport.addFilter(_PRIVACY)
    caplog.set_level(logging.INFO, logger="httpx")
    async def private():
        token = _PRIVATE_REQUEST.set(True)
        try:
            transport.info("private api_key=%s", CREDENTIAL["api_key"])
            entered.set(); await release.wait()
        finally:
            _PRIVATE_REQUEST.reset(token)
    async def ordinary():
        await entered.wait()
        transport.info("unrelated diagnostic survives")
        release.set()
    await asyncio.gather(private(), ordinary())
    assert CREDENTIAL["api_key"] not in caplog.text and "unrelated diagnostic survives" in caplog.text
    await run("list_users", credential_data=CREDENTIAL)
    assert CREDENTIAL["api_key"] not in caplog.text


@pytest.mark.asyncio
async def test_actual_current_httpx_trace_adapter_hides_query_and_jwt(api, monkeypatch):
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from utils.outbound_trace_privacy import OutboundTraceProvider
    from tests.test_outbound_trace_privacy import RecordingSampler, StartObserver
    sampler, observer, exporter = RecordingSampler(), StartObserver(), InMemorySpanExporter()
    provider = TracerProvider(sampler=sampler)
    provider.add_span_processor(observer); provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = HTTPXClientInstrumentor()
    monkeypatch.setenv("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_REQUEST", ".*")
    def traced_transport(**kwargs):
        client = api.transport(**kwargs)
        instrumentor.instrument_client(client, tracer_provider=OutboundTraceProvider(provider))
        return client
    monkeypatch.setattr(httpx, "AsyncClient", traced_transport)
    try:
        await run("list_users", credential_data=CREDENTIAL)
        spans = exporter.get_finished_spans()
        assert spans
        serialized = repr(sampler.observed) + repr(observer.observed) + repr([s.to_json() for s in spans])
        assert CREDENTIAL["api_key"] not in serialized and CREDENTIAL["api_secret"] not in serialized
        assert api.requests[0].headers["Authorization"] not in serialized
        assert "api_key=" not in serialized and "payload=" not in serialized
    finally:
        provider.shutdown()


@pytest.mark.parametrize("data", [
    {**CREDENTIAL, "credential_type": "other_provider"},
    {**CREDENTIAL, "api_secret": "https://wrong.invalid/key"},
    {**CREDENTIAL, "api_key": "your-api-key"},
    {**CREDENTIAL, "api_secret": "Bearer fixture"},
])
def test_strict_manual_shape(data):
    with pytest.raises(ValidationError):
        StreamChatServerCredential.model_validate(data)


def test_operation_catalog_is_closed_and_children_declare_real_parent_chain():
    from coder.workflow.operation_catalog import get_operations_for_node_type
    operations = {op.name for op in get_operations_for_node_type(NODE)}
    assert operations == {row[0] for row in OPERATIONS}
    schema = StreamChatNodeConfig.model_json_schema()
    defs = schema["$defs"]
    assert defs["GetMessageConfig"]["properties"]["message_id"]["x-dynamic-options"]["depends_on"] == "channel_id"
    assert defs["GetMessageConfig"]["properties"]["channel_id"]["x-dynamic-options"]["depends_on"] == "channel_type"
    assert all("x-creator" not in json.dumps(v) for v in defs.values())


@pytest.mark.asyncio
async def test_original_wrong_family_factory_blob_never_reaches_provider(api):
    with pytest.raises(ValueError, match="Stream Chat Server Key"):
        await run("list_channel_types", credential_data={**CREDENTIAL, "credential_type": "unrelated_provider"})
    assert api.requests == []


@pytest.mark.asyncio
async def test_existing_different_membership_refuses_without_mutation(api):
    api.body = {**DURATION, "channel": {**channel(), "member_count": 2}, "members": [{"user": user()}]}
    # Apply the mismatched envelope only to channel reads, keeping actual type/user preflights.
    original = api.callback
    def channel_only(request):
        if request.url.path.startswith("/channels/"):
            api.body = {**DURATION, "channel": {**channel(), "member_count": 2}, "members": [{"user": user()}]}
        else:
            api.body = None
        if original:
            original(request)
    api.callback = channel_only
    with pytest.raises(ValueError, match="complete membership differs"):
        await run("get_or_create_private_channel", OPERATIONS[8][1], credential_data=CREDENTIAL)
    assert all(r.method == "GET" for r in api.requests)

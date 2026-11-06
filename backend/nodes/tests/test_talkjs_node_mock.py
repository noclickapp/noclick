"""Prepared UNRUN native/handler/current-row fixtures; synthetic app data only."""
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import jwt
import pytest
from nodes import talkjs_node as tn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup

CREDS = {"credential_type": tn.FAMILIES[0], "app_id": "app42", "server_secret": "sk_test_synthetic+/=private-key-long-enough"}
STAMP = datetime(2026, 10, 6, tzinfo=timezone.utc)
USER = {"id": "alice", "createdAt": 1700000000000, "name": "Private name", "role": None, "locale": "en-US", "email": ["private@example.test"], "phone": ["private"], "photoUrl": "private", "pushTokens": {"private": True}, "custom": {"private": "value"}}
CONV = {"id": "conv42", "createdAt": 1700000000000, "participants": {"alice": {"access": "ReadWrite", "notify": True, "joinedAt": 1700000000000, "readUntil": 1700000000000, "isUnread": True}}, "subject": "Private subject", "lastMessage": {"text": "private"}, "welcomeMessages": ["private"], "custom": {"private": "value"}, "everyoneReadUntil": 1700000000000}
MSG = {"id": "msg42", "conversationId": "conv42", "senderId": "alice", "type": "UserMessage", "origin": "rest", "createdAt": 1700000000000, "editedAt": None, "text": "Private message", "attachment": {"url": "private"}, "location": [1, 2], "content": [{"private": True}], "readBy": ["private"], "reactions": {"private": {}}, "custom": {"private": "value"}}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

class Response:
    def __init__(self, payload, *, status=200, raw=None, content_type="application/json"):
        self.status_code, self.headers = status, {"content-type": content_type}
        self.payload, self.raw = payload, raw
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw if self.raw is not None else json.dumps(self.payload).encode()

@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            logging.getLogger("httpx").info("private %s", kwargs["headers"]["Authorization"])
            logging.getLogger("httpcore.http2").debug("private %s", kwargs)
            item = responses.pop(0)
            return item if isinstance(item, Response) else Response(item)
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(tn, "guarded_async_client", client)
    return SimpleNamespace(calls=calls, responses=responses)

async def run(op, args=None, **context):
    return await run_node_operation(node_type=tn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=CREDS, user_id="actor", **context)

def test_actual_factory_family_numeric_forms_and_closed_operations():
    node = NodeFactory.create_node(node_id="native", node_type=tn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "list_users", "limit": "20"}, "credentials": CREDS})
    assert node.config.config.limit == 20
    assert len(tn.TalkJSNode.get_config_schema()["properties"]["config"]["discriminator"]["mapping"]) == 16
    for family in (None, "http_bearer", "talkjs_public_app_id"):
        bad = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert tn.TalkJSNode.validate_config(bad)["valid"] is False
        with pytest.raises(ValueError, match="family"): tn.TalkJSNode.parse_config(bad)
    for config in ({"operation": "arbitrary_request"}, {"operation": "test_connection", "url": "https://evil.test"}, {"operation": "list_conversations", "limit": 31}, {"operation": "list_users", "limit": True}, {"operation": "get_user", "user_id": "../other"}, {"operation": "update_conversation_metadata", "conversation_id": "conv42"}, {"operation": "update_message", "conversation_id": "conv42", "message_id": "msg42", "metadata_mode": "merge", "custom_metadata_json": '{"x":NaN}'}):
        with pytest.raises(ValueError): tn.TalkJSNode.parse_config({"config": config, "credentials": CREDS})

@pytest.mark.asyncio
async def test_exact_per_request_admin_jwt_wire_privacy_and_closed_projection(wire, caplog):
    wire.responses.extend([{"data": [USER]}, USER])
    with caplog.at_level(logging.DEBUG):
        result = await run("test_connection")
        await run("get_user", {"user_id": "alice"})
    tokens = [c["headers"]["Authorization"].removeprefix("Bearer ") for c in wire.calls]
    assert len(set(tokens)) == 2
    for token in tokens:
        claims = jwt.decode(token, CREDS["server_secret"], algorithms=["HS256"], issuer="app42")
        assert claims["tokenType"] == "admin" and "sub" not in claims and claims["exp"] - claims["iat"] == 30
        assert jwt.get_unverified_header(token)["alg"] == "HS256"
        assert token not in caplog.text and token not in json.dumps(result)
    call = wire.calls[0]
    assert call["url"] == "https://api.talkjs.com/v1/app42/users" and call["params"] == {"limit": 1}
    assert call["headers"]["TalkJS-REST-Version"] == "2024-01-01"
    assert CREDS["server_secret"] not in caplog.text and "private@example.test" not in json.dumps(result)
    assert result["data"]["account_identity_verified"] is False and result["data"]["protected_read_completed"] is True
    assert result["data"]["results"] == [{"id": "alice", "createdAt": 1700000000000, "role": None, "locale": "en-US"}]
    assert tn._PRIVATE_REQUEST.get() is False
    logging.getLogger("httpx").warning("unrelated outside private context")
    assert "unrelated outside private context" in caplog.text


@pytest.mark.asyncio
async def test_current_parent_witnesses_history_message_and_participation(wire):
    wire.responses.extend([USER, {"data": [CONV]}, CONV, MSG, CONV, USER, {"id": "alice", "access": "ReadWrite", "notify": "MentionsOnly", "joinedAt": 1700000000000, "readUntil": 1700000000000}])
    history = await run("list_user_conversations", {"user_id": "alice"})
    assert wire.calls[1]["params"] == {"limit": 20, "orderBy": "createdAt", "orderDirection": "DESC"}
    assert history["data"]["collection_exhausted"] is None and history["data"]["next_starting_after"] == "conv42"
    result = await run("get_message", {"conversation_id": "conv42", "message_id": "msg42"})
    assert result["data"]["conversationId"] == "conv42" and "text" not in result["data"]
    participation = await run("get_participation", {"conversation_id": "conv42", "user_id": "alice"})
    assert participation["data"]["notify"] == "MentionsOnly" and "readUntil" not in participation["data"]
    wire.responses.extend([CONV, {**MSG, "conversationId": "other"}])
    with pytest.raises(tn.TalkJSAPIError, match="another conversation"):
        await run("get_message", {"conversation_id": "conv42", "message_id": "msg42"})

@pytest.mark.asyncio
async def test_real_dispatcher_metadata_omission_clear_and_write_receipts(wire):
    wire.responses.extend([USER, {}, CONV, {}, CONV, MSG, {}, CONV, {}])
    await run("sync_user", {"user_id": "alice", "name": "Name", "confirm_changes": True})
    assert wire.calls[1]["json"] == {"name": "Name"}
    updated = await run("update_conversation_metadata", {"conversation_id": "conv42", "subject_mode": "clear", "metadata_mode": "merge", "custom_metadata_json": '{"remove":null,"keep":"v"}', "confirm_changes": True})
    assert wire.calls[3]["json"] == {"subject": None, "custom": {"remove": None, "keep": "v"}} and "participants" not in wire.calls[3]["json"]
    assert updated["data"]["acknowledged"] is True and updated["data"]["independent_readback_verified"] is False
    await run("update_message", {"conversation_id": "conv42", "message_id": "msg42", "metadata_mode": "clear", "mark_edited": True, "confirm_changes": True})
    assert wire.calls[6]["json"] == {"custom": None, "markEdited": True}
    deleted = await run("delete_conversation", {"conversation_id": "conv42", "confirm_changes": True})
    assert wire.calls[-1]["method"] == "DELETE" and deleted["data"]["absence_verified"] is False and deleted["data"]["irreversible"] is True

@pytest.mark.asyncio
async def test_explicit_conversation_creation_and_single_message_payload(wire):
    wire.responses.extend([Response({}, status=404), USER, {}, CONV, USER, [{"id": "new_message"}]])
    created = await run("create_conversation", {"conversation_id": "newconv", "participant_ids": ["alice"], "confirm_changes": True})
    assert wire.calls[2]["json"] == {"participants": ["alice"]} and created["data"]["atomic_creation_verified"] is False
    sent = await run("send_message", {"conversation_id": "conv42", "sender_id": "alice", "text": "Explicit synthetic message", "idempotency_key": "explicit-key", "confirm_changes": True})
    assert wire.calls[-1]["json"] == [{"text": "Explicit synthetic message", "sender": "alice", "type": "UserMessage", "idempotencyKey": "explicit-key"}]
    assert sent["data"]["message_id"] == "new_message" and sent["data"]["delivery_verified"] is False and sent["data"]["idempotency_window_hours"] == 24
    before = len(wire.calls)
    with pytest.raises(ValueError, match="Confirm"):
        await run("send_message", {"conversation_id": "conv42", "sender_id": "alice", "text": "No send", "idempotency_key": "no-send"})
    assert len(wire.calls) == before
    wire.responses.append(CONV)
    with pytest.raises(ValueError, match="already exists"):
        await run("create_conversation", {"conversation_id": "conv42", "participant_ids": ["alice"], "confirm_changes": True})

@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["http401", "http403", "http429", "http201", "http204", "html", "nan", "overflow", "deep", "wrong_id", "wrong_shape"])
async def test_safe_errors_never_replay_or_echo_tokens(wire, case):
    response = Response(USER)
    if case.startswith("http"): response.status_code = int(case[4:]); response.payload = {"secret": CREDS["server_secret"]}
    if case == "html": response.headers["content-type"] = "text/html"
    if case == "nan": response.raw = b'{"id":"alice","createdAt":NaN}'
    if case == "overflow": response.raw = b'{"id":"alice","createdAt":1e309}'
    if case == "deep": response.raw = b'['*40+b'0'+b']'*40
    if case == "wrong_id": response.payload = {**USER, "id": "bob"}
    if case == "wrong_shape": response.payload = {}
    wire.responses.append(response)
    with pytest.raises(tn.TalkJSAPIError) as error: await run("get_user", {"user_id": "alice"})
    assert error.value.authority_rejected is (case in ("http401", "http403")) and CREDS["server_secret"] not in str(error.value)
    assert len(wire.calls) == 1 and tn._PRIVATE_REQUEST.get() is False

@pytest.mark.asyncio
async def test_documented_http_only_success_opaque_metadata_and_response_bound(monkeypatch, wire):
    wire.responses.append({**USER, "status": {"opaque": True}, "errors": ["future metadata"], "name": CREDS["server_secret"]})
    result = await run("get_user", {"user_id": "alice", "include_names": True})
    assert result["data"]["name"] == "[redacted]"
    wire.responses.append(USER); monkeypatch.setattr(tn, "MAX_BYTES", 10)
    with pytest.raises(tn.TalkJSAPIError, match="byte bound"): await run("get_user", {"user_id": "alice"})
    assert len(wire.calls) == 2

@pytest.mark.asyncio
async def test_picker_current_parent_continuation_and_no_false_exhaustion(wire):
    wire.responses.append({"data": [USER]})
    first = await tn.TalkJSNode.load_field_options("user_id", CREDS, context={"_user_id": "actor"})
    assert first["options"] == [{"value": "alice", "label": "alice"}] and first["next_page_token"]
    before = len(wire.calls)
    with pytest.raises(ValueError, match="another current"):
        await tn.TalkJSNode.load_field_options("conversation_id", CREDS, context={"_user_id": "actor"}, page_token=first["next_page_token"])
    assert len(wire.calls) == before
    wire.responses.extend([USER, {"data": []}])
    last = await tn.TalkJSNode.load_field_options("user_id", CREDS, context={"_user_id": "actor"}, page_token=first["next_page_token"])
    assert last["options"] == [] and last["next_page_token"] is None
    wire.responses.append(CONV)
    sender = await tn.TalkJSNode.load_field_options("sender_id", CREDS, context={"_user_id": "actor", "conversation_id": "conv42"})
    assert sender["options"] == [{"value": "alice", "label": "alice"}]

@pytest.mark.asyncio
async def test_current_family_revocation_owner_grant_and_saved_picker(monkeypatch, wire):
    from utils import credentials
    from wss.handlers import workflow_handler
    from contextlib import asynccontextmanager
    row = {"credential_type": tn.FAMILIES[0], "revoked_at": None, "credential": "sealed"}
    current_row = row
    principals = []
    class Connection:
        async def fetchrow(self, sql, cid, principal, org):
            assert cid == "saved" and org == "org"
            principals.append(principal)
            return current_row if principal == "owner" else None
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()
    pool = Pool()
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value="org"))
    monkeypatch.setattr(credentials, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: (_ for _ in ()).throw(AssertionError("No decrypt"))))
    for current_row in (None, {**row, "revoked_at": STAMP}):
        with pytest.raises(ValueError):
            await tn._current_data(CREDS, credential_id="saved", user_id="owner", pool=pool, organization_id="org")
    assert wire.calls == []
    current_row = row
    current = {**CREDS, "server_secret": "sk_test_current-secret-long-enough-synthetic", "credential_type": "stale"}
    monkeypatch.setattr(credentials, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: dict(current)))
    current_row = {**row, "credential_type": "http_bearer"}
    with pytest.raises(ValueError, match="family"):
        await tn._current_data(CREDS, credential_id="saved", user_id="owner", pool=pool, organization_id="org")
    current_row = row
    monkeypatch.setattr(credentials, "get_workflow_owner_id", AsyncMock(return_value="owner"))
    allowed = AsyncMock(return_value=True); monkeypatch.setattr(credentials, "is_credential_authorized_for_workflow", allowed)
    monkeypatch.setattr(credentials, "credential_lender", AsyncMock(return_value=None))
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value=None))
    wire.responses.append({"data": [USER]})
    result = await run_node_lookup(node_type=tn.NODE_TYPE, field_name="user_id", credential_id="saved", user_id="actor", pool=pool, organization_id="org", workflow_id="flow", context={"_user_id": "forged", "_credential_id": "forged"})
    assert result["options"][0]["value"] == "alice" and "owner" in principals
    jwt.decode(wire.calls[-1]["headers"]["Authorization"][7:], current["server_secret"], algorithms=["HS256"], issuer="app42")
    allowed.return_value = False
    before = len(wire.calls)
    with pytest.raises(ValueError):
        await tn._current_data(CREDS, credential_id="saved", user_id="actor", pool=pool, organization_id="org", workflow_id="flow")
    assert len(wire.calls) == before


@pytest.mark.asyncio
async def test_post_connect_blob_alone_does_not_claim_current_access(wire):
    assert (await tn.TalkJSNode.validate_credential_access(CREDS))["valid"] is None
    assert wire.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"app_id": "another_app"}, {"server_secret": "sk_test_changed-secret-long-enough"}])
async def test_current_app_or_secret_change_stops_before_signing(monkeypatch, wire, change):
    current = tn._shape(CREDS)
    monkeypatch.setattr(tn, "_current_data", AsyncMock(side_effect=[current, {**current, **change}]))
    monkeypatch.setattr(tn.jwt, "encode", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No signing after authority change")))
    with pytest.raises(ValueError, match="changed"): await run("test_connection")
    assert wire.calls == []

@pytest.mark.asyncio
async def test_parent_cursor_and_send_access_refusals_do_not_write(wire):
    wire.responses.extend([CONV, {**MSG, "conversationId": "other"}])
    with pytest.raises(tn.TalkJSAPIError, match="another conversation"):
        await run("list_messages", {"conversation_id": "conv42", "starting_after": "msg42"})
    wire.responses.extend([{**CONV, "participants": {"alice": {"access": "Read", "notify": True}}}, USER])
    with pytest.raises(ValueError, match="ReadWrite"):
        await run("send_message", {"conversation_id": "conv42", "sender_id": "alice", "text": "No permission", "idempotency_key": "refused", "confirm_changes": True})
    assert all(c["method"] == "GET" for c in wire.calls)

@pytest.mark.asyncio
async def test_http200_empty_ack_shape_uncertainty_stops_without_replay(wire):
    wire.responses.extend([CONV, MSG, {"unexpected": True}])
    with pytest.raises(tn.TalkJSAPIError, match="may have applied"):
        await run("delete_message", {"conversation_id": "conv42", "message_id": "msg42", "confirm_changes": True})
    assert [c["method"] for c in wire.calls] == ["GET", "GET", "DELETE"]

@pytest.mark.asyncio
async def test_message_required_nullable_fields_and_picker_cap_are_honest(wire):
    wire.responses.extend([CONV, {k: v for k, v in MSG.items() if k != "editedAt"}])
    with pytest.raises(tn.TalkJSAPIError, match="response is unverified"):
        await run("get_message", {"conversation_id": "conv42", "message_id": "msg42"})
    for index in range(10):
        if index:
            wire.responses.append({**USER, "id": "u" + str(index - 1)})
        wire.responses.append({"data": [{**USER, "id": "u" + str(index)}]})
    with pytest.raises(tn.TalkJSAPIError, match="bounded search"):
        await tn.TalkJSNode.load_field_options("user_id", CREDS, context={"_user_id": "actor"}, search="unmatched")

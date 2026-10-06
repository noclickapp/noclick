"""Unrun native source fixtures. All transport/storage values are synthetic."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from nodes import nylas_node as native
from nodes.core.run_op import run_node_operation, run_node_lookup
from nodes.core.connection_evidence import collect_evidence
from nodes.core.credential_connect import validate_for_connect
from nodes.core.registry import NodeFactory
from repositories.credentials import credential_access_predicate

NODE = "automation-nylas"
USER = "00000000-0000-4000-8000-000000000001"
OWNER = "00000000-0000-4000-8000-000000000002"
CID = "00000000-0000-4000-8000-000000000042"
ORG = "00000000-0000-4000-8000-000000000003"
STAMP = datetime(2026, 10, 6, tzinfo=timezone.utc)
KEY = {"credential_type": "nylas_api_key", "api_key": "synthetic-Nylas-key-42", "grant_id": "grant-42", "region": "us"}
TOKEN = {"credential_type": "nylas_access_token", "access_token": "synthetic-Nylas-token-42", "grant_id": "grant-42", "region": "eu"}
GRANT = {"id": "grant-42", "provider": "microsoft", "grant_status": "valid", "blocked": False,
         "scope": ["Mail.ReadWrite", "Contacts.ReadWrite", "Calendars.ReadWrite"],
         "email": "private@example.test", "settings": {"secret": "not-output"}, "created_at": 1}


class _Scope:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_):
        return False


class _Pool:
    def __init__(self):
        self.row = {"credential_type": "nylas_api_key", "owner_id": OWNER, "credential": b"synthetic-ciphertext",
                    "revoked_at": None, "token_version": 7, "updated_at": STAMP, "approval_revision": 1}
        self.allowed = True
        self.calls = []

    def acquire(self):
        return _Scope(self)

    async def fetchrow(self, sql, *args):
        assert "FROM credentials c" in sql and credential_access_predicate() in sql
        assert str(args[0]) == CID and str(args[1]) == USER and args[2] == ORG
        if len(args) == 6:
            assert args[3:] == (USER, False, None)
            assert "workflow_authorized_credentials" in sql
        else:
            assert len(args) == 3
        self.calls.append((sql, args))
        return deepcopy(self.row) if self.allowed else None


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def state(monkeypatch):
    s = SimpleNamespace(requests=[], grant=deepcopy(GRANT), objects={}, counter=0, pool=_Pool(),
                        status=200, callback=None, page=None, blob=deepcopy(KEY), events=[], decrypts=0)
    for kind in ("message", "thread", "folder", "calendar", "event", "contact", "draft", "contact_group"):
        s.objects[(kind, kind + "-42")] = {"id": kind + "-42", "grant_id": "grant-42", "object": kind,
            "calendar_id": "calendar-42", "source": "address_book", "read_only": False,
            "is_owned_by_user": True, "is_primary": False, "name": "Private name", "subject": "Private subject",
            "body": "Private content", "emails": [{"email": "private@example.test"}],
            "participants": [{"email": "private@example.test"}], "metadata": {"url": "https://secret.example.test"},
            "when": {"start_time": 1, "end_time": 2, "private_url": "https://secret.example.test"}}

    async def provider(request):
        s.requests.append(request)
        if s.callback:
            response = s.callback(request)
            if response is not None:
                return response
        if s.status != 200:
            return httpx.Response(s.status, json={"error": {"message": KEY["api_key"], "provider_error": {"private": "body"}}})
        assert request.url.host in {"api.us.nylas.com", "api.eu.nylas.com"}
        assert request.headers["Authorization"] in {"Bearer " + KEY["api_key"], "Bearer " + TOKEN["access_token"]}
        assert request.headers["Accept"] == "application/json"
        parts = request.url.path.split("/")
        assert parts[1:3] == ["v3", "grants"] and parts[3] in {"grant-42", "me"}
        if len(parts) == 4:
            return httpx.Response(200, json={"data": s.grant})
        kind = "contact_group" if parts[4:] == ["contacts", "groups"] else parts[4].removesuffix("s")
        rid = parts[5] if len(parts) > 5 and kind != "contact_group" else None
        if request.method in {"POST", "PUT"}:
            import json
            body = json.loads(request.content)
            s.counter += 1
            rid = rid or kind + "-new-" + str(s.counter)
            obj = deepcopy(s.objects.get((kind, rid), {"id": rid, "grant_id": "grant-42", "object": kind, "source": "address_book"}))
            obj.update(body)
            s.objects[(kind, rid)] = obj
            return httpx.Response(200, json={"data": obj})
        if request.method == "DELETE":
            s.objects.pop((kind, rid), None)
            return httpx.Response(200, json={"request_id": "request-42"})
        if rid:
            obj = s.objects.get((kind, rid))
            return httpx.Response(200, json={"data": obj}) if obj else httpx.Response(404, json={"error": {"type": "not_found"}})
        if s.page is not None:
            return httpx.Response(200, json=s.page)
        return httpx.Response(200, json={"data": [v for (k, _), v in s.objects.items() if k == kind], "next_cursor": None})

    client = httpx.AsyncClient
    monkeypatch.setattr(native, "guarded_async_client", lambda **_: client(transport=httpx.MockTransport(provider)))
    crypto = MagicMock()
    def decrypt(_):
        s.decrypts += 1
        return deepcopy(s.blob)
    crypto.decrypt_credential.side_effect = decrypt
    monkeypatch.setattr("utils.encryption.get_encryption", lambda: crypto)
    monkeypatch.setattr("utils.credentials.get_encryption", lambda: crypto)
    monkeypatch.setattr("repositories.credential_approvals.CredentialApprovalRepo.admit", AsyncMock(return_value=None))
    return s


async def run(op, args=None, credential=KEY, stored=False, pool=None):
    return await run_node_operation(node_type=NODE, operation=op, arguments=args or {}, user_id=USER,
                                    credential_data=deepcopy(credential), credential_id=CID if stored else None,
                                    organization_id=ORG, pool=pool)


READ_CASES = [("get_grant", {})]
for _kind in ("message", "thread", "folder", "calendar", "contact", "draft"):
    READ_CASES.extend([("list_" + _kind + "s", {}), ("get_" + _kind, {_kind + "_id": _kind + "-42"})])
READ_CASES += [("list_events", {"calendar_id": "calendar-42", "start": 1, "end": 100}),
               ("get_event", {"calendar_id": "calendar-42", "event_id": "event-42"}), ("list_contact_groups", {})]
WRITE_CASES = []
for _kind, _body in [("draft", {"subject": "Unsent", "body": "Private draft", "to": [{"email": "fixture@example.test"}]}),
                     ("contact", {"given_name": "Fixture", "emails": [{"email": "fixture@example.test"}]}),
                     ("calendar", {"name": "Disposable fixture"})]:
    WRITE_CASES.extend([("create_" + _kind, _body), ("update_" + _kind, {_kind + "_id": _kind + "-42", **_body}),
                        ("delete_" + _kind, {_kind + "_id": _kind + "-42"})])


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args", READ_CASES + WRITE_CASES)
async def test_all_native_operations_use_real_dispatcher_and_private_projection(state, op, args):
    output = await run(op, args)
    assert state.requests
    assert "private@example.test" not in str(output) and "Private subject" not in str(output)
    assert KEY["api_key"] not in str(output) and "https://secret" not in str(output)
    if op.startswith(("create_", "update_")):
        assert output["readback_verified"] is True
        writes = [r for r in state.requests if r.method in {"POST", "PUT"}]
        assert len(writes) == 1 and state.requests[-1].method == "GET"
        assert not any("send" in r.url.path or "notetaker" in r.url.path for r in state.requests)
    if op.startswith("delete_"):
        assert output["absence_verified"] is True and output["permanent_erasure"] == "unverified"


@pytest.mark.asyncio
async def test_access_token_uses_me_and_verifies_explicit_grant(state):
    output = await run("get_grant", credential=TOKEN)
    assert output["data"]["id"] == "grant-42" and output["proves"] == "reachability"
    assert state.requests[0].url.host == "api.eu.nylas.com" and state.requests[0].url.path.endswith("/grants/me")
    state.grant["id"] = "another-grant"
    with pytest.raises(ValueError, match="configured grant"):
        await run("list_messages", credential=TOKEN)
    assert state.requests[-1].url.path.endswith("/grants/me")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"credential_type": "other_vendor"}, {"region": "https://localhost"},
                                     {"grant_id": "me"}, {"api_key": "Bearer secret"}, {"api_key": "https://secret.test"}])
async def test_original_raw_credential_shape_blocks_before_transport(state, change):
    with pytest.raises(ValueError):
        await run("get_grant", credential={**KEY, **change})
    assert state.requests == []


@pytest.mark.asyncio
async def test_factory_original_type_cannot_be_retagged(state):
    instance = NodeFactory.create_node(node_id="fixture", node_type=NODE, node_data={
        "config": {"operation": "get_grant"}, "credentials": {**KEY, "credential_type": "foreign"},
        "credentialIds": {"nylas_api_key": CID}}, user_id=USER)
    with pytest.raises(ValueError, match="Connect a Nylas"):
        await instance.execute({})
    assert state.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data": {}}, {"data": [{"id": "", "grant_id": "grant-42"}]},
                                      {"data": [{"id": "42", "grant_id": "foreign"}]},
                                      {"data": [], "next_cursor": "stuck"}, {"data": [], "next_cursor": 12}])
async def test_malformed_or_unbound_collections_never_become_results(state, payload):
    state.page = payload
    with pytest.raises(ValueError):
        await run("list_messages")


@pytest.mark.asyncio
async def test_parent_binding_and_actual_provider_scope_checks(state):
    state.objects[("event", "event-42")]["calendar_id"] = "another-calendar"
    with pytest.raises(ValueError, match="selected calendar"):
        await run("get_event", {"calendar_id": "calendar-42", "event_id": "event-42"})
    state.requests.clear()
    state.grant["scope"] = ["Mail.Read"]
    with pytest.raises(ValueError, match="provider permissions"):
        await run("create_draft", {"subject": "Unsent", "body": "Private"})
    assert [r.method for r in state.requests] == ["GET"]


@pytest.mark.asyncio
async def test_optin_content_is_bounded_and_scrubs_secret_and_unknown_nested_fields(state):
    obj = state.objects[("message", "message-42")]
    obj["body"] = KEY["api_key"] + " safe"
    obj["to"] = [{"email": "private@example.test", "name": {"secret": KEY["api_key"]}, "url": "https://secret"}]
    output = await run("get_message", {"message_id": "message-42", "include_content": True})
    assert output["data"]["body"] == "[redacted] safe"
    assert output["data"]["to"] == [{"email": "private@example.test"}]
    assert "metadata" not in output["data"] and KEY["api_key"] not in str(output)


@pytest.mark.asyncio
async def test_unknown_write_is_not_replayed_and_readback_mismatch_is_not_success(state):
    def timeout(request):
        if request.method == "POST":
            raise httpx.ReadTimeout(KEY["api_key"], request=request)
    state.callback = timeout
    with pytest.raises(ValueError, match="No request was replayed") as exc:
        await run("create_contact", {"given_name": "Fixture"})
    assert KEY["api_key"] not in str(exc.value) and len([r for r in state.requests if r.method == "POST"]) == 1
    state.callback = None
    def mismatch(request):
        if request.method == "GET" and "contact-new" in request.url.path:
            row = {"id": request.url.path.split("/")[-1], "grant_id": "grant-42", "given_name": "Different"}
            return httpx.Response(200, json={"data": row})
    state.callback = mismatch
    with pytest.raises(ValueError, match="not verified"):
        await run("create_contact", {"given_name": "Fixture"})


@pytest.mark.asyncio
async def test_delete_refuses_primary_or_shared_calendar_and_requires_actual_absence(state):
    state.objects[("calendar", "calendar-42")]["is_primary"] = True
    with pytest.raises(ValueError, match="nonprimary"):
        await run("delete_calendar", {"calendar_id": "calendar-42"})
    assert not any(r.method == "DELETE" for r in state.requests)
    state.objects[("calendar", "calendar-42")]["is_primary"] = False
    state.objects[("calendar", "calendar-42")]["is_owned_by_user"] = False
    with pytest.raises(ValueError, match="owned"):
        await run("update_calendar", {"calendar_id": "calendar-42", "name": "Change"})
    state.callback = lambda r: httpx.Response(200, json={"request_id": "ack"}) if r.method == "DELETE" else None
    with pytest.raises(ValueError, match="absence was not verified"):
        await run("delete_draft", {"draft_id": "draft-42"})


@pytest.mark.asyncio
async def test_unsaved_connect_actual_evidence_is_reachability_not_identity(state, monkeypatch):
    monkeypatch.setattr("nodes.core.credential_connect._collect_evidence", collect_evidence)
    verdict = await validate_for_connect("nylas_api_key", KEY, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert verdict.evidence.proves == "reachability" and not verdict.evidence.account_label
    assert "private@example.test" not in str(verdict.evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(200, True), (401, False), (403, False), (429, None), (500, None)])
async def test_actual_access_hook_preserves_unknown_semantics(state, status, valid):
    state.status = status
    result = await native.NylasNode.validate_credential_access(KEY)
    assert result["valid"] is valid and KEY["api_key"] not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"grant_status": None}, {"grant_status": {"private": KEY["api_key"]}},
                                     {"blocked": "false"}, {"provider": "undocumented"}, {"scope": [None]}])
async def test_malformed_grant_status_is_unknown_not_false_identity(state, change):
    state.grant.update(change)
    result = await native.NylasNode.validate_credential_access(KEY)
    assert result["valid"] is None and KEY["api_key"] not in str(result)


@pytest.mark.asyncio
async def test_stored_authority_uses_real_repository_and_refuses_midwrite_rebind(state):
    result = await run("get_grant", stored=True, pool=state.pool)
    assert result["data"]["id"] == "grant-42" and state.decrypts >= 3
    state.requests.clear()
    def rebind(request):
        if request.method == "POST":
            state.pool.row["token_version"] += 1
    state.callback = rebind
    with pytest.raises(ValueError, match="authority"):
        await run("create_draft", {"subject": "Unsent", "body": "Private"}, stored=True, pool=state.pool)
    assert len([r for r in state.requests if r.method == "POST"]) == 1
    assert not any("draft-new" in r.url.path for r in state.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"credential_type": "foreign"}, {"revoked_at": STAMP}, {"token_version": 0}])
async def test_current_raw_authority_refused_before_decrypt(state, change):
    state.pool.row.update(change)
    with pytest.raises(ValueError):
        await run("get_grant", stored=True, pool=state.pool)
    assert state.decrypts == 0 and state.requests == []


@pytest.mark.asyncio
async def test_real_lookup_loads_current_row_and_private_context(state):
    output = await run_node_lookup(node_type=NODE, field_name="contact_id", credential_id=CID,
                                   user_id=USER, pool=state.pool, organization_id=ORG, context={})
    assert output["options"][0]["value"] == "contact-42"
    assert output["options"][0]["label"] == "contact-42"
    assert "private@example.test" not in str(output)
    assert any(len(args) == 6 for _, args in state.pool.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_real_factory_admission_and_evidence_never_probe_parked_operation(state, monkeypatch, status):
    parked = {"id": CID, "status": status, "owner_id": OWNER, "new_request": False}
    monkeypatch.setattr("repositories.credential_approvals.CredentialApprovalRepo.admit", AsyncMock(return_value=parked))
    result = await run("get_grant", stored=True, pool=state.pool)
    assert result["executed"] is False and result["status"] in {"pending_approval", "rejected"}
    evidence = await collect_evidence(node_type=NODE, credential_id=CID,
                                      user_id=USER, pool=state.pool, organization_id=ORG)
    assert evidence.reachable is not True and state.requests == []


@pytest.mark.asyncio
async def test_picker_cursor_refuses_new_parent_credential_and_repeat(state):
    state.page = {"data": [state.objects[("event", "event-42")]], "next_cursor": "provider-cursor"}
    context = {"calendar_id": "calendar-42", "start": 1, "end": 100}
    first = await native.NylasNode.load_field_options("event_id", KEY, context)
    assert first["next_page_token"]
    state.requests.clear()
    with pytest.raises(ValueError, match="different credentials"):
        await native.NylasNode.load_field_options("event_id", KEY, {**context, "calendar_id": "calendar-other"}, first["next_page_token"])
    assert state.requests == []
    with pytest.raises(ValueError, match="repeated"):
        await native.NylasNode.load_field_options("event_id", KEY, context, first["next_page_token"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status,valid", [(200, True), (401, False), (429, None)])
async def test_real_socket_current_row_access_hook(state, monkeypatch, status, valid):
    from wss.handlers import credentials_handler, workflow_handler
    from wss.receiver.client_events import CredentialValidateAccessRequest
    state.status = status
    monkeypatch.setattr(workflow_handler, "get_user_org_context", AsyncMock(return_value=ORG))
    monkeypatch.setattr(credentials_handler, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda _: deepcopy(KEY)))
    async def capture(_sio, _sid, event):
        state.events.append(event.model_dump())
    monkeypatch.setattr(credentials_handler, "send_event", capture)
    sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    handler = credentials_handler.CredentialsHandler(sio)
    handler.get_pool = AsyncMock(return_value=state.pool)
    await handler.validate_access("fixture", CredentialValidateAccessRequest(request_id="fixture-42", credential_id=CID, node_type=NODE))
    assert state.events[-1]["data"]["valid"] is valid
    assert state.requests and all(r.url.path.endswith("/grants/grant-42") for r in state.requests)

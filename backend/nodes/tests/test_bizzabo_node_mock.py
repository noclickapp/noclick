"""UNRUN actual native discriminator, public wire, projections, parent witnesses and token cache."""
import asyncio
from copy import deepcopy
import json
import logging
import httpx
import pytest
from pydantic import TypeAdapter
from nodes import bizzabo_node as B

USER = "00000000-0000-4000-8000-000000000001"
AUTH = {"credential_type": B.FAMILY, "client_id": "synthetic-public-client", "client_secret": "synthetic-public-secret-123", "account_id": "42"}
TOKEN = "synthetic.jwt.token.only"


def args(op):
    cfg = {"operation": op}
    if op not in {"get_account", "list_events", "list_account_contacts"}: cfg["event_id"] = "71"
    if op in {"get_event_contact", "update_event_contact_metadata"}: cfg["contact_id"] = "81"
    for suffix, key, value in (("session", "session_id", "91"), ("speaker", "speaker_id", "92"), ("partner", "partner_id", "93")):
        if op == "get_event_" + suffix: cfg[key] = value
    if op == "get_event_registration_v2": cfg["registration_id"] = "94"
    if op in {"create_event_contact", "update_event_contact_metadata"}:
        cfg.update(first_name="Owned", last_name="Fixture", owned_disposable_confirmed=True)
        cfg["email" if op == "create_event_contact" else "expected_email"] = "fixture@example.invalid"
    return cfg


class World:
    def __init__(self):
        self.calls, self.after_request = [], None
        self.status, self.body_override, self.registration_page = 200, None, True
        self.auth_status, self.token_response = 200, {"access_token": TOKEN, "token_type": "Bearer", "expires_in": 86400}
        self.event = {"id": 71, "name": "Owned event", "status": "draft", "timezone": "UTC", "startDate": "2026-10-06T09:00:00Z", "endDate": "2026-10-06T10:00:00Z", "created": "2026-10-01", "modified": "2026-10-02", "coverPhotoUrl": "https://private-provider.invalid/media", "supportEmail": "private-provider@example.invalid"}
        self.contact = {"id": 81, "eventId": 71, "created": "2026-10-01", "modified": "2026-10-02", "properties": {"firstName": "Before", "lastName": "Fixture", "email": "fixture@example.invalid", "hasTickets": False, "ticketCount": 0, "ticketType": [], "address": "private-provider", "roles": ["private-provider"]}}
        self.session = {"id": 91, "title": "Session", "startDate": "2026-10-06", "startMinute": 60, "endMinute": 90, "attachments": [{"url": "https://private-provider.invalid"}]}
        self.speaker = {"id": 92, "firstname": "Speaker", "lastname": "Fixture", "title": "Presenter", "email": "private-provider@example.invalid", "picture": "https://private-provider.invalid"}
        self.partner = {"id": 93, "eventId": 71, "name": "Partner", "type": "sponsor", "website": "https://private-provider.invalid"}
        self.registration = {"id": 94, "eventId": 71, "ticketId": 95, "contactId": 81, "formSubmissionStatus": "registered", "validity": "valid", "ticketName": "Fixture type", "magicLink": "https://private-provider.invalid/signed", "billingDetails": {"secret": "private-provider"}, "price": 999}
        self.registration_type = {"id": 95, "eventId": 71, "name": "Fixture type", "price": 999}
        self.contact_list = {"id": 96, "name": "Owned list", "type": "manual", "created": "2026-10-01"}
        self.empty_events = False
        self.write_override = None
    def page(self, rows, query):
        return {"content": deepcopy(rows), "page": {"size": int(query.get("size", 50)), "number": int(query.get("page", 0)), "totalPages": 1, "totalElements": len(rows)}, "links": {"next": "https://private-provider.invalid"}}
    def handle(self, req):
        self.calls.append(req)
        assert req.headers["accept"] == "application/json"
        if req.url.host == "auth.bizzabo.com":
            assert req.method == "POST" and req.url.path == "/oauth/token" and not req.url.query and "authorization" not in req.headers
            assert json.loads(req.content) == {"client_id": AUTH["client_id"], "client_secret": AUTH["client_secret"], "account_id": 42, "audience": "https://api.bizzabo.com/api", "grant_type": "client_credentials"}
            raw, status = deepcopy(self.token_response), self.auth_status
        else:
            assert req.url.host == "api.bizzabo.com" and req.headers["authorization"] == "Bearer " + TOKEN
            status, query, path = self.status, dict(req.url.params), req.url.path
            if status != 200:
                return httpx.Response(status, json={"error": "private-provider"})
            if self.body_override is not None:
                return httpx.Response(200, content=self.body_override, headers={"content-type": "application/json"})
            if req.method != "GET":
                assert req.method in {"POST", "PUT"} and path in {"/v1/events/71/contacts", "/v1/events/71/contacts/81"}
                body = json.loads(req.content)
                assert set(body) == {"properties"} and set(body["properties"]) == {"email", "firstName", "lastName"}
                self.contact["properties"].update(body["properties"])
                raw = deepcopy(self.contact if self.write_override is None else self.write_override)
            elif path == "/v1/account": raw = {"id": 42, "name": "Owned account", "created": "2026-10-01"}
            elif path == "/v1/events": raw = self.page([] if self.empty_events else [self.event], query)
            elif path == "/v1/events/71": raw = deepcopy(self.event)
            elif path in {"/v1/contacts", "/v1/events/71/contacts"}: raw = self.page([self.contact], query)
            elif path == "/v1/events/71/contacts/81": raw = deepcopy(self.contact)
            elif path == "/v1/events/71/contacts/lists": raw = self.page([self.contact_list], query)
            elif path == "/v1/events/71/agenda/sessions": raw = self.page([self.session], query)
            elif path == "/v1/events/71/agenda/sessions/91": raw = deepcopy(self.session)
            elif path == "/v1/events/71/speakers": raw = self.page([self.speaker], query)
            elif path == "/v1/events/71/speakers/92": raw = deepcopy(self.speaker)
            elif path == "/v1/events/71/partners": raw = self.page([self.partner], query)
            elif path == "/v1/events/71/partners/93": raw = deepcopy(self.partner)
            elif path == "/v2/events/71/registrations":
                raw = self.page([self.registration], query)
                if not self.registration_page: raw.pop("page")
            elif path == "/v2/events/71/registrations/94": raw = deepcopy(self.registration)
            elif path == "/v2/events/71/registrationTypes": raw = self.page([self.registration_type], query)
            else: raise AssertionError("No unverified public or private route")
        if self.after_request: self.after_request(req)
        return httpx.Response(status, json=raw)


@pytest.fixture
def world(monkeypatch):
    value = World()
    def client(**kw):
        assert kw["follow_redirects"] is False and kw["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(value.handle), **kw)
    monkeypatch.setattr(B, "guarded_async_client", client)
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("op", B.OPS)
async def test_all_discriminators_schema_and_actual_factory_execute(op, world):
    from nodes.core.registry import NodeFactory
    assert TypeAdapter(B.BizzaboOperation).validate_python(args(op)).operation == op
    assert TypeAdapter(B.BizzaboOperation).json_schema()["discriminator"]["propertyName"] == "operation"
    node = NodeFactory.create_node(node_id="fixture", node_type=B.NODE_TYPE, node_data={"config": args(op), "credentials": deepcopy(AUTH)}, sio=None, sid=None, user_id=USER)
    result = await node.execute({})
    assert result["read_completed"] is True and result["identity_verified"] is True and result["account_id"] == "42"
    assert "private-provider" not in json.dumps(result) and "fixture@example.invalid" not in json.dumps(result)
    assert len([r for r in world.calls if r.url.host == "auth.bizzabo.com"]) == 1
    if op.endswith("_v2"):
        assert world.calls[-1].url.path.startswith("/v2/events/71/")
        assert not any("/v1/v2/" in r.url.path for r in world.calls)
    if op in {"create_event_contact", "update_event_contact_metadata"}:
        assert result["mutation_completed"] is True and result["name_readback_match"] is True
        assert world.calls[-1].method == "GET" and world.calls[-1].url.path == "/v1/events/71/contacts/81"


@pytest.mark.asyncio
async def test_runtime_only_cache_lock_expiry_and_no_blob_overlay(world, monkeypatch):
    clock = [100.0]; monkeypatch.setattr(B.time, "monotonic", lambda: clock[0])
    runtime = B.runtime(deepcopy(AUTH))
    await asyncio.gather(B.request(runtime, "GET", "/v1/account"), B.request(runtime, "GET", "/v1/account"))
    assert len([r for r in world.calls if r.url.host == "auth.bizzabo.com"]) == 1
    assert dict(runtime) == AUTH and TOKEN not in json.dumps(runtime) and runtime.token == TOKEN
    clock[0] = runtime.expires_at + 1
    await B.request(runtime, "GET", "/v1/account")
    assert len([r for r in world.calls if r.url.host == "auth.bizzabo.com"]) == 2 and dict(runtime) == AUTH


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("access_token", "short"), ("token_type", "bearer"), ("expires_in", True), ("expires_in", 0), ("expires_in", 86401), ("expires_in", None)])
async def test_malformed_grant_never_reaches_api_or_persists(world, field, value):
    world.token_response[field] = value
    data = B.runtime(deepcopy(AUTH))
    with pytest.raises(RuntimeError): await B.request(data, "GET", "/v1/account")
    assert len(world.calls) == 1 and world.calls[0].url.host == "auth.bizzabo.com"
    assert data.token is None and dict(data) == AUTH


@pytest.mark.asyncio
@pytest.mark.parametrize("status,kind", [(400, ValueError), (401, ValueError), (403, ValueError), (404, ValueError), (409, ValueError), (422, ValueError), (429, RuntimeError), (500, RuntimeError), (202, RuntimeError), (204, RuntimeError), (302, RuntimeError)])
async def test_status_privacy_and_no_retry(world, status, kind):
    world.status = status
    with pytest.raises(kind) as err: await B.records(AUTH, args("get_account"))
    assert "private-provider" not in str(err.value) and AUTH["client_secret"] not in str(err.value) and TOKEN not in str(err.value)
    assert len(world.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"null", b'"private-provider"', b'{"id":42,"id":42}', b'{"id":NaN}', b'{}', b'{"error":"private-provider"}'])
async def test_malformed_account_is_unverified(world, payload):
    world.body_override = payload
    with pytest.raises((ValueError, RuntimeError)): await B.records(AUTH, args("get_account"))


@pytest.mark.asyncio
async def test_v2_optional_page_is_unknown_and_page_binding_refuses():
    world = World()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(B, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(world.handle), **{k: v for k, v in kw.items() if k != "require_public"}))
    try:
        world.registration_page = False
        out = await B.records(AUTH, args("list_event_registrations_v2"))
        assert out["has_more"] is out["next_page_token"] is out["pagination"] is None
        for page in (None, {}, {"size": 50, "totalElements": 1, "totalPages": 1, "number": 1}):
            with pytest.raises(RuntimeError): B.collection({"content": [], "page": page}, {"page": 0, "size": 50})
    finally: monkey.undo()


@pytest.mark.asyncio
async def test_protected_account_mismatch_never_reaches_event_or_write(world):
    world.body_override = b'{"id":43,"name":"Different account"}'
    with pytest.raises(ValueError): await B.records(AUTH, args("create_event_contact"))
    assert [r.url.path for r in world.calls] == ["/oauth/token", "/v1/account"]


@pytest.mark.asyncio
async def test_empty_events_do_not_replace_protected_account_identity(world):
    world.empty_events = True
    result = await B.records(AUTH, args("list_events"))
    assert result["records"] == [] and result["identity_verified"] is True and result["account_id"] == "42"
    assert [r.url.path for r in world.calls] == ["/oauth/token", "/v1/account", "/v1/events"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["contact", "partner", "registration", "registration_type"])
async def test_foreign_event_response_refuses_current_child(world, kind):
    getattr(world, kind)["eventId"] = 72
    op = {"contact": "get_event_contact", "partner": "get_event_partner", "registration": "get_event_registration_v2", "registration_type": "list_event_registration_types_v2"}[kind]
    with pytest.raises(ValueError): await B.records(AUTH, args(op))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"email": "outside@example.invalid"}, {"hasTickets": True}, {"ticketCount": True}, {"ticketCount": 1}, {"ticketType": ["paid"]}, {"hasTickets": None}])
async def test_owned_update_requires_current_email_and_explicit_no_ticket_state(world, change):
    world.contact["properties"].update(change)
    with pytest.raises(ValueError): await B.records(AUTH, args("update_event_contact_metadata"))
    assert not any(r.method in {"POST", "PUT"} and r.url.host == "api.bizzabo.com" for r in world.calls)


@pytest.mark.asyncio
async def test_write_receipt_mismatch_has_no_automatic_retry(world):
    world.write_override = {**deepcopy(world.contact), "id": 82}
    with pytest.raises(RuntimeError): await B.records(AUTH, args("update_event_contact_metadata"))
    assert len([r for r in world.calls if r.method == "PUT"]) == 1


@pytest.mark.asyncio
async def test_closed_route_refusal_happens_before_auth_transport(world):
    for method, path, body in [("DELETE", "/v1/events/71/contacts/81", None), ("POST", "/v1/events", {}), ("PUT", "/v1/events/71/contacts/81", {"properties": {"role": "admin"}}), ("GET", "https://private.invalid", None), ("GET", "/v1/v2/events/71/registrations", None)]:
        with pytest.raises(ValueError): await B.request(AUTH, method, path, body=body)
    assert world.calls == []


@pytest.mark.asyncio
async def test_untrusted_transport_exception_never_bypasses_redaction(world):
    def failed(_): raise RuntimeError("Bizzabo " + AUTH["client_secret"] + " private-provider")
    world.after_request = failed
    with pytest.raises(RuntimeError) as err: await B.records(AUTH, args("get_account"))
    assert AUTH["client_secret"] not in str(err.value) and "private-provider" not in str(err.value)


@pytest.mark.asyncio
async def test_native_name_filter_encoded_once_and_parent_list_witness(world):
    await B.records(AUTH, {**args("list_event_contact_lists"), "list_name": "Owned & exact"})
    last = world.calls[-1]
    assert last.url.params["filter"] == "name=Owned & exact" and b"%2526" not in last.url.query
    await B.records(AUTH, {**args("list_event_contacts"), "contact_list_id": "96"})
    assert world.calls[-1].url.params["listId"] == "96"
    with pytest.raises(ValueError): await B.records(AUTH, {**args("list_event_contacts"), "contact_list_id": "97"})
    assert not any(r.url.params.get("listId") == "97" for r in world.calls)


@pytest.mark.parametrize("op,change", [("get_event", {"event_id": True}), ("get_event", {"event_id": "9223372036854775808"}), ("list_events", {"page": True}), ("list_events", {"size": 101}), ("create_event_contact", {"owned_disposable_confirmed": "true"}), ("create_event_contact", {"email": "invalid"})])
def test_raw_typed_arguments_refuse_before_transport(op, change, world):
    with pytest.raises(ValueError): TypeAdapter(B.BizzaboOperation).validate_python({**args(op), **change})
    assert world.calls == []


@pytest.mark.parametrize("change", [{"client_id": ""}, {"client_id": True}, {"client_secret": " "}, {"client_secret": "https://private-provider.invalid"}, {"client_secret": "YOUR_CLIENT_SECRET"}, {"account_id": "0"}, {"access_token": TOKEN}, {"credential_type": "slack_oauth"}])
def test_raw_credential_shapes_fail_safely_before_transport(change, world):
    with pytest.raises(ValueError) as err: B.credential({**AUTH, **change})
    assert AUTH["client_secret"] not in str(err.value) and "private-provider" not in str(err.value) and TOKEN not in str(err.value)
    assert world.calls == []


@pytest.mark.asyncio
async def test_http_library_auth_logs_are_suppressed(world, caplog):
    original = world.handle
    def logged(req):
        logging.getLogger("httpx").warning("private-provider " + AUTH["client_secret"])
        logging.getLogger("httpcore.http11").warning(TOKEN)
        return original(req)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(B, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(logged), **{k: v for k, v in kw.items() if k != "require_public"}))
    try:
        with caplog.at_level(logging.WARNING): await B.records(AUTH, args("get_account"))
        assert AUTH["client_secret"] not in caplog.text and TOKEN not in caplog.text and "private-provider" not in caplog.text
    finally: monkey.undo()

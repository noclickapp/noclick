"""Follow Up Boss node, credential, transport and documented webhook contracts."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import httpx
import pytest
from nodes import followupboss_node as fb
from nodes.core import credential_connect as cc
from nodes.core.registry import NodeFactory

TYPE, FAMILY = "automation-followupboss", "followupboss_api_key"
ID, USER = "00000000-0000-4000-8000-000000000042", "00000000-0000-4000-8000-000000000001"
CREDS = {"api_key": "synthetic-fub-key-canary", "system": "FixtureRegisteredSystem", "system_key": "synthetic-fub-system-canary", "expected_account_id": "7", "expected_user_id": "1"}
PERSON = {"id": 42, "name": "Fixture Person", "firstName": "Fixture", "lastName": "Person", "tags": ["Fixture"], "assignedUserId": 1, "emails": [{"value": "private@example.test"}], "phones": [{"value": "private-phone"}], "picture": {"small": "https://private.example.test"}}
NOTE = {"id": 43, "personId": 42, "isHtml": 0, "body": "private-note-body", "subject": "private-note-subject", "createdBy": "Private Actor"}
TASK = {"id": 44, "personId": 42, "assignedUserId": 1, "type": "Follow Up", "name": "Fixture Task", "isCompleted": 0, "person": PERSON}


@pytest.fixture
def ensure_native_db_pool():
    yield


def factory(op, args=None, credential=None):
    data = {"config": {"operation": op, **(args or {})}, "credentials": deepcopy(CREDS if credential is None else credential)}
    return NodeFactory.create_node(node_id="fub-fixture", node_type=TYPE, node_data=data, user_id=USER)


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(calls=[], override=None, account=7, user=1, address="8.8.8.8", create_status=201)
    fb._BACKOFF.clear()
    def respond(request):
        state.calls.append(request)
        assert request.url.host == "api.followupboss.com" and request.url.scheme == "https"
        assert request.headers["X-System"] == CREDS["system"] and request.headers["X-System-Key"] == CREDS["system_key"]
        assert "api_key" not in request.url.params and "access_token" not in request.url.params
        if state.override:
            result = state.override(request)
            if result is not None:
                return result
        path = request.url.path
        if path == "/v1/me":
            return httpx.Response(200, json={"id": state.user, "account": state.account, "name": "Fixture User", "role": "Agent", "apiKey": CREDS["api_key"], "calling": {"token": "private-token"}, "intercomSettings": {"user_hash": "private-hash"}})
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        kind = path.split("/")[2]
        row = deepcopy({"people": PERSON, "notes": NOTE, "tasks": TASK, "stages": {"id": 2, "name": "Lead", "peopleCount": 3, "isProtected": True}}[kind])
        if request.method == "PUT" and kind == "tasks":
            row.update(json.loads(request.content))
        if request.method in {"PUT", "POST"}:
            return httpx.Response(state.create_status if kind == "people" and request.method == "POST" else 200, json=row)
        if path.count("/") == 2:
            return httpx.Response(200, json={"_metadata": {"collection": kind, "offset": 0, "limit": int(request.url.params["limit"]), "total": 1}, kind: [row]})
        return httpx.Response(200, json=row)
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(fb, "_http_client", client)
    return state


CASES = [
    ("get_me", {}, "/me", "GET"), ("list_people", {}, "/people", "GET"),
    ("get_person", {"person_id": "42"}, "/people/42", "GET"),
    ("create_person", {"first_name": "Fixture", "last_name": "Person", "email": "fixture@example.test"}, "/people", "POST"),
    ("update_person", {"person_id": "42", "first_name": "Changed", "last_name": "Person"}, "/people/42", "PUT"),
    ("delete_person", {"person_id": "42"}, "/people/42", "DELETE"), ("list_stages", {}, "/stages", "GET"),
    ("get_note", {"person_id": "42", "note_id": "43"}, "/notes/43", "GET"),
    ("create_note", {"person_id": "42", "subject": "Fixture", "body": "Fixture note"}, "/notes", "POST"),
    ("update_note", {"person_id": "42", "note_id": "43", "subject": "Fixture", "body": "Fixture note"}, "/notes/43", "PUT"),
    ("delete_note", {"person_id": "42", "note_id": "43"}, "/notes/43", "DELETE"),
    ("list_tasks", {"person_id": "42"}, "/tasks", "GET"),
    ("get_task", {"person_id": "42", "task_id": "44"}, "/tasks/44", "GET"),
    ("create_task", {"person_id": "42", "name": "Fixture Task"}, "/tasks", "POST"),
    ("update_task", {"person_id": "42", "task_id": "44", "name": "Changed"}, "/tasks/44", "PUT"),
    ("complete_task", {"person_id": "42", "task_id": "44"}, "/tasks/44", "PUT"),
    ("delete_task", {"person_id": "42", "task_id": "44"}, "/tasks/44", "DELETE"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,args,path,method", CASES)
async def test_actual_factory_run_dispatch_and_fixed_wire(wire, op, args, path, method):
    node = factory(op, args)
    assert isinstance(node, fb.FollowUpBossNode)
    result = await node.run({})
    assert result["account_id"] == 7 and result["user_id"] == 1
    assert wire.calls[-1].url.path == "/v1" + path and wire.calls[-1].method == method
    assert wire.calls[-1].headers["Authorization"] == "Basic " + base64.b64encode((CREDS["api_key"] + ":").encode()).decode()
    text = json.dumps(result)
    for value in (CREDS["api_key"], CREDS["system_key"], "private@example.test", "private-phone", "private-note-body", "private-note-subject", "private-token", "private-hash"):
        assert value not in text
    if op == "create_task":
        assert json.loads(wire.calls[-1].content) == {"personId": 42, "assignedUserId": 1, "name": "Fixture Task", "type": "Follow Up", "isCompleted": False}
    if op == "create_person":
        assert dict(wire.calls[-1].url.params) == {"deduplicate": "true"}
        assert result["created"] is True
    if op == "update_person":
        assert json.loads(wire.calls[-1].content) == {"firstName": "Changed", "lastName": "Person"}
    if op in {"create_note", "update_note"}:
        assert json.loads(wire.calls[-1].content)["isHtml"] is False


def test_real_three_value_shape_and_actual_discriminated_schema():
    minimal = {k: CREDS[k] for k in ("api_key", "system", "system_key")}
    blob, errors, resolved = cc.shape_credential(FAMILY, minimal)
    assert errors == {} and blob == minimal and resolved == (TYPE, fb.FollowUpBossAPIKeyCredential)
    assert len(fb.FollowUpBossNodeConfig.model_json_schema()["properties"]["config"]["discriminator"]["mapping"]) == 18


@pytest.mark.parametrize("tag", [None, 42, [], {}, "foreign_api_key"])
def test_original_present_null_or_foreign_family_before_parse(tag):
    with pytest.raises(ValueError, match="native Follow Up Boss"):
        factory("get_me", credential={**CREDS, "credential_type": tag})
    assert fb.FollowUpBossNode.validate_config({"config": {"operation": "get_me"}, "credentials": {**CREDS, "credential_type": tag}})["valid"] is False


@pytest.mark.parametrize("sidecar", [{"endpoint": "https://foreign.example.test"}, {"headers": {"Authorization": "foreign"}}, {"remindSecondsBefore": 0}, {"sendEmail": True}, {"assignedUserId": 2}, {"event": "Inquiry"}])
def test_actual_factory_rejects_transport_and_effect_sidecars(sidecar):
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("list_people", sidecar)


@pytest.mark.asyncio
async def test_dedup_existing_is_not_created_or_modified(wire):
    wire.create_status = 200
    result = await factory("create_person", CASES[3][1]).run({})
    assert result["created"] is False
    assert len([r for r in wire.calls if r.method != "GET"]) == 1


@pytest.mark.asyncio
async def test_principal_parent_and_other_user_denials_precede_write(wire):
    wire.user = 2
    with pytest.raises(ValueError, match="another account or user"):
        await factory("delete_task", {"person_id": "42", "task_id": "44"}).run({})
    assert len(wire.calls) == 1
    wire.user, wire.calls = 1, []
    wire.override = lambda r: httpx.Response(200, json={**TASK, "personId": 99}) if r.url.path.endswith("tasks/44") else None
    with pytest.raises(ValueError, match="does not match"):
        await factory("delete_task", {"person_id": "42", "task_id": "44"}).run({})
    assert all(r.method == "GET" for r in wire.calls)
    wire.override = lambda r: httpx.Response(200, json={**TASK, "assignedUserId": 2}) if r.url.path.endswith("tasks/44") else None
    with pytest.raises(ValueError, match="current user's task"):
        await factory("complete_task", {"person_id": "42", "task_id": "44"}).run({})
    assert all(r.method == "GET" for r in wire.calls)


@pytest.mark.asyncio
async def test_real_opaque_paging_filter_binding_and_cycle(wire):
    client = fb._Client(fb._Authority(CREDS))
    await client.identity()
    def page(request):
        next_value = request.url.params.get("next")
        return httpx.Response(200, json={"_metadata": {"collection": "people", "offset": 1 if next_value else 0, "limit": 1, "total": 3, "next": "opaque=cursor+value", "nextLink": "https://foreign.example.test/never-follow"}, "people": [{**PERSON, "id": 43 if next_value else 42}]})
    wire.override = page
    first = await client.page("people", {"limit": 1})
    with pytest.raises(ValueError, match="another credential"):
        await client.page("people", {"limit": 2}, first["next_page_token"])
    with pytest.raises(ValueError, match="cursor repeated"):
        await client.page("people", {"limit": 1}, first["next_page_token"])
    assert dict(wire.calls[-1].url.params) == {"limit": "1", "next": "opaque=cursor+value"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 302, 400, 401, 403, 404, 429, 500])
async def test_safe_errors_never_retry_or_repeat_provider_secret(wire, status):
    wire.override = lambda r: httpx.Response(status, json={"errorMessage": CREDS["api_key"]}, headers={"Retry-After": "7"})
    with pytest.raises(ValueError) as error:
        await factory("get_me").run({})
    assert CREDS["api_key"] not in str(error.value) and len(wire.calls) == 1
    if status == 429:
        with pytest.raises(ValueError, match="still throttled"):
            await factory("get_me").run({})
        assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_distinct_supplied_bearer_and_finite_expiry(wire):
    bearer = {k: v for k, v in CREDS.items() if k != "api_key"}
    bearer.update(access_token="synthetic-fub-bearer-canary", expires_at=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat())
    assert (await factory("get_me", credential=bearer).run({}))["user_id"] == 1
    assert wire.calls[-1].headers["Authorization"] == "Bearer " + bearer["access_token"]
    with pytest.raises(ValueError, match="configuration is invalid"):
        factory("get_me", credential={**bearer, "expires_at": "2000-01-01T00:00:00Z"})


@pytest.mark.asyncio
@pytest.mark.parametrize('op,args', [
    ('create_person', {'first_name': 'William', 'last_name': 'Riker', 'email': 'example@example.com'}),
    ('update_person', {'person_id': '14412', 'first_name': 'William', 'last_name': 'Riker'}),
    ('create_note', {'person_id': '12235', 'subject': 'Some note subject', 'body': 'This is the content of the note'}),
])
async def test_documented_empty_write_acknowledgements(wire, op, args):
    # These three endpoints publish {} as their successful response.
    wire.override = lambda request: httpx.Response(200, json={}) if request.method in {'POST', 'PUT'} else None
    result = await factory(op, args).run({})
    assert result['acknowledged'] is True and result['created'] is None and result['data'] == {}


@pytest.mark.asyncio
async def test_hand_connected_picker_and_saved_row_metadata(wire):
    credential = {**CREDS, 'credential_type': FAMILY, 'token_version': 3, 'updated_at': '2026-11-10T00:00:00Z'}
    fresh = await fb.FollowUpBossNode.freshen_credential(credential)
    options = await fb.FollowUpBossNode.load_field_options('person_id', fresh)
    assert options['options'] == [{'value': '42', 'label': 'Fixture Person'}]


def documented_events():
    from pathlib import Path
    return json.loads((Path(__file__).parent / 'fixtures/followupboss/webhook_events.json').read_text())


@pytest.mark.parametrize('event,fixture', list(documented_events().items()))
def test_documented_events_and_exact_provider_signature(event, fixture):
    import hashlib
    import hmac
    body = json.dumps(fixture['body'], separators=(',', ':')).encode()
    secret = CREDS['system_key']
    config = {'operation': 'on_people_event', 'event_type': event, 'signing_secret': secret}
    signature = hmac.new(secret.encode(), base64.b64encode(body), hashlib.sha256).hexdigest()
    headers = {'FUB-Signature': signature}
    assert fb.FollowUpBossNode.verify_webhook_signature(body, headers, config)
    assert not fb.FollowUpBossNode.verify_webhook_signature(body + b' ', headers, config)
    assert not fb.FollowUpBossNode.verify_webhook_signature(body, {}, config)
    assert not fb.FollowUpBossNode.verify_webhook_signature(body, headers, {**config, 'signing_secret': 'wrong'})
    raw_signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert not fb.FollowUpBossNode.verify_webhook_signature(body, {'FUB-Signature': raw_signature}, config)
    output = fb.FollowUpBossNode.resolve_trigger_payload(fixture['body'], config)
    assert output['resourceIds'] == fixture['body']['resourceIds']
    turn = fb.FollowUpBossNode.resolve_agent_event(output)
    assert 'Follow Up Boss' in turn['text']
    assert all(str(person_id) in turn['text'] for person_id in output['resourceIds'])
    assert fb.FollowUpBossNode.filter_trigger_payload(fixture['body'], config)
    assert not fb.FollowUpBossNode.filter_trigger_payload(fixture['body'], {**config, 'event_type': 'unknown'})


@pytest.mark.asyncio
async def test_documented_webhook_registration_and_empty_cleanup(wire):
    url = 'https://acmeLeadProvider.com/callbacks/followupboss/peopleCreated'
    response = {'id': 1004, 'status': 'Active', 'event': 'peopleCreated', 'url': url}
    def webhook(request):
        if request.method == 'POST':
            assert request.url.path == '/v1/webhooks'
            assert json.loads(request.content) == {'event': 'peopleCreated', 'url': url}
            return httpx.Response(200, json=response)
        assert request.method == 'DELETE' and request.url.path == '/v1/webhooks/1004'
        return httpx.Response(200, content=b'')
    wire.override = webhook
    state = await fb.FollowUpBossNode._register_external_webhook(
        webhook_url=url, credential=CREDS, config={'operation': 'on_people_event'}, node_id='fixture')
    assert state == {'external_webhook_id': '1004', 'signing_secret': CREDS['system_key']}
    await fb.FollowUpBossNode._unregister_external_webhook(credential=CREDS, config=state, node_id='fixture')


@pytest.mark.asyncio
async def test_documented_collection_without_opaque_cursor(wire):
    from pathlib import Path
    docs = json.loads((Path(__file__).parent / 'fixtures/followupboss/documented_responses.json').read_text())
    wire.override = lambda request: httpx.Response(200, json=docs['GET /tasks']['body']) if request.url.path == '/v1/tasks' else None
    client = fb._Client(fb._Authority(CREDS))
    await client.identity()
    page = await client.page('tasks', {'limit': 1, 'assignedUserId': 1})
    assert page['data'][0]['id'] == 4066 and page['next_page_token']
    assert client._decode('tasks', {'limit': 1, 'assignedUserId': 1}, page['next_page_token'])['offset'] == 1


@pytest.mark.asyncio
async def test_malformed_published_task_example_remains_rejected(wire):
    from pathlib import Path
    example = json.loads((Path(__file__).parent / 'fixtures/followupboss/invalid_task_update.json').read_text())
    wire.override = lambda request: httpx.Response(
        200, text=example['body'], headers={'Content-Type': 'application/json'}
    ) if request.method == 'PUT' else None
    with pytest.raises(ValueError, match='JSON response is invalid'):
        await factory('update_task', {'person_id': '42', 'task_id': '44', 'name': 'Follow Up'}).run({})
    assert sum(request.method == 'PUT' for request in wire.calls) == 1

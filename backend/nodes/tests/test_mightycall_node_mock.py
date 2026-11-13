"""Provider-published v4 response examples; transport is always mocked."""
import json
from pathlib import Path
import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import mightycall_node as native
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope

FIXTURES = json.loads((Path(__file__).parent / "fixtures/mightycall/responses.json").read_text())["responses"]
CREDENTIAL = {"credential_type": "mightycall_api_token", "api_key": "fixture-mightycall-key", "access_token": "fixture-mightycall-bearer"}
CALL_ID = "7e734dc1-544d-4f04-8ccc-8bd5b197a88c"
CONTACT_ID = "1cbec7858558ea749cd955be"
CONFIGS = {
    "list_calls": {"call_filter": "Missed", "extension": "100", "skip": 10, "page_size": 25},
    "get_call": {"call_id": CALL_ID},
    "make_call": {"from_number": "+15551112233", "to_number": "+15550152729"},
    "list_voicemails": {"voicemail_filter": "UnRead"},
    "get_voicemail": {"voicemail_id": "a123b456-78bc-4976-8075-b2941d553b7b"},
    "list_contacts": {"email": "john.doe@mghtyc.co", "updated_since": "2019-08-05T09:07:00.831Z"},
    "get_contact": {"contact_id": CONTACT_ID},
    "create_contact": {"first_name": "John", "last_name": "Doe", "channels": [{"phone": "+1700555112233"}]},
    "replace_contact": {"contact_id": CONTACT_ID, "first_name": "Jane", "etag": "48d6e9031aa435be"},
    "delete_contact": {"contact_id": CONTACT_ID, "etag": "48d6e9031aa435be"},
    "add_contact_tags": {"contact_id": CONTACT_ID, "tags": ["tag1", "tag2"]},
    "list_tags": {}, "get_contact_limits": {},
    "send_message": {"from_number": "+12345678910", "to_numbers": ["+12345678901"], "message": "Hello, world!"},
    "list_phone_numbers": {}, "get_phone_number": {"phone_number": "17775550078"},
    "get_profile": {}, "get_status": {}, "set_status": {"status": "dnd"}, "get_team": {},
    "on_new_call": {}, "on_new_voicemail": {},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id="mightycall-fixture", node_type="automation-mightycall",
        node_data={"config": {"operation": operation, **CONFIGS[operation], **config}, "credentials": CREDENTIAL})


def mock_transport(monkeypatch, fixture):
    requests = []
    real_client = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return fixture(request) if callable(fixture) else httpx.Response(fixture["status"], json=fixture["body"])
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def fixture_key(operation):
    method, path = native.ROUTES[operation]
    for field, wire in {"call_id": "id", "voicemail_id": "id", "contact_id": "contactId", "phone_number": "phoneNumber"}.items():
        path = path.replace("{" + field + "}", "{" + wire + "}")
    return method + " " + path


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_provider_examples_and_exact_routes(monkeypatch, operation):
    fixture = FIXTURES[fixture_key(operation)]
    requests = mock_transport(monkeypatch, fixture)
    instance = node(operation)
    async def state(mutator, **kwargs):
        return mutator({"seen_ids": []})[1]
    monkeypatch.setattr(instance, "_update_node_state", state)
    result = await instance.execute({})
    assert result["status"] == "success"
    method, path = native.ROUTES[operation]
    cfg = instance.config.config.model_dump()
    path = path.format(**cfg)
    assert requests[0].method == method
    assert requests[0].url.path == "/v4/api" + path
    assert requests[0].headers["x-api-key"] == CREDENTIAL["api_key"]
    assert requests[0].headers["Authorization"] == "Bearer " + CREDENTIAL["access_token"]
    assert CREDENTIAL["access_token"] not in str(result)
    if operation.startswith("on_new_"):
        assert instance.trigger_emitted_event(result) and not instance.trigger_produced_no_event(result)
        event = instance.resolve_agent_event(result)
        assert event["text"] and result["items"][0]["id"] in event["text"]
        item = result["items"][0]
        if operation == "on_new_voicemail":
            assert all(value in event["text"] for value in (item["from"], item["to"], item["voicemailRecord"]["uri"]))
        else:
            assert item["businessNumber"] in event["text"] and item["caller"]["name"] in event["text"]
    else:
        assert result["data"] == fixture["body"]
    if operation == "make_call":
        assert json.loads(requests[0].content) == {"from": "+15551112233", "to": "+15550152729"}
    if operation == "send_message":
        assert json.loads(requests[0].content) == {"from": "+12345678910", "to": ["+12345678901"], "message": "Hello, world!"}
    if operation == "create_contact":
        assert json.loads(requests[0].content) == {"firstName": "John", "lastName": "Doe", "tags": [], "channels": [{"labels": [], "phone": "+1700555112233"}]}
        assert dict(requests[0].url.params) == {"checkIntersection": "false"}
    if operation == "replace_contact":
        assert dict(requests[0].url.params) == {"checkIntersection": "false", "etag": "48d6e9031aa435be"}
        assert "first_name" not in json.loads(requests[0].content)
    if operation == "add_contact_tags":
        assert json.loads(requests[0].content) == ["tag1", "tag2"]
    if operation == "list_calls":
        assert dict(requests[0].url.params) == {"pageSize": "25", "skip": "10", "callFilter": "Missed", "extension": "100"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_call", "on_new_voicemail"])
async def test_baseline_dedup_and_scope(monkeypatch, operation):
    mock_transport(monkeypatch, FIXTURES[fixture_key(operation)])
    instance = node(operation)
    stored = {}
    async def state(mutator, **kwargs):
        new, result = mutator(stored)
        if new is not None:
            stored.clear(); stored.update(new)
        return result
    monkeypatch.setattr(instance, "_update_node_state", state)
    assert (await instance.execute({}))["items"] == []
    assert instance.trigger_produced_no_event({})
    assert (await instance.execute({}))["items"] == []
    stored["seen_ids"] = []
    fresh = await instance.execute({})
    assert fresh["count"] == 1
    assert (await instance.execute({}))["count"] == 0
    assert poll_scope(native.MightyCallNode, {"operation": operation}) == poll_scope(native.MightyCallNode, {"operation": operation, "label": "Renamed", "goal": "cosmetic"})
    assert poll_scope(native.MightyCallNode, {"operation": operation}) != poll_scope(native.MightyCallNode, {"operation": operation, "lookback_hours": 48})


@pytest.mark.asyncio
async def test_poll_reads_all_pages_before_committing(monkeypatch):
    source = FIXTURES["GET /calls"]["body"]["data"]["calls"][0]
    def reply(request):
        skip = int(request.url.params["skip"])
        rows = [{**source, "id": CALL_ID if skip == 0 else "00000000-0000-0000-0000-000000000001"}]
        return httpx.Response(200, json={"data": {"calls": rows, "total": 2}, "isSuccess": True})
    requests = mock_transport(monkeypatch, reply)
    instance = node("on_new_call", call_filter="Missed", extension="100")
    async def state(mutator, **kwargs):
        assert len(requests) == 2
        return mutator({"seen_ids": []})[1]
    monkeypatch.setattr(instance, "_update_node_state", state)
    assert (await instance.execute({}))["count"] == 2
    assert [r.url.params["skip"] for r in requests] == ["0", "1"]
    assert all(r.url.params["callFilter"] == "Missed" and r.url.params["extension"] == "100" for r in requests)
    assert requests[0].url.params["startUtc"] == requests[1].url.params["startUtc"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_failure_and_secret_redaction(monkeypatch, status):
    requests = mock_transport(monkeypatch, {"status": status, "body": {"message": "Rejected " + CREDENTIAL["access_token"]}})
    with pytest.raises(ValueError) as error:
        await node("get_profile").execute({})
    assert CREDENTIAL["access_token"] not in str(error.value) and str(status) in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"isSuccess": False, "message": "Not authorized"}, {"data": {"calls": [], "total": 2}, "isSuccess": True}, {"data": {"calls": [{"dateTimeUtc": "2018-06-05T13:38:29Z"}], "total": 1}, "isSuccess": True}])
async def test_poll_errors_never_commit_seen_state(monkeypatch, body):
    mock_transport(monkeypatch, {"status": 200, "body": body})
    instance = node("on_new_call")
    async def forbidden(*args, **kwargs):
        pytest.fail("Malformed or incomplete reads must not consume events")
    monkeypatch.setattr(instance, "_update_node_state", forbidden)
    with pytest.raises(ValueError):
        await instance.execute({})


def test_schema_credential_and_validation():
    assert native.MightyCallTokenCredential.model_validate({k:v for k,v in CREDENTIAL.items() if k != "credential_type"}).credential_type == "mightycall_api_token"
    schema = native.MightyCallFullConfig.model_json_schema()
    assert len(schema["properties"]["config"]["discriminator"]["mapping"]) == 22
    for operation in ("on_new_call", "on_new_voicemail"):
        cls = native.MightyCallOnNewCallConfig if operation == "on_new_call" else native.MightyCallOnNewVoicemailConfig
        cls_schema = cls.model_json_schema()
        assert cls_schema["properties"]["operation"]["x-is-trigger"] is True
        assert cls_schema["x-requires-webhook"] is True
    for operation, extra in [("get_call", {"call_id": "../profile"}), ("get_contact", {"contact_id": "bad"}), ("get_phone_number", {"phone_number": "+17775550078"}), ("set_status", {"status": "offline"})]:
        with pytest.raises(ConfigValidationError):
            node(operation, **extra).config


@pytest.mark.asyncio
async def test_connection_evidence_shows_the_accounts_business_number(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    fixture = FIXTURES['GET /phonenumbers']
    mock_transport(monkeypatch, fixture)
    async def run(**kwargs):
        return await node(kwargs['operation']).execute({})
    monkeypatch.setattr(run_op, 'run_node_operation', run)
    result = await collect_evidence(node_type='automation-mightycall', user_id='fixture', credential_data=CREDENTIAL)
    assert result.reachable is True
    assert result.samples[0].label == fixture['body']['data']['phoneNumbers'][0]['number']

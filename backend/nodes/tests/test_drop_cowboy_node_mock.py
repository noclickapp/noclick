"""Exercise Drop Cowboy's v1 request mapping through the actual node factory.

Synthetic credentials and provider-shaped responses cover every operation and
rejection paths without contacting a provider account.
"""
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import drop_cowboy_node as dc
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "drop_cowboy_api_key", "account_id": "synthetic-team-41", "secret": "synthetic-secret-72"}
LIST_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="drop-cowboy-fixture", node_type=dc.DropCowboyNode.integration_type,
        node_data={"config": config, "credentials": CREDENTIAL})


def mock(monkeypatch, body=None, *, status=200, content=None):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, content=content) if content is not None else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(dc.httpx, "AsyncClient", client)
    return requests


SMS = {"operation": "send_sms", "phone_number": "+15552223333", "caller_id": "+15557778888", "pool_id": "pool-1", "sms_body": "Hello world", "opt_in": True}
RVM = {"operation": "send_ringless_voicemail", "phone_number": "+15552223333", "brand_id": "brand-1", "foreign_id": "our-send-1", "recording_id": "recording-1", "forwarding_number": "+15557778888"}
CASES = [
    ({"operation": "list_brands"}, "GET", "/brand", [{"brand_id": "brand-1", "company_name": "Fixture Co", "registered": True, "api_allowed": True}]),
    ({"operation": "list_recordings", "api_allowed": False}, "GET", "/recording", [{"media_id": "recording-1", "name": "Greeting", "created_at": 123, "api_allowed": False}]),
    ({"operation": "list_media"}, "GET", "/media", []),
    ({"operation": "list_number_pools"}, "GET", "/pool", [{"pool_id": "pool-1", "name": "SMS pool", "number_count": 3}]),
    ({"operation": "create_contact_list", "list_name": "My Contacts"}, "POST", "/list", {"list_id": LIST_ID, "list_name": "My Contacts", "created_at": 123}),
    ({"operation": "get_contact_list", "list_id": LIST_ID}, "GET", "/list/" + LIST_ID, {"list_id": LIST_ID, "list_name": "My Contacts", "contact_count": 2, "created_at": 123}),
    ({"operation": "rename_contact_list", "list_id": LIST_ID, "list_name": "Renamed"}, "POST", "/list/" + LIST_ID, None),
    ({"operation": "delete_contact_list", "list_id": LIST_ID}, "DELETE", "/list/" + LIST_ID, {"list_id": LIST_ID}),
    ({"operation": "append_contacts", "list_id": LIST_ID, "fields": ["first_name", "phone"], "values": [["Hunter", "+15552223333"]], "region": "US"}, "POST", "/list/" + LIST_ID + "/contacts", {"accepted_count": 0, "rejected": [{"index": 0, "reason": "invalid phone"}]}),
    (SMS, "POST", "/sms", {"status": "queued"}),
    (RVM, "POST", "/rvm", {"status": "queued"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,response", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_each_operation_has_one_exact_provider_request(monkeypatch, config, method, path, response):
    requests = mock(monkeypatch, response)
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and str(request.url).split("?")[0] == dc.BASE_URL + path
    assert request.headers["x-team-id"] == CREDENTIAL["account_id"]
    assert request.headers["x-secret"] == CREDENTIAL["secret"]
    if method == "POST":
        expected = {k: v for k, v in config.items() if k not in {"operation", "list_id"}}
        if path in {"/sms", "/rvm"}:
            expected.update(team_id=CREDENTIAL["account_id"], secret=CREDENTIAL["secret"])
        assert json.loads(request.content) == expected
    if config["operation"] == "list_recordings":
        assert dict(request.url.params) == {"api_allowed": "false"}
    assert result["data"] == response
    if path in {"/sms", "/rvm"}:
        assert result["delivery_verified"] is False and result["data"]["status"] == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["rename_contact_list", "delete_contact_list"])
async def test_empty_write_acknowledgement(monkeypatch, operation):
    mock(monkeypatch, content=b"")
    config = {"operation": operation, "list_id": LIST_ID}
    if operation.startswith("rename"):
        config["list_name"] = "Updated"
    assert (await node(config).execute({}))["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"error": CREDENTIAL["secret"]}), (302, {}), (200, {"status": "error", "message": CREDENTIAL["account_id"]}), (200, {})])
async def test_rejected_and_malformed_reads_never_become_evidence(monkeypatch, status, body):
    mock(monkeypatch, body, status=status)
    with pytest.raises(ValueError) as exc:
        await node({"operation": "list_brands"}).execute({})
    assert CREDENTIAL["secret"] not in str(exc.value) and CREDENTIAL["account_id"] not in str(exc.value)


def test_manually_shaped_credential_has_default_tag():
    from nodes.core.credential_connect import shape_credential, typed_fields
    shaped, errors, resolved = shape_credential("drop_cowboy_api_key", {k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert not errors and resolved is not None
    assert dc.DropCowboyCredential.model_validate(shaped).credential_type == "drop_cowboy_api_key"
    assert dc.DropCowboyNode.connection_evidence.operation == "list_brands"
    assert {f["name"] for f in typed_fields("drop_cowboy_api_key")} == {"account_id", "secret"}


@pytest.mark.parametrize("changes", [{"opt_in": False}, {"sms_body": "x" * 161}, {"phone_number": "5552223333"}])
def test_sms_requires_consent_valid_phone_and_short_message(changes):
    with pytest.raises(ValueError):
        node({**SMS, **changes})


@pytest.mark.parametrize("list_id", ["../other", ".", "..", "a?x=y", "a#b"])
def test_list_path_cannot_escape(list_id):
    with pytest.raises(ValueError):
        dc.GetList(list_id=list_id)


def test_contact_columns_and_voice_source_are_consistent():
    with pytest.raises(ValidationError):
        dc.AppendContacts(list_id=LIST_ID, fields=["phone"], values=[["one", "two"]])
    base = {"brand_id": "brand-1", "foreign_id": "send-1", "phone_number": "+15552223333"}
    for extra in ({}, {"voice_id": "voice-1"}, {"recording_id": "rec-1", "audio_url": "https://example.com/audio.mp3"}):
        with pytest.raises(ValidationError):
            dc.SendRVM(**base, **extra)
    assert dc.SendRVM(**base, voice_id="voice-1", tts_body="Hello").voice_id == "voice-1"


@pytest.mark.asyncio
async def test_credential_can_connect_by_hand_without_linked_metadata():
    from nodes.core.credential_connect import validate_for_connect
    result = await validate_for_connect(credential_type="drop_cowboy_api_key",
        credential_data={k: v for k, v in CREDENTIAL.items() if k != "credential_type"},
        user_id="fixture-user", probe=False)
    assert result.ok and result.rejection is None and not result.field_errors

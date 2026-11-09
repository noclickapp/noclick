"""OwnerRez fixed routes, personal-token auth, mutation bodies and failure behavior."""
import base64
import json
import httpx
import pytest
from pydantic import ValidationError
from nodes import ownerrez_node as native
from nodes.core.registry import NodeFactory

TOKEN = "pt_synthetic-ownerrez-token"
CREDENTIAL = {"credential_type": "ownerrez_personal_token", "email": "owner@example.com", "personal_access_token": TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="ownerrez-test", node_type="automation-ownerrez",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=None, status=200):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
async def test_personal_basic_auth_and_identity(monkeypatch):
    requests = transport(monkeypatch, {"id": 123, "email_address": "owner@example.com"})
    result = await node({"operation": "get_current_user"}).execute({})
    assert result["status"] == "success"
    assert requests[0].url == "https://api.ownerrez.com/v2/users/me"
    assert requests[0].headers["Authorization"] == "Basic " + base64.b64encode(b"owner@example.com:" + TOKEN.encode()).decode()
    assert TOKEN not in str(result)
    assert native.OwnerRezPersonalTokenCredential.model_validate({k:v for k,v in CREDENTIAL.items() if k != "credential_type"}).credential_type == "ownerrez_personal_token"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field,path", [
    ("get_booking", "booking_id", "bookings"), ("get_guest", "guest_id", "guests"),
    ("get_property", "property_id", "properties"), ("get_quote", "quote_id", "quotes")])
async def test_single_resource_read(monkeypatch, operation, field, path):
    requests = transport(monkeypatch, {"id": 42})
    result = await node({"operation":operation, field:42}).execute({})
    assert result["data"]["id"] == 42
    assert requests[0].url.path == "/v2/" + path + "/42"
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,extra,path", [
    ("list_bookings", {"since_utc":"2026-03-01T00:00:00Z"}, "bookings"),
    ("list_guests", {"q":"Smith + café"}, "guests"),
    ("list_properties", {}, "properties"), ("list_quotes", {}, "quotes"),
    ("list_tag_definitions", {}, "tagdefinitions"),
    ("list_tags", {"entity_id": 42, "entity_type":"booking"}, "tags")])
async def test_one_page_lists_and_cursor(monkeypatch, operation, extra, path):
    next_url = "https://api.ownerrez.com/v2/" + path + "?cursor=opaque"
    requests = transport(monkeypatch, {"items": [{"id": 42}], "limit": 20, "offset": 0, "next_page_url":next_url})
    result = await node({"operation":operation, "cursor":"previous+cursor", **extra}).execute({})
    assert len(requests) == 1 and requests[0].url.path == "/v2/" + path
    assert requests[0].url.params["cursor"] == "previous+cursor"
    assert result["items"] == [{"id":42}] and result["has_more"]
    assert result["next_page_url"] == next_url


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_booking", "create_quote"])
async def test_stay_creation_body_and_side_effect_choices(monkeypatch, operation):
    requests = transport(monkeypatch, {"id": 42})
    await node({"operation":operation, "property_id": 7, "guest_id": 8, "arrival":"2026-12-01", "departure":"2026-12-03"}).execute({})
    request = requests[0]
    body = json.loads(request.content)
    assert request.method == "POST" and body["property_id"] == 7 and body["guest_id"] == 8
    assert body["adults"] == 1 and body["arrival"] == "2026-12-01" and "operation" not in body
    if operation == "create_booking":
        assert body["type"] == "booking" and body["generate_charges"] is False
    else:
        assert body["generate_charges"] is True and body["generate_email"] is False and body["hold_dates"] is False


@pytest.mark.asyncio
async def test_guest_creation_and_partial_updates(monkeypatch):
    requests = transport(monkeypatch, {"id": 42})
    await node({"operation":"create_guest", "first_name":"Ada", "email_address":"ada@example.com"}).execute({})
    assert json.loads(requests[0].content) == {"first_name":"Ada", "email_addresses":[{"address":"ada@example.com", "is_default":True}]}
    for operation, field in [("update_guest","guest_id"), ("update_booking","booking_id"), ("update_quote","quote_id")]:
        requests = transport(monkeypatch, {"id":42})
        await node({"operation":operation, field:42, "notes":"Updated"}).execute({})
        assert requests[0].method == "PATCH"
        assert json.loads(requests[0].content) == {"notes":"Updated", **({"generate_charges":False} if operation == "update_quote" else {})}


@pytest.mark.asyncio
async def test_calendar_dates_and_omitted_days(monkeypatch):
    requests = transport(monkeypatch, {"property_id":7, "currency_code":"USD"})
    result = await node({"operation":"get_calendar", "property_id":7, "from_date":"2026-12-01", "to_date":"2026-12-03"}).execute({})
    assert result["status"] == "success"
    assert dict(requests[0].url.params) == {"from":"2026-12-01", "to":"2026-12-03"}
    assert requests[0].url.path == "/v2/calendar/7"


@pytest.mark.asyncio
async def test_tag_add_and_remove(monkeypatch):
    requests = transport(monkeypatch, {"id":42})
    await node({"operation":"add_tag", "entity_id":7, "entity_type":"guest", "name":"VIP"}).execute({})
    assert json.loads(requests[0].content) == {"entity_id":7, "entity_type":"guest", "name":"VIP"}
    requests = transport(monkeypatch, status=204)
    result = await node({"operation":"remove_tag", "tag_id":42}).execute({})
    assert requests[0].method == "DELETE" and requests[0].url.path == "/v2/tags/42"
    assert not requests[0].content and result["deleted"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 409, 429, 500])
async def test_rejections_preserve_message_redact_token_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"message":"Rejected " + TOKEN}, status)
    result = await node({"operation":"get_current_user"}).execute({})
    assert len(requests) == 1 and result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("get_current_user", {}), ("list_properties", {}), ("get_property", []), ("get_property", {"messages":["Error"], "code":"invalid_token"})])
async def test_invalid_response_does_not_prove_connection(monkeypatch, operation, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation":operation, **({"property_id":1} if operation == "get_property" else {})}).execute({})


@pytest.mark.parametrize("config", [
    {"operation":"list_bookings"}, {"operation":"list_guests"},
    {"operation":"get_booking", "booking_id":"../users/me"},
    {"operation":"update_booking", "booking_id":1}, {"operation":"update_guest", "guest_id":1},
    {"operation":"create_booking", "property_id":1, "guest_id":2, "arrival":"2026-12-03", "departure":"2026-12-01"},
    {"operation":"get_calendar", "property_id":1, "from_date":"2026-01-01", "to_date":"2027-01-02"},
])
def test_invalid_config_is_refused(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def documented_cases():
    from pathlib import Path
    replies = json.loads((Path(__file__).parent / "fixtures/ownerrez/documented_responses.json").read_text())
    configs = {
        "list_bookings": {"since_utc":"2026-03-01T00:00:00Z"},
        "get_booking": {"booking_id":42}, "update_booking": {"booking_id":42,"notes":"Updated"},
        "list_guests": {"q":"Smith"}, "get_guest": {"guest_id":42},
        "update_guest": {"guest_id":42,"notes":"Updated"}, "get_property": {"property_id":42},
        "get_calendar": {"property_id":42,"from_date":"2026-12-01","to_date":"2026-12-03"},
        "get_quote": {"quote_id":42}, "update_quote": {"quote_id":42,"notes":"Updated"},
        "list_tags": {"entity_id":42,"entity_type":"booking"},
        "add_tag": {"entity_id":42,"entity_type":"booking","name":"VIP"},
    }
    stay = {"property_id":5678,"guest_id":1234,"arrival":"2026-12-10","departure":"2026-12-15"}
    configs.update(create_booking=stay,create_quote=stay)
    for operation, (method,path) in native.ROUTES.items():
        if operation == "remove_tag":continue
        for field in ("booking_id","guest_id","quote_id","tag_id"):
            path = path.replace("{"+field+"}","{id}")
        if path == "/v2/properties/{property_id}":path = "/v2/properties/{id}"
        yield pytest.param({"operation":operation,**configs.get(operation,{})},replies[method+" "+path]["body"],id=operation)


@pytest.mark.asyncio
@pytest.mark.parametrize("config,body",list(documented_cases()))
async def test_provider_documented_responses(monkeypatch, config, body):
    """The published examples parse even where allOf makes the spec reject them."""
    transport(monkeypatch, body)
    assert (await node(config).execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_documented_error_messages_are_preserved(monkeypatch):
    transport(monkeypatch, {"messages":["Token is inactive", "Please grant access"], "code":"invalid_token"}, 401)
    result = await node({"operation":"get_current_user"}).execute({})
    assert result["error"] == "Token is inactive\nPlease grant access"

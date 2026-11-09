"""FareHarbor fixed route, credential and mutation serialization regressions."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import fareharbor_node as native
from nodes.core.registry import NodeFactory

CREDS = {
    "credential_type": "fareharbor_api_key",
    "app_key": "synthetic-app-42",
    "user_key": "synthetic-user-42",
    "company_shortname": "hawaiianadventures",
}
UUID = "d75102be-9732-4523-90a8-c698eff2b983"
OPERATIONS = json.loads(
    (Path(__file__).parent / "fixtures/fareharbor/operations.json").read_text()
)
BODY = {
    "BookingData": {
        "contact": {
            "email": "surfer@dude.com",
            "name": "Surfer Dude",
            "phone": "+1-443-222-1100",
        },
        "customers": [{"customer_type_rate": 978}],
        "amount_paid": 0,
    },
    "ValidationData": {
        "contact": {
            "email": "surfer@dude.com",
            "name": "Surfer Dude",
            "phone": "+1-443-222-1100",
        },
        "customers": [{"customer_type_rate": 978}],
    },
    "QRCheckin": {"qr_code": "https://fhchk.co/abc", "is_whole_booking": False},
    "BookingNote": {"note": "This is a *note*."},
    "CustomerFieldUpdate": {"value": "10:01"},
    "ResourceUpdate": {"resource_pk": 12345},
    "BookingCheckin": {"checkin_status": None, "customer": 2481},
    "CrewMember": {"username": "jsmith", "role": "captain"},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="fareharbor-fixture",
        node_type="automation-fareharbor",
        node_data={"config": config, "credentials": CREDS},
    )


def transport(monkeypatch, reply):
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request)

    original = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,method,template,fields,body,query,description", OPERATIONS
)
async def test_all_operations_use_exact_single_provider_request(
    monkeypatch, operation, method, template, fields, body, query, description
):
    values = {
        f: UUID if f == "booking_uuid" else "2015-01-22" if f.endswith("date") else 4787
        for f in fields
    }
    config = {"operation": operation, **values, **{q: "no" for q in query}}
    if body:
        config["body"] = BODY[body]
    key, typ = native.RESPONSE_SHAPES[operation]
    reply = {
        key: {"name": "Hawaiian Adventures"}
        if typ is dict
        else []
        if typ is list
        else False
    }
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=reply))
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split("?")[0] == native.BASE + template.format(
        company=CREDS["company_shortname"], **values
    )
    assert dict(request.url.params) == {q: "no" for q in query}
    assert request.headers["X-FareHarbor-API-App"] == CREDS["app_key"]
    assert request.headers["X-FareHarbor-API-User"] == CREDS["user_key"]
    assert request.headers["accept"] == "application/json"
    if body:
        assert json.loads(request.content) == BODY[body]
    else:
        assert not request.content
    assert CREDS["app_key"] not in str(result) and CREDS["user_key"] not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [202, 204, 301, 302, 400, 401, 403, 404, 429, 500])
async def test_failures_do_not_retry_or_disclose_response(monkeypatch, status):
    requests = transport(
        monkeypatch,
        lambda r: httpx.Response(
            status,
            json={"message": CREDS["app_key"]},
            headers={"Location": "https://example.test/"},
        ),
    )
    result = await node({"operation": "get_company"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert len(requests) == 1 and CREDS["app_key"] not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"company": {}},
        [],
        None,
        {"error": "rejected"},
        {"code": "user-key-invalid", "message": "rejected"},
    ],
)
async def test_error_envelopes_and_nonobjects_never_prove_connection(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "get_company"}).execute({})


def test_credential_manual_defaults_and_path_constraints():
    credential = native.FareHarborAPIKeyCredential.model_validate(
        {k: v for k, v in CREDS.items() if k != "credential_type"}
    )
    assert credential.credential_type == "fareharbor_api_key"
    for name, value in [
        ("company_shortname", "../evil"),
        ("company_shortname", "a/b"),
        ("app_key", "https://example.test/key"),
        ("user_key", "key\r\ninjection"),
    ]:
        with pytest.raises(ValidationError):
            native.FareHarborAPIKeyCredential.model_validate({**CREDS, name: value})
    for config in [
        {"operation": "get_item", "item_pk": -1},
        {"operation": "get_booking", "booking_uuid": "../evil"},
        {
            "operation": "list_availabilities_by_date",
            "item_pk": 1867,
            "activity_date": "2015-02-30",
        },
        {
            "operation": "list_availabilities_by_date_range",
            "item_pk": 1867,
            "start_date": "2015-01-23",
            "end_date": "2015-01-22",
        },
        {
            "operation": "create_booking",
            "availability_pk": 4787,
            "body": {"contact": BODY["BookingData"]["contact"], "customers": []},
        },
    ]:
        with pytest.raises(ValueError):
            node(config)


@pytest.mark.asyncio
async def test_connection_preserves_provider_rejection_text(monkeypatch):
    transport(
        monkeypatch,
        lambda r: httpx.Response(
            403, json={"code": "user-key-invalid", "message": "User key is invalid"}
        ),
    )
    result = await node({"operation": "get_company"}).execute({})
    assert result["message"] == "User key is invalid"
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_booking_validation_can_return_documented_unbookable_result(monkeypatch):
    reply = {
        "is_bookable": False,
        "error": "Not enough capacity",
        "code": "bookability-error",
    }
    transport(monkeypatch, lambda r: httpx.Response(200, json=reply))
    result = await node(
        {
            "operation": "validate_booking",
            "availability_pk": 4787,
            "body": BODY["ValidationData"],
        }
    ).execute({})
    assert result["status"] == "success" and result["data"] == reply

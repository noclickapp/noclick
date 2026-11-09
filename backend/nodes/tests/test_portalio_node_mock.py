"""Portal.io native transport contract; all keys and account data are synthetic."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import portalio_node as portal
from nodes.core.registry import NodeFactory

AUTH = {
    "credential_type": "portalio_api_key",
    "application_key": "fixture-app",
    "secret_key": "c3ludGhldGljLXNlY3JldA==",
    "user_api_key": "fixture-user-key",
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(
        node_id="portalio-fixture",
        node_type="automation-portalio",
        node_data={"config": config, "credentials": credentials or AUTH},
    )


def transport(monkeypatch, payload, status=200):
    requests = []

    def send(request):
        requests.append(request)
        return (
            httpx.Response(status, json=payload)
            if status != 204
            else httpx.Response(204)
        )

    native = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return native(transport=httpx.MockTransport(send), **kwargs)

    monkeypatch.setattr(portal.httpx, "AsyncClient", client)
    return requests


CASES = [
    (
        {
            "operation": "list_proposals",
            "statuses": ["Draft", "Accepted"],
            "is_archive": False,
        },
        "GET",
        "/public/proposals",
        {},
    ),
    (
        {"operation": "create_proposal", "sales_person_id": 42, "name": "Living Room"},
        "POST",
        "/public/proposals",
        {"SalesPersonId": ["42"], "Name": ["Living Room"]},
    ),
    (
        {"operation": "get_proposal", "proposal_id": 1042},
        "GET",
        "/public/proposals/1042",
        {},
    ),
    (
        {"operation": "update_proposal", "proposal_id": 1042, "name": "New Name"},
        "POST",
        "/public/proposals/1042",
        {"Name": ["New Name"]},
    ),
    (
        {"operation": "update_description", "proposal_id": 1042, "description": ""},
        "POST",
        "/public/proposals/1042/description",
        {"Description": [""]},
    ),
    (
        {
            "operation": "update_internal_notes",
            "proposal_id": 1042,
            "internal_notes": "Rack & wire",
        },
        "POST",
        "/public/proposals/1042/internalnotes",
        {"InternalNotes": ["Rack & wire"]},
    ),
    (
        {"operation": "get_change_order", "proposal_id": 1042, "change_order_id": 7},
        "GET",
        "/public/proposals/1042/changeorders/7",
        {},
    ),
    (
        {"operation": "list_change_orders", "proposal_id": 1042},
        "GET",
        "/public/proposals/1042/changeorders",
        {},
    ),
    (
        {"operation": "add_area", "proposal_id": 1042, "name": "Living Room"},
        "POST",
        "/public/proposals/1042/area",
        {"Name": ["Living Room"]},
    ),
    (
        {
            "operation": "add_area_option",
            "proposal_id": 1042,
            "area_id": 2,
            "client_description": "Premium",
        },
        "POST",
        "/public/proposals/1042/area/2/option",
        {"ClientDescription": ["Premium"]},
    ),
    (
        {"operation": "assign_contact", "proposal_id": 1042, "contact_id": 3},
        "POST",
        "/public/proposals/1042/contact/3",
        {},
    ),
    (
        {"operation": "assign_location", "proposal_id": 1042, "location_id": 4},
        "POST",
        "/public/proposals/1042/location/4",
        {},
    ),
    (
        {"operation": "list_contacts", "contact_types": ["Person", "Company"]},
        "GET",
        "/public/people",
        {},
    ),
    (
        {
            "operation": "create_contact",
            "party_type": "Person",
            "contact_type": "Client",
            "first_name": "Jane",
        },
        "POST",
        "/public/people",
        {"PartyType": ["Person"], "ContactType": ["Client"], "FirstName": ["Jane"]},
    ),
    (
        {"operation": "get_contact", "person_id": 3, "include_counts": True},
        "GET",
        "/public/people/3",
        {},
    ),
    (
        {"operation": "list_contact_locations", "contact_id": 3},
        "GET",
        "/public/people/3/location",
        {},
    ),
    (
        {
            "operation": "create_contact_location",
            "contact_id": 3,
            "street": "123 Main St",
            "is_primary": False,
        },
        "POST",
        "/public/people/3/location",
        {"Street": ["123 Main St"], "IsPrimary": ["false"]},
    ),
    ({"operation": "list_users"}, "GET", "/public/users", {}),
    (
        {
            "operation": "search_catalog",
            "category_ids": [1, 2],
            "brands": ["Sonos", "Sony"],
        },
        "GET",
        "/public/catalog",
        {},
    ),
    ({"operation": "list_categories"}, "GET", "/public/catalog/categories", {}),
    (
        {"operation": "get_catalog_item", "item_id": 5, "extended_details": True},
        "GET",
        "/public/catalog/5",
        {},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body", CASES)
async def test_each_operation_is_one_signed_request(
    monkeypatch, config, method, path, body
):
    status = 204 if config["operation"] == "assign_contact" else 200
    payload = (
        [{"id": 42}]
        if config["operation"] in {"list_categories", "list_change_orders"}
        else {"id": 42}
    )
    requests = transport(monkeypatch, payload, status)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == (
        None if status == 204 else payload
    )
    assert len(requests) == 1
    request = requests[0]
    assert (
        request.method == method
        and request.url.path == path
        and request.url.host == "api.portal.io"
    )
    assert parse_qs(request.content.decode(), keep_blank_values=True) == body
    assert request.headers["Accept"] == "application/json"
    assert request.headers["X-MSS-API-APPID"] == AUTH["application_key"]
    assert request.headers["X-MSS-API-USERKEY"] == AUTH["user_api_key"]
    canonical = method + "https://api.portal.io" + path
    if method != "GET":
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        canonical += "application/x-www-form-urlencoded"
    canonical += request.headers["X-MSS-CUSTOM-DATE"] + AUTH["user_api_key"]
    expected = base64.b64encode(
        hmac.new(
            AUTH["secret_key"].encode("ascii"), canonical.encode(), hashlib.sha256
        ).digest()
    ).decode()
    assert request.headers["X-MSS-SIGNATURE"] == expected
    assert AUTH["secret_key"] not in str(request.url) + str(
        request.headers
    ) + json.dumps(result)
    if config["operation"] == "list_proposals":
        assert request.url.params.get_list("Statuses") == ["Draft", "Accepted"]
        assert (
            request.url.params["IsArchive"] == "false"
            and request.url.params["PageNumber"] == "1"
        )
    if config["operation"] == "search_catalog":
        assert request.url.params.get_list("CategoryIds") == ["1", "2"]
        assert request.url.params.get_list("Brands") == ["Sonos", "Sony"]
    if config["operation"] == "list_contacts":
        assert request.url.params.get_list("ContactTypes") == ["Person", "Company"]


@pytest.mark.asyncio
async def test_sandbox_and_documented_user_response(monkeypatch):
    payload = json.loads(
        (Path(__file__).parent / "fixtures/portalio/users.json").read_text()
    )
    requests = transport(monkeypatch, payload)
    result = await node(
        {"operation": "list_users"}, {**AUTH, "environment": "sandbox"}
    ).execute({})
    assert result["data"]["users"][0]["firstName"] == "Alex"
    assert requests[0].url.host == "sandbox.api.portal.io"


@pytest.mark.asyncio
async def test_rejection_keeps_provider_message_and_redacts_secrets(monkeypatch):
    transport(
        monkeypatch, {"message": "Not Authorized", "debug": AUTH["secret_key"]}, 401
    )
    result = await node({"operation": "list_users"}).execute({})
    assert result["status"] == "error" and result["http_status"] == 401
    assert (
        "Not Authorized" in result["error"]
        and AUTH["secret_key"] not in result["error"]
    )


@pytest.mark.asyncio
async def test_error_envelope_on_http_success(monkeypatch):
    transport(
        monkeypatch,
        {"responseStatus": {"errorCode": "Forbidden", "message": "No permission"}},
    )
    assert (await node({"operation": "list_users"}).execute({}))[
        "error"
    ] == "No permission"


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_proposal", "proposal_id": "../users"},
        {"operation": "get_proposal", "proposal_id": 0},
        {"operation": "list_contacts", "page_number": 0},
        {"operation": "search_catalog", "category_id": 1, "category_ids": [2]},
        {
            "operation": "create_contact",
            "party_type": "Company",
            "contact_type": "Client",
            "first_name": "Jane",
        },
        {
            "operation": "create_contact_location",
            "contact_id": 1,
            "street": "Main St",
            "country": "US",
        },
    ],
)
def test_bad_inputs_fail_before_http(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_connect_type_default_and_evidence():
    credential = portal.PortalioApiKeyCredential.model_validate(
        {k: v for k, v in AUTH.items() if k != "credential_type"}
    )
    assert credential.credential_type == "portalio_api_key"
    assert portal.PortalioNode.connection_evidence.operation == "list_users"


@pytest.mark.asyncio
async def test_connection_evidence_shows_account_users(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence

    transport(
        monkeypatch,
        {"users": [{"firstName": "Alex", "lastName": "Johnson"}], "usersCount": 1},
    )
    evidence = await collect_evidence(
        node_type="automation-portalio",
        user_id="00000000-0000-4000-8000-000000000001",
        credential_data=AUTH,
    )
    assert evidence.reachable is True
    assert [sample.label for sample in evidence.samples] == ["Alex"]

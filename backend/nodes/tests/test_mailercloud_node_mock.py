"""Offline request and publisher-example regressions for Mailercloud v1."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import mailercloud_node as native
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NodeFactory

CONTRACT = json.loads((Path(__file__).parent / "fixtures/mailercloud/contract.json").read_text())
KEY = "synthetic-mailercloud-key-42"
CREDENTIAL = {"credential_type": "mailercloud_api_key", "api_key": KEY}
CONFIGS = {
    "get_account": {},
    "create_contact": {"email": "john.doe@example.com", "list_id": "KYHH"},
    "upsert_contact": {"email": "john.doe@example.com", "list_id": "KYHH"},
    "update_contact": {"contact_id": "ABCD", "first_name": "John"},
    "get_contact": {"contact_id": "ABCD"},
    "delete_contact": {"contact_id": "ABCD"},
    "list_contacts": {"list_id": "KYHH", "page": 2, "limit": 20},
    "create_list": {"name": "Email subscription-list"},
    "update_list": {"list_id": "HHda", "name": "Subscibers List"},
    "get_list": {"list_id": "HHda"},
    "delete_list": {"list_id": "HHda"},
    "list_lists": {"search_name": "subscription"},
    "create_tag": {"name": "customer"},
    "update_tag": {"tag_id": "ABCD", "name": "customer"},
    "delete_tag": {"tag_id": "ABCD"},
    "list_tags": {"search": "customer"},
    "list_campaigns": {"status": "Finished"},
    "get_campaign": {"campaign_id": "ABCD"},
    "list_campaign_opens": {"campaign_id": "ABCD"},
    "list_campaign_clicks": {"campaign_id": "ABCD"},
    "list_senders": {"search": "marketing"},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="mailercloud-fixture", node_type="automation-mailercloud",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return payload(request) if callable(payload) else httpx.Response(status, json=payload)
    def client(**options):
        assert options["follow_redirects"] is False
        assert options["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **options)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_publisher_routes_auth_and_examples(monkeypatch, operation):
    fixture = CONTRACT[operation]
    config = CONFIGS[operation]
    requests = transport(monkeypatch, fixture["response"])
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success"
    assert result["data"] == fixture["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture["method"]
    assert request.headers["Authorization"] == KEY
    assert request.url.host == "cloudapi.mailercloud.com"
    selected_id = next((v for k, v in config.items() if k.endswith("_id")), None)
    assert request.url.path == "/v1" + fixture["path"].replace("{id}", selected_id or "")
    if operation == "update_list":
        assert dict(request.url.params) == {"id": "HHda"}
    if operation == "get_contact":
        assert json.loads(request.content) == {}
    elif fixture["method"] in {"POST", "PUT", "PATCH"}:
        body = json.loads(request.content)
        assert "operation" not in body
        assert "tracking_consent" not in body
        assert all(k not in body for k in ("contact_id", "campaign_id", "tag_id"))
        if operation.startswith("list_"):
            assert body["page"] == config.get("page", 1)
            assert body["limit"] == config.get("limit", 10)
    else:
        assert not request.content


@pytest.mark.asyncio
async def test_contact_consent_and_email_identifier(monkeypatch):
    requests = transport(monkeypatch, {"message": "Contact updated"})
    result = await node({"operation": "update_contact", "contact_id": "john.doe@example.com",
        "tracking_consent": "denied", "tags": []}).execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content) == {"tracking_consent": "denied", "tags": []}
    assert str(requests[0].url).endswith("john.doe%40example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 404, 429, 500])
async def test_provider_rejections_are_errors_and_secrets_are_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"errors": [{"message": "Authorization failed " + KEY}]}, status)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert KEY not in str(result) and "Authorization failed" in result["error"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_account_evidence_identifies_unsaved_key(monkeypatch):
    requests = transport(monkeypatch, CONTRACT["get_account"]["response"])
    result = await collect_evidence(node_type="automation-mailercloud", user_id="fixture-user",
        credential_data=CREDENTIAL)
    assert result.reachable is True and result.account_label == "MailerCloud User"
    assert len(requests) == 1 and requests[0].url.path == "/v1/client/plan"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": []}, "unexpected"])
async def test_missing_account_identity_is_not_success(monkeypatch, payload):
    transport(monkeypatch, payload)
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_delete_string_schema_and_no_content(monkeypatch):
    transport(monkeypatch, "List deleted successfully")
    assert (await node({"operation": "delete_list", "list_id": "HHda"}).execute({}))["status"] == "success"
    transport(monkeypatch, lambda request: httpx.Response(204))
    assert (await node({"operation": "delete_contact", "contact_id": "ABCD"}).execute({}))["http_status"] == 204


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 302, 500])
async def test_non_json_and_redirects_are_not_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, text="<html>login</html>",
        headers={"Location": "https://example.test/"}))
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"
    assert len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../other"},
    {"operation": "list_tags", "limit": 9},
    {"operation": "list_lists", "page": 4},
    {"operation": "create_list", "name": "x"},
    {"operation": "create_list", "name": "bad/name"},
    {"operation": "create_contact", "email": "john@example.com"},
    {"operation": "custom_request"},
])
def test_invalid_inputs_do_not_execute(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)

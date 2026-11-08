"""Exercise the real factory and SSRF HTTP seam without provider credentials."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import givebutter_node as gb
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "givebutter_api_key", "api_key": "fixture-givebutter-key"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.givebutter.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, body = responses.pop(0)
        return httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(gb, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-givebutter", operation=operation,
        arguments=arguments or {}, credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")


CASES = [
    ("list_campaigns", {}, "GET", "/v1/campaigns", {}),
    ("get_campaign", {"campaign_id": 42}, "GET", "/v1/campaigns/42", {}),
    ("create_campaign", {"type": "fundraise", "title": "Annual Appeal", "goal": 5000}, "POST", "/v1/campaigns", {"type": "fundraise", "title": "Annual Appeal", "goal": 5000}),
    ("update_campaign", {"campaign_id": 42, "goal": 0}, "PUT", "/v1/campaigns/42", {"goal": 0}),
    ("list_contacts", {"email": "donor@example.org"}, "GET", "/v1/contacts", {"email": "donor@example.org"}),
    ("get_contact", {"contact_id": 42}, "GET", "/v1/contacts/42", {}),
    ("create_contact", {"first_name": "Jane", "last_name": "Donor", "primary_email": "jane@example.org"}, "POST", "/v1/contacts", {"first_name": "Jane", "last_name": "Donor", "primary_email": "jane@example.org"}),
    ("update_contact", {"contact_id": 42, "note": "Follow up"}, "PUT", "/v1/contacts/42", {"note": "Follow up"}),
    ("restore_contact", {"contact_id": 42}, "PATCH", "/v1/contacts/42/restore", {}),
    ("add_contact_tags", {"contact_id": 42, "tags": ["volunteer"]}, "POST", "/v1/contacts/42/tags/add", {"tags": ["volunteer"]}),
    ("remove_contact_tags", {"contact_id": 42, "tags": ["volunteer"]}, "POST", "/v1/contacts/42/tags/remove", {"tags": ["volunteer"]}),
    ("list_contact_activities", {"contact_id": 42}, "GET", "/v1/contacts/42/activities", {}),
    ("create_contact_activity", {"contact_id": 42, "type": "note", "note": "Thanked donor"}, "POST", "/v1/contacts/42/activities", {"type": "note", "note": "Thanked donor"}),
    ("list_funds", {}, "GET", "/v1/funds", {}),
    ("get_fund", {"fund_id": 42}, "GET", "/v1/funds/42", {}),
    ("create_fund", {"name": "Scholarships"}, "POST", "/v1/funds", {"name": "Scholarships"}),
    ("update_fund", {"fund_id": 42, "name": "Scholarships", "code": "SCH"}, "PUT", "/v1/funds/42", {"name": "Scholarships", "code": "SCH"}),
    ("list_transactions", {"contacts": "42"}, "GET", "/v1/transactions", {"contacts": "42"}),
    ("get_transaction", {"transaction_id": 42}, "GET", "/v1/transactions/42", {}),
    ("list_plans", {}, "GET", "/v1/plans", {}),
    ("get_plan", {"plan_id": 42}, "GET", "/v1/plans/42", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,expected", CASES)
async def test_contract_routes_and_payloads(transport, operation, arguments, method, path, expected):
    requests, responses = transport
    body = {"id": "42", "title": "Annual Appeal"}
    if operation.startswith("list_"):
        body = json.loads((Path(__file__).parent / "fixtures/givebutter/campaigns.json").read_text())
    responses.append((200, body))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    if method == "GET":
        assert dict(request.url.params) == expected
        assert not request.content
    else:
        assert (json.loads(request.content) if request.content else {}) == expected
    assert result["data"] == (body["data"] if operation.startswith("list_") else body)
    if operation.startswith("list_"):
        assert result["meta"] == body["meta"] and result["links"] == body["links"]


@pytest.mark.asyncio
async def test_rejection_retains_provider_message_but_redacts_key(transport):
    requests, responses = transport
    responses.append((401, {"message": "Rejected " + AUTH["api_key"]}))
    out = await run("list_campaigns")
    assert out["status"] == "error" and out["http_status"] == 401
    assert out["message"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"message": "not a list"}, {"data": {}}, {"data": [], "errors": ["failed"]}])
async def test_malformed_or_error_list_is_not_success(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError):
        await run("list_campaigns")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments", [
    ("get_contact", {"contact_id": "../contacts"}),
    ("get_contact", {"contact_id": 0}),
    ("add_contact_tags", {"contact_id": 42, "tags": []}),
    ("update_contact", {"contact_id": 42}),
    ("update_campaign", {"campaign_id": 42}),
    ("create_campaign", {"type": "invalid", "title": "Appeal"}),
    ("list_contacts", {"updatedAfter": "not-a-date"}),
])
async def test_invalid_config_makes_no_request(transport, operation, arguments):
    with pytest.raises(ValueError):
        await run(operation, arguments)
    assert not transport[0]


@pytest.mark.parametrize("key", ["Bearer abc", "abc\nInjected", "https://example.org/key"])
def test_invalid_credential(key):
    with pytest.raises(ValueError):
        gb.GivebutterAPIKeyCredential(api_key=key)


def test_saved_workflow_metadata_is_accepted_and_not_forwarded():
    raw = {"config": {"operation": "list_campaigns", "credentialIds": {"givebutter_api_key": "saved-credential"}}, "credentials": AUTH}
    assert gb.GivebutterNode.validate_config(raw)["valid"] is True
    parsed = gb.GivebutterNode.parse_config(raw)
    assert parsed.config.model_dump() == {"operation": "list_campaigns", "scope": None}

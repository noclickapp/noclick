"""OnePageCRM request contracts and provider-published response fixtures."""
import base64
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import onepage_crm_node as crm
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence
from utils import ssrf

FIXTURES = Path(__file__).parent / "fixtures" / "onepage-crm"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
INPUTS = json.loads((FIXTURES / "inputs.json").read_text())
AUTH = {"credential_type": "onepage_crm_api_key", "user_id": "5aba31e99007ba0f570c12f7", "api_key": "synthetic-key-for-tests"}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "app.onepagecrm.com"
        assert request.headers["Authorization"] == "Basic " + base64.b64encode((AUTH["user_id"] + ":" + AUTH["api_key"]).encode()).decode()
        assert AUTH["api_key"] not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, content=body) if isinstance(body, bytes) else httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(crm, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(config, auth=AUTH):
    node = NodeFactory.create_node(node_id="onepage-crm-test", node_type="automation-onepage-crm",
        node_data={"config": deepcopy(config), "credentials": deepcopy(auth)})
    return await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", INPUTS)
async def test_onepage_crm_every_operation_uses_one_documented_request(transport, operation):
    requests, queue = transport
    config = INPUTS[operation]["config"]
    method, path, plural, singular = crm.ROUTES[operation]
    body = RESPONSES[operation]["body"]
    queue.append((201 if method == "POST" else 200, b"" if body is None else body))
    result = await run(config)
    assert result["status"] == "success"
    assert len(requests) == 1 and queue == []
    request = requests[0]
    assert request.method == method
    if "{" in path:
        path = path.replace("{" + singular + "_id}", config[singular + "_id"])
    assert request.url.path == "/api/v3" + path
    if method in {"POST", "PUT"}:
        expected = {k: v for k, v in config.items() if k not in {"operation", singular + "_id"}}
        # A create's contact_id is a body field, not a resource selector.
        if method == "POST" and "contact_id" in config:
            expected["contact_id"] = config["contact_id"]
        if expected.get("linked_deal_id") == "":
            expected.pop("linked_deal_id")
        assert json.loads(request.content) == expected
    if method == "PUT":
        assert request.url.params["partial"] == "true"
    if operation.startswith("list_"):
        assert isinstance(result["items"], list)
    elif method != "DELETE":
        assert result["item"]["id"] == body["data"][singular]["id"]
    else:
        assert result["acknowledged"] is True


@pytest.mark.asyncio
async def test_onepage_crm_pagination_and_filters(transport):
    payload = deepcopy(RESPONSES["list_contacts"]["body"])
    payload["data"].update(page=2, per_page=1, max_page=3, total_count=3)
    transport[1].append((200, payload))
    result = await run({"operation": "list_contacts", "page": 2, "per_page": 1, "email": "joe.bloggs@example.com"})
    assert result["next_page"] == 3
    assert dict(transport[0][0].url.params) == {"page": "2", "per_page": "1", "email": "joe.bloggs@example.com"}


@pytest.mark.asyncio
async def test_onepage_crm_action_completion_is_query_parameter(transport):
    config = INPUTS["update_action"]["config"]
    transport[1].append((200, RESPONSES["update_action"]["body"]))
    await run({"operation": "update_action", "action_id": config["action_id"], "done": True})
    request = transport[0][0]
    assert dict(request.url.params) == {"partial": "true", "done": "true"}
    assert json.loads(request.content) == {}


@pytest.mark.asyncio
async def test_onepage_crm_partial_updates_preserve_omitted_fields_and_empty_arrays(transport):
    cid = INPUTS["update_contact"]["config"]["contact_id"]
    transport[1].append((200, RESPONSES["update_contact"]["body"]))
    await run({"operation": "update_contact", "contact_id": cid, "tags": [], "starred": False})
    assert json.loads(transport[0][0].content) == {"tags": [], "starred": False}
    assert transport[0][0].url.params["partial"] == "true"


@pytest.mark.asyncio
async def test_onepage_crm_connection_evidence_uses_team_names(transport):
    transport[1].append((200, RESPONSES["list_users"]["body"]))
    result = await collect_evidence(node_type="automation-onepage-crm", credential_data=AUTH, user_id="fixture-user")
    assert result.reachable is True
    assert result.samples
    assert "jane.doe@example.com" in str(result.samples)
    assert [request.method for request in transport[0]] == ["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code,body", [
    (401, {"status": 401, "message": "Invalid API key"}),
    (200, {"status": 1, "message": "Permission denied"}),
    (429, {"status": 429, "message": "Too many requests"}),
    (302, b""),
    (200, b"<html>Sign in</html>"),
])
async def test_onepage_crm_provider_errors_and_redirects_do_not_pass(transport, code, body):
    transport[1].append((code, body))
    result = await run({"operation": "list_users"})
    assert result["status"] == "error" and len(transport[0]) == 1


@pytest.mark.asyncio
async def test_onepage_crm_reflected_secret_is_redacted(transport):
    transport[1].append((401, {"status": 1, "message": "Rejected " + AUTH["api_key"]}))
    result = await run({"operation": "list_users"})
    assert AUTH["api_key"] not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"status": 0, "data": {}},
    {"status": 0, "data": [{"user": {"first_name": "Missing ID"}}]},
])
async def test_onepage_crm_malformed_success_does_not_become_evidence(transport, payload):
    transport[1].append((200, payload))
    with pytest.raises(ValueError):
        await run({"operation": "list_users"})


@pytest.mark.asyncio
async def test_onepage_crm_wrong_resource_is_refused(transport):
    transport[1].append((200, RESPONSES["get_contact"]["body"]))
    with pytest.raises(ValueError, match="different resource"):
        await run({"operation": "get_contact", "contact_id": "another-id"})


@pytest.mark.parametrize("config", [
    {"operation": "get_contact", "contact_id": "../users"},
    {"operation": "create_contact", "first_name": "Nobody"},
    {"operation": "create_action", "contact_id": "contact", "text": "x" * 141},
    {"operation": "update_contact", "contact_id": "contact"},
    {"operation": "list_contacts", "per_page": 101},
    {"operation": "create_note", "contact_id": "contact", "text": "note", "date": "2026-02-30"},
    {"operation": "update_deal", "deal_id": "deal", "contact_id": "other"},
    {"operation": "list_users", "unexpected": "value"},
])
def test_onepage_crm_invalid_configs_are_refused(config):
    with pytest.raises(ValueError):
        crm.OnePageCRMNode.parse_config({"config": config, "credentials": AUTH})


def test_onepage_crm_manual_credentials_have_default_type():
    assert crm.OnePageCRMAPIKeyCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"}).credential_type == "onepage_crm_api_key"

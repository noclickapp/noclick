"""Exercise NeetoForm through native discovery with intercepted HTTP requests.

Fixtures cover every operation's exact route and payload plus pagination,
credential isolation, provider rejections and malformed responses.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import neetoform_node as node
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "neetoform_api_key", "subdomain": "spinkart", "api_key": "fixture-neetoform-private-key"}
CASES = json.loads((Path(__file__).parent / "fixtures/neetoform/operations.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def handle(request):
        requests.append(request)
        assert request.url.host == "spinkart.neetoform.com"
        assert request.headers["X-Api-Key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)

    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: guarded(**kwargs, transport=httpx.MockTransport(handle)))
    return requests, replies


def make(config, auth=AUTH):
    return NodeFactory.create_node(node_id="neetoform-test", node_type="automation-neetoform",
                                   node_data={"config": config, "credentials": auth})


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_neetoform_operations(case, transport):
    requests, replies = transport
    replies.append((case["response_status"], case["response"]))
    result = await make(case["config"]).execute({})
    assert result == {**case["response"], "status": "success"}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == "/api/external/v2" + case["path"]
    assert dict(request.url.params) == case["params"]
    assert (json.loads(request.content) if request.content else None) == case["body"]


async def test_neetoform_filters(transport):
    requests, replies = transport
    replies.append((200, {"submissions": []}))
    await make({"operation": "list_submissions", "form_id": "f1", "status": "all", "search": "customer",
                "submitted_after": "2026-10-01", "submitted_before": "2026-11-01", "page_number": 2, "order": "desc"}).execute({})
    params = dict(requests[0].url.params)
    assert params == {"status": "all", "search": "customer", "submitted_after": "2026-10-01", "submitted_before": "2026-11-01", "page_number": "2", "page_size": "30", "order": "desc"}


async def test_neetoform_form_choices_and_pagination(transport):
    requests, replies = transport
    replies.append((200, {"forms": [{"id": "f1", "title": "Feedback"}], "pagination": {"current_page_number": 2, "total_pages": 3}}))
    result = await node.NeetoformNode.load_field_options("form_id", AUTH, page_token="2", search="Feed")
    assert result == {"options": [{"value": "f1", "label": "Feedback"}], "next_page_token": "3"}
    assert requests[0].url.params["page_number"] == "2"
    assert requests[0].url.params["search"] == "Feed"


@pytest.mark.parametrize("status,error", [(401, "Could not authenticate, invalid API Key"), (403, "Access denied"), (422, "title is required")])
async def test_neetoform_provider_errors(transport, status, error):
    requests, replies = transport
    replies.append((status, {"error": error}))
    result = await make({"operation": "list_forms"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": error}
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [{}, [], {"forms": "wrong"}, {"forms": [None]}])
async def test_neetoform_malformed_response(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError, match="unexpected response|invalid resource"):
        await make({"operation": "list_forms"}).execute({})


async def test_neetoform_never_follows_redirects(transport):
    requests, replies = transport
    replies.append((302, {"error": "Moved"}))
    result = await make({"operation": "list_forms"}).execute({})
    assert result["status"] == "error"
    assert len(requests) == 1


async def test_neetoform_redacts_echoed_key_and_signing_secret(transport):
    requests, replies = transport
    secret = "webhook-private-signing-secret"
    replies.append((201, {"webhook": {"id": "w1", "debug": AUTH["api_key"] + secret}}))
    result = await make({"operation": "create_workspace_webhook", "endpoint": "https://example.com/hook", "secret": secret}).execute({})
    assert AUTH["api_key"] not in json.dumps(result)
    assert secret not in json.dumps(result)
    assert json.loads(requests[0].content)["webhook"]["secret"] == secret


@pytest.mark.parametrize("subdomain", ["evil.com", "https://acme.neetoform.com", "acme.neetoform.com@evil.com", "a/b", "-acme", "acme:443"])
def test_neetoform_refuses_untrusted_workspace(subdomain):
    with pytest.raises(ValueError):
        node.NeetoformAPIKeyCredential.model_validate({**AUTH, "subdomain": subdomain})


@pytest.mark.parametrize("config", [
    {"operation": "get_form", "form_id": "../webhooks"},
    {"operation": "delete_submissions", "form_id": "f1", "ids": []},
    {"operation": "create_form", "title": "Feedback"},
    {"operation": "create_workspace_webhook", "endpoint": "https://example.com", "events": ["unknown"]},
    {"operation": "list_forms", "page_number": 0},
    {"operation": "get_form_insights", "form_id": "f1", "start_date": "2026-10-01"},
])
def test_neetoform_rejects_invalid_configuration(config):
    assert node.NeetoformNode.validate_config({"config": config, "credentials": AUTH})["valid"] is False


def test_neetoform_editor_labels_do_not_become_api_fields():
    config = {"operation": "get_form", "form_id": "f1", "form_id__label": "Feedback", "credentialIds": {"neetoform_api_key": "saved"}}
    parsed = node.NeetoformNode.parse_config({"config": config, "credentials": AUTH})
    assert node._request_parts(parsed.config) == ("GET", "/forms/f1", {}, None)
    assert node.NeetoformNode.validate_config({"config": config, "credentials": AUTH})["valid"] is True


@pytest.mark.parametrize("api_key", ["", "   ", "https://example.com/key", "your-api-key", "bad\nkey"])
def test_neetoform_invalid_api_key(api_key):
    with pytest.raises(ValueError):
        node.NeetoformAPIKeyCredential.model_validate({**AUTH, "api_key": api_key})

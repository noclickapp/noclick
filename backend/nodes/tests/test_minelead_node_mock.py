"""Request contracts and parsers using Minelead's own published examples."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import minelead_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-minelead-key-42"
RESPONSES = json.loads((Path(__file__).parent / "fixtures/minelead/responses.json").read_text())["responses"]
CASES = [
    ({"operation": "search_emails", "domain": "domain.com", "max_emails": 4, "generic": False, "light_mode": True, "enrich": True, "deep": True, "max_deep_results": 10}, "GET /search", {"domain": "domain.com", "max-emails": "4", "generic": "false", "light-mode": "true", "enrich": "true", "deep": "true", "max_deep_results": "10"}),
    ({"operation": "enrich_email", "email": "john.smith@example.com", "name": "John Smith", "company": "example.com"}, "GET /enrich", {"email": "john.smith@example.com", "name": "John Smith", "company": "example.com"}),
    ({"operation": "get_buying_intent", "company": "Acme Corp", "domain": "acme.com", "refresh": "true", "level": 1}, "GET /buying-intent", {"company": "Acme Corp", "domain": "acme.com", "refresh": "true", "level": "1"}),
    ({"operation": "validate_email", "email": "email@domain.com", "firstname": "john", "lastname": "doe"}, "GET /validate", {"email": "email@domain.com", "firstname": "john", "lastname": "doe"}),
    ({"operation": "detect_disposable", "email": "test@10minutemail.com"}, "GET /detect-disposable", {"email": "test@10minutemail.com"}),
    ({"operation": "find_email", "domain": "example.com", "firstname": "john", "lastname": "smith"}, "GET /find", {"domain": "example.com", "firstname": "john", "lastname": "smith"}),
    ({"operation": "find_social_emails", "url": "https://www.youtube.com/@mkbhd"}, "GET /social-email-finder", {"url": "https://www.youtube.com/@mkbhd"}),
    ({"operation": "generate_leads", "tags": ["new york", "hotel"]}, "POST /tags", {"tags": ["new york", "hotel"]}),
    ({"operation": "list_leads"}, "GET /leads", {}),
    ({"operation": "add_leads", "leads": [{"email": "press@domain1.com"}, {"email": "info@domain2.com"}]}, "POST /leads", {"leads": [{"email": "press@domain1.com"}, {"email": "info@domain2.com"}]}),
    ({"operation": "delete_leads", "email": ["press@domain1.com", "info@domain3.com"]}, "DELETE /leads", {"email": ["press@domain1.com", "info@domain3.com"]}),
    ({"operation": "list_history", "start": 0, "limit": 7}, "GET /history", {"start": "0", "limit": "7"}),
    ({"operation": "list_campaigns"}, "GET /campaigns", {}),
    ({"operation": "list_recipients"}, "GET /campaigns-recipients", {}),
    ({"operation": "create_recipients", "list_name": "mylist", "emails": ["press@domain1.com", "info@domain2.com"]}, "POST /campaigns-recipients", {"list_name": "mylist", "emails": ["press@domain1.com", "info@domain2.com"]}),
    ({"operation": "edit_recipients", "id": 1, "action": "add", "emails": ["john@minelead.io", "jane@minelead.io"]}, "PUT /campaigns-recipients", {"id": 1, "operation": "add", "emails": ["john@minelead.io", "jane@minelead.io"]}),
    ({"operation": "get_account"}, "POST /account", {"key": TOKEN}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="minelead-test", node_type="automation-minelead", node_data={
        "config": config, "credentials": credential or {"credential_type": "minelead_api_key", "api_key": TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def handler(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,route,expected", CASES)
async def test_published_requests_and_provider_examples(monkeypatch, config, route, expected):
    requests = transport(monkeypatch, RESPONSES[route])
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1  # never silently repeat a paid operation
    request = requests[0]
    method, path = route.split()
    assert request.method == method
    assert request.url.host == "api.minelead.io" and request.url.path == "/v1" + path
    assert dict(request.url.params) == {"key": TOKEN, **(expected if method == "GET" else {})}
    if method != "GET":
        assert json.loads(request.content) == expected
    else:
        assert request.content == b""
    if config["operation"] == "get_account":
        assert "api_key" not in result["data"]["data"]
        assert result["data"]["data"]["email"] == "email_address@example.com"
    else:
        assert result["data"] == RESPONSES[route]
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 402, 429, 500])
async def test_errors_redact_key_and_never_follow_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, json={"status": "error", "message": "Unauthorized Access " + TOKEN}, headers={"Location": "https://example.com"}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Unauthorized Access [redacted]"
    assert len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"status": "error", "message": "Unauthorized Access"}, [], {}, {"status": "success", "data": {}}, {"status": "success", "data": {"api_key": TOKEN}}])
async def test_failed_or_missing_account_identity_is_not_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_network_and_malformed_json_are_sanitized(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout(str(request.url), request=request)
    requests = transport(monkeypatch, timeout)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result) and len(requests) == 1
    transport(monkeypatch, lambda request: httpx.Response(200, text="<html>" + TOKEN))
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"


def test_manual_credential_and_required_operation_fields():
    credential = native.MineleadAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "minelead_api_key"
    assert TOKEN not in repr(credential)
    for config in [{"operation": "search_emails"}, {"operation": "find_email", "domain": "example.com"}, {"operation": "edit_recipients", "id": 1, "action": "send", "emails": ["a@example.com"]}]:
        with pytest.raises(ValueError):
            node(config)


@pytest.mark.asyncio
async def test_optional_filters_are_omitted_and_history_is_one_page(monkeypatch):
    requests = transport(monkeypatch, RESPONSES["GET /search"])
    await node({"operation": "search_emails", "domain": "example.com"}).execute({})
    assert dict(requests[0].url.params) == {"key": TOKEN, "domain": "example.com"}
    requests = transport(monkeypatch, RESPONSES["GET /history"])
    result = await node({"operation": "list_history", "start": 7, "limit": 7}).execute({})
    assert result["status"] == "success" and len(requests) == 1
    assert requests[0].url.params["start"] == "7"

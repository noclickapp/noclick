"""Offline request, parser, manual-connect and failure coverage for WhoisFreaks."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import whoisfreaks_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-whoisfreaks-key"
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/whoisfreaks/operations.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="whoisfreaks-test",
        node_type="automation-whoisfreaks",
        node_data={
            "config": config,
            "credentials": {"credential_type": "whoisfreaks_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, body=None, status=200, text=None):
    requests = []

    def respond(request):
        requests.append(request)
        return (
            httpx.Response(status, text=text)
            if text is not None
            else httpx.Response(status, json=body)
        )

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", FIXTURES)
async def test_every_operation_routes_query_and_body(monkeypatch, operation):
    fixture = FIXTURES[operation]
    body = {"apiKey": TOKEN, "apiCredits": {"totalCredits": 500, "servedRequest": 12}}
    requests = transport(
        monkeypatch,
        body,
        text="secondary-key-generated" if operation == "rotate_api_key" else None,
    )
    result = await node(fixture["config"]).run({})
    assert result["status"] == "success", result
    request = requests[0]
    assert len(requests) == 1 and request.method == fixture["method"]
    assert (
        request.url.host == "api.whoisfreaks.com"
        and request.url.path == fixture["path"]
    )
    route = native.ROUTES[operation]
    config = node(fixture["config"]).config.config.model_dump(exclude_none=True)
    expected = {
        k: str(config[k]).lower() if isinstance(config[k], bool) else str(config[k])
        for k in route["query"]
        if k in config
    }
    expected["apiKey"] = TOKEN
    if route["format"]:
        expected["format"] = "json"
    assert dict(request.url.params) == expected
    if route["body"]:
        assert json.loads(request.content) == {
            k: config[k] for k in route["body"] if k in config
        }
    else:
        assert not request.content
    assert TOKEN not in str(result)
    if operation == "get_account_usage":
        assert result["items"] and "500" in str(result["items"])
    if operation == "rotate_api_key":
        assert (
            result["result"] == "secondary-key-generated"
            and not result["credential_updated"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_http_errors_never_echo_key_or_url(monkeypatch, status):
    requests = transport(
        monkeypatch, {"message": "Provided API key is invalid. " + TOKEN}, status
    )
    result = await node({"operation": "get_account_usage"}).run({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        "not-json-object",
        {"status": False, "message": "Invalid " + TOKEN},
        {"apiKey": TOKEN},
    ],
)
async def test_usage_cannot_verify_an_empty_or_error_response(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({"operation": "get_account_usage"}).run({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_provider_pagination_is_preserved_and_not_followed(monkeypatch):
    body = {
        "status": True,
        "current_page": 2,
        "total_pages": 8,
        "domains": ["whoisfreaks.com"],
    }
    requests = transport(monkeypatch, body)
    result = await node(
        {"operation": "get_reverse_whois", "keyword": "whoisfreaks", "page": 2}
    ).run({})
    assert result["data"] == body and len(requests) == 1


@pytest.mark.asyncio
async def test_transport_error_does_not_leak_query(monkeypatch):
    def client(**kwargs):
        async def fail(request):
            raise httpx.ConnectError(str(request.url))

        return httpx.AsyncClient(transport=httpx.MockTransport(fail), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    result = await node({"operation": "get_account_usage"}).run({})
    assert result["status"] == "error" and TOKEN not in str(result)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_live_dns"},
        {"operation": "bulk_dns"},
        {"operation": "get_domain_typos"},
        {"operation": "bulk_domain_availability", "tld": ["com"]},
        {
            "operation": "bulk_domain_availability",
            "domainNames": ["a.com"],
            "tld": ["com"],
        },
        {"operation": "bulk_whois", "domainNames": []},
        {"operation": "bulk_ip_geolocation", "ips": ["8.8.8.8"] * 101},
        {"operation": "get_reverse_whois", "keyword": "test", "page": 0},
    ],
)
def test_target_modes_and_batch_bounds(config):
    with pytest.raises(ValidationError):
        native.WhoisfreaksFullConfig.model_validate(
            {"config": config, "credentials": {"api_key": TOKEN}}
        )


def test_manual_credential_default_and_hidden_secret():
    credential = native.WhoisfreaksAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "whoisfreaks_api_key"
    schema = credential.model_json_schema()
    assert schema["properties"]["api_key"]["ui:widget"] == "password"
    assert "credential_type" not in schema["required"]
    assert native.WhoisfreaksNode.connection_evidence.operation == "get_account_usage"


DOCUMENTED = json.loads((Path(__file__).parent / "fixtures/whoisfreaks/responses.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", [
    ("get_live_whois", "GET /v2.0/whois/live"),
    ("get_historical_whois", "GET /v2.0/whois/history"),
    ("get_subdomains", "GET /v1.0/subdomains"),
    ("get_ip_whois", "GET /v1.0/ip-whois"),
])
async def test_provider_documented_responses(monkeypatch, operation, route):
    body = DOCUMENTED[route]["body"]
    transport(monkeypatch, body)
    result = await node(FIXTURES[operation]["config"]).run({})
    assert result["status"] == "success"
    assert result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("config,body", [
    ({"operation": "bulk_dns", "domainNames": ["whoisfreaks.com"], "ipAddresses": ["8.8.8.8"]},
     {"domainNames": ["whoisfreaks.com"], "ipAddresses": ["8.8.8.8"]}),
    ({"operation": "bulk_domain_availability", "domain": "whoisfreaks.com", "tld": ["edu", "pk"]}, {"tld": ["edu", "pk"]}),
])
async def test_alternative_batch_modes(monkeypatch, config, body):
    requests = transport(monkeypatch, {"status": True})
    assert (await node(config).run({}))["status"] == "success"
    assert json.loads(requests[0].content) == body

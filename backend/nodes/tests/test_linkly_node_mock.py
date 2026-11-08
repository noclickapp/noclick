"""Exercise actual Linkly factory dispatch without contacting a provider account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import linkly_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "synthetic-linkly-api-key-42"
CREDENTIAL = {"credential_type": "linkly_api_key", "api_key": TOKEN}
RESPONSES = json.loads(
    (Path(__file__).parent / "fixtures/linkly/responses.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="linkly-test",
        node_type="automation-linkly",
        node_data={"config": config, "credentials": CREDENTIAL},
    )


def transport(monkeypatch, response):
    requests = []

    def reply(request):
        requests.append(request)
        return (
            response(request)
            if callable(response)
            else httpx.Response(200, json=response)
        )

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Expected routes are independent of the implementation's route table.
CASES = [
    ({"operation": "list_workspaces"}, "GET", "/api/v1/workspaces", None),
    (
        {"operation": "list_links", "workspace_id": "42", "page": 2, "page_size": 25},
        "GET",
        "/api/v1/workspace/42/list_links",
        None,
    ),
    ({"operation": "get_workspace_link", "id": 24}, "GET", "/api/v1/get_link/24", None),
    (
        {
            "operation": "create_or_update_workspace_link",
            "workspace_id": "42",
            "url": "https://www.example.com",
            "enabled": False,
            "name": "Summer promo",
        },
        "POST",
        "/api/v1/workspace/42/links",
        {"url": "https://www.example.com", "enabled": False, "name": "Summer promo"},
    ),
    (
        {"operation": "delete_link", "workspace_id": "42", "id": 24},
        "DELETE",
        "/api/v1/workspace/42/links/24",
        None,
    ),
    (
        {"operation": "delete_links", "workspace_id": "42", "ids": [24, 25]},
        "DELETE",
        "/api/v1/workspace/42/links",
        {"ids": [24, 25]},
    ),
    (
        {"operation": "restore_links", "workspace_id": "42", "ids": [24, 25]},
        "POST",
        "/api/v1/workspace/42/links/restore",
        {"ids": [24, 25]},
    ),
    (
        {"operation": "export_links", "workspace_id": "42"},
        "GET",
        "/api/v1/workspace/42/links/export",
        None,
    ),
    (
        {"operation": "list_domains", "workspace_id": "42"},
        "GET",
        "/api/v1/workspace/42/domains",
        None,
    ),
    (
        {
            "operation": "create_domain_in_workspace",
            "workspace_id": "42",
            "name": "links.example.com",
        },
        "POST",
        "/api/v1/workspace/42/domains",
        {"name": "links.example.com"},
    ),
    (
        {"operation": "delete_domain", "workspace_id": "42", "domain_id": "33"},
        "DELETE",
        "/api/v1/workspace/42/domains/33",
        None,
    ),
    (
        {
            "operation": "update_domain_favicon",
            "workspace_id": "42",
            "id": "33",
            "favicon_url": "https://example.com/favicon.png",
        },
        "PATCH",
        "/api/v1/workspace/42/domains/33/favicon",
        {"favicon_url": "https://example.com/favicon.png"},
    ),
    (
        {"operation": "get_clicks", "workspace_id": "42", "bots": False},
        "GET",
        "/api/v1/workspace/42/clicks",
        None,
    ),
    (
        {"operation": "get_click_counters", "workspace_id": "42", "counter": "country"},
        "GET",
        "/api/v1/workspace/42/clicks/counters/country",
        None,
    ),
    (
        {
            "operation": "list_conversions",
            "workspace_id": "42",
            "since": "2020-01-01",
            "after": "01KYPH20SEJY4HQSCPMWW60QE0",
        },
        "GET",
        "/api/v1/conversions",
        None,
    ),
    (
        {
            "operation": "create_conversion",
            "workspace_id": "42",
            "event_name": "purchase",
            "amount_cents": 4999,
            "event_id": "shopify-1234",
        },
        "POST",
        "/api/v1/conversions",
        {"event_name": "purchase", "amount_cents": 4999, "event_id": "shopify-1234"},
    ),
    (
        {"operation": "list_link_webhooks", "link_id": 12345},
        "GET",
        "/api/v1/link/12345/webhooks",
        None,
    ),
    (
        {
            "operation": "subscribe_webhook_to_link",
            "link_id": 12345,
            "url": "https://hooks.example.com/abc123",
        },
        "POST",
        "/api/v1/link/12345/webhooks",
        {"url": "https://hooks.example.com/abc123"},
    ),
    (
        {
            "operation": "unsubscribe_webhook_from_link",
            "link_id": 12345,
            "hook_id": "https%3A%2F%2Fhooks.example.com%2Fabc123",
        },
        "DELETE",
        "/api/v1/link/12345/webhooks/https://hooks.example.com/abc123",
        None,
    ),
    (
        {"operation": "list_workspace_webhooks", "workspace_id": 42},
        "GET",
        "/api/v1/workspace/42/webhooks",
        None,
    ),
    (
        {
            "operation": "subscribe_webhook_to_workspace",
            "workspace_id": 42,
            "url": "https://hooks.example.com/abc123",
        },
        "POST",
        "/api/v1/workspace/42/webhooks",
        {"url": "https://hooks.example.com/abc123"},
    ),
    (
        {
            "operation": "unsubscribe_webhook_from_workspace",
            "workspace_id": 42,
            "hook_id": "https://hooks.example.com/abc123",
        },
        "DELETE",
        "/api/v1/workspace/42/webhooks/https://hooks.example.com/abc123",
        None,
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config,method,path,body", CASES, ids=[v[0]["operation"] for v in CASES]
)
async def test_linkly_exact_method_route_auth_and_body(
    monkeypatch, config, method, path, body
):
    requests = transport(monkeypatch, {"id": 24})
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.host == "api.linklyhq.com"
    assert req.url.path == path
    assert req.url.params["api_key"] == TOKEN and "authorization" not in req.headers
    assert (json.loads(req.content) if req.content else None) == body
    if "conversions" in path:
        assert req.url.params["workspace_id"] == "42"
    if "hook_id" in config:
        raw_path = req.url.raw_path.decode().split("?")[0]
        assert raw_path.endswith("https%3A%2F%2Fhooks.example.com%2Fabc123")
        assert "%253A" not in raw_path


@pytest.mark.asyncio
async def test_linkly_deep_object_filters_false_values_and_pagination(monkeypatch):
    response = {"links": [], "page_number": 2, "total_pages": 3, "total_entries": 52}
    requests = transport(monkeypatch, response)
    result = await node(
        {
            "operation": "list_links",
            "workspace_id": "42",
            "page": 2,
            "page_size": 25,
            "deleted": False,
            "filter": {"utm_campaign": "Summer + café"},
        }
    ).execute({})
    assert result["data"] == response and len(requests) == 1
    assert dict(requests[0].url.params) == {
        "api_key": TOKEN,
        "page": "2",
        "page_size": "25",
        "deleted": "false",
        "filter[utm_campaign]": "Summer + café",
    }


@pytest.mark.asyncio
async def test_linkly_explicit_null_clears_nullable_link_field(monkeypatch):
    requests = transport(monkeypatch, {"id": 24})
    await node(
        {
            "operation": "create_or_update_workspace_link",
            "workspace_id": "42",
            "id": 24,
            "url": "https://www.example.com",
            "note": None,
        }
    ).execute({})
    assert json.loads(requests[0].content) == {
        "id": 24,
        "url": "https://www.example.com",
        "note": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (200, {"id": "existing", "attributed": True}),
        (201, {"id": "new", "attributed": True}),
        (202, {"attributed": False}),
    ],
)
async def test_linkly_conversion_preserves_attribution_and_never_retries(
    monkeypatch, status, body
):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, json=body))
    result = await node(
        {
            "operation": "create_conversion",
            "workspace_id": "42",
            "event_name": "purchase",
        }
    ).execute({})
    assert result == {"status": "success", "http_status": status, "data": body}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("key,example", list(RESPONSES.items()))
async def test_linkly_provider_authored_examples_are_preserved(
    monkeypatch, key, example
):
    matching = next(
        (
            (cfg, method, path, body)
            for cfg, method, path, body in CASES
            if native.ROUTES[cfg["operation"]][0:2]
            == (key.split(" ", 1)[0], key.split(" ", 1)[1])
        ),
        None,
    )
    assert matching is not None
    transport(monkeypatch, example["body"])
    assert (await node(matching[0]).execute({}))["data"] == example["body"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_linkly_rejections_preserve_provider_text_redact_key_and_do_not_retry(
    monkeypatch, status
):
    requests = transport(
        monkeypatch,
        lambda req: httpx.Response(
            status,
            json={"error": "Rejected " + TOKEN},
            headers={"Location": "https://example.com"},
        ),
    )
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert (
        "Rejected" in result["error"]
        and TOKEN not in str(result)
        and len(requests) == 1
    )


@pytest.mark.asyncio
async def test_linkly_html_and_network_errors_do_not_prove_connection(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, text="<html>Sign in</html>"))
    assert (await node({"operation": "list_workspaces"}).execute({}))[
        "status"
    ] == "error"

    def fail(req):
        raise httpx.ConnectError("url contains " + TOKEN)

    transport(monkeypatch, fail)
    result = await node({"operation": "list_workspaces"}).execute({})
    assert result["status"] == "error" and TOKEN not in str(result)


def test_linkly_schema_registration_evidence_and_required_api_key_workspace():
    assert NODE_REGISTRY["automation-linkly"] is native.LinklyNode
    assert native.LinklyNode.connection_evidence.operation == "list_workspaces"
    assert len(CASES) == len(native.ROUTES) == 22
    for config in [
        {"operation": "list_conversions"},
        {"operation": "create_conversion", "event_name": "purchase"},
        {"operation": "delete_links", "workspace_id": "42", "ids": []},
        {"operation": "list_links", "workspace_id": "../bad"},
        {"operation": "get_clicks", "workspace_id": "42", "format": "csv"},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            native.LinklyNode.parse_config(
                {"config": config, "credentials": CREDENTIAL}
            )

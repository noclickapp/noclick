"""SecurityTrails contract regressions at the HTTP boundary; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import securitytrails_node as native
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory

KEY = "synthetic-securitytrails-key-936"
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/securitytrails/v1_examples.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="securitytrails-test",
        node_type="automation-securitytrails",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "securitytrails_api_key",
                "api_key": KEY,
            },
        },
    )


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


# Independent expected method/path pairs, with provider-documented v1 examples.
CASES = [
    ("get_usage", {}, "GET", "/v1/account/usage"),
    ("get_domain", {"hostname": "oracle.com"}, "GET", "/v1/domain/oracle.com"),
    ("explore_ips", {"ipaddress": "8.8.8.8"}, "GET", "/v1/ips/nearby/8.8.8.8"),
    (
        "get_domain_whois",
        {"hostname": "securitytrails.com"},
        "GET",
        "/v1/domain/securitytrails.com/whois",
    ),
    (
        "get_ip_useragents",
        {"ipaddress": "192.0.2.1"},
        "GET",
        "/v1/ips/192.0.2.1/useragents",
    ),
    (
        "search_domains",
        {"filter": {"apex_domain": "oracle.com"}, "include_ips": True, "page": 2},
        "POST",
        "/v1/domains/list",
    ),
    (
        "get_subdomains",
        {"hostname": "oracle.com"},
        "GET",
        "/v1/domain/oracle.com/subdomains",
    ),
    (
        "get_domain_statistics",
        {"filter": {"ipv4": "8.8.8.8"}},
        "POST",
        "/v1/domains/stats",
    ),
    (
        "get_domain_tags",
        {"hostname": "oracle.com"},
        "GET",
        "/v1/domain/oracle.com/tags",
    ),
    (
        "get_dns_history",
        {"hostname": "oracle.com", "type": "a", "page": 3},
        "GET",
        "/v1/history/oracle.com/dns/a",
    ),
    (
        "get_associated_domains",
        {"hostname": "google.com", "page": 2},
        "GET",
        "/v1/domain/google.com/associated",
    ),
    ("search_ips", {"query": "ptr_part = 'ns1'", "page": 2}, "POST", "/v1/ips/list"),
    (
        "get_ip_statistics",
        {"query": "ptr_part = 'amazon.com'"},
        "POST",
        "/v1/ips/stats",
    ),
    ("get_ip_whois", {"ipaddress": "1.1.1.1"}, "GET", "/v1/ips/1.1.1.1/whois"),
    ("list_projects", {}, "GET", "/v2/projects"),
    (
        "search_assets",
        {
            "project_id": "p1",
            "filter": {"asset_properties": {"asset_id": {"eq": "example.com"}}},
            "pagination": {"limit": 10, "next_cursor": "opaque-cursor"},
            "enrichments": ["whois", "dns_records"],
        },
        "POST",
        "/v2/projects/p1/assets/_search",
    ),
    (
        "list_asset_exposures",
        {"project_id": "p1", "asset_id": "example.com"},
        "GET",
        "/v2/projects/p1/assets/example.com/exposures",
    ),
    ("list_project_tags", {"project_id": "p1"}, "GET", "/v2/projects/p1/tags"),
    (
        "get_tag_task",
        {"project_id": "p1", "task_id": "t1"},
        "GET",
        "/v2/projects/p1/tags/_task_status/t1",
    ),
    (
        "apply_asset_tag",
        {"project_id": "p1", "asset_id": "example.com", "tag_name": "High Priority"},
        "PUT",
        "/v2/projects/p1/assets/example.com/tags/High Priority",
    ),
    (
        "remove_asset_tag",
        {"project_id": "p1", "asset_id": "example.com", "tag_name": "High Priority"},
        "DELETE",
        "/v2/projects/p1/assets/example.com/tags/High Priority",
    ),
    (
        "create_project_tag",
        {"project_id": "p1", "tag_name": "High Priority"},
        "POST",
        "/v2/projects/p1/tags/High Priority",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,config,method,path", CASES, ids=[case[0] for case in CASES]
)
async def test_operation_uses_one_contract_route_and_preserves_response(
    monkeypatch, operation, config, method, path
):
    body = EXAMPLES.get(operation, {}).get(
        "body", {"data": [], "meta": {"pagination": {"next_cursor": "next-page"}}}
    )
    requests = transport(monkeypatch, body)
    result = await node({"operation": operation, **config}).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.securitytrails.com"
    if path.startswith("/v1/"):
        assert request.url.params["apikey"] == KEY
    else:
        assert request.headers["apikey"] == KEY and "apikey" not in request.url.params
    if "page" in config:
        assert request.url.params["page"] == str(config["page"])
    if "cursor" in config:
        assert request.url.params["cursor"] == config["cursor"]
    if "additional_fields" in config:
        assert (
            request.url.params.get_list("additional_fields")
            == config["additional_fields"]
        )
    if "filter" in config or "query" in config:
        assert json.loads(request.content) == {
            key: config[key]
            for key in ("filter", "query", "pagination", "enrichments")
            if key in config
        }
    else:
        assert request.content == b""
    assert KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["apply_asset_tag", "remove_asset_tag"])
async def test_asynchronous_tag_acknowledgement_does_not_claim_completion(
    monkeypatch, operation
):
    body = {
        "data": {
            "complete": False,
            "task_ids": ["task-42"],
            "assets": ["example.com"],
            "add_tags": ["triage"],
        }
    }
    requests = transport(monkeypatch, body)
    result = await node(
        {
            "operation": operation,
            "project_id": "p1",
            "asset_id": "example.com",
            "tag_name": "triage",
        }
    ).execute({})
    assert result["data"] == body and len(requests) == 1
    assert "readback_verified" not in result and "complete" not in result


@pytest.mark.asyncio
async def test_account_evidence_shows_usage_and_rejects_unrecognised_envelope(
    monkeypatch,
):
    transport(monkeypatch, EXAMPLES["get_usage"]["body"])
    result = await node({"operation": "get_usage"}).execute({})
    assert result["items"] == [{"name": "Monthly API usage: 100 of 10000 requests"}]
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match="incomplete account usage"):
        await node({"operation": "get_usage"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_provider_errors_are_not_success_or_retried_and_redact_key(
    monkeypatch, status
):
    requests = transport(monkeypatch, {"message": "rejected " + KEY}, status=status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_usage"}).execute({})
    assert str(status) in str(error.value) and KEY not in str(error.value)
    assert "rejected" in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_transport_error_never_echoes_query_secret(monkeypatch):
    transport(monkeypatch, httpx.ConnectError("request url contains " + KEY))
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_usage"}).execute({})
    assert KEY not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [[], "not JSON object", {"error": "rejected"}, {"errors": ["denied"]}]
)
async def test_invalid_success_is_not_accepted(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="invalid response"):
        await node({"operation": "get_domain", "hostname": "example.com"}).execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_domain", "hostname": "https://example.com"},
        {"operation": "get_ip_whois", "ipaddress": "not-an-ip"},
        {"operation": "get_dns_history", "hostname": "example.com", "type": "bad"},
        {
            "operation": "get_dns_history",
            "hostname": "example.com",
            "type": "a",
            "page": 0,
        },
        {
            "operation": "list_asset_exposures",
            "project_id": "../p1",
            "asset_id": "example.com",
        },
        {"operation": "create_project_tag", "project_id": "p1", "tag_name": ".."},
        {
            "operation": "search_assets",
            "project_id": "p1",
            "pagination": {"limit": 1001},
        },
    ],
)
def test_invalid_input_is_rejected_before_http(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_typed_in_credential_has_default_discriminator_and_one_required_field():
    shaped, errors, _ = shape_credential("securitytrails_api_key", {"api_key": KEY})
    assert not errors and shaped["api_key"] == KEY
    assert (
        native.SecurityTrailsAPIKeyCredential(api_key=KEY).credential_type
        == "securitytrails_api_key"
    )
    assert (
        native.SecurityTrailsAPIKeyCredential(api_key="  " + KEY + " ").api_key == KEY
    )
    assert native.SecurityTrailsNode.connection_evidence.operation == "get_usage"

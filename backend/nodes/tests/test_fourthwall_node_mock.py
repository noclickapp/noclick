"""Fourthwall HTTP contracts; no live credentials are used."""
import json
from pathlib import Path
import httpx
import pytest
from nodes.core.base import ConfigValidationError
from nodes import fourthwall_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads(
    (Path(__file__).parent / "fixtures/fourthwall/operations.json").read_text()
)
CREDENTIAL = {
    "credential_type": "fourthwall_api",
    "username": "shop-api-user",
    "password": "synthetic-shop-password-42",
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="fourthwall-test",
        node_type="automation-fourthwall",
        node_data={"config": config, "credentials": CREDENTIAL},
    )


def transport(monkeypatch, response):
    requests = []

    def handle(request):
        requests.append(request)
        return response(request) if callable(response) else response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_every_operation_calls_one_documented_endpoint(monkeypatch, operation):
    case = CASES[operation]
    reply = (
        {"name": "My shop", "id": "shop-123"}
        if operation == "get_current_shop"
        else {"results": [], "total": 0}
    )
    status = 204 if operation == "archive_product" else 200
    requests = transport(
        monkeypatch,
        httpx.Response(status, json=reply) if status == 200 else httpx.Response(204),
    )
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == (reply if status == 200 else None)
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case["method"] and req.url.host == "api.fourthwall.com"
    expected_path = case["path"]
    for key, value in case["config"].items():
        expected_path = expected_path.replace("{" + key + "}", str(value))
    assert req.url.path == expected_path
    assert (
        req.headers["authorization"]
        == httpx.BasicAuth(CREDENTIAL["username"], CREDENTIAL["password"])._auth_header
    )
    if operation == "create_collection":
        assert json.loads(req.content) == {
            "name": "My collection",
            "description": "My collection description",
            "offerIds": [],
        }
    if operation == "update_product_state":
        assert json.loads(req.content) == {"state": "PUBLIC"}
    assert CREDENTIAL["password"] not in str(result)


@pytest.mark.asyncio
async def test_filters_arrays_and_provider_pagination_preserved(monkeypatch):
    body = {
        "results": [{"id": "order-1"}],
        "paging": {"page": 2, "size": 5},
        "total": 42,
    }
    requests = transport(monkeypatch, httpx.Response(200, json=body))
    result = await node(
        {
            "operation": "list_orders",
            "page": 2,
            "size": 5,
            "email": "supporter@fourthwall.com",
            "createdAt_gt": "2020-08-13T09:05:36.939Z",
            "status": ["CONFIRMED", "SHIPPED"],
        }
    ).execute({})
    assert result["data"] == body
    assert requests[0].url.params.get_list("status") == ["CONFIRMED", "SHIPPED"]
    assert requests[0].url.params["createdAt[gt]"].startswith("2020-08-13T09:05:36.939")
    assert requests[0].url.params["page"] == "2"


@pytest.mark.asyncio
async def test_false_and_empty_list_are_sent(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={"id": "collection-1"}))
    await node(
        {
            "operation": "update_collection_availability",
            "collectionId": "collection-1",
            "available": False,
        }
    ).execute({})
    await node(
        {
            "operation": "update_collection_products",
            "collectionId": "collection-1",
            "offerIds": [],
        }
    ).execute({})
    assert json.loads(requests[0].content) == {"available": False}
    assert json.loads(requests[1].content) == {"offerIds": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_rejections_not_success_or_retried(monkeypatch, status):
    requests = transport(
        monkeypatch, httpx.Response(status, text="Rejected " + CREDENTIAL["password"])
    )
    result = await node({"operation": "get_current_shop"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1
    from nodes.core import connection_evidence as evidence

    with pytest.raises(evidence._ProviderRefused, match=f"HTTP {status}") as rejected:
        evidence._raise_if_error_envelope(result)
    if status in (401, 403):
        assert evidence._looks_like_auth_rejection(str(rejected.value))


@pytest.mark.asyncio
async def test_array_response_and_timeout(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json=[{"id": "tier-1"}]))
    assert (await node({"operation": "list_tiers"}).execute({}))["data"] == [
        {"id": "tier-1"}
    ]

    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    requests = transport(monkeypatch, timeout)
    assert (await node({"operation": "get_current_shop"}).execute({}))[
        "status"
    ] == "error"
    assert len(requests) == 1


def test_credential_default_and_invalid_inputs():
    assert (
        native.FourthwallAPICredential(
            username="shop-api-user", password="secret-42"
        ).credential_type
        == "fourthwall_api"
    )
    for config in [
        {"operation": "update_product_state", "productId": "p", "state": "ARCHIVED"},
        {"operation": "list_orders", "size": 101},
        {"operation": "get_product", "productId": ".."},
        {"operation": "update_collection_products", "collectionId": "col"},
    ]:
        with pytest.raises(ConfigValidationError):
            native.FourthwallNode.parse_config(
                {"config": config, "credentials": CREDENTIAL}
            )

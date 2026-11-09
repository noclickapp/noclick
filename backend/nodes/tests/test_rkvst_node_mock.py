"""Exercise Rkvst through its native factory with provider examples.

The fake HTTP boundary records requests; no account or real token is used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import rkvst_node as native
from nodes.core.registry import NodeFactory
from nodes.core.connection_evidence import collect_evidence

TOKEN = "synthetic-rkvst-token-42"
ASSET = "add30235-1424-4fda-840a-d5ef82c4c96f"
EVENT = "11bf5b37-e0b8-42e0-8dcf-dc8c4aefc000"
LOCATION = "08838336-c357-460d-902a-3aba9528dd22"
POLICY = "e5fbb0ba-6f36-4aa0-95a0-c7d13b73af88"
FIXTURES = Path(__file__).parent / "fixtures" / "rkvst"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential():
    return {"credential_type": native.FAMILY, "access_token": TOKEN}


def node(config):
    config = {k: json.dumps(v) if k in {"attributes", "event_attributes", "asset_attributes"} and isinstance(v, dict) else v for k, v in config.items()}
    return NodeFactory.create_node(node_id="rkvst-test", node_type="automation-rkvst",
        node_data={"config": config, "credentials": credential()})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_assets"}, "GET", "/archivist/v2/assets"),
    ({"operation": "get_asset", "asset_id": ASSET}, "GET", f"/archivist/v2/assets/{ASSET}"),
    ({"operation": "create_asset", "attributes": {"arc_display_name": "My Garden Fence"}}, "POST", "/archivist/v2/assets"),
    ({"operation": "list_events"}, "GET", "/archivist/v2/assets/-/events"),
    ({"operation": "get_event", "asset_id": ASSET, "event_id": EVENT}, "GET", f"/archivist/v2/assets/{ASSET}/events/{EVENT}"),
    ({"operation": "create_event", "asset_id": ASSET, "event_attributes": {"arc_display_type": "Paint"}}, "POST", f"/archivist/v2/assets/{ASSET}/events"),
    ({"operation": "get_asset_public_url", "asset_id": ASSET}, "GET", f"/archivist/v2/assets/{ASSET}:publicurl"),
    ({"operation": "get_event_public_url", "asset_id": ASSET, "event_id": EVENT}, "GET", f"/archivist/v2/assets/{ASSET}/events/{EVENT}:publicurl"),
    ({"operation": "list_locations"}, "GET", "/archivist/v2/locations"),
    ({"operation": "get_location", "location_id": LOCATION}, "GET", f"/archivist/v2/locations/{LOCATION}"),
    ({"operation": "create_location", "display_name": "Macclesfield, Cheshire", "latitude": 53.2546799, "longitude": -2.1213956}, "POST", "/archivist/v2/locations"),
    ({"operation": "update_location", "location_id": LOCATION, "latitude": 0}, "PATCH", f"/archivist/v2/locations/{LOCATION}"),
    ({"operation": "delete_location", "location_id": LOCATION}, "DELETE", f"/archivist/v2/locations/{LOCATION}"),
    ({"operation": "get_location_permissions", "location_id": LOCATION}, "GET", f"/archivist/v2/locations/{LOCATION}/permissions"),
    ({"operation": "list_access_policies"}, "GET", "/archivist/iam/v1/access_policies"),
    ({"operation": "get_access_policy", "policy_id": POLICY}, "GET", f"/archivist/iam/v1/access_policies/{POLICY}"),
    ({"operation": "get_tenant"}, "GET", "/archivist/v1/tenancies/self"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_each_operation_sends_one_provider_request(monkeypatch, config, method, path):
    examples = {
        "list_assets": "v2ListAssetsResponse", "get_asset": "v2AssetResponse", "create_asset": "v2AssetResponse",
        "get_event": "v2EventResponse", "create_event": "v2EventResponse", "list_events": "v2ListEventsResponse",
        "get_asset_public_url": "v2PublicAssetURLResponse", "get_event_public_url": "v2PublicEventURLResponse",
        "list_locations": "v2ListLocationsResponse", "get_location": "archivistv2Location",
        "create_location": "archivistv2Location", "update_location": "archivistv2Location",
        "get_location_permissions": "v2LocationPermissions", "list_access_policies": "v1ListIAMAccessPoliciesResponse",
        "get_access_policy": "v1IAMAccessPolicy", "get_tenant": "v1AdminTenantResponse",
    }
    name = examples.get(config["operation"])
    body = json.loads((FIXTURES / (name + ".json")).read_text()) if name else {}
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    assert request.url.host == "app.datatrails.ai"
    assert (request.method, request.url.path) == (method, path)
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(result)
    if method == "POST" and "event_attributes" in config:
        payload = json.loads(request.content)
        assert payload["operation"] == "Record" and payload["behaviour"] == "RecordEvidence"
        assert payload["event_attributes"] == config["event_attributes"] and "event_operation" not in payload
    if method == "POST" and "attributes" in config:
        assert json.loads(request.content)["attributes"] == config["attributes"]
    if method == "PATCH":
        assert json.loads(request.content) == {"latitude": 0.0}
        assert request.url.params["mask"] == "latitude"
    if method != "GET":
        assert result["write_acknowledged"] and result["readback_verified"] is False


@pytest.mark.asyncio
async def test_documented_asset_page_and_continuation(monkeypatch):
    body = json.loads((FIXTURES / "v2ListAssetsResponse.json").read_text())
    requests = transport(monkeypatch, body, status=206)
    result = await node({"operation": "list_assets", "page_token": "abc+/=", "page_size": 25}).execute({})
    assert result["items"][0]["attributes"]["arc_display_name"] == "My Garden Fence"
    assert result["has_more"] and not result["complete"] and result["next_page_token"] == "abcd"
    assert dict(requests[0].url.params) == {"page_size": "25", "page_token": "abc+/="}


@pytest.mark.asyncio
async def test_event_filter_uses_provider_operation(monkeypatch):
    requests = transport(monkeypatch, {"events": [], "next_page_token": ""})
    result = await node({"operation": "list_events", "event_operation": "Record"}).execute({})
    assert requests[0].url.params["operation"] == "Record" and "event_operation" not in requests[0].url.params
    assert result["items"] == [] and result["complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 429, 500])
async def test_rejections_preserve_status_and_redact_token(monkeypatch, code):
    transport(monkeypatch, {"message": "denied " + TOKEN}, status=code)
    result = await node({"operation": "list_assets"}).execute({})
    assert result["status"] == "error" and result["status_code"] == code
    assert TOKEN not in str(result) and "denied" in result["message"]


@pytest.mark.asyncio
async def test_connection_evidence_detects_rejection(monkeypatch):
    transport(monkeypatch, {"message": "Unauthorized"}, status=401)
    result = await collect_evidence(node_type="automation-rkvst", user_id="rkvst-test-user", credential_data=credential())
    assert result.reachable is False


@pytest.mark.asyncio
async def test_redacts_success_response(monkeypatch):
    transport(monkeypatch, {"assets": [{"identity": TOKEN, "attributes": {"name": TOKEN}}]})
    assert TOKEN not in str(await node({"operation": "list_assets"}).execute({}))


@pytest.mark.parametrize("asset_id", ["../tenancies/self", "https://evil.test", "x?query=y", "x/events/y", "x#fragment"])
def test_resource_ids_cannot_change_route(asset_id):
    with pytest.raises(ValidationError):
        native.GetAsset(asset_id=asset_id)


def test_manual_credential_shape():
    shaped = native.RkvstBearerTokenCredential(access_token="  " + TOKEN + "  ")
    assert shaped.credential_type == "rkvst_bearer_token" and shaped.access_token == TOKEN
    for value in ["https://example.test", "Bearer " + TOKEN, "<token>"]:
        with pytest.raises(ValidationError):
            native.RkvstBearerTokenCredential(access_token=value)


@pytest.mark.asyncio
async def test_write_timeout_does_not_retry(monkeypatch):
    requests = []
    def fail(request):
        requests.append(request)
        raise httpx.ReadTimeout("private " + TOKEN)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fail), **kw))
    with pytest.raises(ValueError, match="check the provider") as exc:
        await node({"operation": "create_asset", "attributes": {}}).execute({})
    assert len(requests) == 1 and TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_tenant_response_does_not_expose_sso_secret(monkeypatch):
    transport(monkeypatch, {"identity": "tenant/example", "enterprise_sso_config": {"client_id": "public-id", "client_secret": "provider-secret"}})
    result = await node({"operation": "get_tenant"}).execute({})
    assert result["data"]["enterprise_sso_config"] == {"client_id": "public-id"}
    assert "provider-secret" not in str(result)


def test_attribute_editor_requires_json_object_with_string_values():
    valid = native.CreateAsset(attributes='{"arc_display_name":"My Cat"}')
    assert valid.attributes == {"arc_display_name": "My Cat"}
    for value in ['not json', '[]', '{"name": 42}']:
        with pytest.raises(ValidationError):
            native.CreateAsset(attributes=value)

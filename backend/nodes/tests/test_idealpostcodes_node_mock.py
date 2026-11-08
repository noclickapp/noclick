"""Wire regression tests for the pinned Ideal Postcodes contract; no live requests."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import idealpostcodes_node as native
from nodes.core.registry import NodeFactory

KEY = "idealpostcodes-synthetic-key"
MANAGEMENT = "idealpostcodes-synthetic-management"
CASES = json.loads((Path(__file__).parent / "fixtures/idealpostcodes/requests.json").read_text())["cases"]


def node(config, **credentials):
    return NodeFactory.create_node(node_id="idealpostcodes-test", node_type="automation-idealpostcodes",
        node_data={"config": config, "credentials": {"credential_type": "idealpostcodes_api_key", "api_key": KEY, "user_token": MANAGEMENT, **credentials}})


def mock(monkeypatch, response):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.host == "api.ideal-postcodes.co.uk"
        return response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", CASES)
async def test_idealpostcodes_wire_contract(monkeypatch, config, method, path, params, body):
    payload = {"result": {"name": "My API Key"}, "code": 2000, "message": "Success"}
    requests = mock(monkeypatch, httpx.Response(200, json=payload))
    result = await node(config).execute({})
    assert result["status"] == "success" and result["result"] == payload["result"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == "/v1" + path
    assert dict(request.url.params) == {k: str(v) for k, v in params.items()}
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(200, 4010), (400, 4001), (401, 4012), (402, 4020), (429, 4290), (500, 5000)])
async def test_idealpostcodes_rejection_and_redaction(monkeypatch, status, code):
    requests = mock(monkeypatch, httpx.Response(status, json={"code": code, "message": "Rejected " + KEY + MANAGEMENT}))
    result = await node({"operation": "get_key_details"}).execute({})
    assert result["status"] == "error"
    assert KEY not in str(result) and MANAGEMENT not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"code": 2000}, [], {"result": {}, "message": "Success"}])
async def test_idealpostcodes_malformed_success(monkeypatch, payload):
    mock(monkeypatch, httpx.Response(200, json=payload))
    assert (await node({"operation": "get_key_details"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_idealpostcodes_postcode_path_cannot_change_host(monkeypatch):
    requests = mock(monkeypatch, httpx.Response(200, json={"result": [], "code": 2000}))
    await node({"operation": "get_config", "config_name": "a/b?x#frag"}).execute({})
    assert requests[0].url.raw_path.endswith(b"/configs/a%2Fb%3Fx%23frag")
    assert not requests[0].url.query


@pytest.mark.asyncio
async def test_idealpostcodes_api_key_only_and_account_evidence(monkeypatch):
    mock(monkeypatch, httpx.Response(200, json={"result": {"name": "My API Key", "lookups_remaining": 19889}, "code": 2000}))
    assert (await node({"operation": "get_key_details"}, user_token=None).execute({}))["result"]["name"] == "My API Key"
    assert native.IdealpostcodesNode.connection_evidence.identity_operation == "get_key_details"


@pytest.mark.parametrize("value", ["https://example.com/key", "Bearer abc", 'a"b', "a\nb"])
def test_idealpostcodes_invalid_secrets(value):
    with pytest.raises(ValidationError):
        native.IdealpostcodesAPIKeyCredential(api_key=value)


def test_idealpostcodes_usage_interval_bound():
    with pytest.raises(ValidationError):
        native.GetKeyUsage(start=1000, end=0)
    with pytest.raises(ValidationError):
        native.GetKeyUsage(start=0, end=91 * 86400000)


@pytest.mark.asyncio
async def test_idealpostcodes_success_redacts_secrets_recursively(monkeypatch):
    mock(monkeypatch, httpx.Response(200, json={"result": {"api_key": KEY, "nested": [MANAGEMENT]}, "code": 2000}))
    result = await node({"operation": "get_key_details"}).execute({})
    assert KEY not in str(result) and MANAGEMENT not in str(result)


@pytest.mark.asyncio
async def test_idealpostcodes_documented_configs_response(monkeypatch):
    example = json.loads((Path(__file__).parent / "fixtures/idealpostcodes/configs-response.json").read_text())["body"]
    mock(monkeypatch, httpx.Response(200, json=example))
    result = await node({"operation": "list_configs"}).execute({})
    assert result["result"]["configs"][0]["name"] == "woocommerce"
    assert json.loads(result["result"]["configs"][0]["payload"]) == {"removeOrganisation": False}

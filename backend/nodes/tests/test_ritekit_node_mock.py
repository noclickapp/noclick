"""Exercise requests against provider-published examples, without network calls."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.registry import NodeFactory
from nodes import ritekit_node as module

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/ritekit/contract_examples.json").read_text())["operations"]
CREDENTIAL = {"credential_type": "ritekit_client_id", "client_id": "private-client-id"}


def node(config, credentials=CREDENTIAL):
    return NodeFactory.create_node(node_id="ritekit-test", node_type="automation-ritekit",
        node_data={"config": config, "credentials": credentials})


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as instance:
            yield instance
    monkeypatch.setattr(module, "guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_ritekit_published_contract(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.ritekit.com"
        expected_path = example["path"].replace("{hashtag}", quote(example["config"].get("hashtag", ""), safe=""))
        assert request.url.path == expected_path
        params = {k: str(v) for k, v in example["config"].items() if k != "hashtag"}
        if "tags" in params:
            params["tags"] = ",".join(example["config"]["tags"])
        assert dict(request.url.params) == {**params, "client_id": CREDENTIAL["client_id"]}
        assert not request.content
        return httpx.Response(200, json=example["response"])
    transport(monkeypatch, handler)
    result = await node({"operation": operation, **example["config"]}).execute({})
    assert result == {"status": "success", "data": example["response"]}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status, body", [
    (401, {"result": False, "message": "Unauthorized"}),
    (429, {"result": False, "message": "Rate limit"}),
    (200, {"result": False, "message": "Rejected private-client-id"}),
    (200, {"result": True, "list": {}}),
    (200, []),
])
async def test_ritekit_rejects_errors_without_leaking_key(monkeypatch, status, body):
    transport(monkeypatch, lambda request: httpx.Response(status, json=body))
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_ctas"}).execute({})
    assert CREDENTIAL["client_id"] not in str(error.value)


@pytest.mark.asyncio
async def test_ritekit_invalid_json_and_transport_failure(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, text="<html>not JSON</html>"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "list_ctas"}).execute({})
    def fail(request):
        raise httpx.ConnectError(str(request.url), request=request)
    transport(monkeypatch, fail)
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_ctas"}).execute({})
    assert CREDENTIAL["client_id"] not in str(error.value)


def test_ritekit_manual_credential_and_evidence():
    credential = module.RitekitClientIdCredential(client_id="  private-client-id  ")
    assert credential.credential_type == "ritekit_client_id"
    assert credential.client_id == "private-client-id"
    assert module.RitekitNode.connection_evidence.operation == "list_ctas"
    for value in ["", "<token>", "https://ritekit.com/token", "a b"]:
        with pytest.raises(ValidationError):
            module.RitekitClientIdCredential(client_id=value)


@pytest.mark.asyncio
async def test_ritekit_missing_credential_never_requests(monkeypatch):
    def fail(request):
        pytest.fail("Missing credential must not make a request")
    transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="Connect a RiteKit"):
        await node({"operation": "list_ctas"}, None).execute({})

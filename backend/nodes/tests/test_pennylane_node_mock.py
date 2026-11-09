"""Fixed request mapping, cursor preservation, manual connect and failure semantics."""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError
from nodes.pennylane_node import PennylaneAPIToken, PennylaneFullConfig, PennylaneNode, ROUTES

CASES = json.loads((Path(__file__).parent / "fixtures/pennylane/requests.json").read_text())["cases"]
TOKEN = "pennylane-test-secret"


def node(config, **credential):
    return PennylaneNode(node_id="test", node_type="automation-pennylane", node_data={},
        config=PennylaneFullConfig.model_validate({"config":config,
            "credentials":{"api_token":TOKEN, **credential}}), sio=Mock())


def mock_http(monkeypatch, handler):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c
    monkeypatch.setattr("nodes.pennylane_node.guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c:c["operation"])
async def test_pennylane_published_request_mapping(monkeypatch, case):
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.method == case["method"]
        assert request.url.host == "app.pennylane.com"
        assert request.url.path == case["path"]
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert request.headers["x-company-id"] == "12345"
        if case["body"] is not None:
            assert json.loads(request.content) == case["body"]
        else:
            assert request.content == b""
        if case["operation"].startswith("list_"):
            assert request.url.params["limit"] == "20"
            if "cursor" in case["config"]:
                assert request.url.params["cursor"] == case["config"]["cursor"]
        else:
            assert not request.url.query
        if case["operation"] in {"mark_customer_invoice_paid", "update_supplier_invoice_payment_status"}:
            return httpx.Response(204)
        return httpx.Response(200, json=case["response"])
    mock_http(monkeypatch, handler)
    result=await node({"operation":case["operation"], **case["config"]}, company_id="12345").execute({})
    assert len(calls)==1
    assert result == ({"status":"success", "acknowledged":True} if case["operation"] in
        {"mark_customer_invoice_paid", "update_supplier_invoice_payment_status"} else case["response"])


def test_pennylane_catalog_and_manual_credential():
    assert len(ROUTES) == len(CASES) == 25
    c=PennylaneAPIToken(api_token=TOKEN)
    assert c.credential_type == "pennylane_api_token"
    assert c.company_id is None
    assert PennylaneNode.connection_evidence.identity_operation == "get_me"


@pytest.mark.parametrize("token", ["", "https://app.pennylane.com", "Bearer secret", "abc\nfoo"])
def test_pennylane_rejects_invalid_token(token):
    with pytest.raises((ValidationError, ValueError)):
        PennylaneAPIToken(api_token=token)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301,400,401,403,404,422,429,500])
async def test_pennylane_rejections_redact_provider_message(monkeypatch,status):
    mock_http(monkeypatch,lambda r:httpx.Response(status,json={"message":"Rejected "+TOKEN}))
    with pytest.raises(ValueError) as error:
        await node({"operation":"get_me"}).execute({})
    assert TOKEN not in str(error.value)
    assert "Rejected [redacted]" in str(error.value)
    assert str(status) in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"items":[],"has_more":"yes"}, {"items":None,"has_more":False}])
async def test_pennylane_rejects_malformed_pages(monkeypatch,payload):
    mock_http(monkeypatch,lambda r:httpx.Response(200,json=payload))
    with pytest.raises(ValueError):
        await node({"operation":"list_customers"}).execute({})


@pytest.mark.asyncio
async def test_pennylane_timeout_does_not_retry_write(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private transport detail",request=request)
    mock_http(monkeypatch,handler)
    with pytest.raises(ValueError,match="inspect the account"):
        await node({"operation":"create_supplier","name":"Pennylane"}).execute({})
    assert len(calls)==1


def test_pennylane_invalid_config_stays_local():
    for config in [{"operation":"get_customer","id":"../other"},
                   {"operation":"list_customers","limit":101},
                   {"operation":"create_customer_invoice","draft":False},
                   {"operation":"create_supplier","name":"Acme","url":"https://example.com"}]:
        with pytest.raises(ValidationError):
            node(config)

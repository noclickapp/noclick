"""TemplateFox's published request and response examples, exercised without an account."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import templatefox_node as native
from nodes.core.registry import NodeFactory

TOKEN = "sk_synthetic_templatefox_key"
FIXTURES = Path(__file__).parent / "fixtures" / "templatefox"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="templatefox-test",
        node_type="automation-templatefox",
        node_data={
            "config": config,
            "credentials": {"credential_type": "templatefox_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, body, status=200):
    requests = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", json.loads((FIXTURES / "operations.json").read_text()))
async def test_documented_operation_contract(monkeypatch, case):
    calls = transport(monkeypatch, case["response"])
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "data": case["response"]}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert (
        request.url.host == "api.templatefox.com"
        and request.headers["x-api-key"] == TOKEN
    )
    assert dict(request.url.params) == case.get("query", {})
    if "body" in case:
        body = json.loads(request.content)
        assert all(body[k] == v for k, v in case["body"].items())
        assert "template_id" not in body if "/templates/" in case["path"] else True


@pytest.mark.asyncio
async def test_patch_explicit_null_clears_but_omission_preserves(monkeypatch):
    calls = transport(monkeypatch, {"version_number": 3, "tag": None})
    await node(
        {
            "operation": "update_template_version",
            "template_id": "HMQywVpZxqAM",
            "version_number": 3,
            "tag": None,
        }
    ).execute({})
    assert json.loads(calls[0].content) == {"tag": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_error_and_key_redaction(monkeypatch, status):
    calls = transport(monkeypatch, {"detail": "Rejected " + TOKEN}, status)
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [{"success": False}, {"error": "invalid key"}, "bad shape", {}]
)
async def test_error_envelopes_do_not_prove_connection(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"


def test_manual_credential_default_and_cleaning():
    cred = native.TemplatefoxAPIKeyCredential(api_key="  " + TOKEN + "\n")
    assert cred.credential_type == "templatefox_api_key" and cred.api_key == TOKEN
    for bad in ["https://example.com/key", "<token>", "bad\nkey"]:
        with pytest.raises(ValidationError):
            native.TemplatefoxAPIKeyCredential(api_key=bad)


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_template_fields", "template_id": "../other"},
        {
            "operation": "create_pdf",
            "template_id": "HMQywVpZxqAM",
            "data": {},
            "export_type": "binary",
        },
        {"operation": "extract_pdf_pages", "pages": "1-3"},
        {
            "operation": "rotate_pdf",
            "pdf_url": "https://example.com/file.pdf",
            "rotation": 45,
        },
        {
            "operation": "merge_pdf",
            "pdfs": [{"pdf_url": "https://example.com/file.pdf"}],
        },
    ],
)
def test_invalid_requests_fail_before_network(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_delete_accepts_unspecified_json_response(monkeypatch):
    transport(monkeypatch, "ok")
    result = await node(
        {
            "operation": "delete_template_version",
            "template_id": "HMQywVpZxqAM",
            "version_number": 3,
        }
    ).execute({})
    assert result == {"status": "success", "data": "ok"}

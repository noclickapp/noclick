"""Factory-level request/parser checks using DocuSeal's published API examples."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import docuseal_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = "docuseal-test-account-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/docuseal/contract_examples.json").read_text())["operations"]
CONFIGS = {
    "list_templates": {"q": "Example", "archived": False, "after": 1},
    "list_submissions": {"template_id": 1, "status": "pending", "archived": False},
    "list_submitters": {"submission_id": 1, "completed_after": "2024-09-01T12:00:00Z"},
    "get_template": {"id": 1}, "archive_template": {"id": 1},
    "update_template": {"id": 1, "name": "New Document Name", "roles": ["Agent", "Customer"], "archived": False},
    "clone_template": {"id": 1, "name": "Cloned Template"},
    "get_submission": {"id": 1}, "archive_submission": {"id": 1},
    "update_submission": {"id": 1, "name": "New Submission Name", "archived": False},
    "get_submission_documents": {"id": 1, "merge": True}, "get_submitter": {"id": 7},
    "update_submitter": {"id": 1, "email": "john.doe@example.com", "values": {"Full Name": "John Doe"}, "send_email": True},
    "create_submission": {"template_id": 1000001, "send_email": False, "submitters": [{"email": "john.doe@example.com", "role": "First Party", "values": {"Full Name": "John Doe"}}]},
    "create_template_from_pdf": {"name": "Test PDF", "documents": [{"name": "Agreement", "file": "https://www.docuseal.com/examples/nda.pdf"}]},
    "create_template_from_html": {"name": "Test Template", "html": '<p>Agreement</p><signature-field name="Signature" role="First Party" />'},
}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation="list_templates", *, credentials=None, config=None):
    return NodeFactory.create_node(node_id="docuseal-test", node_type="automation-docuseal", node_data={
        "config": {"operation": operation, **(CONFIGS[operation] if config is None else config)},
        "credentials": credentials or {"credential_type": "docuseal_api_key", "api_key": TOKEN},
    })


def transport(monkeypatch, body=None, *, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers={"Location": "https://untrusted.example.test/"})
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, "AsyncClient", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(EXAMPLES))
async def test_all_operations_exact_request_and_documented_response(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = transport(monkeypatch, example["response"])
    instance = node(operation)
    assert await instance.execute({}) == {"data": example["response"], "http_status": 200}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example["method"]
    assert request.url.path == example["path"].replace("{id}", str(CONFIGS[operation].get("id")))
    assert request.url.host == "api.docuseal.com" and request.headers["X-Auth-Token"] == TOKEN
    expected = instance.config.config.model_dump(exclude_none=True, exclude={"operation", "id"})
    if native.ROUTES[operation][2]:
        assert json.loads(request.content) == expected and not request.url.query
    else:
        assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in expected.items()}
        assert not request.content


@pytest.mark.asyncio
async def test_eu_empty_account_evidence(monkeypatch):
    body = {"data": [], "pagination": {"count": 0, "next": None, "prev": None}}
    requests = transport(monkeypatch, body)
    output = await node(credentials={"credential_type": "docuseal_api_key", "api_key": TOKEN, "region": "eu"}, config={}).execute({})
    assert output["data"] == body and len(requests) == 1
    assert requests[0].url.host == "api.docuseal.eu"
    assert native.DocusealNode.connection_evidence.operation == "list_templates"


@pytest.mark.asyncio
async def test_cursor_preserved_without_extra_requests(monkeypatch):
    body = {"data": [{"id": 23, "name": "Customer agreement"}], "pagination": {"count": 1, "next": 23, "prev": 1}}
    requests = transport(monkeypatch, body)
    assert (await node().execute({}))["data"] == body
    assert len(requests) == 1 and requests[0].url.params["after"] == "1"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [201, 204, 301, 302, 401, 403, 404, 429, 500])
async def test_failure_redirect_no_leak_or_retry(monkeypatch, status):
    requests = transport(monkeypatch, {"error": TOKEN}, status=status)
    with pytest.raises(ValueError, match=f"HTTP {status}") as exc:
        await node("create_submission").execute({})
    assert TOKEN not in str(exc.value) and "[redacted]" in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body", [("list_templates", {}), ("list_templates", {"data": [], "pagination": {}, "error": "denied"}), ("get_submission", []), ("create_submission", {}), ("create_submission", ["bad"])])
async def test_malformed_response(monkeypatch, operation, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="unexpected response"):
        await node(operation).execute({})


@pytest.mark.asyncio
async def test_redaction(monkeypatch):
    transport(monkeypatch, {"id": 1, "name": TOKEN, "api_key": TOKEN, "nested": {"secret": TOKEN, "value": TOKEN}})
    output = await node("get_template").execute({})
    assert TOKEN not in str(output) and output["data"]["name"] == "[redacted]"


@pytest.mark.asyncio
async def test_transport_failure_no_automatic_write_retry(monkeypatch):
    calls = []
    original = httpx.AsyncClient
    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout(TOKEN, request=request)
    monkeypatch.setattr(native.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(fail), **kwargs))
    with pytest.raises(ValueError, match="inspect writes") as exc:
        await node("create_submission").execute({})
    assert len(calls) == 1 and TOKEN not in str(exc.value)


def test_registration_schema_and_credential_guard():
    assert NODE_REGISTRY["automation-docuseal"] is native.DocusealNode
    schema = native.DocusealFullConfig.model_json_schema()
    assert schema["$defs"]["DocusealAPIKeyCredential"]["title"] == "Docuseal API Key"
    for config in [{"operation": "get_template", "id": "../other"}, {"operation": "list_templates", "limit": 0}, {"operation": "create_submission", "template_id": 1, "submitters": []}, {"operation": "create_template_from_pdf", "documents": [{}]}]:
        with pytest.raises((ValueError, ValidationError)):
            native.DocusealNode.parse_config({"config": config, "credentials": {"api_key": TOKEN}})
    bad = {"config": {"operation": "list_templates"}, "credentials": {"credential_type": "other", "api_key": TOKEN}}
    with pytest.raises(ValueError, match="DocuSeal"):
        native.DocusealNode.parse_config(bad)
    assert native.DocusealNode.validate_config(bad)["valid"] is False
    with pytest.raises(ValidationError):
        native.DocusealAPIKeyCredential(api_key="https://example.test/key")
    with pytest.raises(ValidationError):
        native.DocusealAPIKeyCredential(api_key=TOKEN, region="https://evil.test")


@pytest.mark.asyncio
async def test_connection_rejection_preserves_provider_words(monkeypatch):
    transport(monkeypatch, {"error": "Invalid API key"}, status=401)
    with pytest.raises(ValueError, match="Invalid API key"):
        await node().execute({})

"""Published Fuse v1 examples through the actual factory and HTTP boundary."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import fuseai_node as native
from nodes.core.registry import NodeFactory

TOKEN = "af_synthetic_test_token"
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/fuseai/contract_examples.json").read_text()
)["operations"]
ID = "68a1f20b9c41d20014b3e901"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def config(operation):
    result = {"operation": operation}
    if operation in {
        "get_list",
        "rename_list",
        "delete_list",
        "list_rows",
        "add_members",
        "remove_members",
        "list_columns",
        "create_column",
        "delete_column",
    }:
        result["listId"] = ID
    if operation == "delete_column":
        result["columnId"] = "68a1f3009c41d20014b3e9a1"
    if operation in {
        "get_campaign",
        "stop_campaign",
        "duplicate_campaign",
        "list_campaign_steps",
        "list_campaign_leads",
    }:
        result["campaignId"] = "6a8dce146dc0b3d9029c22d0"
    if operation == "get_job":
        result["jobId"] = ID
    if operation in {"create_list", "rename_list", "create_column"}:
        result["name"] = "Q3 Fintech CFOs"
    if operation in {"add_members", "remove_members"}:
        result["contactIds"] = ["68a1f2c89c41d20014b3e955"]
    if operation == "find_person_email":
        result["linkedinUrl"] = "https://www.linkedin.com/in/jane-doe"
    if operation == "verify_email":
        result["email"] = "jane@stripe.com"
    if operation == "resolve_company":
        result["domain"] = "stripe.com"
    return result


def node(cfg):
    return NodeFactory.create_node(
        node_id="fuseai-test",
        node_type="automation-fuseai",
        node_data={
            "config": cfg,
            "credentials": {"credential_type": "fuseai_api_token", "api_token": TOKEN},
        },
    )


def transport(monkeypatch, status, body):
    calls = []

    def respond(request):
        calls.append(request)
        return (
            httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
        )

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(EXAMPLES))
async def test_published_examples_exact_requests(monkeypatch, operation):
    example = EXAMPLES[operation]
    calls = transport(monkeypatch, example["status"], example["body"])
    cfg = config(operation)
    result = await node(cfg).execute({})
    assert result["status"] == "success" and result["http_status"] == example["status"]
    assert len(calls) == 1
    request = calls[0]
    assert request.method == example["method"] and request.url.host == "api.tryfuse.ai"
    assert request.url.path == "/api/v1" + example["path"].format(**cfg)
    assert request.headers["Authorization"] == httpx.BasicAuth(TOKEN, "")._auth_header
    if example["method"] in {"POST", "PATCH"} or operation == "remove_members":
        expected = {
            k: v
            for k, v in cfg.items()
            if k not in {"operation", "listId", "campaignId", "columnId", "jobId"}
        }
        if operation == "create_list":
            expected["entityType"] = "contactList"
        if operation == "create_column":
            expected["type"] = "string"
        assert (json.loads(request.content) if request.content else {}) == expected
    if example["status"] != 204:
        assert result["data"] == example["body"]


@pytest.mark.asyncio
async def test_paging_filters_not_automatically_followed(monkeypatch):
    body = EXAMPLES["list_lists"]["body"]
    calls = transport(monkeypatch, 200, body)
    result = await node(
        {
            "operation": "list_lists",
            "limit": 2,
            "pageNum": 2,
            "search": "CFO + café",
            "entityType": "contactList",
        }
    ).execute({})
    assert dict(calls[0].url.params) == {
        "limit": "2",
        "pageNum": "2",
        "search": "CFO + café",
        "entityType": "contactList",
    }
    assert result["data"]["pagination"] == body["pagination"] and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [301, 302, 400, 401, 403, 404, 409, 422, 429, 500, 202]
)
async def test_errors_and_redaction(monkeypatch, status):
    calls = transport(monkeypatch, status, {"error": {"message": "Rejected " + TOKEN}})
    result = await node(config("create_list")).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"user": None},
        {"user": {}},
        {"user": {"id": ""}},
        {"error": "bad", "user": {"id": "x"}},
    ],
)
async def test_probe_requires_identity(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize(
    "cfg",
    [
        {"operation": "get_list", "listId": "../business/me"},
        {"operation": "add_members", "listId": ID, "contactIds": []},
        {"operation": "list_lists", "limit": 1001},
        {"operation": "list_campaigns", "pageNum": 0},
        {"operation": "rename_list", "listId": ID},
        {"operation": "find_person_email"},
        {"operation": "resolve_company"},
    ],
)
def test_invalid_inputs(cfg):
    with pytest.raises(ValidationError):
        native.FuseaiFullConfig.model_validate({"config": cfg})


def test_manual_connect_default():
    assert (
        native.FuseaiAPITokenCredential(api_token=TOKEN).credential_type
        == "fuseai_api_token"
    )
    assert native.FuseaiNode.connection_evidence.identity_operation == "get_account"
    for value in ["https://example.com/token", "Basic abc", "abc:def"]:
        with pytest.raises(ValueError):
            native.FuseaiAPITokenCredential(api_token=value)

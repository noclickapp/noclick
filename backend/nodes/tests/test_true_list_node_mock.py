"""True List HTTP serialization, account evidence and rejection behavior."""
import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path

import httpx
import pytest

from nodes import true_list_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / "fixtures/true-list/responses.json").read_text())
TOKEN = "synthetic-true-list-secret"
CREDENTIAL = {"credential_type": "true_list_api_token", "api_token": TOKEN}
UUID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="true-list-test", node_type="automation-true-list",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def client(monkeypatch, body, status=200, headers=None):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def make(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", make)
    return calls


CASES = [
    ({"operation": "get_account"}, FIXTURES["account"], "GET", "/me"),
    ({"operation": "verify_email", "email": "bob@example.com"}, {"emails": [FIXTURES["email"]]}, "POST", "/api/v1/verify_inline"),
    ({"operation": "verify_emails", "emails": ["bob@example.com", "jon@example.com"]}, {"emails": [FIXTURES["email"]]}, "POST", "/api/v1/verify_inline"),
    ({"operation": "check_email", "email": "bob@example.com"}, {"emails": [FIXTURES["email"]]}, "POST", "/api/v1/verify_inline"),
    ({"operation": "create_batch", "rows": [["email@email.com", "one,two"], ["email2@email.com", "second"]], "uuid": UUID, "webhook_url": "https://example.com/callback", "validation_strategy": "fast"}, FIXTURES["batch"], "POST", "/api/v1/batches"),
    ({"operation": "list_batches"}, [FIXTURES["batch"]], "GET", "/api/v1/batches"),
    ({"operation": "get_batch", "uuid": UUID}, FIXTURES["batch"], "GET", "/api/v1/batches/" + UUID),
    ({"operation": "delete_batch", "uuid": UUID}, FIXTURES["batch"], "DELETE", "/api/v1/batches/" + UUID),
    ({"operation": "list_results", "batch_uuid": "none", "email_state": "unknown", "email_sub_state": "timed_out", "email_address": "jane", "page": 2, "per_page": 100}, {"email_addresses": [FIXTURES["email"]]}, "GET", "/api/v1/email_addresses"),
    ({"operation": "get_result", "id": 123456}, {"email_address": FIXTURES["email"]}, "GET", "/api/v1/email_addresses/123456"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,body,method,path", CASES, ids=[x[0]["operation"] for x in CASES])
async def test_true_list_operations(monkeypatch, config, body, method, path):
    calls = client(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.truelist.io"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    operation = config["operation"]
    if operation == "get_account":
        assert result["name"] == "Fixture User" and result["email"] == "fixture@example.com"
        assert "token" not in result and "api_keys" not in result
        assert "must-not-escape" not in json.dumps(result)
    else:
        assert result["data"] == body
    if operation in {"verify_email", "verify_emails", "check_email"}:
        assert request.url.params["email"] == (" ".join(config["emails"]) if "emails" in config else config["email"])
        assert request.url.params["timeout"] == "30" and request.url.params["validation_strategy"] == "accurate"
        assert request.url.params.get_list("checks") == (["syntax", "mx", "disposable", "role"] if operation == "check_email" else [])
        assert request.content == b""
    elif operation == "create_batch":
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        message = BytesParser(policy=default).parsebytes(b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
        parts = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
        assert parts["file"].get_filename() == "truelist.csv"
        assert parts["file"].get_payload(decode=True) == b'email@email.com,"one,two"\r\nemail2@email.com,second\r\n'
        assert parts["uuid"].get_payload() == UUID
        assert parts["webhook_url"].get_payload() == config["webhook_url"]
        assert parts["validation_strategy"].get_payload() == "fast"
        assert set(parts) == {"file", "uuid", "webhook_url", "validation_strategy"}
    elif operation == "list_results":
        assert dict(request.url.params) == {k: str(v) for k, v in config.items() if k != "operation"}
    else:
        assert not request.url.params and not request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 408, 422, 429, 500])
async def test_true_list_rejections(monkeypatch, status):
    calls = client(monkeypatch, {"error": "Provider rejected " + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_account"}).execute({})
    assert TOKEN not in str(error.value) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"errors": ["invalid token"]}, {"error": "invalid token"}])
async def test_true_list_account_requires_identity(monkeypatch, body):
    client(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "get_batch", "uuid": "../me"},
    {"operation": "get_result", "id": 0},
    {"operation": "verify_email", "email": "a@b.com c@d.com"},
    {"operation": "verify_email", "email": "a@b.com", "timeout": 31},
    {"operation": "verify_emails", "emails": ["a@b.com"]},
    {"operation": "verify_emails", "emails": ["a@b.com"] * 4},
    {"operation": "create_batch", "rows": [["a@b.com"], ["missing"]]},
    {"operation": "create_batch", "rows": [["a@b.com"], ["b@c.com"]], "filename": "../upload.csv"},
    {"operation": "list_results", "per_page": 101},
])
def test_true_list_invalid_configs(config):
    with pytest.raises(ValueError):
        node(config)


def test_true_list_manual_credential_default_and_foreign_type():
    credential = native.TrueListAPITokenCredential(api_token="  synthetic-secret  ")
    assert credential.credential_type == "true_list_api_token" and credential.api_token == "synthetic-secret"
    with pytest.raises(ValueError):
        node({"operation": "get_account"}, {**CREDENTIAL, "credential_type": "unrelated_api_key"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,reachable", [
    (200, FIXTURES["account"], True),
    (401, {"error": "User could not be found via token"}, False),
])
async def test_true_list_connection_evidence(monkeypatch, status, body, reachable):
    from nodes.core.connection_evidence import collect_evidence
    calls = client(monkeypatch, body, status)
    result = await collect_evidence(node_type="automation-true-list", credential_data=CREDENTIAL,
        user_id="550e8400-e29b-41d4-a716-446655440000")
    assert result.reachable is reachable and len(calls) == 1
    if reachable:
        assert result.account_label == "Fixture User"
    else:
        assert "User could not be found via token" in result.error

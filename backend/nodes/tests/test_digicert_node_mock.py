"""Offline published-contract wire and manual-connect regressions."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import digicert_node as dc
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

F = Path(__file__).parent / "fixtures/digicert"
CONFIGS = json.loads((F / "configs.json").read_text())
CONTRACT = json.loads((F / "contract.json").read_text())
TOKEN = "synthetic-digicert-token"
ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="dc-test",
        node_type="automation-digicert",
        node_data={
            "config": config,
            "credentials": {"credential_type": "digicert_api_key", "api_key": TOKEN},
        },
    )


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    monkeypatch.setattr(dc, "guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONFIGS)
async def test_every_operation_sends_one_published_request(monkeypatch, operation):
    seen = []

    def handler(r):
        seen.append(r)
        assert r.url.host == "one.digicert.com"
        assert r.headers["X-API-Key"] == TOKEN
        assert r.headers["Accept"] == "application/json"
        assert TOKEN not in str(r.url)
        return httpx.Response(200, json={"id": ID})

    transport(monkeypatch, handler)
    assert (await node(CONFIGS[operation]).execute({}))["status"] == "success"
    assert len(seen) == 1
    r = seen[0]
    expected = CONTRACT["operations"][operation]
    assert r.method == expected["method"]
    path = expected["path"]
    for key in ["id", "validationId", "userId"]:
        path = path.replace("{" + key + "}", ID)
    assert r.url.path == "/documentmanager" + path.replace(
        "{name}", "signing-credential"
    )
    config = CONFIGS[operation]
    if "account_id" in config:
        assert r.url.params["account_id"] == ID
    if operation == "revoke_credential":
        assert r.url.params["user_id"] == ID
    if "reason" in config:
        assert json.loads(r.content) == {"reason": config["reason"]}
    if operation in {
        "enable_validation",
        "disable_validation",
        "invalidate_validation",
    }:
        assert json.loads(r.content) == {
            k: v for k, v in config.items() if k not in {"operation", "validation_id"}
        }
    if operation == "cancel_credential":
        assert json.loads(r.content) == {"notes": "cancellation notes"}
    if r.method == "GET":
        assert r.content == b""


@pytest.mark.asyncio
async def test_cursor_page_retains_pagination(monkeypatch):
    payload = {
        "data": [{"id": ID, "action": "CREATE"}],
        "pagination": {
            "has_more": True,
            "next_cursor_id": ID,
            "next_cursor_timestamp": "2026-06-07T04:25:42.722",
        },
    }

    def handler(r):
        assert r.url.params["cursor_id"] == ID
        assert r.url.params["cursor_timestamp"] == "2026-06-07T04:25:42.722"
        assert r.url.params["limit"] == "100"
        return httpx.Response(200, json=payload)

    transport(monkeypatch, handler)
    result = await node(
        {
            "operation": "list_audit_logs",
            "cursor_id": ID,
            "cursor_timestamp": "2026-06-07T04:25:42.722",
            "limit": 100,
        }
    ).execute({})
    assert result["data"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
async def test_error_envelopes_and_secret_redaction(monkeypatch, status):
    transport(
        monkeypatch,
        lambda r: httpx.Response(
            status,
            json={
                "error": "Unauthorized",
                "error_description": "Unauthorized " + TOKEN,
            },
        ),
    )
    result = await node(CONFIGS["list_audit_logs"]).execute({})
    assert result["status"] == "error"
    assert result["message"] == "Unauthorized [redacted]"
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_empty_success(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(204))
    assert (await node(CONFIGS["retry_validation"]).execute({}))["data"] is None


@pytest.mark.asyncio
async def test_no_retry_or_redirect_on_write(monkeypatch):
    seen = []

    def handler(r):
        seen.append(r)
        return httpx.Response(
            307, headers={"Location": "https://attacker.example/"}, json={}
        )

    transport(monkeypatch, handler)
    assert (await node(CONFIGS["revoke_credential"]).execute({}))["status"] == "error"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_non_json_is_unverifiable(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node(CONFIGS["list_audit_logs"]).execute({})


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "one.digicert.com.attacker.test",
        "https://one.digicert.com",
        "one.digicert.com/path",
    ],
)
def test_host_allowlist(host):
    with pytest.raises(ValidationError):
        dc.DigicertAPIKeyCredential(api_key=TOKEN, host=host)


@pytest.mark.parametrize(
    "field,value",
    [("validation_id", "../x"), ("name", "a/b"), ("user_id", "bad?query")],
)
def test_identifiers_cannot_inject_routes(field, value):
    operation = {
        "validation_id": "get_validation",
        "name": "get_credential",
        "user_id": "get_user_validations",
    }[field]
    with pytest.raises(ValueError):
        node({**CONFIGS[operation], field: value})


def test_manual_connect_defaults_type_and_strips_secret():
    shaped, errors, _ = shape_credential(
        "digicert_api_key", {"api_key": " " + TOKEN + " "}
    )
    assert not errors
    assert shaped["api_key"] == TOKEN
    assert (
        dc.DigicertAPIKeyCredential.model_validate(shaped).credential_type
        == "digicert_api_key"
    )
    assert dc.DigicertNode.connection_evidence.operation == "list_audit_logs"


@pytest.mark.asyncio
async def test_empty_auth_refusal_keeps_status_for_connection_evidence(monkeypatch):
    from nodes.core.connection_evidence import (
        _raise_if_error_envelope,
        _ProviderRefused,
    )

    transport(monkeypatch, lambda r: httpx.Response(403))
    result = await node(CONFIGS["list_audit_logs"]).execute({})
    assert result["status_code"] == 403
    with pytest.raises(_ProviderRefused, match="HTTP 403"):
        _raise_if_error_envelope(result)


def test_organization_rejection_requires_the_contract_uuid():
    with pytest.raises(ValueError):
        node(
            {**CONFIGS["reject_organization_validation"], "validation_id": "not-a-uuid"}
        )

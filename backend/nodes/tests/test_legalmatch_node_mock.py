"""Offline checks against the pinned QBI operation map; all responses are synthetic."""
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, quote

import httpx
import pytest
from pydantic import ValidationError

from nodes import legalmatch_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads(
    (Path(__file__).parent / "fixtures/legalmatch/contract_operations.json").read_text()
)
CREDENTIAL = {
    "credential_type": "legalmatch_basic",
    "username": "qbi-test-user",
    "password": "synthetic-qbi-password-42",
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(
        node_id="legalmatch-offline",
        node_type="automation-legalmatch",
        node_data={"config": config, "credentials": credentials or CREDENTIAL},
    )


def transport(monkeypatch, reply):
    requests = []

    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else httpx.Response(200, json=reply)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CASES)
async def test_pinned_method_path_and_basic_auth(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, {})
    result = await node(case["config"]).execute({})
    assert result["success"] is True
    assert len(requests) == 1
    request = requests[0]
    expected = case["path"]
    for key, value in case["config"].items():
        expected = expected.replace("{" + key + "}", quote(str(value), safe=""))
    assert request.url.scheme == "https" and request.url.host == "qbi.legalmatch.com"
    assert request.method == case["method"] and request.url.path == expected
    expected_auth = base64.b64encode(
        (CREDENTIAL["username"] + ":" + CREDENTIAL["password"]).encode()
    ).decode()
    assert request.headers["Authorization"] == "Basic " + expected_auth
    if case["method"] == "POST":
        assert result["request_accepted"] is True
        assert result["completion_verified"] is False
    else:
        assert "request_accepted" not in result
    assert CREDENTIAL["password"] not in str(result)


@pytest.mark.asyncio
async def test_mapping_form_encoding_and_review_defaults(monkeypatch):
    requests = transport(monkeypatch, {})
    await node(
        {
            "operation": "assign_mapping",
            "qbo_customer_id": "123 + 456",
            "sf_account": "001&abc",
        }
    ).execute({})
    assert requests[0].headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(requests[0].content.decode()) == {
        "qbo_customer_id": ["123 + 456"],
        "sf_account": ["001&abc"],
        "match_method": ["manual"],
        "redirect_to": ["/admin/unmatched"],
    }
    await node(
        {
            "operation": "acknowledge_review",
            "sf_account": "001abc",
            "reason": "Checked + confirmed",
        }
    ).execute({})
    assert parse_qs(requests[1].content.decode(), keep_blank_values=True) == {
        "sf_account": ["001abc"],
        "qbo_customer_id": [""],
        "reason": ["Checked + confirmed"],
        "finding_type": ["owner_mismatch"],
        "redirect_to": ["/admin/sf-validation"],
    }


@pytest.mark.asyncio
async def test_query_filters_and_resolution_form(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({"operation": "list_logs", "max_lines": 42, "level": "ERROR"}).execute(
        {}
    )
    assert dict(requests[0].url.params) == {"max_lines": "42", "level": "ERROR"}
    assert not requests[0].content
    await node({"operation": "run_backfills", "mode": "full"}).execute({})
    assert dict(requests[1].url.params) == {"mode": "full"}
    assert not requests[1].content
    await node(
        {"operation": "resolve_gap", "gap_id": 42, "resolution": "fixed"}
    ).execute({})
    assert requests[2].url.path == "/admin/gap/42/resolve"
    assert parse_qs(requests[2].content.decode()) == {"resolution": ["fixed"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 303, 401, 403, 429, 500])
async def test_rejection_and_redirect_never_followed_or_retried(monkeypatch, status):
    requests = transport(
        monkeypatch,
        lambda request: httpx.Response(
            status,
            text="rejected " + CREDENTIAL["password"],
            headers={"Location": "https://example.com/"},
        ),
    )
    result = await node({"operation": "run_full_sync"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert CREDENTIAL["password"] not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_connection_evidence_uses_protected_read(monkeypatch):
    requests = transport(monkeypatch, {"arbitrary": []})
    evidence = native.LegalMatchNode.connection_evidence
    assert evidence.proves == "reachability"
    result = await node({"operation": evidence.operation}).execute({})
    assert result["success"] and requests[0].method == "GET"
    assert requests[0].url.path == "/admin/sync-status"


@pytest.mark.asyncio
async def test_undocumented_html_is_not_success(monkeypatch):
    transport(
        monkeypatch, lambda request: httpx.Response(200, text="<html>login</html>")
    )
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "get_sync_status"}).execute({})


@pytest.mark.asyncio
async def test_transport_error_does_not_leak_or_retry(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout(CREDENTIAL["password"], request=request)

    requests = transport(monkeypatch, timeout)
    with pytest.raises(ValueError, match="inspect writes") as exc:
        await node({"operation": "mark_paid", "sf_account": "001abc"}).execute({})
    assert CREDENTIAL["password"] not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], {"items": []}, "value", 42])
async def test_unconstrained_json_response_is_preserved(monkeypatch, payload):
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        ),
    )
    result = await node({"operation": "get_gap_summary"}).execute({})
    assert result["data"] == payload


def test_manual_credential_defaults_and_validation():
    credential = native.LegalMatchBasicCredential.model_validate(
        {k: v for k, v in CREDENTIAL.items() if k != "credential_type"}
    )
    assert credential.credential_type == "legalmatch_basic"
    for changes in (
        {"credential_type": "other"},
        {"username": "bad:user"},
        {"username": "   "},
        {"password": "https://example.com/password"},
    ):
        with pytest.raises(ValidationError):
            native.LegalMatchBasicCredential.model_validate({**CREDENTIAL, **changes})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "list_logs", "max_lines": 0},
        {"operation": "list_logs", "max_lines": 10001},
        {"operation": "run_backfills", "mode": "made-up"},
        {"operation": "mark_paid"},
        {"operation": "get_sync_status", "url": "https://example.com"},
    ],
)
def test_invalid_input_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.asyncio
async def test_error_redacts_before_truncation(monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(401, text="x" * 1995 + CREDENTIAL["password"]),
    )
    result = await node({"operation": "get_sync_status"}).execute({})
    assert result["status"] == "error"
    assert "synth" not in result["message"]

"""Offline Brex protocol and parser regressions for every published operation.

Sources are recorded beside each fixture in fixtures/brex/{requests,responses}.json.
Sixteen response specimens are copied from Brex's official guide/Postman examples.
Four are explicitly schema-generated (not provider-authored conformance evidence).
Provider mistakes are retained, including unresolved allOf placeholders in old
Postman card specimens. Tests never repair a provider body to fit the node.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes.brex_node import (
    BREX_OPERATIONS,
    BREX_TRIGGER_EVENTS,
    BrexAPITokenCredential,
    BrexNode,
    BrexNodeConfig,
)

FIXTURES = Path(__file__).parent / "fixtures/brex"
CASES = json.loads((FIXTURES / "requests.json").read_text())
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
TOKEN = "brex-offline-test-token"


def make_node(config, credentials=True):
    return BrexNode(
        node_id="brex-test",
        node_type="automation-brex",
        node_data={},
        config=BrexNodeConfig.model_validate(
            {
                "config": config,
                "credentials": {"api_token": TOKEN} if credentials else None,
            }
        ),
        sio=Mock(),
    )


async def run(monkeypatch, config, body=None, status=200, content=None, exception=None):
    requests = []

    def transport(request):
        requests.append(request)
        if exception:
            raise exception("offline", request=request)
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=body)

    original = httpx.AsyncClient

    def client(*args, **kwargs):
        return original(transport=httpx.MockTransport(transport), trust_env=False)

    monkeypatch.setattr("nodes.brex_node.httpx.AsyncClient", client)
    result = await make_node(config).execute({})
    return result, requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(CASES))
async def test_documented_operation(monkeypatch, operation):
    """Real httpx serialization and parsing for each documented API operation."""
    case = CASES[operation]
    response = RESPONSES[operation]
    result, requests = await run(
        monkeypatch, {"operation": operation, **case["config"]}, response["body"]
    )
    assert len(requests) == 1
    request = requests[0]
    assert (request.method, request.url.path) == (case["method"], case["path"])
    assert request.url.scheme == "https" and request.url.host == "api.brex.com"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    assert dict(request.url.params) == case["query"]
    if "body" in case:
        assert json.loads(request.content) == case["body"]
        assert request.headers["Content-Type"] == "application/json"
    else:
        assert request.content == b""
    if operation in {"create_card", "create_transfer"}:
        assert request.headers["Idempotency-Key"] == case["config"]["idempotency_key"]
    assert result["status"] == "success" and result["action"] == operation
    expected = (
        {"accounts": response["body"]}
        if operation == "list_card_accounts"
        else response["body"]
    )
    assert result["data"] == expected
    assert result["timing_ms"]["api_request"] >= 0
    assert response["source"].startswith("https://")


def test_fixture_coverage_matches_all_operations():
    assert set(CASES) == set(RESPONSES) == set(BREX_OPERATIONS)
    schema = BrexNodeConfig.model_json_schema()
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == set(CASES) | set(BREX_TRIGGER_EVENTS)


@pytest.mark.asyncio
async def test_expense_filter_arrays_and_false_flags(monkeypatch):
    result, requests = await run(
        monkeypatch,
        {
            "operation": "list_expenses",
            "limit": 2,
            "cursor": "next-page",
            "expand": "merchant, location",
            "user_ids": "user-a,user-b",
            "payment_status": "CLEARED,PROCESSING",
            "load_custom_fields": False,
            "load_expense_addenda": True,
            "purchased_at_start": "2024-01-01T00:00:00Z",
            "updated_at_start": "2024-02-01T00:00:00Z",
        },
        {"items": [], "next_cursor": "another-page"},
    )
    query = requests[0].url.params
    assert query.get_list("expand[]") == ["merchant", "location"]
    assert query.get_list("user_id[]") == ["user-a", "user-b"]
    assert query.get_list("payment_status[]") == ["CLEARED", "PROCESSING"]
    assert query["load_custom_fields"] == "false"
    assert query["load_expense_addenda"] == "true"
    assert query["purchased_at_start"] == "2024-01-01T00:00:00Z"
    assert query["updated_at_start"] == "2024-02-01T00:00:00Z"
    assert result["data"]["next_cursor"] == "another-page"
    assert len(requests) == 1  # A page is not silently auto-paginated.


@pytest.mark.asyncio
async def test_transaction_filters_use_unbracketed_user_ids(monkeypatch):
    _, requests = await run(
        monkeypatch,
        {
            "operation": "list_card_transactions",
            "user_ids": "user-a,user-b",
            "expand": "expense_id",
            "posted_at_start": "2024-01-01T00:00:00Z",
        },
        {"items": []},
    )
    assert requests[0].url.params.get_list("user_ids") == ["user-a", "user-b"]
    assert requests[0].url.params.get_list("expand[]") == ["expense_id"]
    assert "user_id[]" not in requests[0].url.params


@pytest.mark.asyncio
async def test_empty_optional_filters_are_omitted(monkeypatch):
    _, requests = await run(
        monkeypatch,
        {
            "operation": "list_cards",
            "cursor": "",
            "user_id": "",
        },
        {"items": []},
    )
    assert dict(requests[0].url.params) == {"limit": "100"}


@pytest.mark.asyncio
async def test_card_id_cannot_add_path_segments(monkeypatch):
    _, requests = await run(
        monkeypatch,
        {
            "operation": "get_card",
            "card_id": "card/a?other=1",
        },
        RESPONSES["get_card"]["body"],
    )
    assert requests[0].url.raw_path == b"/v2/cards/card%2Fa%3Fother%3D1"


@pytest.mark.asyncio
async def test_manual_approval_and_smallest_currency_unit(monkeypatch):
    config = {
        "operation": "create_transfer",
        **CASES["create_transfer"]["config"],
        "approval_type": "MANUAL",
    }
    _, requests = await run(monkeypatch, config, RESPONSES["create_transfer"]["body"])
    body = json.loads(requests[0].content)
    assert body["approval_type"] == "MANUAL"
    assert body["amount"] == {"amount": 100000, "currency": "USD"}


@pytest.mark.asyncio
async def test_physical_card_shipping_and_metadata(monkeypatch):
    address = {
        "line1": "1725 Slough Avenue",
        "city": "Scranton",
        "state": "PA",
        "country": "US",
        "postal_code": "18505",
    }
    config = {
        "operation": "create_card",
        "idempotency_key": "same-create-key",
        "user_id": "owner",
        "card_name": "Physical card",
        "card_type": "PHYSICAL",
        "limit_type": "USER",
        "mailing_address": json.dumps(address),
        "metadata": '{"workflow":"onboarding"}',
    }
    _, requests = await run(monkeypatch, config, RESPONSES["create_card"]["body"])
    body = json.loads(requests[0].content)
    assert body["mailing_address"] == address
    assert body["metadata"] == {"workflow": "onboarding"}
    assert "spend_controls" not in body


@pytest.mark.asyncio
async def test_clear_memo_survives_runtime_config_cleanup(monkeypatch):
    from nodes.core.base import runtime_config_view

    config = runtime_config_view(
        {
            "config": {
                "operation": "update_expense",
                "expense_id": "expense-id",
                "memo": "",
            }
        },
        BrexNodeConfig,
    )["config"]
    _, requests = await run(monkeypatch, config, RESPONSES["update_expense"]["body"])
    assert json.loads(requests[0].content) == {"memo": None}


@pytest.mark.parametrize(
    "config",
    [
        {
            "operation": "create_card",
            "idempotency_key": "a",
            "user_id": "u",
            "card_name": "c",
            "limit_type": "CARD",
        },
        {
            "operation": "create_card",
            "idempotency_key": "a",
            "user_id": "u",
            "card_name": "c",
            "card_type": "PHYSICAL",
        },
        {
            "operation": "create_card",
            "idempotency_key": "a",
            "user_id": "u",
            "card_name": "c",
            "spend_controls": "{}",
        },
        {"operation": "create_card", "user_id": "u", "card_name": "c"},
        {"operation": "update_card", "card_id": "c", "metadata": "[]"},
        {"operation": "update_card", "card_id": "c", "spend_controls": "invalid JSON"},
        {
            "operation": "create_transfer",
            **CASES["create_transfer"]["config"],
            "amount": 0,
        },
        {"operation": "list_expenses", "limit": 101},
    ],
)
def test_invalid_writes_and_limits_fail_before_http(config):
    with pytest.raises(ValidationError):
        make_node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_error_status_and_text_survive(monkeypatch, status):
    # Error message envelope: https://developer.brex.com/guides/error_codes
    message = "Access denied"
    result, _ = await run(
        monkeypatch, {"operation": "get_company"}, {"message": message}, status=status
    )
    assert result["status"] == "error" and result["status_code"] == status
    assert result["error"] == message


@pytest.mark.asyncio
async def test_provider_error_cannot_echo_the_token(monkeypatch):
    result, _ = await run(
        monkeypatch,
        {"operation": "get_company"},
        {"message": f"Rejected {TOKEN}"},
        status=401,
    )
    assert TOKEN not in json.dumps(result)
    assert "[redacted]" in result["error"]


@pytest.mark.asyncio
async def test_missing_credentials_fail_before_http():
    with pytest.raises(ValueError, match="Connect a Brex API token"):
        await make_node({"operation": "get_company"}, credentials=False).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, [], "unexpected", {}, {"id": "company-id"}])
async def test_unknown_identity_response_is_not_success(monkeypatch, body):
    result, _ = await run(monkeypatch, {"operation": "get_company"}, body)
    assert result["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"items": "wrong"}, {"items": ["primitive"]}])
async def test_invalid_page_shape_is_not_success(monkeypatch, body):
    result, _ = await run(monkeypatch, {"operation": "list_expenses"}, body)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_invalid_json_is_not_success(monkeypatch):
    result, _ = await run(
        monkeypatch, {"operation": "get_company"}, content=b"not JSON"
    )
    assert result["status"] == "error" and "invalid JSON" in result["error"]


@pytest.mark.asyncio
async def test_transport_failure_is_an_error(monkeypatch):
    result, _ = await run(
        monkeypatch, {"operation": "get_company"}, exception=httpx.ConnectTimeout
    )
    assert result["status"] == "error"
    assert result["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
async def test_connection_evidence_names_the_company(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence

    body = RESPONSES["get_company"]["body"]
    result, _ = await run(monkeypatch, {"operation": "get_company"}, body)

    async def operation(**kwargs):
        assert kwargs["operation"] == "get_company" and kwargs["arguments"] == {}
        return result

    monkeypatch.setattr("nodes.core.run_op.run_node_operation", operation)
    evidence = await collect_evidence(
        node_type="automation-brex",
        user_id="offline-test",
        credential_data={"credential_type": "brex_api_token", "api_token": TOKEN},
    )
    assert evidence.reachable is True
    assert evidence.account_label == body["legal_name"]


def test_manual_token_schema_and_create_validation():
    schema = BrexAPITokenCredential.model_json_schema()
    assert schema["properties"]["api_token"]["ui:widget"] == "password"
    assert schema["x-credential-url"] == "https://dashboard.brex.com/settings/developer"
    assert "x-oauth-provider" not in schema
    assert BrexNode.connection_evidence.identity_keys == ("legal_name",)

"""Exercise YNAB's real node factory and HTTP boundary without an account.

Synthetic fixtures pin all supported routes, write wrappers, milliunits and
delta cursors. Negative cases verify errors cannot become connection evidence.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import ynab_node as ynab
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-ynab-personal-access-token"
CREDENTIAL = {"credential_type": "ynab_personal_access_token", "access_token": TOKEN}
CASES = json.loads((Path(__file__).parent / "fixtures/ynab/operations.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    def send(request):
        requests.append(request)
        assert request.url.host == "api.ynab.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)

    monkeypatch.setattr(ynab, "guarded_async_client", client)
    return requests, replies


def node(config, credentials=CREDENTIAL):
    return NodeFactory.create_node(node_id="ynab-fixture", node_type="automation-ynab",
        node_data={"config": config, "credentials": credentials})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_ynab_operations_use_exact_provider_contract(transport, case):
    requests, replies = transport
    replies.append((case["status"], case["response"]))
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "operation": case["config"]["operation"], "data": case["response"]["data"]}
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert (request.method, request.url.path) == (case["method"], case["path"])
    assert (json.loads(request.content) if request.content else None) == case["body"]
    params = {key: str(value).lower() if isinstance(value, bool) else str(value)
        for key, value in case["config"].items()
        if key in {"include_accounts", "since_date", "until_date", "type", "last_knowledge_of_server"}}
    assert dict(request.url.params) == (params if request.method == "GET" else {})
    assert TOKEN not in json.dumps(result)


@pytest.mark.asyncio
async def test_ynab_connection_evidence_names_real_account_plans(transport):
    requests, replies = transport
    replies.append((200, {"data": {"plans": [{"id": "household", "name": "Household"}]}}))
    result = await collect_evidence(node_type="automation-ynab", user_id="00000000-0000-4000-8000-000000000001", credential_data=CREDENTIAL)
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ["Household"]
    assert requests[0].url.path == "/v1/plans"


@pytest.mark.asyncio
async def test_ynab_plan_picker_search_uses_the_same_read(transport):
    _, replies = transport
    replies.append((200, {"data": {"plans": [{"id": "p1", "name": "Home"}, {"id": "p2", "name": "Business"}]}}))
    assert await ynab.YnabNode.load_field_options("plan_id", CREDENTIAL, search="home") == [{"value": "p1", "label": "Home"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 404, 409, 429, 500])
async def test_ynab_provider_errors_keep_status_and_redact_token(transport, status):
    requests, replies = transport
    replies.append((status, {"error": {"id": "rejected", "name": "not_authorized", "detail": "Provider rejected " + TOKEN}}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "get_user"}).execute({})
    assert f"HTTP {status}" in str(error.value)
    assert "Provider rejected [redacted]" in str(error.value)
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_ynab_rejected_token_is_failed_connection_evidence(transport):
    _, replies = transport
    replies.append((401, {"error": {"id": "401", "name": "unauthorized", "detail": "Unauthorized"}}))
    result = await collect_evidence(node_type="automation-ynab", user_id="00000000-0000-4000-8000-000000000001", credential_data=CREDENTIAL)
    assert result.reachable is False and "Unauthorized" in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": None}, {"data": {}}, {"data": {"user": []}}, {"data": {"user": {}}, "error": {"name": "bad"}}])
async def test_ynab_invalid_success_envelopes_do_not_pass(transport, payload):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError):
        await node({"operation": "get_user"}).execute({})


@pytest.mark.parametrize("token", ["https://app.ynab.com/settings", "Bearer abc", "abc\nxyz", "<token>", "", "key\u00a0abc"])
def test_ynab_bad_credentials_are_refused(token):
    with pytest.raises(ValueError):
        ynab.YnabPersonalAccessTokenCredential(access_token=token)


@pytest.mark.parametrize("config", [
    {"operation": "get_plan", "plan_id": "../other"},
    {"operation": "get_transaction", "plan_id": "plan", "transaction_id": "a/b"},
    {"operation": "create_account", "plan_id": "p", "name": "Cash", "type": "cash", "balance": 1.25},
    {"operation": "create_account", "plan_id": "p", "name": "Cash", "type": "cash", "balance": True},
    {"operation": "get_month", "plan_id": "p", "month": "2016-13-01"},
])
def test_ynab_invalid_ids_amounts_and_dates_are_refused(config):
    with pytest.raises(ValueError):
        node(config)


def test_ynab_token_paste_noise_is_trimmed():
    assert ynab.YnabPersonalAccessTokenCredential(access_token="  " + TOKEN + "\n").access_token == TOKEN

"""Offline wire-contract, tenant isolation, pagination and OAuth regressions."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes.scoro_node import ScoroNode, ScoroNodeConfig, ScoroOAuthCredential
from nodes.scoro_operations import SCORO_OPERATIONS
from nodes.oauth.scoro_oauth import OAUTH_PROVIDER, ScoroOAuthProviderSpec

CASES = json.loads(
    (Path(__file__).parent / "fixtures/scoro/protocol.json").read_text()
)["cases"]
CREDENTIAL = {
    "credential_type": "scoro_oauth",
    "access_token": "test-access-token",
    "site_host": "tutorial.scoro.com",
    "company_account_id": "tutorial",
}


def make_node(config, credential=None):
    return ScoroNode(
        node_id="scoro-test",
        node_type="automation-scoro",
        node_data={},
        config=ScoroNodeConfig.model_validate(
            {"config": config, "credentials": credential or CREDENTIAL}
        ),
    )


def mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    factory = lambda *a, **kw: original(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("nodes.scoro_node.guarded_async_client", factory)
    monkeypatch.setattr(ScoroOAuthProviderSpec, "_client", lambda *a: factory())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(CASES))
async def test_wire_contract(monkeypatch, operation):
    case = CASES[operation]
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            case["status"],
            **({"json": case["response"]} if case["response"] is not None else {})
        )

    mock_client(monkeypatch, handler)
    result = await make_node(case["config"]).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert (req.method, req.url.path, req.url.host) == (
        case["method"],
        case["path"],
        "tutorial.scoro.com",
    )
    assert req.headers["Authorization"] == "Bearer test-access-token"
    assert req.headers["Scoro-Company-Account"] == "tutorial"
    assert dict(req.url.params) == case["query"]
    assert (json.loads(req.content) if req.content else None) == case["body"]
    assert "test-access-token" not in str(req.url) + req.content.decode()
    assert result["data"] == case["response"] and result["status"] == "success"
    if "per_page" in case["config"]:
        assert result["next_page"] == 3
    else:
        assert "next_page" not in result


def test_every_operation_has_an_independent_protocol_case():
    assert set(CASES) == set(SCORO_OPERATIONS)
    assert len(CASES) == 25


@pytest.mark.asyncio
async def test_filters_and_short_last_page(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[{"id": 42, "companyName": "Acme Ltd"}])

    mock_client(monkeypatch, handler)
    result = await make_node(
        {
            "operation": "list_companies",
            "per_page": 100,
            "sort": "id",
            "filters_json": '{"modifiedDateTime":{"from":"2026-01-01T00:00:00Z"},"isDeleted":false,"managerId":[1,2]}',
        }
    ).execute({})
    assert result["next_page"] is None
    query = requests[0].url.params
    assert query["filters[modifiedDateTime][from]"] == "2026-01-01T00:00:00Z"
    assert query.get_list("filters[managerId][]") == ["1", "2"]
    assert query["filters[isDeleted]"] == "false"


@pytest.mark.asyncio
async def test_connection_choices_use_account_data(monkeypatch):
    mock_client(
        monkeypatch,
        lambda r: httpx.Response(200, json=[{"id": 42, "companyName": "Acme Ltd"}]),
    )
    result = await ScoroNode.load_field_options(
        "company_id", credential_data=CREDENTIAL
    )
    assert result == {
        "options": [{"value": "42", "label": "Acme Ltd"}],
        "next_page_token": None,
    }


@pytest.mark.parametrize(
    "host",
    [
        "evil.com",
        "tutorial.scoro.com.evil.com",
        "https://tutorial.scoro.com",
        "localhost",
        "a.scoro.com:443",
        "a.scoro.com/path",
    ],
)
def test_tenant_host_is_bound_to_scoro(host):
    with pytest.raises(ValidationError):
        ScoroOAuthCredential.model_validate({**CREDENTIAL, "site_host": host})


@pytest.mark.parametrize(
    "operation",
    ["create_project", "create_quote", "create_invoice", "create_time_entry"],
)
def test_required_body_fields_are_required(operation):
    with pytest.raises(ValidationError):
        make_node({"operation": operation, "task_id": 42})


def test_patch_needs_a_change_and_dates_need_timezone():
    with pytest.raises(ValidationError):
        make_node({"operation": "update_task", "task_id": 42})
    with pytest.raises(ValidationError):
        make_node(
            {
                "operation": "create_task",
                "name": "Call",
                "due_date_time": "2026-10-19T09:00:00",
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_errors_are_not_success_and_creates_are_not_retried(monkeypatch, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={"error": "denied", "message": 'Access denied to account "tutorial"'},
        )

    mock_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="Scoro API error"):
        await make_node(
            {"operation": "create_company", "company_name": "Acme Ltd"}
        ).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_oauth_pkce_exchange_and_rotating_refresh(monkeypatch):
    monkeypatch.setenv("SCORO_CLIENT_ID", "test-client")
    monkeypatch.setenv("SCORO_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("SCORO_REDIRECT_URI", raising=False)
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/v4/users/me":
            assert request.headers["Scoro-Company-Account"] == "tutorial"
            return httpx.Response(200, json={"firstName": "Jane", "lastName": "Smith"})
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "rotated-refresh",
                "expires_in": 3600,
            },
        )

    mock_client(monkeypatch, handler)
    context = {k: CREDENTIAL[k] for k in ["site_host", "company_account_id"]}
    tokens, name = await OAUTH_PROVIDER.exchange(
        "test-code",
        "https://noclick.com/api/auth/oauth/scoro/callback",
        "v" * 43,
        context=context,
    )
    assert name == "Jane" and tokens.refresh_token == "rotated-refresh"
    grant = parse_qs(requests[0].content.decode())
    assert grant["code_verifier"] == ["v" * 43] and grant["client_secret"] == [
        "test-secret"
    ]
    assert (
        requests[0].url.host == "tutorial.scoro.com"
        and requests[0].url.path == "/auth/oauth/token"
    )
    tokens = await OAUTH_PROVIDER.bind_refresh(context)("old-refresh")
    assert tokens.refresh_token == "rotated-refresh"
    assert parse_qs(requests[-1].content.decode())["grant_type"] == ["refresh_token"]
    response = httpx.Response(
        200,
        json={"access_token": "new-access"},
        request=httpx.Request("POST", "https://tutorial.scoro.com/auth/oauth/token"),
    )
    with pytest.raises(ValueError, match="refresh_token"):
        OAUTH_PROVIDER.parse_tokens(response, context=context)

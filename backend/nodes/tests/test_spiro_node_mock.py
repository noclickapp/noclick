"""Provider-authored request/response examples, plus failure and OAuth seams."""
import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes.core.registry import NodeFactory
from nodes.oauth.spiro_oauth import OAUTH_PROVIDER
from nodes.spiro_node import CONFIG_MODELS, SpiroOAuthCredential

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/spiro/contract_examples.json").read_text()
)
CASES = FIXTURE["operations"]
CREDENTIAL = {
    "credential_type": "spiro_oauth",
    "access_token": "issued-spiro-access-123",
    "refresh_token": "issued-spiro-refresh-123",
}


def node(config):
    return NodeFactory.create_node(
        node_id="spiro-test",
        node_type="automation-spiro",
        node_data={"config": config, "credentials": CREDENTIAL},
    )


def transport(monkeypatch, handler, module="nodes.spiro_node"):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session

    monkeypatch.setattr(module + ".guarded_async_client", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(CASES))
async def test_documented_requests_and_responses(monkeypatch, name):
    case = CASES[name]
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == case["method"]
        assert request.url.host == "api.spiro.ai"
        assert request.url.path == case["path"].format(**case["path_values"])
        assert (
            request.headers["authorization"] == "Bearer " + CREDENTIAL["access_token"]
        )
        assert request.headers["accept"] == "application/vnd.api+json"
        assert request.headers["content-type"] == "application/vnd.api+json"
        if case["request"]:
            expected = copy.deepcopy(case["request"])
            expected["data"]["attributes"].pop(
                "parent_id", None
            )  # not an exposed field
            if name == "create_opportunity":
                expected["data"]["attributes"][
                    "close_at"
                ] = "2019-06-25T08:35:17Z"  # request schema example
            for relation_name, relation in (
                expected["data"].get("relationships", {}).items()
            ):
                relation["data"]["id"] = str(relation["data"]["id"])
                # JSON:API identifiers include type even where an example omits it.
                relation["data"].setdefault("type", relation_name)
            assert json.loads(request.content) == expected
        return httpx.Response(
            case["status"],
            json=case["response"],
            headers={"content-type": "application/vnd.api+json; charset=utf-8"},
        )

    transport(monkeypatch, handler)
    result = await node(case["config"]).execute({})
    assert result["status"] == "success", result
    assert result["data"] == case["response"]["data"]
    assert len(requests) == 1
    if case["method"] != "GET":
        assert result["write_acknowledged"] is True


@pytest.mark.asyncio
async def test_pagination_filters_and_no_following_provider_links(monkeypatch):
    body = copy.deepcopy(CASES["list_contacts"]["response"])
    body["meta"]["pagination"]["next_page"] = 2
    body["links"] = {"next": "https://untrusted.invalid/steal"}
    requests = []

    def handler(request):
        requests.append(request)
        assert dict(request.url.params) == {
            "page[number]": "1",
            "page[size]": "50",
            "filter[email]": "adam@apiro.ai",
        }
        return httpx.Response(200, json=body)

    transport(monkeypatch, handler)
    result = await node(
        {"operation": "list_contacts", "filter_email": "adam@apiro.ai"}
    ).execute({})
    assert result["next_page"] == 2 and result["has_more"] is True
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"errors": [{"detail": "Rejected"}]},
        {"data": {}},
        {"data": [{"id": "1", "type": "company", "attributes": {}}]},
        {"data": [{"id": "../1", "type": "contact", "attributes": {}}]},
        {"data": [], "meta": {"pagination": {"next_page": 1}}},
    ],
)
async def test_bad_responses_never_claim_success(monkeypatch, body):
    transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    assert (await node({"operation": "list_contacts"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_mutation_timeout_has_unknown_outcome_and_no_retry(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("timeout", request=request)

    transport(monkeypatch, handler)
    result = await node(CASES["create_contact"]["config"]).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_mutation_wrong_resource_is_unknown(monkeypatch):
    body = copy.deepcopy(CASES["update_contact"]["response"])
    body["data"]["id"] = "999999"
    transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    result = await node(CASES["update_contact"]["config"]).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown"


@pytest.mark.asyncio
async def test_credential_rejection_retains_provider_detail(monkeypatch):
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            401, json={"error": "The access token is invalid"}
        ),
    )
    result = await node({"operation": "list_users"}).execute({})
    assert result["status"] == "error" and result["http_status"] == 401
    assert "The access token is invalid" in result["error"]


def test_manual_credential_default_and_required_fields():
    credential = SpiroOAuthCredential.model_validate(
        {k: v for k, v in CREDENTIAL.items() if k != "credential_type"}
    )
    assert credential.credential_type == "spiro_oauth"
    for value in ["https://example.com/token", "<token>", "Bearer secret"]:
        with pytest.raises(ValidationError):
            SpiroOAuthCredential(
                access_token=value, refresh_token=CREDENTIAL["refresh_token"]
            )


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_contact", "id": "../1"},
        {"operation": "get_company", "id": 0},
        {"operation": "update_contact", "id": 1},
        {
            "operation": "create_opportunity",
            "name": "Deal",
            "company_id": 1,
            "pipeline_id": 2,
        },
        {
            "operation": "create_activity",
            "subject": "Call",
            "description": "Done",
            "owner_type": "user",
            "owner_id": 1,
        },
    ],
)
def test_invalid_configs_fail_before_network(config):
    with pytest.raises(ValidationError):
        CONFIG_MODELS[config["operation"]].model_validate(config)


@pytest.mark.asyncio
async def test_oauth_identity_uses_jsonapi_and_names_organization(monkeypatch):
    def handler(request):
        assert (
            request.url.host == "api.spiro.ai" and request.url.path == "/api/v1/users"
        )
        assert request.headers["accept"] == "application/vnd.api+json"
        return httpx.Response(200, json=CASES["list_users"]["response"])

    transport(monkeypatch, handler, "nodes.oauth.spiro_oauth")
    name = await OAUTH_PROVIDER.account_name(CREDENTIAL["access_token"])
    assert name == "Spiro organization · sandy@koss.example"


def test_oauth_json_token_request_and_rotation(monkeypatch):
    monkeypatch.setenv("SPIRO_CLIENT_ID", "test-spiro-client")
    monkeypatch.setenv("SPIRO_CLIENT_SECRET", "test-spiro-secret")
    request = OAUTH_PROVIDER.token_request(
        {"grant_type": "refresh_token", "refresh_token": "issued-refresh"}
    )
    assert request["json"] == {
        "grant_type": "refresh_token",
        "refresh_token": "issued-refresh",
        "client_id": "test-spiro-client",
        "client_secret": "test-spiro-secret",
    }
    assert OAUTH_PROVIDER.rotates_refresh_tokens is True

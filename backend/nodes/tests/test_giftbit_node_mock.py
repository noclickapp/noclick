"""Giftbit wire regressions using the provider's published v1 response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import giftbit_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-giftbit-token-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/giftbit/published_examples.json").read_text())["responses"]
CASES = [
    ({"operation": "get_account"}, "GET /ping", {}),
    ({"operation": "list_brands", "currencyisocode": "USD", "embeddable": True}, "GET /brands", {"currencyisocode": "USD", "embeddable": "true", "limit": "20", "offset": "0"}),
    ({"operation": "get_brand", "brand_code": "WHOLEFOODS"}, "GET /brands/{brand_code}", {}),
    ({"operation": "list_regions"}, "GET /regions", {}),
    ({"operation": "create_order", "id": "clientProvidedGiftId_abc123", "price_in_cents": 5000, "gift_template": "XDKHE", "contacts": '[{"email":"pjohnson@giftbit.com"}]', "brand_codes": '["itunesus","amazonus"]'}, "POST /campaign", {"id": "clientProvidedGiftId_abc123", "price_in_cents": 5000, "gift_template": "XDKHE", "contacts": [{"email": "pjohnson@giftbit.com"}], "brand_codes": ["itunesus", "amazonus"], "delivery_type": "GIFTBIT_EMAIL"}),
    ({"operation": "get_order", "id": "clientProvidedGiftId_abc1232"}, "GET /campaign/{id}", {}),
    ({"operation": "get_links", "id": "clientProvidedGiftId_abc123"}, "GET /links/{id}", {}),
    ({"operation": "create_direct_link_order", "id": "clientProvidedId_abc123", "price_in_cents": 2500, "region": "USA", "link_count": 1, "expiry": "2025-01-01"}, "POST /direct_links", {"id": "clientProvidedId_abc123", "price_in_cents": 2500, "region": "USA", "link_count": 1, "expiry": "2025-01-01"}),
    ({"operation": "create_embedded_reward", "id": "myGift12345", "price_in_cents": 2500, "brand_code": "itunesus"}, "POST /embedded", {"id": "myGift12345", "price_in_cents": 2500, "brand_code": "itunesus"}),
    ({"operation": "get_funds"}, "GET /funds", {}),
    ({"operation": "add_funds", "currencyisocode": "USD", "fund_amount_in_cents": 25000, "id": "clientProvidedId_abc123"}, "POST /funds", {"currencyisocode": "USD", "fund_amount_in_cents": 25000, "id": "clientProvidedId_abc123"}),
    ({"operation": "list_rewards", "campaign_uuid": "8f5835dfb637413793c5d55f8ea95e23", "limit": 1}, "GET /gifts", {"campaign_uuid": "8f5835dfb637413793c5d55f8ea95e23", "limit": "1", "offset": "0", "order": "desc"}),
    ({"operation": "get_reward", "uuid": "d30be501ed2546e580c5c9eaf56633d9"}, "GET /gifts/{uuid}", {}),
    ({"operation": "resend_reward", "uuid": "7e0ef82bc386493498f145578268f1b2"}, "PUT /gifts/{uuid}", {"resend": True}),
    ({"operation": "cancel_reward", "uuid": "d30be501ed2546e580c5c9eaf56633d9"}, "DELETE /gifts/{uuid}", {}),
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, environment="testbed"):
    return NodeFactory.create_node(node_id="giftbit-contract", node_type="automation-giftbit",
        node_data={"config": config, "credentials": {"credential_type": "giftbit_api_token", "api_token": TOKEN, "environment": environment}})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,contract,expected", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_giftbit_published_example_wire(monkeypatch, config, contract, expected):
    requests = transport(monkeypatch, EXAMPLES[contract])
    result = await node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    method, path = contract.split(" ")
    for key in ("id", "brand_code", "uuid"):
        path = path.replace("{" + key + "}", config.get(key, ""))
    assert request.method == method and request.url.path == "/papi/v1" + path
    assert request.url.host == "api-testbed.giftbit.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if method == "GET":
        assert dict(request.url.params) == expected
    else:
        assert not request.url.params
    if method in {"POST", "PUT"}:
        assert json.loads(request.content) == expected
    if method == "DELETE":
        assert request.content == b""
    for key, value in EXAMPLES[contract].items():
        assert result[key] == value
    assert TOKEN not in str(result)
    if config["operation"] == "list_rewards":
        assert result["next_offset"] == 1


@pytest.mark.asyncio
async def test_giftbit_shortlink_order_and_pending_links(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["POST /campaign"])
    config = {"operation": "create_order", "gift_template": "XDKHE", "delivery_type": "SHORTLINK", "link_count": 1, "price_in_cents": 2500, "brand_codes": '["itunesus", "amazonus"]', "expiry": "2023-07-07", "id": "clientProvidedGiftId_abc123"}
    result = await node(config, "production").execute({})
    assert requests[0].url.host == "api.giftbit.com"
    assert json.loads(requests[0].content)["delivery_type"] == "SHORTLINK"
    assert "contacts" not in json.loads(requests[0].content)
    assert result["campaign"]["status"] == "API_CREATING"
    transport(monkeypatch, EXAMPLES["GET /links/{id}"])
    result = await node({"operation": "get_links", "id": config["id"]}).execute({})
    assert result["info"]["code"] == "INFO_LINKS_GENERATION_IN_PROGRESS"
    assert "shortlinks" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 402, 422, 429, 500])
async def test_giftbit_provider_error_is_never_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"error": {"message": "Provider rejection " + TOKEN}, "status": status}, status)
    with pytest.raises(ValueError, match=r"Provider rejection \[redacted\]"):
        await node({"operation": "get_funds"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_giftbit_timeout_write_is_ambiguous_and_not_retried(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout("secret " + TOKEN))
    with pytest.raises(ValueError, match="may have been accepted") as exc:
        await node(CASES[10][0]).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_giftbit_path_encoding_and_identity(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES["GET /campaign/{id}"])
    await node({"operation": "get_order", "id": "order/one?x=1#frag"}).execute({})
    assert requests[0].url.raw_path == b"/papi/v1/campaign/order%2Fone%3Fx%3D1%23frag"
    transport(monkeypatch, {"info": {"code": "INFO_CREDENTIALS"}})
    with pytest.raises(ValueError, match="recognizable account"):
        await node({"operation": "get_account"}).execute({})


@pytest.mark.parametrize("config", [
    {"operation": "create_order", "id": "order", "price_in_cents": 5000, "gift_template": "XDKHE"},
    {"operation": "create_order", "id": "order", "price_in_cents": 5000, "gift_template": "XDKHE", "delivery_type": "SHORTLINK"},
    {"operation": "create_direct_link_order", "id": "order", "price_in_cents": 5000},
    {"operation": "create_direct_link_order", "id": "order", "price_in_cents": 5000, "brand_codes": "{}"},
    {"operation": "create_direct_link_order", "id": "order", "price_in_cents": 5000, "brand_codes": '["itunesus"]', "expiry": "2026-02-30"},
    {"operation": "list_rewards", "delivery_status": "LINKCREATED"},
    {"operation": "list_rewards", "created_date_greater_than": "yesterday"},
    {"operation": "add_funds", "id": "fund", "currencyisocode": "AUD", "fund_amount_in_cents": 25000},
])
def test_giftbit_invalid_input_fails_before_http(config):
    with pytest.raises(ValueError):
        node(config)


def test_giftbit_manual_credential_default_and_environment():
    credential = native.GiftbitAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == "giftbit_api_token" and credential.environment == "testbed"
    for changes in ({"api_token": "Bearer " + TOKEN}, {"environment": "https://attacker.example"}):
        with pytest.raises(ValidationError):
            native.GiftbitAPITokenCredential.model_validate({"api_token": TOKEN, **changes})

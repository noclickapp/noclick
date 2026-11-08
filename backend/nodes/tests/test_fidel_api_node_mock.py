"""Exercise published routes and examples through NoClick's native runner."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from nodes import fidel_api_node as fidel
from nodes.core.connection_evidence import collect_evidence
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "fidel_api_key", "api_key": "sk_test_fixture_not_live"}
USER = "00000000-0000-4000-8000-000000000001"
ID = "3b7ec790-6422-4674-a3cc-129a9290d3c1"
EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/fidel-api/responses.json").read_text()
)


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.fidel.uk"
        assert request.headers["Fidel-Key"] == AUTH["api_key"]
        assert request.headers["Content-Type"] == "application/json"
        assert AUTH["api_key"] not in str(request.url)
        return replies.pop(0)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        fidel,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(
        node_type="automation-fidel-api",
        operation=operation,
        arguments=arguments or {},
        credential_data=AUTH.copy(),
        user_id=USER,
    )


CASES = [
    ("create_brand", {"name": "Test Brand"}, "POST", "/brands"),
    ("list_brands", {}, "GET", "/brands"),
    ("get_brand", {"brand_id": ID}, "GET", "/brands/" + ID),
    (
        "update_brand",
        {"brand_id": ID, "website_url": "https://example.com"},
        "PATCH",
        "/brands/" + ID,
    ),
    ("delete_brand", {"brand_id": ID}, "DELETE", "/brands/" + ID),
    ("create_program", {"name": "Test Program"}, "POST", "/programs"),
    ("list_programs", {}, "GET", "/programs"),
    ("get_program", {"program_id": ID}, "GET", "/programs/" + ID),
    (
        "update_program",
        {"program_id": ID, "name": "Updated Program"},
        "PATCH",
        "/programs/" + ID,
    ),
    ("delete_webhook", {"hook_id": ID}, "DELETE", "/hooks/" + ID),
    (
        "update_webhook",
        {"hook_id": ID, "url": "https://example.com/hooks"},
        "PATCH",
        "/hooks/" + ID,
    ),
    ("get_webhook", {"hook_id": ID}, "GET", "/hooks/" + ID),
    ("list_webhooks", {"program_id": ID}, "GET", "/programs/" + ID + "/hooks"),
    (
        "create_webhook_program",
        {
            "program_id": ID,
            "event": "marketplace.offer.live",
            "url": "https://example.com/hooks",
        },
        "POST",
        "/programs/" + ID + "/hooks",
    ),
    (
        "create_webhook_brand",
        {"event": "brand.consent", "url": "https://example.com/hooks"},
        "POST",
        "/hooks",
    ),
    (
        "create_offer",
        {
            "program_id": ID,
            "brand_id": ID,
            "country_code": "USA",
            "name": "Test Offer",
            "start_date": "2026-11-09T00:00:00",
            "type": {"name": "discount", "value": 10},
        },
        "POST",
        "/programs/" + ID + "/offers",
    ),
    (
        "update_offer",
        {"offer_id": ID, "name": "Updated Offer"},
        "PATCH",
        "/offers/" + ID,
    ),
    ("delete_offer", {"offer_id": ID}, "DELETE", "/offers/" + ID),
    ("list_offers", {}, "GET", "/offers"),
    (
        "create_offer_descriptor",
        {"offer_id": ID, "name": "Test Descriptor"},
        "POST",
        "/offers/" + ID + "/descriptors",
    ),
    (
        "list_offer_descriptors",
        {"offer_id": ID},
        "GET",
        "/offers/" + ID + "/descriptors",
    ),
    (
        "delete_offer_descriptor",
        {"offer_id": ID, "descriptor_id": ID},
        "DELETE",
        "/offers/" + ID + "/descriptors/" + ID,
    ),
    ("list_offer_locations", {"offer_id": ID}, "GET", "/offers/" + ID + "/locations"),
    (
        "create_offer_location",
        {
            "offer_id": ID,
            "address": "Rua dos Campeões Europeus",
            "city": "Porto",
            "country": "Portugal",
            "zip_code": "4350-415",
        },
        "POST",
        "/offers/" + ID + "/location",
    ),
    (
        "list_transactions_by_program",
        {"program_id": ID},
        "GET",
        "/programs/" + ID + "/transactions",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path", CASES)
async def test_fidel_api_published_routes_and_responses(
    transport, operation, arguments, method, path
):
    example = EXAMPLES[operation]
    transport[1].append(httpx.Response(example["status_code"], json=example["body"]))
    result = await run(operation, arguments)
    assert result["status"] == "success"
    assert len(transport[0]) == 1
    assert transport[0][0].method == method
    assert transport[0][0].url.path == "/v1" + path
    assert not transport[1]
    if example["status_code"] != 204:
        assert result["data"] == example["body"]


@pytest.mark.asyncio
async def test_fidel_api_nested_body_casing_and_custom_metadata(transport):
    transport[1].append(httpx.Response(201, json={"items": []}))
    arguments = dict(next(args for op, args, _, _ in CASES if op == "create_offer"))
    arguments.update(
        type={"name": "discount", "value": 10, "max_reward_amount": 100},
        fees={"fidel_fee": 25, "uncapped_publisher_fee": False},
        metadata={"my_custom_key": "preserved"},
        days_of_week=[0, 6],
    )
    await run("create_offer", arguments)
    body = json.loads(transport[0][0].content)
    assert body == {
        "brandId": ID,
        "countryCode": "USA",
        "name": "Test Offer",
        "startDate": "2026-11-09T00:00:00",
        "type": {"name": "discount", "value": 10.0, "maxRewardAmount": 100.0},
        "fees": {"fidelFee": 25.0, "uncappedPublisherFee": False},
        "metadata": {"my_custom_key": "preserved"},
        "daysOfWeek": [0, 6],
    }


@pytest.mark.asyncio
async def test_fidel_api_pagination_filters_and_false_values(transport):
    page = {"items": [], "count": 17, "last": {"id": ID}}
    transport[1].append(httpx.Response(200, json=page))
    result = await run(
        "list_offers",
        {
            "limit": 25,
            "start": '{"id":"last-id"}',
            "approval": False,
            "activation": True,
            "brand_id": ID,
            "expiring_in_days": 0,
        },
    )
    assert dict(transport[0][0].url.params) == {
        "limit": "25",
        "start": '{"id":"last-id"}',
        "approval": "false",
        "activation": "true",
        "brandId": ID,
        "expiringInDays": "0",
    }
    assert result["data"] == page


@pytest.mark.asyncio
async def test_fidel_api_connection_evidence_is_account_brands(transport):
    transport[1].append(
        httpx.Response(
            200, json={"items": [{"id": ID, "name": "My Account Brand"}], "count": 1}
        )
    )
    result = await collect_evidence(
        node_type="automation-fidel-api", credential_data=AUTH, user_id=USER
    )
    assert result.reachable is True
    assert result.samples[0].label == "My Account Brand"
    assert transport[0][0].url.path == "/v1/brands"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_fidel_api_provider_failures_and_redaction(transport, status):
    transport[1].append(
        httpx.Response(status, json={"message": "Rejected " + AUTH["api_key"]})
    )
    result = await run("list_brands")
    assert result["status"] == "error" and result["http_status"] == status
    assert AUTH["api_key"] not in json.dumps(result)
    assert "Rejected" in result["error"] and len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["../secret", "a/b", "a%2fb", "https://example.com", "abc\n"]
)
async def test_fidel_api_path_injection_refused(transport, bad):
    with pytest.raises(ValueError):
        await run("get_brand", {"brand_id": bad})
    assert not transport[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not json", b"[]"])
async def test_fidel_api_malformed_success_refused(transport, body):
    transport[1].append(httpx.Response(200, content=body))
    with pytest.raises(ValueError):
        await run("list_brands")


def test_fidel_api_manual_credential_default():
    credential = fidel.FidelAPIKeyCredential(api_key=AUTH["api_key"])
    assert credential.credential_type == "fidel_api_key"
    for invalid in ["https://example.com", "key with spaces", ""]:
        with pytest.raises(ValueError):
            fidel.FidelAPIKeyCredential(api_key=invalid)


@pytest.mark.asyncio
async def test_fidel_api_nested_error_and_success_error_envelope(transport):
    transport[1].append(
        httpx.Response(401, json={"error": {"message": "API key is invalid"}})
    )
    result = await run("list_brands")
    assert result["error"] == "API key is invalid"
    transport[1].append(httpx.Response(200, json={"error": {"message": "Rejected"}}))
    result = await run("list_brands")
    assert result["status"] == "error"

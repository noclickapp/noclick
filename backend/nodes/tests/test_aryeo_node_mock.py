"""Aryeo's published examples exercised through the native node factory.

Fixtures are copied from the pinned Aryeo OpenAPI 2021-06-17 response examples:
https://raw.githubusercontent.com/AryeoHQ/aryeo-api-go-sdk/master/api/openapi.yaml
No account or live credential is used.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import aryeo_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/aryeo/contract_examples.json").read_text()
)
TOKEN = "synthetic-aryeo-token-for-tests"
ID = "00000000-0000-4000-8000-000000000000"


def node(config):
    return NodeFactory.create_node(
        node_id="aryeo-test",
        node_type="automation-aryeo",
        node_data={
            "config": config,
            "credentials": {"credential_type": "aryeo_api_token", "api_token": TOKEN},
        },
    )


def transport(monkeypatch, body, status=200):
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_published_examples_and_exact_one_request(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = transport(monkeypatch, example["response"], example["status"])
    result = await node(example["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == example["response"].get("data")
    assert len(requests) == 1
    request = requests[0]
    path = example["path"]
    for key, value in example["config"].items():
        path = path.replace("{" + key + "}", value)
    assert request.method == example["method"]
    assert request.url.host == "api.aryeo.com" and request.url.path == "/v1" + path
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert request.headers["Aryeo-Version"] == "2021-06-17"
    if operation in {"cancel_appointment", "reschedule_appointment"}:
        assert json.loads(request.content)["notify_customer"] is False
    if operation == "create_order":
        assert json.loads(request.content) == {"notify": False}


@pytest.mark.asyncio
async def test_query_filters_arrays_and_page_metadata(monkeypatch):
    body = {
        "status": "success",
        "data": [],
        "links": {"next": "https://other.invalid/"},
        "meta": {"current_page": 2},
    }
    requests = transport(monkeypatch, body)
    result = await node(
        {
            "operation": "list_appointments",
            "page": "2",
            "per_page": "10",
            "filter_user_ids": [ID, ID],
            "filter_tense": "UPCOMING",
            "include": "order,users",
        }
    ).execute({})
    assert requests[0].url.params.get_list("filter[user_ids]") == [ID, ID]
    assert requests[0].url.params["filter[tense]"] == "UPCOMING"
    assert requests[0].url.params["page"] == "2"
    assert result["meta"] == body["meta"] and result["links"] == body["links"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_order_payload_preserves_false_and_uppercase_enum(monkeypatch):
    requests = transport(monkeypatch, {"status": "success", "data": {"id": ID}}, 201)
    await node(
        {
            "operation": "create_order",
            "address_id": ID,
            "customer_id": ID,
            "fulfillment_status": "UNFULFILLED",
            "notify": False,
            "lock_download_for_payment": False,
        }
    ).execute({})
    assert json.loads(requests[0].content) == {
        "address_id": ID,
        "customer_id": ID,
        "fulfillment_status": "UNFULFILLED",
        "notify": False,
        "lock_download_for_payment": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_provider_rejections_are_errors_and_secrets_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    result = await node({"operation": "list_listings"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [{}, {"status": "error", "data": []}, {"status": "success", "data": {}}]
)
async def test_malformed_list_envelope_is_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_listings"}).execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_listing", "listing_id": "../orders"},
        {"operation": "list_listings", "page": "0"},
        {"operation": "create_order", "fulfillment_status": "fulfilled"},
        {
            "operation": "reschedule_appointment",
            "appointment_id": ID,
            "start_at": "2026-01-01",
            "end_at": "2026-01-02",
        },
        {
            "operation": "reschedule_appointment",
            "appointment_id": ID,
            "start_at": "2026-01-02T00:00:00Z",
            "end_at": "2026-01-01T00:00:00Z",
        },
    ],
)
def test_invalid_inputs_rejected(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_default_and_evidence_contract():
    c = native.AryeoAPITokenCredential(api_token=TOKEN)
    assert c.credential_type == "aryeo_api_token"
    assert native.AryeoNode.connection_evidence.operation == "list_listings"
    assert len(native.ROUTES) == 15
    assert (
        native.AryeoAPITokenCredential.model_json_schema()["properties"]["api_token"][
            "ui:widget"
        ]
        == "password"
    )

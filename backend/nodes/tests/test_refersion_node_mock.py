"""Refersion HTTP-boundary regressions; no live requests or credentials.

Request examples: https://refersion.dev/openapi/api-public.resolved.json (3.0.0).
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import refersion_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads(
    (Path(__file__).parent / "fixtures/refersion/requests.json").read_text()
)
TOKEN = "synthetic-refersion-access-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="refersion-test",
        node_type="automation-refersion",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "refersion_access_token",
                "access_token": TOKEN,
            },
        },
    )


def transport(monkeypatch, response):
    calls = []

    def handle(request):
        calls.append(request)
        return response

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_published_request_contract(monkeypatch, case):
    payload = {
        "data": [{"id": 42, "name": "Summer Sale Offer"}],
        "meta": {"currentPage": 1, "lastPage": 2},
    }
    calls = transport(monkeypatch, httpx.Response(200, json=payload))
    result = await node(case["config"]).execute({})
    assert result["status"] == "success" and result["data"] == payload
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case["method"]
    assert request.url.host == "api.refersion.com" and request.url.path == case["path"]
    assert dict(request.url.params) == case["query"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_filters_arrays_false_and_explicit_null(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(200, json={"data": []}))
    await node(
        {
            "operation": "list_affiliates",
            "status": ["approved", "pending"],
            "has_pending_conversions": False,
            "offer_ids": [42, 43],
            "page": 2,
            "limit": 20,
        }
    ).execute({})
    assert calls[0].url.params.get_list("status[]") == ["approved", "pending"]
    assert calls[0].url.params.get_list("offerIds[]") == ["42", "43"]
    assert calls[0].url.params["hasPendingConversions"] == "false"
    assert calls[0].url.params["page"] == "2"
    await node(
        {
            "operation": "update_affiliate",
            "affiliate_id": 12345,
            "body": {"id": 12345, "company": None, "sendEmailNotifications": False},
        }
    ).execute({})
    assert json.loads(calls[1].content) == {
        "id": 12345,
        "company": None,
        "sendEmailNotifications": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 422, 429, 500])
async def test_provider_rejections_and_retry_after(monkeypatch, status):
    calls = transport(
        monkeypatch,
        httpx.Response(
            status,
            json={"error": "Rejected credential " + TOKEN},
            headers={"Retry-After": "42"},
        ),
    )
    result = await node({"operation": "list_offers"}).execute({})
    assert result["status"] == "error" and result["status_code"] == status
    assert result["retry_after"] == "42" and TOKEN not in str(result)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_no_content_and_no_redirects(monkeypatch):
    transport(monkeypatch, httpx.Response(204))
    result = await node(
        {"operation": "delete_webhook_endpoint", "endpoint_id": "ep_2abcDEF456ghi"}
    ).execute({})
    assert result["status"] == "success" and result["data"] is None
    transport(
        monkeypatch, httpx.Response(302, headers={"Location": "https://other.example/"})
    )
    assert (await node({"operation": "list_offers"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_mismatched_affiliate_ids_refused_before_http(monkeypatch):
    calls = transport(monkeypatch, httpx.Response(200, json={}))
    with pytest.raises(ValueError, match="match"):
        await node(
            {
                "operation": "update_affiliate",
                "affiliate_id": 1,
                "body": {"id": 2, "status": "APPROVED"},
            }
        ).execute({})
    assert calls == []


@pytest.mark.parametrize("value", ["../other", "https://example.com", ""])
def test_invalid_webhook_endpoint_path(value):
    with pytest.raises(ValueError):
        node({"operation": "delete_webhook_endpoint", "endpoint_id": value})


def test_manual_credential_default_and_token_shape():
    assert (
        native.RefersionAccessTokenCredential(access_token=TOKEN).credential_type
        == "refersion_access_token"
    )
    for value in ["Bearer " + TOKEN, "https://example.com/key", "has\ncontrols"]:
        with pytest.raises(ValidationError):
            native.RefersionAccessTokenCredential(access_token=value)


@pytest.mark.parametrize(
    "body",
    [
        {"topics": []},
        {"topics": ["conversion.created", "conversion.created"]},
        {"url": "http://example.com"},
        {},
    ],
)
def test_webhook_edit_requires_valid_change(body):
    with pytest.raises(ValidationError):
        native.UpdateWebhookEndpointRequest(**body)


def test_nullable_payload_fields_and_unset_optional_fields():
    body = native.UpdateAffiliateRequest(id=12345, company=None, firstName=None)
    assert native._request_body(body.model_dump(by_alias=True, exclude_unset=True)) == {
        "id": 12345,
        "company": None,
    }


@pytest.mark.asyncio
async def test_connection_evidence_shows_account_offers_and_rejects_dead_token(
    monkeypatch,
):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op

    async def execute_probe(**kwargs):
        assert kwargs["operation"] == "list_offers"
        return await node({"operation": kwargs["operation"]}).execute({})

    monkeypatch.setattr(run_op, "run_node_operation", execute_probe)
    transport(
        monkeypatch,
        httpx.Response(200, json={"data": [{"id": 42, "name": "Summer Sale Offer"}]}),
    )
    result = await collect_evidence(
        node_type="automation-refersion",
        user_id="refersion-test",
        credential_data={
            "credential_type": "refersion_access_token",
            "access_token": TOKEN,
        },
    )
    assert result.reachable is True and result.samples[0].label == "Summer Sale Offer"
    transport(
        monkeypatch, httpx.Response(401, json={"error": "Authentication required"})
    )
    result = await collect_evidence(
        node_type="automation-refersion",
        user_id="refersion-test",
        credential_data={
            "credential_type": "refersion_access_token",
            "access_token": TOKEN,
        },
    )
    assert result.reachable is False and not result.samples

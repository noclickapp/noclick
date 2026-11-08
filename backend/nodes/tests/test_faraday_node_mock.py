"""Offline wire-contract checks. Keys and account data are synthetic."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import faraday_node as native
from nodes.core.registry import NodeFactory

ID = "b80217ae-7628-4c66-8a19-5bf452495c39"
KEY = "synthetic-faraday-key-42"
AUTH = {"credential_type": "faraday_api_key", "api_key": KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **fields):
    return NodeFactory.create_node(
        node_id="faraday-test",
        node_type="automation-faraday",
        node_data={"config": {"operation": operation, **fields}, "credentials": AUTH},
    )


def transport(monkeypatch, status=200, body=None, headers=None):
    requests = []
    client_class = httpx.AsyncClient

    def reply(request):
        requests.append(request)
        return httpx.Response(
            status, **({"json": body} if body is not None else {}), headers=headers
        )

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return client_class(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ("get_current_account", "GET", "/accounts/current", {}, 200, None),
    ("list_datasets", "GET", "/datasets", {}, 200, None),
    ("get_dataset", "GET", "/datasets/" + ID, {"dataset_id": ID}, 200, None),
    (
        "rerun_dataset",
        "POST",
        "/datasets/" + ID + "/force_update",
        {"dataset_id": ID},
        202,
        None,
    ),
    ("list_cohorts", "GET", "/cohorts", {}, 200, None),
    ("get_cohort", "GET", "/cohorts/" + ID, {"cohort_id": ID}, 200, None),
    (
        "create_cohort",
        "POST",
        "/cohorts",
        {"name": "Customers", "stream_name": "transaction", "min_count": 1},
        201,
        {"name": "Customers", "stream_name": "transaction", "min_count": 1},
    ),
    (
        "update_cohort",
        "PATCH",
        "/cohorts/" + ID,
        {"cohort_id": ID, "name": "Customers", "min_count": 2},
        200,
        {"name": "Customers", "min_count": 2},
    ),
    ("delete_cohort", "DELETE", "/cohorts/" + ID, {"cohort_id": ID}, 204, None),
    (
        "rerun_cohort",
        "POST",
        "/cohorts/" + ID + "/force_update",
        {"cohort_id": ID},
        202,
        None,
    ),
    ("list_outcomes", "GET", "/outcomes", {}, 200, None),
    ("get_outcome", "GET", "/outcomes/" + ID, {"outcome_id": ID}, 200, None),
    (
        "create_outcome",
        "POST",
        "/outcomes",
        {"name": "Lead Conversion", "attainment_cohort_id": ID},
        201,
        {
            "name": "Lead Conversion",
            "attainment_cohort_id": ID,
            "preview": True,
            "prediction_mode": "auto",
        },
    ),
    (
        "update_outcome",
        "PATCH",
        "/outcomes/" + ID,
        {"outcome_id": ID, "name": "Lead Conversion"},
        200,
        {"name": "Lead Conversion"},
    ),
    (
        "rerun_outcome",
        "POST",
        "/outcomes/" + ID + "/force_update",
        {"outcome_id": ID},
        202,
        None,
    ),
    ("list_scopes", "GET", "/scopes", {}, 200, None),
    ("get_scope", "GET", "/scopes/" + ID, {"scope_id": ID}, 200, None),
    (
        "rerun_scope",
        "POST",
        "/scopes/" + ID + "/force_update",
        {"scope_id": ID},
        202,
        None,
    ),
    ("list_targets", "GET", "/targets", {}, 200, None),
    ("get_target", "GET", "/targets/" + ID, {"target_id": ID}, 200, None),
    (
        "rerun_target",
        "POST",
        "/targets/" + ID + "/force_update",
        {"target_id": ID},
        202,
        None,
    ),
    (
        "lookup_target",
        "POST",
        "/targets/" + ID + "/lookup",
        {"target_id": ID, "email": "jane@example.com"},
        200,
        {"identity_sets": [{"email": "jane@example.com"}]},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,path,fields,status,body", CASES)
async def test_faraday_wire_contract(
    monkeypatch, operation, method, path, fields, status, body
):
    resource = {
        "id": ID,
        "name": "Customers",
        "status": "ready",
        "api_key": "other-account-key",
    }
    response = (
        None
        if status in {202, 204}
        else [resource]
        if operation.startswith("list_")
        else resource
    )
    requests = transport(monkeypatch, status, response)
    instance = node(operation, **fields)
    instance.emit = AsyncMock()
    result = await instance.execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url) == native.BASE_URL + path
    assert request.headers["Authorization"] == "Bearer " + KEY
    if body is None:
        assert request.content == b""
    else:
        assert json.loads(request.content) == body
        assert request.headers["Content-Type"] == (
            "application/merge-patch+json" if method == "PATCH" else "application/json"
        )
    assert result["http_status"] == status
    assert result["status"] == ("accepted" if status == 202 else "success")
    assert "other-account-key" not in json.dumps(result)
    assert KEY not in json.dumps(result)
    instance.emit.assert_awaited_once_with(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_faraday_provider_rejection_is_not_success(monkeypatch, status):
    requests = transport(
        monkeypatch, status, {"error": "EXPIRED_API_KEY", "note": "Refused " + KEY}
    )
    with pytest.raises(ValueError) as exc:
        await node("get_current_account").execute({})
    assert str(status) in str(exc.value) and KEY not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body", [{"error": "EXPIRED_API_KEY", "note": "Key expired"}, [], "bad shape", {}]
)
async def test_faraday_invalid_identity_never_proves_account(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node("get_current_account").execute({})


@pytest.mark.parametrize(
    "key", ["Bearer abc", "https://faraday.ai/key", "abc\nInjected", "<token>"]
)
def test_faraday_manual_key_validation(key):
    with pytest.raises(ValidationError):
        native.FaradayAPIKeyCredential(api_key=key)


def test_faraday_manual_credential_default():
    assert (
        native.FaradayAPIKeyCredential(api_key=KEY).credential_type == "faraday_api_key"
    )
    assert (
        native.FaradayNode.connection_evidence.identity_operation
        == "get_current_account"
    )


@pytest.mark.parametrize(
    "fields", [{"cohort_id": "../accounts"}, {"cohort_id": ID, "unexpected": True}]
)
def test_faraday_invalid_operation_input(fields):
    with pytest.raises(ValueError):
        node("get_cohort", **fields)


@pytest.mark.asyncio
async def test_faraday_lookup_no_match_is_a_valid_domain_outcome(monkeypatch):
    transport(
        monkeypatch,
        body={"error": "Could not match an identity with the provided information"},
    )
    result = await node(
        "lookup_target", target_id=ID, email="john.doe@example.com"
    ).execute({})
    assert result["status"] == "success" and result["matched"] is False


@pytest.mark.asyncio
async def test_faraday_lookup_preserves_null_prediction(monkeypatch):
    body = {
        "match_type": "email_only",
        "fdy_outcome_example_propensity_probability": None,
    }
    transport(monkeypatch, body=body)
    result = await node(
        "lookup_target", target_id=ID, email="john.doe@example.com"
    ).execute({})
    assert result["matched"] is True
    assert result["data"]["fdy_outcome_example_propensity_probability"] is None


@pytest.mark.asyncio
async def test_faraday_provider_authored_lookup_response(monkeypatch):
    example = json.loads(
        (Path(__file__).parent / "fixtures/faraday/lookup_response.json").read_text()
    )
    body = example["body"]
    transport(monkeypatch, body=body)
    result = await node("lookup_target", target_id=ID, email=body["email"]).execute({})
    assert result["matched"] is True
    assert result["data"] == body

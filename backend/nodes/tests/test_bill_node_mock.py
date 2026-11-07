"""BILL docs responses and real HTTP serialization, without account access.

Fixture source URLs and provenance are recorded per operation in responses.json.
Guides: https://developer.bill.com/docs/ap-bills, /creating-a-us-vendor,
/ar-customers, /ap-bill-approvals, /ap-payments and /record-ap-payments.
List envelopes and SUCCESS are defined by the official OpenAPI response schemas:
https://developer.bill.com/openapi/bill-v3-api.json.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote

import httpx
import pytest

from nodes.bill_node import BillNode, BillNodeConfig, BILL_ROUTES


FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/bill/responses.json").read_text()
)


def node(config, environment="sandbox"):
    return BillNode(
        node_id="bill-test",
        node_type="automation-bill",
        node_data={},
        sio=Mock(),
        config=BillNodeConfig(
            config=config,
            credentials={
                "credential_type": "bill_session",
                "dev_key": "test-developer-secret",
                "session_id": "test-session-secret",
                "environment": environment,
            },
        ),
    )


async def run(config, response, status=200, environment="sandbox"):
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(status, json=response)

    original = httpx.AsyncClient
    with patch(
        "nodes.bill_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(transport),
        ),
    ):
        result = await node(config, environment).execute({})
    return result, requests


@pytest.mark.parametrize("operation", FIXTURES)
async def test_documented_operation(operation):
    fixture = FIXTURES[operation]
    config = {"operation": operation, **fixture["config"]}
    result, requests = await run(
        config, fixture["response"], fixture["response_status"]
    )
    assert result["status"] == "success"
    assert result["action"] == operation
    expected = fixture["response"]
    if operation == "list_approval_policies":
        expected = {"policies": expected}
    assert result["data"] == expected
    (request,) = requests
    assert request.method == fixture["method"]
    route = BILL_ROUTES[operation]
    expected_path = fixture["path"]
    for field, key in route["path_fields"].items():
        expected_path = expected_path.replace(
            "{" + key + "}", quote(config[field], safe="")
        )
    assert request.url.raw_path.decode().split("?")[0] == "/connect" + expected_path
    assert request.url.host == "gateway.stage.bill.com"
    assert request.headers["devKey"] == "test-developer-secret"
    assert request.headers["sessionId"] == "test-session-secret"
    assert "test-developer-secret" not in str(request.url)
    assert "test-session-secret" not in str(request.url)
    if route["body_fields"]:
        parsed = node(config).config.config
        values = parsed.model_dump(mode="json", exclude_none=True)
        expected_body = {
            key: json.loads(values[field])
            if field in parsed.json_fields
            else values[field]
            for field, key in route["body_fields"].items()
            if field in values
        }
        if route["array_body"]:
            expected_body = expected_body["actions"]
        assert json.loads(request.content) == expected_body
        assert request.headers["content-type"] == "application/json"
    else:
        assert request.content == b""


async def test_pagination_and_production_host():
    result, requests = await run(
        {
            "operation": "list_vendors",
            "max_results": 10,
            "sort": "createdTime:desc",
            "filters": "name:fz:acme corp",
            "page": "next-page-token",
        },
        {"results": [], "nextPage": "page-two", "prevPage": "page-zero"},
        environment="production",
    )
    (request,) = requests
    assert request.url.host == "gateway.prod.bill.com"
    assert dict(request.url.params) == {
        "max": "10",
        "sort": "createdTime:desc",
        "filters": "name:fz:acme corp",
        "page": "next-page-token",
    }
    assert result["data"] == {
        "results": [],
        "nextPage": "page-two",
        "prevPage": "page-zero",
    }


async def test_payment_scheduling_preserves_date_and_false_flags():
    fixture = FIXTURES["schedule_payment"]
    _, requests = await run(
        {"operation": "schedule_payment", **fixture["config"]}, fixture["response"], 201
    )
    body = json.loads(requests[0].content)
    assert body["processDate"] == "2026-12-31"
    assert body["processingOptions"] == {"requestPayFaster": False, "createBill": False}
    assert requests[0].url.path == "/connect/v3/payments"


async def test_record_payment_does_not_schedule_funds():
    fixture = FIXTURES["record_payment"]
    _, requests = await run(
        {"operation": "record_payment", **fixture["config"]}, fixture["response"]
    )
    assert requests[0].url.path == "/connect/v3/bills/record-payment"
    assert json.loads(requests[0].content)["toPrintCheck"] is False


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_api_errors_preserve_provider_message_and_redact_secrets(status):
    result, _ = await run(
        {"operation": "list_vendors"},
        [
            {
                "code": "BDC_1121",
                "message": "Session expired test-session-secret test-developer-secret",
            }
        ],
        status,
    )
    assert result["status"] == "error"
    assert result["status_code"] == status
    assert "Session expired" in result["error"]
    assert "test-session-secret" not in str(result)
    assert "test-developer-secret" not in str(result)


@pytest.mark.parametrize("body", [[], {"status": "FAILURE"}, {}])
async def test_unexpected_or_failed_responses_are_not_success(body):
    result, _ = await run({"operation": "list_vendors"}, body)
    assert result["status"] == "error"


@pytest.mark.parametrize("value", ["not json", "[]", "null"])
async def test_bad_json_object_fails_before_request(value):
    config = {
        "operation": "create_vendor",
        "name": "Happy Music Supplies",
        "address": value,
    }
    with patch("nodes.bill_node.httpx.AsyncClient") as client:
        with pytest.raises(ValueError, match="address must be"):
            await node(config).execute({})
        client.assert_not_called()


async def test_connection_evidence_reads_vendors_without_required_arguments():
    assert BillNode.connection_evidence.operation == "list_vendors"
    result, requests = await run({"operation": "list_vendors"}, {"results": []})
    assert result["status"] == "success"
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/connect/v3/vendors"


async def test_transport_errors_do_not_leak_request_secrets():
    with patch("nodes.bill_node.httpx.AsyncClient") as client:
        client.return_value.__aenter__.return_value.request.side_effect = (
            httpx.ConnectError("test-session-secret")
        )
        result = await node({"operation": "list_vendors"}).execute({})
    assert result == {
        "status": "error",
        "action": "list_vendors",
        "error": "Could not reach the BILL API",
    }


async def test_invalid_json_response_is_not_success():
    original = httpx.AsyncClient
    with patch(
        "nodes.bill_node.httpx.AsyncClient",
        side_effect=lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, text="<html>unexpected</html>")
            ),
        ),
    ):
        result = await node({"operation": "list_vendors"}).execute({})
    assert result["status"] == "error"
    assert result["error"] == "BILL returned invalid JSON"

"""Offline HTTP and native operation coverage; response from TrackingMore's quick-start guide."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import trackingmore_node as tm

BODY = json.loads((Path(__file__).parent / "fixtures/trackingmore/get_results.json").read_text())
KEY = {"credential_type": "trackingmore_api_key", "api_key": "test-trackingmore-secret"}


def transport(monkeypatch, response):
    original = httpx.AsyncClient
    calls = []
    def handler(request):
        assert request.url.host == "api.trackingmore.com"
        assert request.headers["Tracking-Api-Key"] == KEY["api_key"]
        assert KEY["api_key"] not in str(request.url)
        assert "Authorization" not in request.headers and "Trackingmore-Api-Key" not in request.headers
        calls.append(request)
        return response(request)
    monkeypatch.setattr(tm.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return calls


@pytest.mark.asyncio
async def test_native_operation_uses_staging_credential_resolution(monkeypatch):
    from nodes.core.run_op import run_node_operation
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", AsyncMock(return_value=dict(KEY)))
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=BODY))
    row = BODY["data"][0]
    result = await run_node_operation(node_type="automation-trackingmore", operation="get_tracking_result",
        arguments={"tracking_number": row["tracking_number"], "courier_code": row["courier_code"]},
        user_id="00000000-0000-4000-8000-000000000002", credential_id="00000000-0000-4000-8000-000000000001", pool=object())
    assert result["status"] == "success" and result["data"]["shipment"]["id"] == row["id"]
    assert len(calls) == 1 and calls[0].method == "GET" and calls[0].url.path == "/v4/trackings/get"
    assert dict(calls[0].url.params) == {"tracking_numbers": row["tracking_number"], "courier_code": row["courier_code"], "items_amount": "100", "pages_amount": "1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(200, 401), (200, "200"), (202, 200), (403, 403), (429, 429), (200, 429), (503, 511)])
async def test_http_and_meta_failures_are_sanitized_without_retries(monkeypatch, status, code):
    calls = transport(monkeypatch, lambda request: httpx.Response(status, json={"meta": {"code": code, "message": KEY["api_key"]}, "data": BODY["data"]}))
    raw = {"credentials": KEY, "config": {"operation": "list_couriers"}}
    node = tm.TrackingMoreNode("tm", "automation-trackingmore", raw, config=tm.TrackingMoreNode.parse_config(raw))
    result = await node.execute({})
    assert result["status"] == "error" and len(calls) == 1 and KEY["api_key"] not in str(result)
    if 429 in (status, code):
        assert result["retry_after_seconds"] == 120 and result["_halt_downstream"] is True


@pytest.mark.asyncio
async def test_malformed_success_is_refused(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"meta": {"code": 200}, "data": {}}))
    with pytest.raises(tm.TrackingMoreAPIError):
        await tm.request(KEY, "GET", "/v4/couriers/all")

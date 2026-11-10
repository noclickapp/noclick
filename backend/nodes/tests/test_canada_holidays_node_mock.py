"""Factory/HTTP boundary checks using the provider's published response examples."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import canada_holidays_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/canada-holidays/responses.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id="canada-holidays-fixture", node_type=native.CanadaHolidaysNode.integration_type,
        node_data={"config": config, "credentials": credentials})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, text=body) if isinstance(body, str) else httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_holidays", "year": 2023}, "/api/v1/holidays", {"year": "2023", "optional": "false"}),
    ({"operation": "list_federal_holidays"}, "/api/v1/holidays", {"optional": "false", "federal": "true"}),
    ({"operation": "list_non_federal_holidays"}, "/api/v1/holidays", {"optional": "false", "federal": "false"}),
    ({"operation": "list_optional_holidays"}, "/api/v1/holidays", {"optional": "true"}),
    ({"operation": "get_holiday", "holiday_id": 35}, "/api/v1/holidays/{holidayId}", {"optional": "false"}),
    ({"operation": "list_provinces"}, "/api/v1/provinces", {"optional": "false"}),
    ({"operation": "get_province", "province_id": "MB"}, "/api/v1/provinces/{provinceId}", {"optional": "false"}),
    ({"operation": "get_province_with_optional_holidays", "province_id": "MB"}, "/api/v1/provinces/{provinceId}", {"optional": "true"}),
    ({"operation": "get_api_info"}, "/api/v1", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,params", CASES)
async def test_canada_holidays_documented_responses_and_requests(monkeypatch, config, path, params):
    body = EXAMPLES[path]
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result == {**body, "status": "success", "operation": config["operation"]}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.url.host == "canada-holidays.ca"
    assert request.url.path == path.replace("{holidayId}", "35").replace("{provinceId}", "MB")
    assert dict(request.url.params) == params
    assert not request.content and "authorization" not in request.headers


@pytest.mark.asyncio
async def test_canada_holidays_preserves_yaml_spec(monkeypatch):
    text = "openapi: 3.0.0\ninfo:\n  version: 1.15.0\n"
    requests = transport(monkeypatch, text)
    result = await node({"operation": "get_api_spec"}, credentials={}).execute({})
    assert result["spec"] == text and result["status"] == "success"
    assert requests[0].url.path == "/api/v1/spec" and not requests[0].url.params


@pytest.mark.asyncio
async def test_canada_holidays_combined_filters_and_observed_dates(monkeypatch):
    body = EXAMPLES["/api/v1/holidays"]
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_holidays", "year": 2031, "federal": False, "optional": True}).execute({})
    assert dict(requests[0].url.params) == {"year": "2031", "federal": "false", "optional": "true"}
    assert result["holidays"][0]["date"] == "2023-01-01"
    assert result["holidays"][0]["observedDate"] == "2023-01-02"
    assert result["holidays"][0]["nameFr"] == body["holidays"][0]["nameFr"]


@pytest.mark.parametrize("config", [
    {"operation": "get_holiday", "holiday_id": 0}, {"operation": "get_holiday", "holiday_id": 36},
    {"operation": "get_holiday"}, {"operation": "get_province", "province_id": "../../spec"},
    {"operation": "get_province", "province_id": "on"}, {"operation": "get_province"},
    {"operation": "list_holidays", "year": 2012}, {"operation": "list_holidays", "year": 2039},
    {"operation": "get_api_info", "url": "https://example.test"}, {"operation": "write_holiday"},
])
def test_canada_holidays_rejects_unsupported_inputs(config):
    assert not native.CanadaHolidaysNode.validate_config({"config": config})["valid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body,status,error", [
    ({"error": {"status": 400, "message": "Bad Request"}}, 400, httpx.HTTPStatusError),
    ({"error": {"message": "Failed"}}, 200, ValueError),
    ({"holidays": {}}, 200, ValueError), ({"holidays": [None]}, 200, ValueError),
    ([], 200, ValueError), ("unavailable", 503, httpx.HTTPStatusError),
    ("moved", 302, httpx.HTTPStatusError), ("<html>Error</html>", 200, ValueError),
])
async def test_canada_holidays_failures_do_not_report_success(monkeypatch, body, status, error):
    requests = transport(monkeypatch, body, status)
    with pytest.raises(error):
        await node({"operation": "list_holidays"}).execute({})
    assert len(requests) == 1


def test_canada_holidays_public_schema_and_evidence():
    schema = native.CanadaHolidaysNode.get_config_schema()
    assert native.CanadaHolidaysNode.get_config_model().model_fields["credentials"].annotation is type(None)
    assert native.CanadaHolidaysNode.connection_evidence.proves == "reachability"
    assert native.CanadaHolidaysNode.connection_evidence.operation == "get_api_info"
    assert len(schema["$defs"]) >= 10

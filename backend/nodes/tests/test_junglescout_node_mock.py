"""All six published operations through the native run seam, with documented responses."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import junglescout_node as js
from nodes.core.run_op import run_node_operation
from utils import ssrf

RESPONSES = json.loads((Path(__file__).parent / "fixtures/junglescout/responses.json").read_text())
AUTH = {"credential_type": "junglescout_api_key", "key_name": "fixture-name", "api_key": "fixture-secret"}
CASES = [
    ("list_keywords_by_asin", {"asins": ["B08RT1NF23"], "include_variants": False}),
    ("list_keywords_by_keyword", {"search_terms": ["yoga"], "min_word_count": 1}),
    ("get_historical_search_volume", {"keyword": "yoga", "start_date": "2024-01-01", "end_date": "2024-01-31"}),
    ("list_products", {"include_keywords": ["pasta"], "exclude_top_brands": False, "min_price": 10}),
    ("get_sales_estimates", {"asin": "B08JYQLKXZ", "start_date": "2024-01-01", "end_date": "2024-01-31"}),
    ("get_share_of_voice", {"keyword": "golf"}),
]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(js, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, credential=AUTH):
    return await run_node_operation(node_type="automation-junglescout", operation=operation,
        arguments=arguments or {}, credential_data=deepcopy(credential), user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments", CASES)
async def test_published_queries(transport, operation, arguments):
    requests, replies = transport
    replies.append((200, deepcopy(RESPONSES[operation])))
    output = await run(operation, {**arguments, "marketplace": "uk"})
    assert output["status"] == "success" and output["data"] == RESPONSES[operation]["data"]
    assert output["identity_verified"] is False
    request = requests[0]
    assert len(requests) == 1 and not replies
    assert (request.method, request.url.path) == js.ROUTES[operation]
    assert request.url.host == "developer.junglescout.com" and request.url.params["marketplace"] == "uk"
    assert request.headers["Authorization"] == "fixture-name:fixture-secret"
    assert request.headers["X-API-Type"] == "junglescout"
    assert request.headers["Accept"] == js.MEDIA_TYPE
    assert request.headers["Content-Type"] == "application/vnd.api+json"
    assert "fixture-secret" not in str(request.url)
    if request.method == "POST":
        assert json.loads(request.content) == {"data": {"type": request.url.path.rsplit("/", 1)[1], "attributes": arguments}}
        assert request.url.params["page[size]"] == "50"
    else:
        assert not request.content
        for key, value in arguments.items():
            assert request.url.params[key] == value


@pytest.mark.asyncio
async def test_cursor_roundtrip_does_not_follow_response_host(transport):
    requests, replies = transport
    body = deepcopy(RESPONSES["list_products"])
    body["links"] = {"next": "https://untrusted.invalid/path?page%5Bcursor%5D=opaque%2Bcursor%3D"}
    replies.extend([(200, body), (200, {"data": []})])
    output = await run("list_products", {"page_size": 1})
    assert output["next_page_cursor"] == "opaque+cursor=" and output["has_more"]
    output = await run("list_products", {"page_size": 1, "page_cursor": output["next_page_cursor"]})
    assert requests[1].url.host == "developer.junglescout.com"
    assert requests[1].url.params["page[cursor]"] == "opaque+cursor="
    assert output["data"] == [] and output["has_more"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 422, 429, 500])
async def test_provider_rejection_is_not_success(transport, code):
    _, replies = transport
    replies.append((code, {"errors": [{"detail": "No access for fixture-secret"}]}))
    output = await run("list_products")
    assert output["status"] == "error" and output["success"] is False
    assert output["http_status"] == code and output["message"] == "No access for [redacted]"


@pytest.mark.asyncio
async def test_connection_check_uses_credential_marketplace(transport):
    requests, replies = transport
    replies.append((200, {"data": []}))
    assert (await run("list_products", {"page_size": 1}, {**AUTH, "marketplace": "de"}))["success"]
    assert requests[0].url.params["marketplace"] == "de"
    assert js.JunglescoutNode.connection_evidence.proves == "reachability"


@pytest.mark.parametrize("field,value", [("api_key", "https://example.com"), ("api_key", "a\nb"), ("key_name", "name:secret"), ("api_key", "<token>")])
def test_invalid_header_values(field, value):
    with pytest.raises(ValidationError):
        js.JunglescoutAPIKeyCredential.model_validate({**AUTH, field: value})


def test_credential_tag_default_and_request_constraints():
    assert js.JunglescoutAPIKeyCredential(key_name="fixture-name", api_key="fixture-secret").credential_type == "junglescout_api_key"
    for cls, values in [(js.Products, {"page_size": 101}), (js.KeywordsByAsin, {"asins": ["invalid"]}),
                        (js.SalesEstimates, {"asin": "B08JYQLKXZ", "start_date": "2024-02-01", "end_date": "2024-01-01"}),
                        (js.Products, {"include_keywords": ["a" * 51]})]:
        with pytest.raises(ValidationError):
            cls(**values)

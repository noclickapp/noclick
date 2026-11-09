"""Fixed-route contract tests; all requests use a fake key and an offline transport."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import wodify_core_node as wd
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "wodify_core_api_key", "api_key": "wodify-test-key-12345"}
USER = "00000000-0000-4000-8000-000000000001"
CASES = json.loads((Path(__file__).parent / "fixtures/wodify-core/operations.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.wodify.com"
        assert request.headers["x-api-key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(wd, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, config=None):
    return await run_node_operation(node_type="automation-wodify-core", operation=operation,
        arguments=config or {}, credential_data=AUTH, user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["operation"])
async def test_wodify_core_routes_and_body(wire, case):
    requests, replies = wire
    response = {"pagination": {"page": 2, "page_size": 10, "has_more": True}, "clients": [{"id": 7, "first_name": "Jane"}]}
    replies.append((200, response))
    result = await run(case["operation"], case["config"])
    assert result["data"] == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    expected_path = case["path"]
    payload = dict(case["config"])
    for key in tuple(payload):
        if "{" + key + "}" in expected_path:
            expected_path = expected_path.replace("{" + key + "}", str(payload.pop(key)))
    assert request.url.path == "/v1" + expected_path
    if request.method == "GET":
        assert dict(request.url.params) == {key: str(value) for key, value in payload.items()}
        assert not request.content
    else:
        assert json.loads(request.content) == payload
        assert not request.url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Invalid key"}), (429, {"message": "Rate limited"}),
    (200, {"wodify_validation_result": "Client is inactive"}), (200, {"is_success": False})])
async def test_wodify_core_rejects_provider_errors_without_retry(wire, status, body):
    requests, replies = wire
    replies.append((status, body))
    with pytest.raises(ValueError):
        await run("list_clients")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_wodify_core_redacts_key(wire):
    requests, replies = wire
    replies.append((401, {"message": "Rejected " + AUTH["api_key"]}))
    with pytest.raises(ValueError) as error:
        await run("list_clients")
    assert AUTH["api_key"] not in str(error.value)
    replies.append((200, {"echo": AUTH["api_key"]}))
    assert (await run("list_clients"))["data"]["echo"] == "[redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,collection,row,label", [
    ("location_id", "locations", {"id": 17, "name": "Main Gym"}, "Main Gym"),
    ("gender_id", "genders", {"gender_id": 1, "gender": "Female"}, "Female"),
    ("client_id", "clients", {"id": 9, "first_name": "Jane", "last_name": "Doe"}, "Jane Doe"),
    ("lead_source_id", "sources", {"id": 3, "source": "Website"}, "Website"),
])
async def test_wodify_core_picker_and_pagination(wire, field, collection, row, label):
    requests, replies = wire
    replies.append((200, {collection: [row], "pagination": {"page": 2, "page_size": 100, "has_more": True}}))
    result = await wd.WodifyCoreNode.load_field_options(field, credential_data=AUTH, user_id=USER, page_token="2")
    assert result == {"options": [{"value": str(next(iter(row.values()))), "label": label}], "next_page_token": "3"}
    assert requests[0].url.params["page"] == "2"


def test_wodify_core_pasted_key_needs_no_type_field():
    assert wd.WodifyCoreApiKeyCredential(api_key=AUTH["api_key"]).credential_type == AUTH["credential_type"]


@pytest.mark.parametrize("operation,config", [
    ("create_client", {"first_name": "Jane"}),
    ("create_lead", {}),
    ("get_client", {"client_id": "../../admin"}),
    ("list_clients", {"page_size": 101}),
    ("list_clients", {"page": 0}),
    ("add_lead_tags", {"lead_id": 9, "tags": []}),
])
def test_wodify_core_invalid_inputs(operation, config):
    with pytest.raises((ValidationError, ValueError)):
        wd.WodifyCoreNode.parse_config({"config": {"operation": operation, **config}, "credentials": AUTH})

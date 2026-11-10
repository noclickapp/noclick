"""Exercise BigMailer through the native factory with provider-published examples.

The transport records real requests so routes, auth, pagination and body shaping
are checked independently of the response returned to the workflow.
"""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes import bigmailer_node as bm
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / "fixtures/bigmailer/operations.json").read_text())
AUTH = {"credential_type": "bigmailer_api_key", "api_key": "fixture-bigmailer-key"}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.bigmailer.io"
        assert request.headers["X-API-Key"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(bm, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(config):
    config = deepcopy(config)
    operation = config.pop("operation")
    return await run_node_operation(node_type="automation-bigmailer", operation=operation,
        arguments=config, credential_data=AUTH, user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", CASES)
async def test_published_operations(transport, name):
    requests, replies = transport
    case = CASES[name]
    replies.append((200, case["response"]))
    result = await run(case["config"])
    assert result == case["response"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    path = case["path"]
    for key, value in case["config"].items():
        path = path.replace("{" + key + "}", quote(str(value), safe=""))
    assert request.url.path == path
    if request.method == "POST":
        assert json.loads(request.content) == case["body"]
    else:
        assert request.content == b""
    if name.startswith("list_"):
        assert dict(request.url.params) == {"limit": "10"}


@pytest.mark.asyncio
async def test_cursor_and_contact_list_scope(transport):
    requests, replies = transport
    replies.append((200, CASES["list_contacts"]["response"]))
    config = {**CASES["list_contacts"]["config"], "limit": 100, "cursor": "K5pwIGH3hgYrhytbDUY5eQ==",
              "list_id": "b4326936-9e08-4cf9-95fe-c44c8cf4e4ef"}
    result = await run(config)
    assert result["cursor"] == CASES["list_contacts"]["response"]["cursor"]
    assert dict(requests[0].url.params) == {"limit": "100", "cursor": config["cursor"], "list_id": config["list_id"]}


@pytest.mark.asyncio
async def test_email_identifier_and_false_subscription_values(transport):
    requests, replies = transport
    replies.append((200, CASES["update_contact"]["response"]))
    await run({"operation": "update_contact", "brand_id": CASES["update_contact"]["config"]["brand_id"],
               "contact_id": "chris+tag@bigmailer.io", "unsubscribe_all": False, "list_ids": []})
    assert requests[0].url.raw_path.endswith(b"/contacts/chris%2Btag%40bigmailer.io")
    assert json.loads(requests[0].content) == {"unsubscribe_all": False, "list_ids": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 404, 429, 500])
async def test_provider_failure_is_not_success_or_retried(transport, code):
    requests, replies = transport
    replies.append((code, {"message": "Provider rejected the request"}))
    with pytest.raises(httpx.HTTPStatusError):
        await run(CASES["upsert_contact"]["config"])
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"data": {}}, {"message": "bad gateway"}])
async def test_bad_list_response_fails(transport, payload):
    requests, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError):
        await run({"operation": "list_brands"})
    assert len(requests) == 1


@pytest.mark.parametrize("identifier", ["..", "../contacts", "x?secret=1", "a#b", "a\nb"])
def test_contact_path_cannot_change_resource(identifier):
    with pytest.raises(ValidationError):
        bm.BigmailerNodeConfig(config={"operation": "get_contact", "brand_id": CASES["get_contact"]["config"]["brand_id"], "contact_id": identifier})


@pytest.mark.parametrize("payload", [{"name": "NAME"}, {"name": "NAME", "string": "a", "integer": 1}])
def test_field_value_requires_one_value(payload):
    with pytest.raises(ValidationError):
        bm.BigmailerFieldValue(**payload)


def test_manual_credential_defaults_and_evidence():
    credential = bm.BigmailerApiKeyCredential(api_key="  fixture-bigmailer-key  ")
    assert credential.credential_type == "bigmailer_api_key"
    assert credential.api_key == AUTH["api_key"]
    assert bm.BigmailerNode.connection_evidence.operation == "list_brands"
    assert credential.api_key not in repr(credential)
    assert "api_key=" not in repr(credential)


@pytest.mark.asyncio
async def test_contact_update_modes_and_deliverability_query(transport):
    requests, replies = transport
    replies.extend([(200, CASES["upsert_contact"]["response"]), (200, CASES["update_contact"]["response"])])
    await run({**CASES["upsert_contact"]["config"], "validate_email": "true"})
    assert dict(requests[0].url.params) == {"validate": "true"}
    assert "validate_email" not in json.loads(requests[0].content)
    await run({**CASES["update_contact"]["config"], "field_values_op": "add", "list_ids_op": "remove", "unsubscribe_ids_op": "replace"})
    assert dict(requests[1].url.params) == {"field_values_op": "add", "list_ids_op": "remove", "unsubscribe_ids_op": "replace"}
    assert not set(dict(requests[1].url.params)) & set(json.loads(requests[1].content))


@pytest.mark.asyncio
async def test_redirect_is_not_followed(transport):
    requests, replies = transport
    replies.append((302, {"location": "https://elsewhere.example"}))
    with pytest.raises(httpx.HTTPStatusError):
        await run({"operation": "list_brands"})
    assert len(requests) == 1

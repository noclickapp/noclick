"""Wire-level tests for the published HaloPSA v2 operations; no live account."""
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import halopsa_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {
    "credential_type": "halopsa_access_token",
    "instance_url": "https://fixture.halopsa.com",
    "access_token": "synthetic-test-token",
}


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        assert request.url.host == "fixture.halopsa.com"
        assert request.headers["authorization"] == "Bearer " + AUTH["access_token"]
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        node,
        "guarded_async_client",
        lambda **kw: native(**kw, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(
        node_type="automation-halopsa",
        operation=operation,
        arguments=arguments or {},
        credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(node.ROUTES))
async def test_every_operation_maps_to_one_contract_request(transport, operation):
    method, path, collection, mode = node.ROUTES[operation]
    args = {}
    row = {"id": 42, "name": "Example", "summary": "Example"}
    if mode == "get":
        args["id"] = 42
    if collection == "actions":
        args["ticket_id"] = 7
    if mode in {"create", "update"}:
        args.update(
            {"summary": "Example"}
            if collection == "tickets"
            else {"note": "Example"}
            if collection == "actions"
            else {"name": "Example"}
        )
        if mode == "update":
            args["id"] = 42
        elif collection == "sites":
            args["client_id"] = 7
        elif collection == "users":
            args["site_id"] = 7
    payload = {collection: [row], "record_count": 101} if mode == "list" else row
    transport[1].append((201 if method == "POST" else 200, payload))
    result = await run(operation, args)
    assert result["data"] == payload
    assert len(transport[0]) == 1
    request = transport[0][0]
    assert request.method == method
    assert request.url.path == "/api" + path + ("/42" if mode == "get" else "")
    if method == "POST":
        assert json.loads(request.content) == [args]
    if mode == "list" and collection != "actions":
        assert request.url.params["pageinate"] == "true"
        assert result["next_page"] == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://fixture.halopsa.com",
        "https://fixture.halopsa.com.evil.test",
        "https://127.0.0.1",
        "https://u:p@fixture.halopsa.com",
        "https://fixture.halopsa.com/api",
        "https://fixture.halopsa.com?key=x",
    ],
)
def test_invalid_instance_urls_refused(url):
    with pytest.raises(ValueError):
        node.HalopsaAccessTokenCredential(**{**AUTH, "instance_url": url})


def test_manual_credential_type_default():
    assert (
        node.HalopsaAccessTokenCredential(
            instance_url=AUTH["instance_url"], access_token=AUTH["access_token"]
        ).credential_type
        == AUTH["credential_type"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [
        (401, {"error": "denied"}),
        (429, {}),
        (302, {}),
        (200, {"errors": ["denied"]}),
        (200, {"unexpected": []}),
    ],
)
async def test_failed_or_malformed_reads_never_pass(transport, status, payload):
    transport[1].append((status, payload))
    with pytest.raises(ValueError):
        await run("list_clients")


@pytest.mark.asyncio
async def test_token_echo_is_redacted(transport):
    transport[1].append(
        (200, {"id": 1, "name": AUTH["access_token"], "password": "sensitive"})
    )
    result = await run("get_client", {"id": 1})
    assert AUTH["access_token"] not in json.dumps(result)
    assert "sensitive" not in json.dumps(result)


def test_empty_update_refused():
    with pytest.raises(ValueError):
        node.HalopsaUpdateClientConfig(id=1)

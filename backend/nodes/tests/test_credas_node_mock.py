"""Wire-level tests for Credas Connect: never call a live account."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.registry import NodeFactory
from nodes.credas_node import CredasAPIKeyCredential, CredasNode

ENTITY = "9811e0dc-7bbb-4fdf-be96-b8c7c105080f"
PROCESS = "1e144e85-f45b-4ae3-8915-ae2826ea1e55"
JOURNEY = "8c55ebc3-7ac2-469e-9837-94023aa82c3d"


def node(config, environment="demo"):
    obj = NodeFactory.create_node(
        node_id="credas-test",
        node_type="automation-credas",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "credas_api_key",
                "api_key": "unit-test-secret",
                "environment": environment,
            },
        },
    )
    obj.emit = AsyncMock()
    return obj


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            yield session

    monkeypatch.setattr("nodes.credas_node.guarded_async_client", client)


@pytest.mark.asyncio
async def test_entity_search_proves_account_and_preserves_page(monkeypatch):
    def handle(req):
        assert req.method == "GET"
        assert str(req.url).startswith(
            "https://portal.credasdemo.com/api/v2/ci/entities/search?"
        )
        assert dict(req.url.params) == {"searchText": "Alice", "pageNumber": "2"}
        assert req.headers["X-API-KEY"] == "unit-test-secret"
        return httpx.Response(
            200,
            json={"totalEntities": 2, "entities": [{"id": ENTITY, "name": "Alice"}]},
        )

    transport(monkeypatch, handle)
    obj = node({"operation": "search_entities", "searchText": "Alice", "pageNumber": 2})
    result = await obj.execute({})
    assert result["entities"][0]["name"] == "Alice"
    assert result["total_entities"] == 2
    assert result["page_number"] == 2
    obj.emit.assert_awaited_once_with(result)
    assert CredasNode.connection_evidence.operation == "search_entities"


@pytest.mark.asyncio
async def test_create_process_is_one_post_with_typed_entities(monkeypatch):
    import json

    calls = []

    def handle(req):
        calls.append(req)
        assert req.method == "POST"
        assert str(req.url) == "https://portal.credas.com/api/v2/ci/processes"
        assert json.loads(req.content) == {
            "journeyId": JOURNEY,
            "processEntities": [{"id": ENTITY, "actorId": 1, "contactViaEmail": True}],
            "skipSendingEntityInvites": False,
        }
        return httpx.Response(200, json={"id": PROCESS})

    transport(monkeypatch, handle)
    result = await node(
        {
            "operation": "create_process",
            "journeyId": JOURNEY,
            "processEntities": [{"id": ENTITY, "actorId": 1, "contactViaEmail": True}],
        },
        "production",
    ).execute({})
    assert result["data"]["id"] == PROCESS
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_create_entity_omits_unset_fields(monkeypatch):
    import json

    def handle(req):
        assert req.method == "POST"
        assert req.url.path == "/api/v2/ci/entities"
        assert json.loads(req.content) == {
            "firstName": "Alice",
            "surname": "Smith",
            "reference": "CRM-100",
        }
        return httpx.Response(200, json={"id": ENTITY})

    transport(monkeypatch, handle)
    result = await node(
        {
            "operation": "create_entity",
            "firstName": "Alice",
            "surname": "Smith",
            "reference": "CRM-100",
        }
    ).execute({})
    assert result["data"]["id"] == ENTITY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,path",
    [
        ("approve_entity", "approve"),
        ("reject_entity", "reject"),
        ("reset_entity_approval", "reset"),
        ("expire_invite", "expire-invite"),
    ],
)
async def test_status_updates_have_no_spurious_body(monkeypatch, operation, path):
    def handle(req):
        assert req.method == "PUT"
        assert req.url.path == f"/api/v2/ci/entities/{ENTITY}/{path}"
        assert req.content == b""
        return httpx.Response(204)

    transport(monkeypatch, handle)
    result = await node({"operation": operation, "entityId": ENTITY}).execute({})
    assert result["status"] == "success"
    assert result["data"] is None


@pytest.mark.asyncio
async def test_invite_delivery_flags_are_json(monkeypatch):
    import json

    def handle(req):
        assert req.method == "PUT"
        assert req.url.path == f"/api/v2/ci/entities/{ENTITY}/resend-invite"
        assert json.loads(req.content) == {
            "contactByEmail": False,
            "contactBySms": True,
        }
        return httpx.Response(200)

    transport(monkeypatch, handle)
    assert (
        await node(
            {
                "operation": "resend_invite",
                "entityId": ENTITY,
                "contactByEmail": False,
                "contactBySms": True,
            }
        ).execute({})
    )["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_rejection_never_looks_successful_or_leaks_key(monkeypatch, status):
    calls = []

    def handle(req):
        calls.append(req)
        return httpx.Response(
            status,
            text="Rejected unit-test-secret",
            headers={"Location": "https://attacker.invalid"},
        )

    transport(monkeypatch, handle)
    result = await node({"operation": "list_journeys"}).execute({})
    assert result["status"] == "error"
    assert result["http_status"] == status
    assert result["message"] == "Rejected [redacted]"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_invalid_json_is_unverified(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "get_entity", "entityId": ENTITY}).execute({})


def test_manual_credential_has_default_type_and_fixed_host_selection():
    assert (
        CredasAPIKeyCredential(api_key="unit-test-secret").credential_type
        == "credas_api_key"
    )
    with pytest.raises(ValidationError):
        CredasAPIKeyCredential(
            api_key="unit-test-secret", environment="https://attacker.invalid"
        )
    with pytest.raises(ValidationError):
        CredasAPIKeyCredential(api_key="https://example.com")
    verdict = CredasNode.validate_config(
        {"config": {"operation": "get_entity", "entityId": "../other"}}
    )
    assert verdict["valid"] is False

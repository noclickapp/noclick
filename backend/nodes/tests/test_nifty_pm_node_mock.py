"""Exercise every Nifty action against unmodified provider contract examples."""
import json
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError
from nodes import nifty_pm_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/nifty-pm/contract-examples.json").read_text()
)["operations"]
TOKEN = "nft_user_synthetic_test_token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="nifty-example",
        node_type="automation-nifty-pm",
        node_data={
            "config": config,
            "credentials": {
                "credential_type": "nifty_pm_personal_access_token",
                "access_token": TOKEN,
            },
        },
    )


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        return response(request)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), **kwargs
        ) as value:
            yield value

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_published_contract_examples(monkeypatch, operation):
    example = EXAMPLES[operation]
    calls = transport(
        monkeypatch,
        lambda req: httpx.Response(example["status"], json=example["response"])
        if example["response"] is not None
        else httpx.Response(example["status"]),
    )
    result = await node(example["config"]).execute({})
    assert result["status"] == "success"
    assert len(calls) == 1
    request = calls[0]
    assert request.method == example["method"]
    assert request.url.path == "/api/v3" + example["path"].replace(
        "{id}", example["config"].get("id", "")
    )
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if example["response"] is not None:
        assert result["data"] == (
            example["response"]["data"]
            if operation.startswith(("list_", "search_"))
            else example["response"]
        )
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_patch_omits_unset_values_preserves_false_and_idempotency(monkeypatch):
    calls = transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"id": "KfS0ha8P", "completed": False}),
    )
    await node(
        {
            "operation": "update_task",
            "id": "KfS0ha8P",
            "completed": False,
            "expectedUpdatedAt": "2026-05-31T12:00:00.000Z",
            "idempotency_key": "example-key",
        }
    ).execute({})
    assert json.loads(calls[0].content) == {
        "completed": False,
        "expectedUpdatedAt": "2026-05-31T12:00:00.000Z",
    }
    assert calls[0].headers["Idempotency-Key"] == "example-key"


@pytest.mark.asyncio
async def test_cursor_and_nullable_total_are_preserved(monkeypatch):
    payload = {
        "data": [],
        "total": None,
        "limit": 2,
        "hasMore": True,
        "nextCursor": "opaque+/=",
    }
    calls = transport(monkeypatch, lambda req: httpx.Response(200, json=payload))
    result = await node(
        {
            "operation": "list_tasks",
            "projectId": "iV6vIU8N",
            "limit": 2,
            "cursor": "previous+/=",
        }
    ).execute({})
    assert result["total"] is None and result["nextCursor"] == "opaque+/="
    assert dict(calls[0].url.params) == {
        "projectId": "iV6vIU8N",
        "limit": "2",
        "cursor": "previous+/=",
        "includeTotal": "false",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409, 422, 429, 500])
async def test_provider_errors_are_reported_without_token_or_retry(monkeypatch, status):
    calls = transport(
        monkeypatch,
        lambda req: httpx.Response(
            status, json={"detail": "Rejected " + TOKEN, "code": "provider_code"}
        ),
    )
    result = await node({"operation": "get_current_member"}).execute({})
    assert result == {
        "status": "error",
        "http_status": status,
        "error": "Rejected [redacted]",
        "code": "provider_code",
    }
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_write_timeout_is_not_retried(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    calls = transport(monkeypatch, timeout)
    result = await node(
        {"operation": "create_task", "name": "Ship", "projectId": "iV6vIU8N"}
    ).execute({})
    assert result["status"] == "error" and "before retrying" in result["error"]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_malformed_collection_is_rejected(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={"data": {}}))
    with pytest.raises(ValueError, match="collection envelope"):
        await node({"operation": "list_tasks"}).execute({})


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_task", "id": "../members"},
        {"operation": "list_tasks", "limit": 201},
        {"operation": "update_task", "id": "KfS0ha8P"},
        {"operation": "create_message", "text": "Hello"},
        {
            "operation": "create_time_entry",
            "taskId": "KfS0ha8P",
            "start": "2026-06-01T12:00:00Z",
            "end": "2026-05-01T12:00:00Z",
        },
    ],
)
def test_invalid_inputs(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_manual_credential_default_and_evidence():
    credential = native.NiftyPMTokenCredential(access_token="  " + TOKEN + "  ")
    assert credential.credential_type == "nifty_pm_personal_access_token"
    assert credential.access_token == TOKEN
    assert (
        native.NiftyPMNode.connection_evidence.identity_operation
        == "get_current_member"
    )
    for value in ["Bearer abc", "https://example.com/token"]:
        with pytest.raises(ValueError):
            native.NiftyPMTokenCredential(access_token=value)

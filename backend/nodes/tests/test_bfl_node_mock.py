"""Exercise BFL through NoClick's real standalone operation runner.

HTTP and public DNS are fixture-only, so tests never spend provider credits.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import bfl_node as bfl
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / "fixtures/bfl/operations.json").read_text())
KEY = "bfl-fixture-secret-12345"
AUTH = {"credential_type": "bfl_api_key", "api_key": KEY}
USER = "00000000-0000-4000-8000-000000000001"
TASK = {
    "id": "fixture-task",
    "polling_url": "https://api.us1.bfl.ai/v1/get_result?id=fixture-task",
    "cost": 4.0,
}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        assert request.headers["x-key"] == KEY
        assert KEY not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        bfl,
        "guarded_async_client",
        lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-bfl",
        operation=operation,
        arguments=arguments or {},
        credential_data=auth,
        user_id=USER,
    )


def response(operation):
    return {
        "get_credits": {"credits": 0.0},
        "list_finetunes": {"finetunes": ["fixture-finetune"]},
        "get_finetune_details": {
            "finetune_details": {"id": "fixture-finetune", "iterations": 300}
        },
        "delete_finetune": {
            "status": "success",
            "message": "Deleted",
            "deleted_finetune_id": "my-finetune",
            "timestamp": "2026-11-09T00:00:00Z",
        },
        "get_result": {
            "id": "fixture-task",
            "status": "Ready",
            "result": {"sample": "https://delivery.bfl.ai/result.png"},
        },
    }.get(operation, TASK)


@pytest.mark.parametrize("operation", CASES)
@pytest.mark.asyncio
async def test_bfl_native_operations(transport, operation):
    requests, replies = transport
    case = CASES[operation]
    replies.append((200, response(operation)))
    result = await run(operation, case["config"])
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert request.url.path == case["path"]
    assert request.url.host == "api.bfl.ai"
    if request.method == "GET":
        assert dict(request.url.params) == {
            k: str(v) for k, v in case["config"].items()
        }
    else:
        assert json.loads(request.content) == case["config"]
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_bfl_returned_regional_polling_url(transport):
    requests, replies = transport
    replies.append((200, {"id": "fixture-task", "status": "Pending", "progress": 0.0}))
    result = await run(
        "get_result", {"id": "fixture-task", "polling_url": TASK["polling_url"]}
    )
    assert result["data"]["status"] == "Pending"
    assert str(requests[0].url) == TASK["polling_url"]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/v1/get_result?id=fixture-task",
        "https://api.bfl.ai.evil.example/v1/get_result?id=fixture-task",
        "http://api.bfl.ai/v1/get_result?id=fixture-task",
        "https://api.bfl.ai:443/v1/get_result?id=fixture-task",
        "https://user@api.bfl.ai/v1/get_result?id=fixture-task",
        "https://api.bfl.ai/v1/get_result?id=another-task",
        "https://api.bfl.ai/v1/credits?id=fixture-task",
        "https://api.bfl.ai/v1/get_result?id=fixture-task&secret=x",
    ],
)
@pytest.mark.asyncio
async def test_bfl_rejects_untrusted_polling_destination(transport, url):
    with pytest.raises(ValueError, match="polling_url"):
        await run("get_result", {"id": "fixture-task", "polling_url": url})
    assert transport[0] == []


@pytest.mark.parametrize("status", [401, 403, 422, 429, 500, 302])
@pytest.mark.asyncio
async def test_bfl_provider_errors_not_success_or_retried(transport, status):
    transport[1].append((status, {"detail": "Rejected " + KEY}))
    with pytest.raises(ValueError) as exc:
        await run("get_credits")
    assert KEY not in str(exc.value)
    assert str(status) in str(exc.value)
    assert len(transport[0]) == 1


@pytest.mark.parametrize(
    "operation,body",
    [
        ("get_credits", {}),
        ("get_credits", {"credits": "many"}),
        ("list_finetunes", {"finetunes": {}}),
        ("get_result", {"id": "different", "status": "Ready"}),
        ("get_result", {"id": "fixture-task", "status": "Invented"}),
        ("generate_flux_2_pro", {"id": "fixture-task"}),
        (
            "delete_finetune",
            {**response("delete_finetune"), "deleted_finetune_id": "different"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_bfl_malformed_or_mismatched_response(transport, operation, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError, match="could not be verified"):
        await run(operation, CASES[operation]["config"])


@pytest.mark.parametrize(
    "field,value", [("width", 63), ("width", 1000), ("safety_tolerance", 8)]
)
def test_bfl_native_input_constraints(field, value):
    with pytest.raises(ValidationError):
        bfl.BflGenerateFluxPro11Config(**{field: value})


def test_bfl_manual_credential_default_and_cleanup():
    credential = bfl.BflAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "bfl_api_key"
    assert credential.api_key == KEY
    assert bfl.BflNode.connection_evidence.operation == "get_credits"

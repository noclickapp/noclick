"""Contract request coverage through the runtime factory and real HTTP serialization."""
import json
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import harvey_node as native
from nodes.core.run_op import run_node_operation
from utils import ssrf

TOKEN = "synthetic-harvey-test-token"
AUTH = {"credential_type": "harvey_api_token", "api_token": TOKEN}
ID = "12345678-1234-5678-1234-567812345678"
CASES = json.loads((Path(__file__).parent / "fixtures/harvey/wire.json").read_text())


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
        assert request.url.host == "api.harvey.ai"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        code, body = replies.pop(0)
        return httpx.Response(code, json=body)

    client = ssrf.guarded_async_client
    monkeypatch.setattr(
        native,
        "guarded_async_client",
        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, config=None):
    return await run_node_operation(
        node_type="automation-harvey",
        operation=operation,
        arguments=config or {},
        credential_data=AUTH.copy(),
        user_id="00000000-0000-4000-8000-000000000001",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"])
async def test_exactly_one_provider_contract_request(transport, case):
    requests, replies = transport
    replies.append((case["status"], case["response"]))
    result = await run(case["operation"], case["config"])
    assert result["status"] == "success" and result["data"] == case["response"]
    if case["operation"] == "list_projects":
        assert result["items"] == case["response"]["response"]["content"]["projects"]
        assert result["items"][0]["name"] == "Example Legal Project"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"] and request.url.path == case["path"]
    assert list(request.url.params.multi_items()) == [tuple(x) for x in case["query"]]
    if case["form"] is not None:
        message = BytesParser(policy=default).parsebytes(
            ("Content-Type: " + request.headers["Content-Type"] + "\r\n\r\n").encode()
            + request.content
        )
        fields = {
            part.get_param("name", header="content-disposition"): part.get_content()
            for part in message.iter_parts()
        }
        assert fields == {k: str(v) for k, v in case["form"].items()}
    else:
        assert (json.loads(request.content) if request.content else None) == case[
            "body"
        ]


@pytest.mark.asyncio
async def test_arrays_dates_and_explicit_continuation(transport):
    requests, replies = transport
    body = {
        "pagination": {"has_more": True, "next_cursor": "next-page"},
        "requests": [],
    }
    replies.append((200, body))
    result = await run(
        "list_intake_requests",
        {
            "status": ["TODO", "IN_PROGRESS"],
            "created_after": "2026-10-01T00:00:00Z",
            "cursor": "previous-page",
        },
    )
    assert result["data"] == body and len(requests) == 1
    assert requests[0].url.params.get_list("status") == ["TODO", "IN_PROGRESS"]
    assert requests[0].url.params["created_after"] == "2026-10-01T00:00:00Z"
    assert requests[0].url.params["cursor"] == "previous-page"
    replies.append((200, {}))
    await run("get_files", {"file_ids": [ID, "11111111-2222-3333-4444-555555555555"]})
    assert (
        requests[-1].url.params["file_ids"]
        == ID + ",11111111-2222-3333-4444-555555555555"
    )


@pytest.mark.asyncio
async def test_false_omission_null_and_batch_failures_survive(transport):
    requests, replies = transport
    replies.append((200, {"errors": [{"code": "client_not_found"}]}))
    result = await run(
        "upsert_matters",
        {
            "matters": [
                {
                    "client_id": "10022421",
                    "matter_id": "M001",
                    "allowed": False,
                    "notice": None,
                }
            ]
        },
    )
    assert result["partial_failure"] is True
    assert json.loads(requests[-1].content) == {
        "matters": [
            {
                "client_id": "10022421",
                "matter_id": "M001",
                "allowed": False,
                "notice": None,
            }
        ]
    }
    replies.append((200, {}))
    await run(
        "update_intake_request", {"request_id": ID, "description": None, "due_at": None}
    )
    assert json.loads(requests[-1].content) == {"description": None, "due_at": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [301, 400, 401, 403, 404, 429, 500])
async def test_errors_preserve_rejection_without_token_or_retry(transport, code):
    requests, replies = transport
    replies.append((code, {"error": "Rejected " + TOKEN}))
    with pytest.raises(ValueError) as exc:
        await run("list_projects")
    assert str(code) in str(exc.value) and "Rejected" in str(exc.value)
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "list_projects", "page": 0},
        {"operation": "list_projects", "created_after": 2, "created_before": 1},
        {"operation": "get_files", "file_ids": []},
        {"operation": "delete_project", "project_id": "../escape"},
        {"operation": "create_project"},
        {
            "operation": "add_review_table_row",
            "review_table_id": 1,
            "file_ids": [ID] * 26,
        },
        {"operation": "update_intake_request", "request_id": ID},
        {"operation": "update_intake_request", "request_id": ID, "status": None},
        {"operation": "list_intake_requests", "created_after": "2026-10-01T00:00:00"},
        {"operation": "upsert_clients", "clients": []},
    ],
)
def test_bad_inputs_rejected(config):
    with pytest.raises((ValueError, ValidationError)):
        native.HarveyNode.parse_config({"config": config, "credentials": AUTH})


def test_hand_connected_credential_and_evidence():
    assert (
        native.HarveyTokenCredential(api_token=TOKEN).credential_type
        == "harvey_api_token"
    )
    assert native.HarveyNode.connection_evidence.operation == "list_projects"
    for bad in ["Bearer abc", "https://example.test/token", "abc\r\nInjected: yes"]:
        with pytest.raises(ValueError):
            native.HarveyTokenCredential(api_token=bad)

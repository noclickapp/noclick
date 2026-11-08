"""Exercise the native factory and HTTP boundary without live credentials."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import extrovert_node as ext
from nodes.core.run_op import run_node_operation
from utils import ssrf

UID = "8d256aa6-9b12-49a7-93ee-bf41634b5b60"
OTHER = "9d256aa6-9b12-49a7-93ee-bf41634b5b60"
AUTH = {"credential_type": "extrovert_api_key", "api_key": "fixture-not-a-live-key"}
ROUTES = json.loads(
    (Path(__file__).parent / "fixtures/extrovert/routes.json").read_text()
)
CASES = {
    "list_team_members": {},
    "list_campaigns": {},
    "get_campaign": {"campaign_id": UID},
    "create_campaign": {
        "owner_id": UID,
        "name": "Outreach",
        "type": "TARGET_USER",
        "voice_id": OTHER,
        "skip_teammates_leads": True,
    },
    "update_campaign": {
        "campaign_id": UID,
        "name": "Renamed",
        "voice_id": OTHER,
        "skip_teammates_leads": False,
    },
    "start_campaign": {"campaign_id": UID},
    "stop_campaign": {"campaign_id": UID},
    "create_prospect_list": {
        "list_name": "Founders",
        "campaign_id": UID,
        "user_urls": ["https://www.linkedin.com/in/example"],
        "move_own_duplicated": False,
        "should_be_deleted_if_inactive": True,
    },
    "get_prospect_list": {"list_id": UID},
    "add_prospects_to_list": {
        "list_id": UID,
        "user_urls": ["https://www.linkedin.com/in/example"],
        "move_own_duplicated": False,
        "should_be_deleted_if_inactive": False,
    },
    "list_prospects": {
        "campaigns_ids": [UID, OTHER],
        "is_important": False,
        "limit": 25,
        "offset": 5,
    },
    "get_prospect": {"prospect_id": UID},
    "replace_prospect_notes": {"prospect_id": UID, "notes": "Follow up next week"},
    "mark_prospect_important": {"prospect_id": UID, "is_important": False},
    "list_comments": {
        "owner_id": UID,
        "campaign_id": OTHER,
        "view": "Need approval",
        "offset": 10,
    },
    "get_comment": {"owner_id": UID, "post_id": OTHER},
    "set_comment_draft": {
        "owner_id": UID,
        "post_id": OTHER,
        "text": "Thanks for sharing",
    },
    "approve_comment": {"owner_id": UID, "post_id": OTHER},
    "skip_comment": {"owner_id": UID, "post_id": OTHER},
    "list_conversations": {"owner_id": UID, "view": "for-review"},
    "get_conversation": {
        "connection_id": UID,
        "mark_as_read": False,
        "message_offset": 30,
    },
    "prepare_reply": {"connection_id": UID, "text": "Thanks for connecting"},
    "edit_reply": {"dm_id": UID, "text": "Updated text"},
    "send_reply": {"dm_id": UID, "mode": "queued"},
    "snooze_conversation": {"connection_id": UID, "until_date": "2027-01-01"},
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
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        ext,
        "guarded_async_client",
        lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(op, args=None):
    return await run_node_operation(
        node_type="automation-extrovert",
        operation=op,
        arguments=args or {},
        credential_data=AUTH,
        user_id=UID,
    )


@pytest.mark.parametrize("operation", CASES)
async def test_extrovert_documented_request(operation, transport):
    requests, replies = transport
    route, args = ROUTES[operation], CASES[operation]
    payload = {
        "status": "success",
        "data": {"status": "queued", "processId": OTHER},
        "message": "Operation completed successfully",
    }
    replies.append((route["success"][0], payload))
    result = await run(operation, args)
    assert result["data"] == payload["data"]
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == route["method"]
    expected = route["path"]
    for wire, field in route["path_fields"].items():
        expected = expected.replace("{" + wire + "}", args[field])
    assert request.url.path == expected
    assert request.url.host == "api.goextrovert.com"
    assert request.headers["X-API-Key"] == AUTH["api_key"]
    assert AUTH["api_key"] not in str(request.url)
    if route["has_body"]:
        assert json.loads(request.content) == {
            wire: args[field] for wire, field in route["body"].items() if field in args
        } | (
            {"mode": "queued"}
            if operation == "send_reply" and "mode" not in args
            else {}
        )
    else:
        assert request.content == b""
    for wire, field in route["query"].items():
        if field in args:
            value = args[field]
            expected_values = (
                value
                if isinstance(value, list)
                else [str(value).lower() if isinstance(value, bool) else str(value)]
            )
            assert request.url.params.get_list(wire) == expected_values


async def test_extrovert_evidence_and_pagination(transport):
    requests, replies = transport
    data = [{"id": UID, "name": "Fixture Member"}]
    replies.append((200, {"status": "success", "data": data, "message": "OK"}))
    assert (await run("list_team_members"))["data"] == data
    assert ext.ExtrovertNode.connection_evidence.operation == "list_team_members"
    payload = {
        "status": "success",
        "data": {"items": [], "pagination": {"total": 31, "offset": 5, "limit": 25}},
        "message": "OK",
    }
    replies.append((200, payload))
    assert (await run("list_prospects", CASES["list_prospects"]))["data"] == payload[
        "data"
    ]
    assert len(requests) == 2


@pytest.mark.parametrize("code", [401, 403, 409, 429, 500, 302])
async def test_extrovert_failure_never_retried_or_reported_sent(code, transport):
    requests, replies = transport
    replies.append((code, {"message": "Rejected " + AUTH["api_key"]}))
    result = await run("send_reply", {"dm_id": UID})
    assert result["status"] == "error" and result["http_status"] == code
    assert AUTH["api_key"] not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.parametrize("payload", [{}, {"status": "error", "message": "failed"}, []])
async def test_extrovert_malformed_success_refused(payload, transport):
    _, replies = transport
    replies.append((200, payload))
    with pytest.raises(ValueError, match="unexpected response envelope"):
        await run("list_campaigns")


async def test_extrovert_path_is_encoded(transport):
    requests, replies = transport
    replies.append((200, {"status": "success", "data": {}, "message": "OK"}))
    await run("get_campaign", {"campaign_id": "a/b?x=1"})
    assert requests[0].url.raw_path == b"/client/v2/campaign/a%2Fb%3Fx%3D1"


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "list_conversations", "owner_id": UID, "view": "Suggested"},
        {
            "operation": "list_comments",
            "owner_id": UID,
            "campaign_id": OTHER,
            "view": "all",
        },
        {"operation": "send_reply", "dm_id": "not-a-uuid"},
        {"operation": "prepare_reply", "connection_id": UID, "text": "x" * 1251},
        {"operation": "get_conversation", "connection_id": UID, "message_limit": 31},
    ],
)
def test_extrovert_invalid_config_refused(config):
    with pytest.raises(ValidationError):
        ext.ExtrovertNodeConfig.model_validate({"config": config, "credentials": AUTH})


def test_extrovert_manual_key_has_default_type():
    assert (
        ext.ExtrovertApiKeyCredential(api_key=" fixture-key ").credential_type
        == "extrovert_api_key"
    )
    with pytest.raises(ValidationError):
        ext.ExtrovertApiKeyCredential(api_key="bad\nheader")

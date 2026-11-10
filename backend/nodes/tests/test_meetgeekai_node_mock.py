"""Offline MeetGeek requests against examples from the pinned provider OpenAPI.

Exercise every route, pagination, credential validation and rejection handling
through the same node factory used by workflows, without a provider account.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import meetgeekai_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory
from nodes.core.base import ConfigValidationError
from utils import ssrf

AUTH = {"credential_type": "meetgeekai_api_key", "api_key": "synthetic-meetgeek-test-key"}
MEETING = "7e0f1953-b2ce-45b8-97b2-03c09da3a602"
FIXTURE = json.loads((Path(__file__).parent / "fixtures/meetgeekai/openapi-examples.json").read_text())
CASES = [
    ("list_meetings", {"limit": 25, "cursor": "gASVSgAAAAAAAABdlCiMGDIwMj=="}, "GET /v1/meetings"),
    ("get_meeting", {"meeting_id": MEETING}, "GET /v1/meetings/{meetingId}"),
    ("delete_meeting", {"meeting_id": MEETING}, "DELETE /v1/meetings/{meetingId}"),
    ("get_insights", {"meeting_id": MEETING}, "GET /v1/meetings/{meetingId}/insights"),
    ("get_highlights", {"meeting_id": MEETING, "type": "next_steps"}, "GET /v1/meetings/{meetingId}/highlights"),
    ("get_summary", {"meeting_id": MEETING}, "GET /v1/meetings/{meetingId}/summary"),
    ("get_transcript", {"meeting_id": MEETING, "limit": 25, "cursor": "gASVSgAAAAAAAABdlCiMGDIwMj=="}, "GET /v1/meetings/{meetingId}/transcript"),
    ("download_recording", {"meeting_id": MEETING}, "POST /v1/meetings/{meetingId}/download"),
    ("list_teams", {}, "GET /v1/teams"),
    ("list_team_meetings", {"team_id": 101437, "limit": 25}, "GET /v1/teams/{teamId}/meetings"),
    ("join_meeting", {"join_link": "https://meet.google.com/uum-kpde-wym", "language_code": "en-US", "template_name": "General meeting", "meeting_name": "Q3 Town Hall"}, "POST /v1/bot/join"),
    ("upload_recording", {"download_url": "https://my-bucket.s3.us-west-2.amazonaws.com/photos/2023-08-23/meeting.mp4", "language_code": "en-US", "template_name": "General meeting"}, "POST /v1/upload"),
]


def node(operation, config=None, auth=None):
    return NodeFactory.create_node(node_id="meetgeekai-test", node_type="automation-meetgeekai",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": auth or AUTH})


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    def send(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_key"]
        return responses.pop(0)
    guarded = ssrf.guarded_async_client
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: guarded(**kw, transport=httpx.MockTransport(send)))
    return requests, responses


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,key", CASES)
async def test_documented_routes_and_responses(transport, operation, config, key):
    requests, responses = transport
    example = FIXTURE["responses"][key]
    responses.append(httpx.Response(example["status"], json=example["body"]) if example["body"] is not None else httpx.Response(example["status"]))
    output = await node(operation, config).execute({})
    assert output["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    method, path = key.split(" ", 1)
    assert request.method == method
    assert request.url.path == path.replace("{meetingId}", MEETING).replace("{teamId}", "101437")
    assert request.url.host == "api.meetgeek.ai"
    expected = {k: v for k, v in config.items() if k not in {"meeting_id", "team_id"}}
    if method == "GET":
        if operation in {"list_meetings", "get_transcript", "list_team_meetings"}: expected.setdefault("limit", 100)
        assert dict(request.url.params) == {k: str(v) for k, v in expected.items()}
    elif expected:
        assert json.loads(request.content) == expected
    else:
        assert not request.content
    if example["body"]:
        for field, value in example["body"].items(): assert output[field] == value
    if operation == "delete_meeting": assert output["deleted"] is True
    if operation == "upload_recording": assert output["http_status"] == 202


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_provider_rejections_are_not_success(transport, status):
    requests, responses = transport
    responses.append(httpx.Response(status, json={"message": "unauthorized " + AUTH["api_key"]}, headers={"Location": "https://other.example/"}))
    result = await node("list_meetings").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert AUTH["api_key"] not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_no_content_insights_and_bad_json(transport):
    _, responses = transport
    responses.extend([httpx.Response(204), httpx.Response(200, json=[])])
    assert (await node("get_insights", {"meeting_id": MEETING}).execute({}))["has_content"] is False
    with pytest.raises(ValueError, match="JSON object"):
        await node("get_meeting", {"meeting_id": MEETING}).execute({})


@pytest.mark.asyncio
async def test_regional_host_and_encoded_identifier(transport):
    requests, responses = transport
    responses.append(httpx.Response(200, json={}))
    await node("get_meeting", {"meeting_id": "meeting/with?characters"}, {**AUTH, "api_base_url": "https://api-eu.meetgeek.ai"}).execute({})
    assert requests[0].url.host == "api-eu.meetgeek.ai"
    assert requests[0].url.raw_path == b"/v1/meetings/meeting%2Fwith%3Fcharacters"


@pytest.mark.asyncio
async def test_choices_preserve_cursors_and_deduplicate_teams(transport):
    requests, responses = transport
    responses.append(httpx.Response(200, json=FIXTURE["responses"]["GET /v1/meetings"]["body"]))
    result = await native.MeetGeekNode.load_field_options("meeting_id", credential_data=AUTH, page_token="next-page")
    assert result["options"][0]["value"] == MEETING
    assert result["next_page_token"] == "gASVSgAAAAAAAABdlCiMGDIwMj=="
    assert requests[0].url.params["cursor"] == "next-page"
    responses.append(httpx.Response(200, json=FIXTURE["responses"]["GET /v1/teams"]["body"]))
    result = await native.MeetGeekNode.load_field_options("team_id", credential_data=AUTH)
    assert len(result["options"]) == 3
    assert {row["value"] for row in result["options"]} == {"101437", "101438", "101439"}


def test_manual_credential_defaults_and_host_restrictions():
    assert NODE_REGISTRY["automation-meetgeekai"] is native.MeetGeekNode
    assert native.MeetGeekAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == AUTH["credential_type"]
    for bad in ["Bearer some-key", "https://app.meetgeek.ai/key", "<token>"]:
        with pytest.raises(ValidationError): native.MeetGeekAPIKeyCredential(api_key=bad)
    with pytest.raises(ValidationError): native.MeetGeekAPIKeyCredential(**AUTH, api_base_url="https://evil.example")
    with pytest.raises(ConfigValidationError): node("list_meetings", {"limit": 501})
    with pytest.raises(ConfigValidationError): node("join_meeting", {"join_link": "not-a-url"})

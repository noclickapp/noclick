"""Wire-level ToneDen v1 tests through the production operation runner."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import toneden_node as td
from nodes.core.run_op import run_node_operation
from nodes.oauth.toneden_oauth import OAUTH_PROVIDER
from utils import ssrf

AUTH = {"credential_type": "toneden_oauth", "access_token": "synthetic-toneden-access"}

CASES = [
    (
        "get_current_user",
        {},
        "GET",
        "/users/me",
        {},
        None,
        {"user": {"id": 7, "display_name": "Test Artist"}},
    ),
    (
        "list_links",
        {"user_id": 7, "offset": 20, "limit": 10, "target_type": "music"},
        "GET",
        "/users/7/links",
        {"offset": "20", "limit": "10", "target_type": "music"},
        None,
        {"links": []},
    ),
    (
        "get_link",
        {"link_id": 8},
        "GET",
        "/links/8",
        {},
        None,
        {"link": {"id": 8, "title": "Music"}},
    ),
    (
        "create_link",
        {
            "user_id": 7,
            "title": "Music",
            "target_type": "music",
            "target_url": "https://example.org/song",
        },
        "POST",
        "/links",
        {},
        {
            "user_id": 7,
            "title": "Music",
            "target_type": "music",
            "target_url": "https://example.org/song",
        },
        {"link": {"id": 8}},
    ),
    (
        "update_link",
        {"link_id": 8, "title": "New", "show_socials": False},
        "PUT",
        "/links/8",
        {},
        {"title": "New", "show_socials": False},
        {"link": {"id": 8, "title": "New"}},
    ),
    ("delete_link", {"link_id": 8}, "DELETE", "/links/8", {}, None, {"success": True}),
    (
        "expand_link",
        {"target_type": "music", "isrc": "US1234567890"},
        "GET",
        "/links/expand",
        {"target_type": "music", "isrc": "US1234567890"},
        None,
        {"link": {"target_type": "music"}},
    ),
    (
        "check_link_path",
        {"path": "my-song", "subdomain": "fanlink", "link_id": 8},
        "GET",
        "/links/validPath",
        {"path": "my-song", "subdomain": "fanlink", "link_id": "8"},
        None,
        {"valid": False, "type": "path", "reason": "Taken"},
    ),
    (
        "get_link_insights",
        {
            "link_id": 8,
            "metric": "clickthroughs",
            "aggregate_interval": "day",
            "aggregate_by_referrer": False,
            "for_distinct_fans": True,
        },
        "GET",
        "/links/8/insights",
        {
            "metric": "clickthroughs",
            "aggregate_interval": "day",
            "aggregate_by_referrer": "false",
            "for_distinct_fans": "true",
        },
        None,
        {"insights": [{"clickthroughs": 3}]},
    ),
    (
        "get_link_overview",
        {"link_id": 8},
        "GET",
        "/links/8/insights/overview",
        {},
        None,
        {"insights": {"clicks": 9}},
    ),
    (
        "list_ad_campaigns",
        {"user_id": 7, "status": "paused"},
        "GET",
        "/users/7/advertising/campaigns",
        {"status": "paused", "limit": "100", "offset": "0"},
        None,
        {"campaigns": []},
    ),
    (
        "get_ad_campaign",
        {"campaign_id": 9},
        "GET",
        "/advertising/campaigns/9",
        {},
        None,
        {"campaign": {"id": 9}},
    ),
    (
        "update_ad_campaign",
        {
            "campaign_id": 9,
            "title": "Paused",
            "status": "paused",
            "budget_amount": 12.5,
        },
        "PUT",
        "/advertising/campaigns/9",
        {},
        {"title": "Paused", "status": "paused", "budget_amount": 12.5},
        {"campaign": {"id": 9}},
    ),
    (
        "get_ad_campaign_insights",
        {"campaign_id": 9},
        "GET",
        "/advertising/campaigns/9/insights",
        {},
        None,
        {"insights": {"today": {"total": {"clicks": 5}}}},
    ),
    (
        "get_ad_creative_insights",
        {"campaign_id": 9},
        "GET",
        "/advertising/campaigns/9/creativeInsights",
        {},
        None,
        {"ads": []},
    ),
    (
        "list_attachments",
        {"user_id": 7, "type": "contest"},
        "GET",
        "/users/7/attachments",
        {"type": "contest", "offset": "0", "limit": "100"},
        None,
        {"attachments": []},
    ),
    (
        "get_attachment",
        {"attachment_id": 10},
        "GET",
        "/attachments/10",
        {},
        None,
        {"attachment": {"id": 10}},
    ),
    (
        "create_attachment",
        {"owner_id": 7, "title": "Contest", "type": "contest", "is_hidden": False},
        "POST",
        "/attachments",
        {},
        {"owner_id": 7, "title": "Contest", "type": "contest", "is_hidden": False},
        {"attachment": {"id": 10}},
    ),
    (
        "update_attachment",
        {"attachment_id": 10, "title": "New", "message": "Enter now"},
        "PUT",
        "/attachments/10",
        {},
        {"title": "New", "message": "Enter now"},
        {"attachment": {"id": 10}},
    ),
    (
        "delete_attachment",
        {"attachment_id": 10},
        "DELETE",
        "/attachments/10",
        {},
        None,
        {"success": True},
    ),
    (
        "get_attachment_entries",
        {"attachment_id": 10, "aggregate_interval": "hour"},
        "GET",
        "/attachments/10/entries",
        {"aggregate_interval": "hour"},
        None,
        {"unlocks": [{"hour": "2026-01-01T00:00:00Z", "facebook": 2}]},
    ),
    (
        "get_attachment_unlocks",
        {"attachment_id": 10},
        "GET",
        "/attachments/10/unlocks",
        {"aggregate_interval": "day"},
        None,
        {"unlocks": [{"day": "2026-01-01", "downloads": 2}]},
    ),
    (
        "get_playbook_campaign",
        {"campaign_id": 11},
        "GET",
        "/playbooks/campaigns/11",
        {},
        None,
        {"campaign": {"id": 11}},
    ),
    (
        "update_playbook_campaign",
        {
            "campaign_id": 11,
            "title": "Paused",
            "status": "paused",
            "is_archived": False,
        },
        "PUT",
        "/playbooks/campaigns/11",
        {},
        {"title": "Paused", "status": "paused", "is_archived": False},
        {"campaign": {"id": 11}},
    ),
]


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(
        ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"])
    )

    async def send(request):
        requests.append(request)
        return replies.pop(0)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(
        td,
        "guarded_async_client",
        lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)),
    )
    return requests, replies


async def run(operation, config=None, auth=AUTH):
    return await run_node_operation(
        node_type="automation-toneden",
        operation=operation,
        arguments=config or {},
        credential_data=deepcopy(auth),
        user_id="test-user",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,query,body,response", CASES)
async def test_toneden_operations(
    wire, operation, config, method, path, query, body, response
):
    requests, replies = wire
    replies.append(httpx.Response(200, json=response))
    assert await run(operation, config) == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.scheme == "https" and request.url.host == "www.toneden.io"
    assert request.url.path == "/api/v1" + path
    assert dict(request.url.params) == query
    assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
    assert AUTH["access_token"] not in str(request.url)
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.parametrize("bad", ["../1", "1/links", "https://evil.test", 0, -1])
@pytest.mark.asyncio
async def test_toneden_invalid_id_never_sends(wire, bad):
    with pytest.raises(ValueError):
        await run("get_link", {"link_id": bad})
    assert wire[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["other_oauth", None, "", [], {}])
async def test_toneden_wrong_credential_type_never_sends(wire, tag):
    with pytest.raises(ValueError):
        await run("get_current_user", auth={**AUTH, "credential_type": tag})
    assert wire[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(302, headers={"Location": "https://evil.test"}),
        httpx.Response(401, json={"message": "Rejected " + AUTH["access_token"]}),
        httpx.Response(429, json={"message": "Rate limited"}),
        httpx.Response(200, json={"error": "Denied"}),
        httpx.Response(200, json={"success": False}),
        httpx.Response(200, json={"user": []}),
        httpx.Response(200, json={}),
        httpx.Response(200, text="Login", headers={"Content-Type": "text/html"}),
        httpx.Response(200, content=b"{", headers={"Content-Type": "application/json"}),
    ],
)
async def test_toneden_response_failures(wire, reply):
    wire[1].append(reply)
    with pytest.raises(ValueError) as error:
        await run("get_current_user")
    assert AUTH["access_token"] not in str(error.value)
    assert len(wire[0]) == 1


def test_toneden_oauth_matches_official_contract():
    assert OAUTH_PROVIDER.token_format == "json"
    assert OAUTH_PROVIDER.token_auth == "body"
    assert (
        OAUTH_PROVIDER.authorize_url == "https://www.toneden.io/auth/oauth2/authorize"
    )
    assert OAUTH_PROVIDER.identity_url == td.BASE_URL + "/users/me"
    assert OAUTH_PROVIDER.name_field == "user.display_name"
    assert td.TONEDEN_SCOPES.declared_scopes() == []
    assert set(td.TONEDEN_SCOPES) == {case[0] for case in CASES}

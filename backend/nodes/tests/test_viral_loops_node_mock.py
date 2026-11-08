"""Request boundaries and provider response handling, without live credentials."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import viral_loops_node as vl
from nodes.core.registry import NodeFactory

AUTH = {"credential_type": "viral_loops_api_token", "api_token": "fixture-campaign-private-token"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    async def send(request):
        requests.append(request)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs) as instance:
            yield instance

    monkeypatch.setattr(vl, "guarded_async_client", client)
    return requests, replies


def node(operation, **arguments):
    return NodeFactory.create_node(node_id="viral-loops-test", node_type="automation-viral-loops",
        node_data={"config": {"operation": operation, **arguments}, "credentials": AUTH})


@pytest.mark.parametrize("operation,path,args", [
    ("get_campaign", "/campaign/data", {}),
    ("get_campaign_stats", "/campaign/stats", {}),
    ("get_participant", "/campaign/participant/data", {"email": "alice@example.com"}),
    ("get_participant_referrals", "/campaign/participant/referrals", {"referralCode": "abc", "limit": 20, "offset": 40, "conversionStatus": 1}),
    ("get_participant_order", "/campaign/participant/order", {"email": "alice@example.com"}),
    ("get_participant_rank", "/campaign/participant/rank", {"email": "alice@example.com"}),
    ("get_participant_referrer", "/campaign/participant/referrer", {"email": "alice@example.com"}),
    ("get_pending_rewards", "/campaign/participant/rewards/pending", {}),
    ("get_given_rewards", "/campaign/participant/rewards/given", {"referralCode": "abc"}),
])
async def test_viral_loops_reads(transport, operation, path, args):
    requests, replies = transport
    body = {"campaignName": "Launch", "nested": {"preserved": True}}
    replies.append((200, body))
    assert await node(operation, **args).execute({}) == {"status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/api/v3" + path
    assert request.url.host == "app.viral-loops.com"
    assert request.headers["apiToken"] == AUTH["api_token"]
    assert AUTH["api_token"] not in str(request.url)
    assert not request.content
    for key, value in args.items():
        assert request.url.params[key] == str(value)


@pytest.mark.parametrize("operation,path,args,expected", [
    ("query_participants", "/query", {"participants": [{"email": "alice@example.com"}], "filter": {"limit": 10, "skip": 20}}, {"participants": [{"email": "alice@example.com"}], "filter": {"limit": 10, "skip": 20}}),
    ("search_participants", "/search", {"filters": {"source": "referred", "searchTerm": "alice"}, "pagination": {"offset": 20, "limit": 10}}, {"filters": {"source": "referred", "searchTerm": "alice", "conversionStatus": "all"}, "pagination": {"offset": 20, "limit": 10}}),
    ("convert_participant", "/convert", {"user": {"email": "alice@example.com"}, "options": {"value": 12.5}}, {"user": {"email": "alice@example.com"}, "options": {"value": 12.5}}),
    ("redeem_reward", "/rewards/redeem", {"user": {"referralCode": "abc"}, "rewardId": "reward-1"}, {"user": {"referralCode": "abc"}, "rewardId": "reward-1"}),
])
async def test_viral_loops_posts(transport, operation, path, args, expected):
    requests, replies = transport
    replies.append((200, {"success": True}))
    await node(operation, **args).execute({})
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/v3/campaign/participant" + path
    assert requests[0].headers["apiToken"] == AUTH["api_token"]
    assert not requests[0].url.query
    assert json.loads(requests[0].content) == expected


@pytest.mark.parametrize("status,body", [(403, {"error": "Forbidden", "message": "Invalid API token"}), (200, {"success": False, "message": "Not redeemed"}), (200, False)])
async def test_viral_loops_rejections(transport, status, body):
    requests, replies = transport
    replies.append((status, body))
    with pytest.raises(ValueError):
        await node("get_campaign").execute({})
    assert len(requests) == 1


async def test_viral_loops_verbatim_rejection(transport):
    requests, replies = transport
    replies.append((403, {"message": "Invalid API token"}))
    with pytest.raises(ValueError, match=r"^Invalid API token \(HTTP 403\)$"):
        await node("get_campaign").execute({})


def test_viral_loops_requires_participant_identity():
    with pytest.raises(ValidationError, match="email or referral code"):
        vl.ViralLoopsFullConfig.model_validate({"config": {"operation": "convert_participant", "user": {}}})


def test_viral_loops_connection_evidence_is_campaign_read():
    evidence = vl.ViralLoopsNode.connection_evidence
    assert evidence.identity_operation == "get_campaign"
    assert "campaignName" in evidence.identity_keys
    assert evidence.proves == "account"
    assert vl.ViralLoopsFullConfig.model_validate({"config": {"operation": evidence.identity_operation}, "credentials": AUTH})


async def test_viral_loops_registration(transport):
    requests, replies = transport
    replies.append((200, {"referralCode": "new-code", "isNew": True}))
    result = await node("register_participant", user={"email": "alice@example.com", "firstname": "Alice"}, referrer={"referralCode": "friend"}).execute({})
    assert result["data"] == {"referralCode": "new-code", "isNew": True}
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert str(requests[0].url) == "https://app.viral-loops.com/api/v3/campaign/participant"
    assert json.loads(requests[0].content) == {"user": {"email": "alice@example.com", "firstname": "Alice"}, "referrer": {"referralCode": "friend"}}


@pytest.mark.parametrize("code,body,reachable,label", [
    (200, {"campaignName": "Launch Waitlist", "companyName": "Acme"}, True, "Launch Waitlist"),
    (403, {"message": "Invalid API token"}, False, None),
])
async def test_viral_loops_connect_evidence_uses_real_read(transport, code, body, reachable, label):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = transport
    replies.append((code, body))
    result = await collect_evidence(node_type="automation-viral-loops", credential_id=None,
        credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is reachable
    assert result.account_label == label
    assert len(requests) == 1
    assert requests[0].url.path == "/api/v3/campaign/data"
    if not reachable:
        assert result.error == "Invalid API token (HTTP 403)"

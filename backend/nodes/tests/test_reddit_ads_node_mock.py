"""Exercise Reddit Ads requests through the registered workflow factory.

Synthetic responses verify payloads, refresh and pagination boundaries without
accessing an advertiser account or spending advertising funds.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import reddit_ads_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

CONTRACT = json.loads((Path(__file__).parent / "fixtures/reddit-ads/contract.json").read_text())["operations"]
TOKEN = "synthetic-reddit-ads-token"
CREDENTIAL = {"credential_type": "reddit_oauth", "access_token": TOKEN, "refresh_token": "synthetic-refresh", "expires_at": "2099-01-01T00:00:00Z"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id="reddit-ads-test", node_type="automation-reddit-ads",
        node_data={"config": config, "credentials": credential or CREDENTIAL})


def transport(monkeypatch, body=None, status=200):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body if body is not None else {"data": {"id": "123", "name": "Example"}})
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def config(operation):
    result = {"operation": operation}
    for field in native.re.findall(r"{(\w+)}", native.OPERATIONS[operation][1]):
        result[field] = "1e200a0b-4e98-32cc-dd47-3006e4c85bb2" if field == "business_id" else "123"
    if operation.startswith("create_"):
        result["name"] = "Example campaign"
    if operation.startswith("update_"):
        result["configured_status"] = "PAUSED"
    result.update({
        "create_campaign": {"objective": "CLICKS"},
        "create_ad_group": {"campaign_id": "456", "bid_strategy": "BIDLESS", "bid_type": "CPC", "goal_type": "DAILY_SPEND", "goal_value": 10000000},
        "create_ad": {"ad_group_id": "789", "post_id": "t3_12345"},
        "get_report": {"starts_at": "2026-11-01T00:00:00Z", "ends_at": "2026-11-02T00:00:00Z", "fields": ["IMPRESSIONS", "CLICKS", "SPEND"]},
    }.get(operation, {}))
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", CONTRACT)
async def test_reddit_ads_every_route_and_body(monkeypatch, operation):
    requests = transport(monkeypatch)
    result = await node(config(operation)).execute({})
    assert result["status"] == "success" and len(requests) == 1
    request = requests[0]
    method, path = CONTRACT[operation]["method"], CONTRACT[operation]["path"]
    assert request.method == method
    assert request.url.path == "/api/v3" + native.re.sub(r"{(\w+)}", lambda m: config(operation)[m[1]], path)
    assert request.url.host == "ads-api.reddit.com"
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert request.headers["user-agent"] == "NoClick:reddit-ads:v1.0"
    if method in {"POST", "PATCH"}:
        data = json.loads(request.content)["data"]
        assert "operation" not in data and "page_size" not in data
        for key in native.re.findall(r"{(\w+)}", path):
            assert key not in data
        if operation.startswith("update_"):
            assert data == {"configured_status": "PAUSED"}
        if operation == "create_campaign":
            assert data == {"name": "Example campaign", "configured_status": "PAUSED", "objective": "CLICKS"}
        if operation == "create_ad_group":
            assert data["type"] == "MANUAL" and data["campaign_id"] == "456"
    else:
        assert request.content in {b"", b"null"}


@pytest.mark.asyncio
async def test_reddit_ads_identity_and_continuation(monkeypatch):
    identity = {"data": {"type": "MEMBER", "reddit_username": "advertiser", "id": "123"}}
    transport(monkeypatch, identity)
    assert (await node({"operation": "get_me"}).execute({}))["data"] == identity["data"]
    assert native.RedditAdsNode.connection_evidence.identity_operation == "get_me"
    next_url = native.BASE + "/ad_accounts/123/campaigns?page.token=opaque%2Btoken&page.size=17"
    body = {"data": [], "pagination": {"next_url": next_url}}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "list_campaigns", "ad_account_id": "123", "next_page_url": next_url}).execute({})
    assert str(requests[0].url) == next_url and result["pagination"] == body["pagination"]


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://evil.test/api/v3/ad_accounts/123/campaigns?page.token=x",
    native.BASE + "/ad_accounts/456/campaigns?page.token=x",
    native.BASE + "/ads/123?page.token=x",
    "http://ads-api.reddit.com/api/v3/ad_accounts/123/campaigns",
    "https://ads-api.reddit.com@evil.test/api/v3/ad_accounts/123/campaigns",
    native.BASE + "/ad_accounts/123/campaigns#fragment",
])
async def test_reddit_ads_foreign_pagination_refused(monkeypatch, url):
    requests = transport(monkeypatch)
    with pytest.raises(ValueError, match="same account"):
        await node({"operation": "list_campaigns", "ad_account_id": "123", "next_page_url": url}).execute({})
    assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
async def test_reddit_ads_provider_rejections(monkeypatch, status):
    requests = transport(monkeypatch, {"message": "Insufficient permissions"}, status)
    result = await node({"operation": "get_me"}).execute({})
    assert result == {"status": "error", "http_status": status, "error": {"message": "Insufficient permissions"}}
    assert len(requests) == 1 and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"data": {}, "errors": []}])
async def test_reddit_ads_unexpected_response(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError, match="envelope"):
        await node({"operation": "get_me"}).execute({})


@pytest.mark.asyncio
async def test_reddit_ads_shared_refresh_hooks(monkeypatch):
    from nodes.core import oauth_refresh
    async def refresh(**kwargs):
        assert kwargs["provider"] == "reddit"
        kwargs["credential"]["access_token"] = "renewed-token"
        return "renewed-token"
    ensure = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", ensure)
    requests = transport(monkeypatch)
    credential = {**CREDENTIAL, "refresh_token": "synthetic-refresh", "expires_at": "2000-01-01T00:00:00Z"}
    await node({"operation": "get_me"}, credential).execute({})
    assert requests[0].headers["authorization"] == "Bearer renewed-token"
    ensure.assert_awaited_once()
    freshen = AsyncMock(return_value={**credential, "access_token": "freshened"})
    monkeypatch.setattr(oauth_refresh, "freshen_oauth_credential", freshen)
    assert (await native.RedditAdsNode.freshen_credential(credential))["access_token"] == "freshened"
    assert freshen.call_args.kwargs["provider"] == "reddit"
    assert await native.RedditAdsNode.freshen_credential({"access_token": TOKEN}) == {"access_token": TOKEN}


def test_reddit_ads_schema_scope_manual_and_registration():
    assert NODE_REGISTRY["automation-reddit-ads"] is native.RedditAdsNode
    assert set(native.OPERATIONS) == set(CONTRACT) and len(CONTRACT) == 21
    assert set(native.REDDIT_ADS_SCOPES.declared_scopes()) == {"adsread", "adsedit"}
    assert native.RedditAdsOAuthCredential(**CREDENTIAL).credential_type == "reddit_oauth"
    for operation in native.OPERATIONS:
        assert native.REDDIT_ADS_SCOPES.require(operation).scopes == tuple(CONTRACT[operation]["scopes"])
    from nodes.core.credential_connect import shape_credential
    assert not shape_credential("reddit_oauth", CREDENTIAL)[1]
    for cfg in [
        {"operation": "update_ad_group", "ad_group_id": "123", "goal_type": "DAILY_SPEND"},
        {"operation": "update_campaign", "campaign_id": "123"},
        {"operation": "get_campaign", "campaign_id": "../123"},
        {"operation": "create_campaign", "ad_account_id": "123", "name": "Test", "objective": "UNKNOWN"},
        {"operation": "list_ads", "ad_account_id": "123", "page_size": 101},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            native.RedditAdsNode.parse_config({"config": cfg, "credentials": CREDENTIAL})

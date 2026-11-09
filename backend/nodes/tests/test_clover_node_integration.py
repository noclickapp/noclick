"""Clover's official 60-operation catalog, region routing, and OAuth rotation."""

import json
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote
from pathlib import Path
from copy import deepcopy

import httpx
import pytest
import respx

from nodes.clover_node import (
    CONFIG_MODELS,
    OPERATIONS,
    REGION_API_BASES,
    CloverAPIKeyCredential,
    CloverNode,
    CloverNodeConfig,
    _field_name,
)
from nodes.oauth.clover_oauth import OAUTH_PROVIDER
from nodes.clover_node import POLL_MODELS, CloverOAuthCredential


def make_node(config, *, region="sandbox", merchant_id="merchant-1"):
    return CloverNode(
        node_id="clover-test",
        node_type="automation-clover",
        node_data={},
        config=CloverNodeConfig(
            config=config,
            credentials=CloverAPIKeyCredential(
                merchant_id=merchant_id,
                api_token="secret-token",
                region=region,
            ),
        ),
        sio=Mock(),
        sid="sid",
        workflow_id="workflow",
        user_id="user",
    )


def sample_config(name, op):
    fields = {
        _field_name(variable, "path"): "sample/id"
        for variable in re.findall(r"\{([^}]+)\}", op["path"])
        if variable != "mId"
    }
    fields.update(
        {
            _field_name(param["name"], "query"): "sample"
            for param in op["params"]
            if param["in"] == "query" and param["required"]
        }
    )
    if op["body"] and op["method"] in {"POST", "PUT", "PATCH"}:
        fields["body_json"] = '{"name":"Example"}'
    return CONFIG_MODELS[name](**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,op", list(OPERATIONS.items()))
async def test_every_documented_operation_routes_to_its_official_path(name, op):
    path = op["path"]
    for variable in re.findall(r"\{([^}]+)\}", path):
        value = "merchant-1" if variable == "mId" else "sample/id"
        path = path.replace("{" + variable + "}", quote(value, safe=""))
    base = REGION_API_BASES["sandbox"]
    with respx.mock(assert_all_called=True) as router:
        route = router.request(op["method"], base + path).mock(
            return_value=httpx.Response(200, json={"elements": [{"id": "one"}]})
        )
        result = await make_node(sample_config(name, op)).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer secret-token"
    if op["body"] and op["method"] in {"POST", "PUT", "PATCH"}:
        assert json.loads(request.content) == {"name": "Example"}
    assert result["status"] == "success"
    assert result["operation"] == name
    assert result["data"]["elements"][0]["id"] == "one"
    assert result["timing_ms"]["api_request"] >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize("region,base", REGION_API_BASES.items())
async def test_each_region_uses_only_its_documented_host(region, base):
    with respx.mock(assert_all_called=True) as router:
        route = router.get(base + "/v3/merchants/merchant-1").mock(
            return_value=httpx.Response(200, json={"name": "My Merchant"})
        )
        result = await make_node(
            CONFIG_MODELS["get_merchant"](), region=region
        ).execute({})
    assert route.called
    assert result["data"]["name"] == "My Merchant"


@pytest.mark.asyncio
async def test_path_encoding_body_validation_and_error_status():
    config = CONFIG_MODELS["inventory_get_item"](path_itemid="a/b?c")
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            REGION_API_BASES["sandbox"] + "/v3/merchants/merchant-1/items/a%2Fb%3Fc"
        ).mock(return_value=httpx.Response(204))
        result = await make_node(config).execute({})
    assert route.called and result["data"] == {"ok": True}
    with pytest.raises(ValueError, match="valid JSON"):
        await make_node(CONFIG_MODELS["inventory_create_item"](body_json="{")).execute(
            {}
        )
    with pytest.raises(ValueError, match="JSON object"):
        await make_node(CONFIG_MODELS["inventory_create_item"](body_json="[]")).execute(
            {}
        )
    with respx.mock:
        respx.get(REGION_API_BASES["sandbox"] + "/v3/merchants/merchant-1").mock(
            return_value=httpx.Response(403, json={"error": "forbidden"})
        )
        with pytest.raises(ValueError, match="Clover API error 403"):
            await make_node(CONFIG_MODELS["get_merchant"]()).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["clover.com", "eu.clover.com", "la.clover.com"])
async def test_oauth_exchange_verifies_merchant_and_rotates_refresh_token(monkeypatch, domain):
    monkeypatch.setenv("CLOVER_CLIENT_ID", "client-1")
    monkeypatch.setenv("CLOVER_CLIENT_SECRET", "secret-1")
    future = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    base = f"https://api.{domain}"
    context = {"merchant_id": "merchant-1", "clover_domain": domain}
    with respx.mock(assert_all_called=True) as router:
        token = router.post(base + "/oauth/v2/token").mock(return_value=httpx.Response(200,
            json={"access_token": "access-1", "refresh_token": "refresh-1", "access_token_expiration": future}))
        router.get(base + "/v3/merchants/merchant-1").mock(return_value=httpx.Response(200, json={"name": "Verified Store"}))
        tokens, account = await OAUTH_PROVIDER.exchange("code-1", "https://noclick.com/api/auth/oauth/clover/callback", context=context)
        assert json.loads(token.calls[0].request.content) == {"client_id": "client-1", "client_secret": "secret-1", "code": "code-1"}
        assert account == "Verified Store"
        assert datetime.fromisoformat(tokens.expires_at).timestamp() == future
        assert tokens.merchant_id == "merchant-1" and tokens.clover_domain == domain
        refreshed = router.post(base + "/oauth/v2/refresh").mock(return_value=httpx.Response(200,
            json={"access_token": "access-2", "refresh_token": "refresh-2", "access_token_expiration": future}))
        pair = await OAUTH_PROVIDER.bind_refresh(context)("refresh-1")
        assert json.loads(refreshed.calls[0].request.content) == {"client_id": "client-1", "refresh_token": "refresh-1"}
        assert pair.refresh_token == "refresh-2"


@pytest.mark.asyncio
async def test_oauth_rejects_missing_rotated_token_unverified_identity_and_foreign_context(monkeypatch):
    monkeypatch.setenv("CLOVER_CLIENT_ID", "client-1")
    monkeypatch.setenv("CLOVER_CLIENT_SECRET", "secret-1")
    context = {"clover_domain": "clover.com", "merchant_id": "merchant-1"}
    with respx.mock:
        respx.post("https://api.clover.com/oauth/v2/refresh").mock(return_value=httpx.Response(200,
            json={"access_token": "access-2", "access_token_expiration": 1999999999}))
        with pytest.raises(ValueError, match="single-use"):
            await OAUTH_PROVIDER.bind_refresh(context)("consumed")
        respx.post("https://api.clover.com/oauth/v2/token").mock(return_value=httpx.Response(200,
            json={"access_token": "access-1", "refresh_token": "refresh-1", "access_token_expiration": 1999999999}))
        respx.get("https://api.clover.com/v3/merchants/merchant-1").mock(return_value=httpx.Response(403))
        with pytest.raises(httpx.HTTPStatusError):
            await OAUTH_PROVIDER.exchange("code", "https://noclick.com/callback", context=context)
    for invalid in ({**context, "clover_domain": "clover.com.evil.example"}, {**context, "merchant_id": "../elsewhere"}, {"clover_domain": "clover.com"}):
        with pytest.raises(ValueError):
            OAUTH_PROVIDER.validate_context(invalid)


@pytest.mark.asyncio
async def test_execute_oauth_uses_bound_refresh_and_adopts_rotation(monkeypatch):
    from nodes.core import oauth_refresh
    credential = CloverOAuthCredential(merchant_id="merchant-1", access_token="old", refresh_token="r1")
    n = make_node(CONFIG_MODELS["get_merchant"]())
    n.config.credentials = credential
    async def fresh(**kwargs):
        kwargs["credential"].update(access_token="new", refresh_token="r2", expires_at="2099-01-01T00:00:00Z")
        assert set(kwargs["additional_token_fields"]) == {"clover_domain", "merchant_id"}
        return "new"
    monkeypatch.setattr(oauth_refresh, "ensure_fresh_oauth_token", fresh)
    with respx.mock:
        route = respx.get("https://api.clover.com/v3/merchants/merchant-1").mock(return_value=httpx.Response(200, json={"name": "Merchant"}))
        await n.execute({})
        assert route.calls[0].request.headers["Authorization"] == "Bearer new"
    assert credential.refresh_token == "r2"


def documented_payload(resource):
    return json.loads((Path(__file__).parent / "fixtures" / "clover" / f"{resource}.json").read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,resource", [("on_new_or_updated_order", "orders"), ("on_new_or_updated_item", "items")])
async def test_poll_documented_payload_baselines_emits_once_and_detects_update(monkeypatch, operation, resource):
    payload = documented_payload(resource)
    n = make_node(POLL_MODELS[operation](lookback_minutes=60))
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        next_state, result = mutator(deepcopy(state))
        if next_state is not None:
            state = next_state
        return result
    monkeypatch.setattr(n, "_update_node_state", update)
    monkeypatch.setattr("nodes.clover_node.time.time", lambda: 2000000000)
    with respx.mock:
        route = respx.get(f"https://apisandbox.dev.clover.com/v3/merchants/merchant-1/{resource}").mock(return_value=httpx.Response(200, json=payload))
        assert (await n.execute({}))["changed_count"] == 0
        # Replay documented records against an existing empty baseline.
        state["seen_ids"] = []
        out = await n.execute({})
        assert out["records"] == payload["elements"]
        assert out["changed_count"] == len(payload["elements"])
        event = n.resolve_agent_event(out)
        assert "merchant-1" in event["text"] and payload["elements"][0]["id"] in event["text"]
        assert (await n.execute({}))["changed_count"] == 0
        # A later timestamp on the same record must be seen as another update.
        changed = deepcopy(payload)
        changed["elements"][0]["modifiedTime"] += 1
        route.mock(return_value=httpx.Response(200, json=changed))
        out = await n.execute({})
        assert out["records"] == changed["elements"][:1]
        params = route.calls[0].request.url.params
        assert params["filter"] == "modifiedTime>=1999996400000"
        assert params["limit"] == "100" and params["offset"] == "0"
    scope = n.schedule_poll_scope({"operation": operation, "lookback_minutes": 60})
    assert scope == n.schedule_poll_scope({"operation": operation, "lookback_minutes": 60, "label": "cosmetic change"})
    assert scope != n.schedule_poll_scope({"operation": operation, "lookback_minutes": 30})


@pytest.mark.asyncio
async def test_poll_paginates_before_committing_seen_state(monkeypatch):
    n = make_node(POLL_MODELS["on_new_or_updated_order"]())
    payload = documented_payload("orders")
    n._filter_unseen = AsyncMock(side_effect=lambda items, key: items)
    with respx.mock:
        route = respx.get("https://apisandbox.dev.clover.com/v3/merchants/merchant-1/orders").mock(side_effect=[
            httpx.Response(200, json={"elements": payload["elements"] * 50}),
            httpx.Response(200, json=payload),
        ])
        out = await n.execute({})
        assert out["changed_count"] == 102
        assert route.calls[1].request.url.params["offset"] == "100"
    n._filter_unseen.reset_mock()
    with respx.mock:
        respx.get("https://apisandbox.dev.clover.com/v3/merchants/merchant-1/orders").mock(side_effect=[
            httpx.Response(200, json={"elements": payload["elements"] * 50}),
            httpx.Response(503),
        ])
        with pytest.raises(ValueError, match="503"):
            await n.execute({})
    n._filter_unseen.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"id": "wrong-shape"}, {"elements": [{}]}, {"elements": [{"id": "x"}]}])
async def test_poll_rejects_malformed_payload_without_consuming_events(payload):
    n = make_node(POLL_MODELS["on_new_or_updated_item"]())
    n._filter_unseen = AsyncMock()
    with respx.mock:
        respx.get("https://apisandbox.dev.clover.com/v3/merchants/merchant-1/items").mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(ValueError, match="Clover"):
            await n.execute({})
    n._filter_unseen.assert_not_called()

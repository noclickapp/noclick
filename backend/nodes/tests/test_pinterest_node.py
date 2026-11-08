"""Pinterest request contract and OAuth tests (no credentials or live calls)."""

import json
from unittest.mock import patch

import httpx
import pytest

from nodes.pinterest_node import (
    OPERATIONS,
    PinterestAccessTokenCredential,
    PinterestNode,
    PinterestNodeConfig,
)
from nodes.oauth.pinterest_oauth import OAUTH_PROVIDER, refresh_access_token


def make_node(operation: str, **fields) -> PinterestNode:
    config = PinterestNodeConfig(
        config={"operation": operation, **fields},
        credentials=PinterestAccessTokenCredential(access_token="test-token"),
    )
    return PinterestNode(
        node_id="pin-1",
        node_type="automation-pinterest",
        node_data={},
        config=config,
        user_id="user-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "fields", "method", "path", "body"),
    [
        ("boards_list", {"page_size": 5}, "GET", "/v5/boards", None),
        (
            "boards_create",
            {"body_json": '{"name":"Recipes"}'},
            "POST",
            "/v5/boards",
            {"name": "Recipes"},
        ),
        (
            "pins_create",
            {
                "body_json": '{"board_id":"123","media_source":{"source_type":"image_url","url":"https://example.com/a.jpg"}}'
            },
            "POST",
            "/v5/pins",
            {
                "board_id": "123",
                "media_source": {
                    "source_type": "image_url",
                    "url": "https://example.com/a.jpg",
                },
            },
        ),
        ("pins_get", {"pin_id": "12/34"}, "GET", "/v5/pins/12%2F34", None),
        ("pins_delete", {"pin_id": "123"}, "DELETE", "/v5/pins/123", None),
        ("get_user_account", {}, "GET", "/v5/user_account", None),
    ],
)
async def test_operation_request(operation, fields, method, path, body):
    seen = []

    def respond(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(respond)
    original = httpx.AsyncClient
    with patch(
        "nodes.pinterest_node.httpx.AsyncClient",
        side_effect=lambda **kw: original(transport=transport, **kw),
    ):
        result = await make_node(operation, **fields).execute({})

    assert result["status"] == "success"
    assert seen[0].method == method
    assert seen[0].url.raw_path.decode().split("?", 1)[0] == path
    if operation == "boards_list":
        assert seen[0].url.params["page_size"] == "5"
    assert seen[0].headers["authorization"] == "Bearer test-token"
    if body is not None:
        assert json.loads(seen[0].content) == body


def test_catalog_has_documented_user_oauth_operations():
    assert len(OPERATIONS) == 264
    assert {
        "boards_list",
        "pins_create",
        "pins_analytics",
        "ad_accounts_list",
    } <= OPERATIONS.keys()
    for name, operation in OPERATIONS.items():
        assert operation["path"].startswith("/")
        assert operation["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        path_names = set(__import__("re").findall(r"\{([^}]+)\}", operation["path"]))
        assert path_names <= {
            p["name"] for p in operation["params"] if p["in"] == "path"
        }, name


@pytest.mark.asyncio
async def test_invalid_body_rejected_before_request():
    with pytest.raises(ValueError, match="valid JSON"):
        await make_node("boards_create", body_json="{bad").execute({})


@pytest.mark.asyncio
async def test_provider_error_is_structured():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(403, json={"message": "scope missing"})
    )
    original = httpx.AsyncClient
    with patch(
        "nodes.pinterest_node.httpx.AsyncClient",
        side_effect=lambda **kw: original(transport=transport, **kw),
    ):
        result = await make_node("boards_list").execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 403
    assert result["error"] == "scope missing"


@pytest.mark.asyncio
async def test_oauth_exchange_uses_basic_auth_and_looks_up_account(monkeypatch):
    monkeypatch.setenv("PINTEREST_CLIENT_ID", "client")
    monkeypatch.setenv("PINTEREST_CLIENT_SECRET", "secret")
    seen = []

    def respond(request: httpx.Request):
        seen.append(request)
        if request.url.path == "/v5/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "scope": "boards:read boards:write pins:read",
                },
            )
        return httpx.Response(200, json={"id": "42", "username": "creator"})

    transport = httpx.MockTransport(respond)
    original = httpx.AsyncClient
    with patch(
        "nodes.core.oauth_provider.httpx.AsyncClient",
        side_effect=lambda **kw: original(transport=transport, **kw),
    ):
        tokens, name = await OAUTH_PROVIDER.exchange(
            "code", "https://example.com/callback"
        )
    assert tokens.scope == "boards:read boards:write pins:read"
    assert tokens.refresh_token == "refresh"
    assert name == "creator"
    assert seen[0].headers["authorization"].startswith("Basic ")
    assert "grant_type=authorization_code" in seen[0].content.decode()
    assert "continuous_refresh=true" in seen[0].content.decode()
    assert seen[1].headers["authorization"] == "Bearer access"


@pytest.mark.asyncio
async def test_refresh_requires_new_continuous_token(monkeypatch):
    monkeypatch.setenv("PINTEREST_CLIENT_ID", "client")
    monkeypatch.setenv("PINTEREST_CLIENT_SECRET", "secret")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"access_token": "new", "expires_in": 3600}
        )
    )
    original = httpx.AsyncClient
    with patch(
        "nodes.core.oauth_provider.httpx.AsyncClient",
        side_effect=lambda **kw: original(transport=transport, **kw),
    ):
        with pytest.raises(ValueError, match="refresh_token"):
            await refresh_access_token("old")


def test_scope_registry_covers_catalog_and_excludes_beta_from_connect():
    from nodes.scopes.pinterest import PINTEREST_SCOPES, MSOT_TIER
    from nodes.pinterest_node import PinterestOAuthCredential

    assert PINTEREST_SCOPES.keys_declared == set(OPERATIONS)
    assert set(PINTEREST_SCOPES.elevated()) == {"msot_events_create"}
    assert PINTEREST_SCOPES.require("msot_events_create").tier == MSOT_TIER
    requested = PinterestOAuthCredential.model_json_schema()["x-oauth-scopes"]
    assert "msot:write" not in requested
    assert len(requested) == 16
    assert set(PINTEREST_SCOPES.declared_scopes()) <= set(requested)
    definition = PinterestNode.get_config_schema()["$defs"][
        "PinterestMsotEventsCreateConfig"
    ]
    assert definition["x-requires-tier"] == MSOT_TIER


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, "ads:write", "msot:write_extra"])
async def test_msot_rejected_without_explicit_grant(scope):
    node = make_node("msot_events_create", ad_account_id="123", body_json="{}")
    node.config.credentials.scope = scope
    with patch("nodes.pinterest_node.httpx.AsyncClient") as client:
        with pytest.raises(ValueError, match="Pinterest restricted beta access"):
            await node.execute({})
        client.assert_not_called()
    assert (
        await PinterestNode.load_field_options(
            "restricted_operations", {"scope": scope}
        )
        == []
    )


@pytest.mark.asyncio
async def test_msot_granted_connection_is_offered_and_executes():
    node = make_node("msot_events_create", ad_account_id="123", body_json="{}")
    node.config.credentials.scope = "ads:write,msot:write"
    options = await PinterestNode.load_field_options(
        "restricted_operations", node.config.credentials.model_dump()
    )
    assert [option["value"] for option in options] == ["msot_events_create"]
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": True})
    )
    with patch(
        "nodes.pinterest_node.httpx.AsyncClient",
        side_effect=lambda **kw: original(transport=transport, **kw),
    ):
        assert (await node.execute({}))["status"] == "success"


@pytest.mark.asyncio
async def test_analytics_preserves_numeric_windows_and_csv_arrays():
    seen = []
    transport = httpx.MockTransport(lambda request: (seen.append(request) or httpx.Response(200, json={})))
    original = httpx.AsyncClient
    with patch("nodes.pinterest_node.httpx.AsyncClient", side_effect=lambda **kw: original(transport=transport, **kw)):
        await make_node(
            "ad_account_analytics", ad_account_id="123", start_date="2026-01-01",
            end_date="2026-01-02", columns=["SPEND_IN_MICRO_DOLLAR", "IMPRESSION_1"],
            granularity="TOTAL", click_window_days=7,
        ).execute({})
    assert seen[0].url.params["click_window_days"] == "7.0"
    assert seen[0].url.params.get_list("columns") == ["SPEND_IN_MICRO_DOLLAR,IMPRESSION_1"]


def test_request_schema_describes_json_and_provider_parameter_types():
    schema = PinterestNode.get_config_schema()["$defs"]
    body = schema["PinterestBoardsCreateConfig"]["properties"]["body_json"]
    assert body["contentMediaType"] == "application/json"
    assert body["contentSchema"]["required"] == ["name"]
    parameters = schema["PinterestAdAccountAnalyticsConfig"]["properties"]
    assert parameters["columns"]["type"] == "array"
    assert parameters["start_date"]["format"] == "date"
    assert parameters["click_window_days"]["type"] == "number"


@pytest.mark.asyncio
async def test_catalog_report_keeps_json_selector_in_named_query_field():
    selector = {"catalog_type": "RETAIL", "report": {"report_type": "FEED_INGESTION_ISSUES", "feed_id": "123"}}
    seen = []
    transport = httpx.MockTransport(lambda request: (seen.append(request) or httpx.Response(200, json={"items": []})))
    original = httpx.AsyncClient
    with patch("nodes.pinterest_node.httpx.AsyncClient", side_effect=lambda **kw: original(transport=transport, **kw)):
        await make_node("reports_stats", parameters=selector).execute({})
    assert json.loads(seen[0].url.params["parameters"]) == selector
    assert "catalog_type" not in seen[0].url.params


@pytest.mark.asyncio
async def test_execute_adopts_rotated_tokens_without_overriding_caller_scope():
    from nodes.core.oauth_audit import caller_path_scope, current_caller_path
    from nodes.pinterest_node import PinterestOAuthCredential

    node = make_node("get_user_account")
    node.config.credentials = PinterestOAuthCredential(
        access_token="old-access", refresh_token="old-refresh"
    )
    seen = []

    async def freshen(**kwargs):
        assert current_caller_path() == "mcp"
        assert "caller_path" not in kwargs
        kwargs["credential"].update(
            access_token="new-access",
            refresh_token="new-refresh",
            expires_at="2099-01-01T00:00:00+00:00",
        )
        return "new-access"

    transport = httpx.MockTransport(
        lambda request: (seen.append(request) or httpx.Response(200, json={"username": "creator"}))
    )
    original = httpx.AsyncClient
    with patch("nodes.pinterest_node.ensure_fresh_oauth_token", side_effect=freshen), patch(
        "nodes.pinterest_node.httpx.AsyncClient",
        side_effect=lambda **kw: original(transport=transport, **kw),
    ), caller_path_scope("mcp"):
        result = await node.execute({})
    assert result["status"] == "success"
    assert seen[0].headers["authorization"] == "Bearer new-access"
    assert node.config.credentials.refresh_token == "new-refresh"
    assert node.config.credentials.expires_at == "2099-01-01T00:00:00+00:00"

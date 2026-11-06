"""Adapty transport, binding, parsing, selectors and connection contracts.

Provider requests use deterministic fixtures; saved credentials use staging’s loader.
"""
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import adapty_node as ad
from nodes.core.registry import NODE_REGISTRY, NodeFactory

USER = "fixture-user"
NODE = "automation-adapty"
APP = '14c3d333-2f3a-455a-aa86-ef83dff6913b'
PID = 'd8533a10-bcce-4e33-8c9d-88b05ac56559'
OTHER = '3286abd3-48b0-4e9c-a5f6-ac0a006804a6'
DEVICE = '3fa85f64-5717-4562-b3fc-2c963f66afa6'

@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "adapty_api_key", "secret_key": "fixture-secret", "app_id": APP,
        "verification_profile_id": PID, **updates}


def profile(**updates):
    return {"data": {"app_id": APP, "profile_id": PID, "customer_user_id": "customer-fixture",
        "timestamp": 1791244800000, "custom_attributes": [{"key": "fixture", "value": "blue"}],
        "access_levels": [{"access_level_id": "premium", "starts_at": None, "expires_at": None,
            "is_in_grace_period": False, "store_transaction_id": "private-transaction"}],
        "subscriptions": [{"secret": "private"}], "total_revenue_usd": 99.9, "segment_hash": "private",
        **updates}}


def make_node(operation, data=None, **config):
    target = {} if operation == "check_connection" else {"identifier_kind": "profile_id", "profile_identifier": PID}
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **target, **config},
        "credentials": credential() if data is None else data}, user_id=USER)


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[])
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected HTTP request"
        status, payload = state.responses.pop(0)
        return httpx.Response(status, content=payload) if isinstance(payload, (str, bytes)) else httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        state.client_options.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state


def test_actual_factory_schema_and_required_device_contract():
    assert NODE_REGISTRY[NODE] is ad.AdaptyNode
    schema = ad.AdaptyNode.get_config_schema()
    defs = schema["$defs"]
    ops = {defs[ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in schema["properties"]["config"]["oneOf"]}
    assert len(ops) == 10 and {"get_profile", "create_profile", "update_profile", "delete_profile", "grant_access_level", "revoke_access_level"} <= ops
    assert not any(word in op for op in ops for word in ("transaction", "stripe", "refund", "mail"))
    assert defs["AdaptyAPIKeyCredential"]["required"] == ["secret_key", "app_id", "verification_profile_id"]
    assert "installation_meta" in defs["AdaptyCreateProfileConfig"]["required"]
    assert defs["AdaptyInstallationMeta"]["required"] == ["device_id"]
    for config in ({"operation": "get_profile", "profile_identifier": "not-uuid"},
            {"operation": "create_profile", "profile_identifier": PID},
            {"operation": "update_profile", "profile_identifier": PID, "installation_meta": {}},
            {"operation": "grant_access_level", "profile_identifier": PID, "access_level_id": "premium", "expires_at": "2026-10-06"}):
        with pytest.raises(ValidationError):
            ad.AdaptyNodeConfig(config=config, credentials=credential())


@pytest.mark.parametrize("updates", [{"credential_type": "other"}, {"app_id": "not-uuid"},
    {"verification_profile_id": "not-uuid"}, {"secret_key": "fixture-secret\nprivate"}, {"secret_key": ""}])
def test_bad_raw_credential_is_refused_without_secret_context(updates):
    with pytest.raises(ValueError) as failure:
        ad._credential(credential(**updates))
    assert "fixture-secret" not in str(failure.value) and "private" not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,identifier", [("profile_id", PID), ("customer_user_id", "customer-fixture")])
async def test_profile_headers_fixed_root_and_projection(http, kind, identifier):
    http.responses = [(200, profile())]
    out = await make_node("get_profile", identifier_kind=kind, profile_identifier=identifier).execute({})
    request = http.calls[0]
    assert str(request.url) == ad.ROOT + "profile/" and request.method == "GET"
    assert request.headers["Authorization"] == "Api-Key fixture-secret"
    assert request.headers["adapty-" + kind.replace("_", "-")] == identifier
    assert ("adapty-customer-user-id" in request.headers) != ("adapty-profile-id" in request.headers)
    assert out["data"]["app_id"] == APP and out["data"]["timestamp"] == 1791244800000
    assert "private" not in json.dumps(out) and "subscriptions" not in out["data"] and "total_revenue_usd" not in out["data"]
    assert out["data"]["access_levels"][0]["expires_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_profile", "update_profile", "delete_profile", "grant_access_level", "revoke_access_level"])
async def test_wrong_app_binding_halts_before_any_mutation(http, operation):
    http.responses = [(200, profile(app_id=OTHER))]
    fields = {"installation_meta": {"device_id": DEVICE}} if operation in {"create_profile", "update_profile"} else {"access_level_id": "premium"} if "access_level" in operation else {}
    with pytest.raises(RuntimeError, match="another app/profile"):
        await make_node(operation, **fields).execute({})
    assert len(http.calls) == 1 and http.calls[0].method == "GET"


@pytest.mark.asyncio
async def test_create_and_patch_documented_body_and_explicit_null(http):
    http.responses = [(200, profile()), (200, profile(profile_id=OTHER, customer_user_id="new-customer"))]
    created = await make_node("create_profile", profile_identifier=OTHER, platform_header="iOS",
        installation_meta={"device_id": DEVICE}, first_name="Fixture", analytics_disabled=True).execute({})
    assert created["operation"] == "create_profile" and [request.method for request in http.calls] == ["GET", "POST"]
    assert http.calls[0].headers["adapty-profile-id"] == PID and http.calls[1].headers["adapty-profile-id"] == OTHER
    assert http.calls[1].headers["adapty-platform"] == "iOS"
    assert json.loads(http.calls[1].content) == {"installation_meta": {"device_id": DEVICE}, "first_name": "Fixture", "analytics_disabled": True}
    http.responses = [(200, profile()), (200, profile())]
    updated = await make_node("update_profile", installation_meta={"device_id": DEVICE}, first_name=None,
        custom_attributes=[{"key": "colour", "value": "blue"}]).execute({})
    assert updated["operation"] == "update_profile" and http.calls[-1].method == "PATCH"
    assert json.loads(http.calls[-1].content) == {"installation_meta": {"device_id": DEVICE}, "first_name": None,
        "custom_attributes": [{"key": "colour", "value": "blue"}]}


@pytest.mark.parametrize("attributes", [[{"key": "x", "value": True}], [{"key": "x", "value": "x" * 51}],
    [{"key": "bad space", "value": "x"}], [{"key": "x", "value": float("nan")}],
    [{"key": "x", "value": "a"}, {"key": "x", "value": "b"}], [{"key": str(i), "value": "x"} for i in range(31)]])
def test_actual_profile_model_rejects_bad_custom_attribute_values(attributes):
    with pytest.raises(ValidationError):
        ad.AdaptyNodeConfig(config={"operation": "create_profile", "profile_identifier": PID,
            "installation_meta": {"device_id": DEVICE}, "custom_attributes": attributes}, credentials=credential())


@pytest.mark.asyncio
async def test_delete_empty_204_and_other_success_shapes_are_not_deletion(http):
    http.responses = [(200, profile()), (204, None)]
    out = await make_node("delete_profile").execute({})
    assert out["http_status"] == 204 and out["deletion_acknowledged"] is True
    assert http.calls[-1].method == "DELETE"
    for status, payload in ((200, profile()), (204, "private")):
        http.responses = [(200, profile()), (status, payload)]
        with pytest.raises(RuntimeError, match="204"):
            await make_node("delete_profile").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,path,dates", [("grant_access_level", "grant", {"starts_at": None, "expires_at": "2099-01-01T00:00:00Z"}),
    ("revoke_access_level", "revoke", {"revoke_at": None})])
async def test_access_writes_have_explicit_effect_and_documented_payload(http, operation, path, dates):
    http.responses = [(200, profile()), (200, profile())]
    out = await make_node(operation, access_level_id="premium", **dates).execute({})
    assert str(http.calls[-1].url) == ad.ROOT + "purchase/profile/" + path + "/access-level/"
    assert json.loads(http.calls[-1].content) == {"access_level_id": "premium", **dates}
    assert out["operation"] == operation and "quiet" in out["confirmation"]


@pytest.mark.asyncio
@pytest.mark.parametrize("level,expected", [({"starts_at": None, "expires_at": None, "is_in_grace_period": False}, True),
    ({"starts_at": None, "expires_at": "2000-01-01T00:00:00Z", "is_in_grace_period": False}, False),
    ({"starts_at": None, "expires_at": "2000-01-01T00:00:00Z", "is_in_grace_period": True}, True),
    ({"starts_at": "2099-01-01T00:00:00Z", "expires_at": None, "is_in_grace_period": True}, False)])
async def test_access_status_is_derived_from_current_dates_and_grace_not_sdk_flag(http, level, expected):
    http.responses = [(200, profile(access_levels=[{"access_level_id": "premium", **level}]))]
    out = await make_node("check_access_level", access_level_id="premium").execute({})
    assert out["has_access"] is expected and out["found"] is True and "is_active" not in out["data"]


@pytest.mark.asyncio
async def test_profile_and_access_pickers_use_only_the_chosen_profile(http):
    http.responses = [(200, profile()), (200, profile(profile_id=OTHER))]
    first = await ad.AdaptyNode.load_field_options("profile_identifier", credential(), context={"identifier_kind": "customer_user_id"})
    assert first == {"options": [{"value": "customer-fixture", "label": "customer-fixture"}], "next_page_token": None}
    selected = await ad.AdaptyNode.load_field_options("access_level_id", credential(),
        context={"identifier_kind": "profile_id", "profile_identifier": OTHER, "app_id": "forged", "secret_key": "forged"}, search="missing")
    assert selected == {"options": [], "next_page_token": None}
    assert http.calls[-1].headers["adapty-profile-id"] == OTHER and http.calls[-1].headers["Authorization"] == "Api-Key fixture-secret"
    before = len(http.calls)
    for context, token in (({}, None), ({"identifier_kind": "other", "profile_identifier": OTHER}, None),
            ({"identifier_kind": "profile_id", "profile_identifier": OTHER}, "invented-page")):
        with pytest.raises(ValueError):
            await ad.AdaptyNode.load_field_options("access_level_id", credential(), context=context, page_token=token)
    assert len(http.calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"errors": "fixture-secret"}), (403, {"errors": "private"}),
    (404, {"errors": "private"}), (429, {"errors": "private"}), (500, {}), (200, {"errors": "fixture-secret"}),
    (200, {}), (200, profile(profile_id=OTHER)), (200, profile(access_levels=[{}]))])
async def test_provider_error_or_malformed_profile_is_static_and_unverified(http, status, payload):
    http.responses = [(status, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("get_profile").execute({})
    assert "fixture-secret" not in str(failure.value) and "private" not in str(failure.value) and len(http.calls) == 1


@pytest.mark.asyncio
async def test_real_manual_connect_is_app_profile_reachability_not_account_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    bad = await credential_connect.validate_for_connect(credential_type="adapty_api_key", credential_data=credential(app_id="bad"), user_id=USER)
    assert not bad.ok and bad.field_errors and http.calls == []
    http.responses = [(200, profile())]
    valid = await credential_connect.validate_for_connect(credential_type="adapty_api_key", credential_data=credential(), user_id=USER)
    assert valid.ok and valid.node_type == NODE and valid.evidence.reachable is True
    assert ad.AdaptyNode.connection_evidence.proves == "reachability" and valid.evidence.account_label is None and valid.evidence.samples[0].label == PID


@pytest.mark.asyncio
async def test_saved_connection_uses_staging_loader_and_replaces_all_app_bindings(monkeypatch, http):
    current = credential(secret_key="current-secret", app_id=OTHER, verification_profile_id=OTHER)
    loader = AsyncMock(return_value=current)
    monkeypatch.setattr(ad, "load_credential", loader)
    pool = object()
    result = await ad.AdaptyNode.freshen_credential(credential(), pool=pool, user_id=USER, credential_id="saved")
    loader.assert_awaited_once_with(pool, USER, "saved", raise_on_error=True)
    assert result["secret_key"] == "current-secret" and result["app_id"] == OTHER and result["verification_profile_id"] == OTHER
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("current", [None, credential(credential_type="other"), credential(app_id="bad")])
async def test_unavailable_or_wrong_family_saved_connection_never_falls_back(monkeypatch, http, current):
    monkeypatch.setattr(ad, "load_credential", AsyncMock(return_value=current))
    with pytest.raises(ValueError):
        await ad.AdaptyNode.freshen_credential(credential(), user_id=USER, credential_id="saved")
    assert http.calls == []


@pytest.mark.asyncio
async def test_staging_validation_hook_checks_bound_profile(http):
    http.responses = [(200, profile())]
    assert await ad.AdaptyNode.validate_credential_access(credential()) == {"valid": True}
    assert http.calls[0].headers["adapty-profile-id"] == PID
    http.responses = [(200, profile(app_id=OTHER))]
    with pytest.raises(RuntimeError, match="another app/profile"):
        await ad.AdaptyNode.validate_credential_access(credential())

"""Public metadata discovery through real Pydantic and native cache functions.

LiveChat fixture shape/signature mirror the owner's prepared source. They do
not import or execute its provider helper. Registry, public request row and
exchange modules are controlled fixtures; no token, DB, browser or provider I/O.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Annotated, Literal, Union
from unittest.mock import AsyncMock
import sys

import pytest
from pydantic import BaseModel, ConfigDict, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core import registry
from utils import credential_request_routes as routes


LIVECHAT_SCOPES = ["agents--all:ro", "chats--access:ro", "chats--access:rw",
                   "customers:ro", "groups--all:ro", "tags--all:ro"]


class LiveChatPATCredential(BaseModel):
    credential_type: Literal["livechat_pat"] = Field("livechat_pat", json_schema_extra={"ui:hidden": True})
    account_id: str = Field(title="Account ID")
    personal_access_token: str = Field(title="Personal Access Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="LiveChat Personal Access Token", json_schema_extra={
        "x-credential-url": "https://platform.text.com/console/",
        "x-credential-instructions": "Fixture mirrors the actual PAT fields; no credentials are supplied.",
    })


class LiveChatOAuthCredential(BaseModel):
    credential_type: Literal["livechat_oauth"] = Field("livechat_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(json_schema_extra={"ui:hidden": True})
    refresh_token: str = Field(json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(title="LiveChat OAuth", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "livechat",
        "x-oauth-scopes": LIVECHAT_SCOPES,
        "x-credential-url": "https://platform.text.com/console/",
    })


LiveChatCredential = Annotated[
    Union[LiveChatOAuthCredential, LiveChatPATCredential],
    Field(discriminator="credential_type"),
]


class _LiveChatOperation(BaseModel):
    operation: Literal["list_chats"] = "list_chats"


class LiveChatNodeConfig(NodeConfig):
    config: _LiveChatOperation
    credentials: LiveChatCredential | None = None


class _LiveChatNode(WorkflowNode):
    @classmethod
    def get_config_model(cls):
        return LiveChatNodeConfig

    async def execute(self, inputs):
        raise AssertionError("Metadata discovery must not execute a provider node")


@pytest.fixture(autouse=True)
def isolate_caches(monkeypatch):
    for name in ("_oauth_providers_cache", "_credential_fields_cache",
                 "_credential_siblings_cache", "_credential_methods_cache"):
        monkeypatch.setattr(routes, name, None)
    monkeypatch.setattr(routes, "_pkce_cache", {})


def _module(monkeypatch, provider, **contracts):
    module = ModuleType(f"nodes.oauth.{provider}_oauth")
    for name, value in contracts.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


async def _livechat_exchange_credential(code, redirect_uri, scopes, context, *, code_verifier):
    # Exact required keyword-only signature of the prepared ticketed helper.
    raise AssertionError("PKCE metadata must not exchange a code or consume a ticket")


def _livechat(monkeypatch):
    monkeypatch.setattr(registry, "NODE_REGISTRY", {"automation-livechat": _LiveChatNode})
    return _module(monkeypatch, "livechat", exchange_credential=_livechat_exchange_credential)


def _leaf(kind, *, oauth=False, hidden=False):
    result = {"type": "object", "properties": {
        "credential_type": {"const": kind, "ui:hidden": True},
        "api_key": {"title": "API Key", "type": "string", "ui:widget": "password",
                    "description": "Existing field guidance", "x-credential-url": "https://example.invalid/key"},
        "email": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "managed": {"type": "string", "ui:hidden": True},
    }, "required": ["api_key"]}
    if oauth:
        result.update({"x-credential-type": "oauth", "x-oauth-provider": kind.removesuffix("_oauth"),
                       "x-oauth-scopes": ["read"], "x-oauth-user-scopes": ["user:read"],
                       "x-oauth-supports-custom-client": True,
                       "x-oauth-requires-custom-client": True,
                       "x-oauth-redirect-uri": "https://example.invalid/callback"})
    if hidden:
        result["x-credential-hidden"] = True
    return result


def _schema_node(schema):
    class Node:
        @classmethod
        def get_config_schema(cls):
            return deepcopy(schema)
    return Node


def _schema(credentials, **defs):
    return {"properties": {"credentials": credentials}, "$defs": defs}


def _set_schema(monkeypatch, schema):
    monkeypatch.setattr(registry, "NODE_REGISTRY", {"fixture": _schema_node(schema)})


def test_actual_nullable_discriminated_livechat_shape_discovers_both_methods_in_source_order(monkeypatch):
    _livechat(monkeypatch)
    schema = _LiveChatNode.get_config_schema()
    credentials = schema["properties"]["credentials"]
    assert credentials["anyOf"][0]["oneOf"] == [
        {"$ref": "#/$defs/LiveChatOAuthCredential"},
        {"$ref": "#/$defs/LiveChatPATCredential"},
    ]
    assert credentials["anyOf"][1] == {"type": "null"}
    for kind in ("livechat_oauth", "livechat_pat"):
        methods = routes._get_sibling_methods(kind)
        assert [method["credential_type"] for method in methods] == ["livechat_oauth", "livechat_pat"]
        oauth, pat = methods
        assert oauth["oauth_provider"] == "livechat" and oauth["requires_pkce"] is True
        assert oauth["oauth_scopes"] == LIVECHAT_SCOPES and oauth["credential_fields"] == []
        assert [(field["name"], field["type"]) for field in pat["credential_fields"]] == [
            ("account_id", "text"), ("personal_access_token", "password")]
        assert pat["requires_pkce"] is False and pat["is_oauth"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["livechat_oauth", "livechat_pat"])
async def test_real_public_request_details_carry_sibling_and_required_pkce_metadata(monkeypatch, kind):
    _livechat(monkeypatch)
    row = {"id": "fixture-request", "credential_type": kind, "message": None,
           "status": "pending", "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
           "provision_attempts": 0, "requester_name": "Fixture requester", "requester_email": None}
    pool = SimpleNamespace(fetchrow=AsyncMock(return_value=row))
    monkeypatch.setattr(routes, "get_native_pool", lambda: pool)
    details = await routes.get_credential_request("synthetic-capability")
    assert [method.credential_type for method in details.available_methods] == ["livechat_oauth", "livechat_pat"]
    assert details.available_methods[0].requires_pkce is True
    assert details.requires_pkce is (kind == "livechat_oauth")
    assert details.oauth_provider == ("livechat" if kind == "livechat_oauth" else None)
    assert details.oauth_scopes == (LIVECHAT_SCOPES if kind == "livechat_oauth" else [])
    assert pool.fetchrow.await_count == 1


def test_direct_ref_union_preserves_all_existing_field_and_oauth_connect_metadata(monkeypatch):
    async def optional_verifier(code, redirect_uri, code_verifier=None):
        raise AssertionError("metadata only")
    _module(monkeypatch, "fixture", exchange_code_for_tokens=optional_verifier)
    schema = _schema({"anyOf": [{"$ref": "#/$defs/ApiCredential"}, {"$ref": "#/$defs/OAuthCredential"}]},
                     ApiCredential=_leaf("fixture_key"), OAuthCredential=_leaf("fixture_oauth", oauth=True))
    _set_schema(monkeypatch, schema)
    before = deepcopy(schema)
    fields, siblings, methods = routes._build_caches()
    assert schema == before
    assert list(fields) == ["fixture_key"]
    assert fields["fixture_key"] == [{"name": "api_key", "label": "API Key", "type": "password",
        "placeholder": "", "required": True, "description": "Existing field guidance",
        "help_url": "https://example.invalid/key"}]
    assert [method["credential_type"] for method in siblings["fixture_key"]] == ["fixture_key", "fixture_oauth"]
    oauth = methods["fixture_oauth"]
    assert oauth["requires_pkce"] is False and oauth["oauth_scopes"] == ["read"]
    assert oauth["oauth_user_scopes"] == ["user:read"]
    assert oauth["supports_custom_client"] is True and oauth["requires_custom_client"] is True
    assert oauth["oauth_redirect_uri"] == "https://example.invalid/callback"


def test_nested_aliases_deduplicate_credential_types_and_keep_declared_order(monkeypatch):
    schema = _schema({"anyOf": [{"$ref": "#/$defs/Alias"}, {"type": "null"}]},
        Alias={"oneOf": [{"$ref": "#/$defs/BCredential"}, {"anyOf": [
            {"$ref": "#/$defs/ACredential"}, {"$ref": "#/$defs/BCredential"}]}]},
        ACredential=_leaf("a_key"), BCredential=_leaf("b_key"))
    _set_schema(monkeypatch, schema)
    fields, siblings, methods = routes._build_caches()
    assert set(fields) == set(methods) == {"a_key", "b_key"}
    assert [method["credential_type"] for method in siblings["a_key"]] == ["b_key", "a_key"]
    assert siblings["a_key"] is siblings["b_key"]


def test_hidden_methods_remain_out_of_visible_sibling_groups_with_original_own_caches(monkeypatch):
    schema = _schema({"anyOf": [{"oneOf": [{"$ref": "#/$defs/HiddenCredential"},
        {"$ref": "#/$defs/VisibleCredential"}]}, {"type": "null"}]},
        HiddenCredential=_leaf("hidden_key", hidden=True), VisibleCredential=_leaf("visible_key"))
    _set_schema(monkeypatch, schema)
    fields, siblings, methods = routes._build_caches()
    assert set(fields) == set(methods) == {"hidden_key", "visible_key"}
    assert "hidden_key" not in siblings
    assert [method["credential_type"] for method in siblings["visible_key"]] == ["visible_key"]


def test_hidden_union_wrapper_does_not_unhide_a_repeated_method(monkeypatch):
    schema = _schema({"anyOf": [{"$ref": "#/$defs/A", "x-credential-hidden": True},
        {"$ref": "#/$defs/B"}, {"$ref": "#/$defs/A"}]}, A=_leaf("a_key"), B=_leaf("b_key"))
    _set_schema(monkeypatch, schema)
    _fields, siblings, _methods = routes._build_caches()
    assert set(siblings) == {"b_key"}
    assert [method["credential_type"] for method in siblings["b_key"]] == ["b_key"]


def test_noncredential_refs_and_nested_fields_do_not_become_siblings_but_all_defs_caches_stay_compatible(monkeypatch):
    schema = _schema({"anyOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/Config"},
        {"$ref": "#/$defs/B"}, {"type": "string"}, {"type": "null"}]},
        A=_leaf("a_key"), B=_leaf("b_key"), Orphan=_leaf("unreferenced_oauth", oauth=True),
        Config={"properties": {"operation": {"const": "list"}, "embedded": {"$ref": "#/$defs/Orphan"}}})
    _set_schema(monkeypatch, schema)
    fields, siblings, methods = routes._build_caches()
    assert set(methods) == {"a_key", "b_key", "unreferenced_oauth"}
    assert set(fields) == {"a_key", "b_key"}
    assert [method["credential_type"] for method in siblings["a_key"]] == ["a_key", "b_key"]
    assert "unreferenced_oauth" not in siblings
    assert routes._discover_oauth_providers() == {"unreferenced"}


@pytest.mark.parametrize("bad_ref", ["#/$defs/Missing", "https://example.invalid/credential.json",
                                      "#/properties/config", "#/$defs/bad~2name", "#/$defs/A/nested"])
def test_missing_nonlocal_and_malformed_refs_refuse_whole_sibling_group_only(monkeypatch, bad_ref):
    schema = _schema({"anyOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}, {"$ref": bad_ref}]},
                     A=_leaf("a_key"), B=_leaf("b_key"))
    _set_schema(monkeypatch, schema)
    fields, siblings, methods = routes._build_caches()
    assert set(fields) == set(methods) == {"a_key", "b_key"}
    assert siblings == {}
    with pytest.raises(ValueError):
        routes._credential_union_leaves(schema)


@pytest.mark.parametrize("cycle", ["direct", "mutual"])
def test_cyclic_refs_refuse_siblings_and_do_not_hang_or_publish_a_partial_group(monkeypatch, cycle):
    aliases = {"Loop": {"$ref": "#/$defs/Loop"}} if cycle == "direct" else {
        "Loop": {"$ref": "#/$defs/Other"}, "Other": {"oneOf": [{"$ref": "#/$defs/Loop"}]}}
    schema = _schema({"oneOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"},
                               {"$ref": "#/$defs/Loop"}]}, A=_leaf("a_key"), B=_leaf("b_key"), **aliases)
    _set_schema(monkeypatch, schema)
    fields, siblings, methods = routes._build_caches()
    assert set(fields) == set(methods) == {"a_key", "b_key"} and siblings == {}
    with pytest.raises(ValueError, match="cyclic"):
        routes._credential_union_leaves(schema)


@pytest.mark.parametrize("shape", ["deep", "wide", "object_cycle", "empty_union", "nonlist_union", "nonschema_branch"])
def test_local_traversal_has_explicit_work_and_shape_bounds(monkeypatch, shape):
    if shape == "deep":
        credentials = {"$ref": "#/$defs/Alias0"}
        defs = {f"Alias{i}": {"$ref": f"#/$defs/Alias{i+1}"} for i in range(34)}
        defs["Alias34"] = _leaf("deep_key")
    elif shape == "wide":
        credentials, defs = {"anyOf": [{"type": "null"}] * 1025}, {}
    elif shape == "object_cycle":
        credentials = {"anyOf": []}
        credentials["anyOf"].append(credentials)
        defs = {}
    elif shape == "empty_union":
        credentials, defs = {"oneOf": []}, {}
    elif shape == "nonlist_union":
        credentials, defs = {"oneOf": {"$ref": "#/$defs/A"}}, {"A": _leaf("a_key")}
    else:
        credentials, defs = {"anyOf": [None]}, {}
    schema = _schema(credentials, **defs)
    with pytest.raises(ValueError):
        routes._credential_union_leaves(schema)
    _set_schema(monkeypatch, schema)
    assert routes._build_caches()[1] == {}


def test_escaped_local_definition_names_resolve_without_fetching_any_reference(monkeypatch):
    schema = _schema({"oneOf": [{"$ref": "#/$defs/A~1Credential"}, {"$ref": "#/$defs/B~0Credential"}]},
                     **{"A/Credential": _leaf("a_key"), "B~Credential": _leaf("b_key")})
    _set_schema(monkeypatch, schema)
    _fields, siblings, _methods = routes._build_caches()
    assert [method["credential_type"] for method in siblings["a_key"]] == ["a_key", "b_key"]


def test_single_direct_ref_retains_existing_single_method_fallback(monkeypatch):
    _set_schema(monkeypatch, _schema({"$ref": "#/$defs/OneCredential"}, OneCredential=_leaf("one_key")))
    assert routes._get_sibling_methods("one_key") == []
    assert routes._get_credential_method("one_key")["credential_type"] == "one_key"
    assert routes._get_credential_fields("one_key")[0]["name"] == "api_key"


def test_invalid_group_does_not_remove_another_nodes_valid_existing_sibling_group(monkeypatch):
    good = _schema({"anyOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}]}, A=_leaf("a_key"), B=_leaf("b_key"))
    bad = deepcopy(good)
    bad["properties"]["credentials"]["anyOf"].append({"$ref": "#/$defs/Missing"})
    monkeypatch.setattr(registry, "NODE_REGISTRY", {"good": _schema_node(good), "bad": _schema_node(bad)})
    _fields, siblings, _methods = routes._build_caches()
    assert [method["credential_type"] for method in siblings["a_key"]] == ["a_key", "b_key"]


@pytest.mark.parametrize("contract,expected", [("required_ticketed", True), ("optional_ticketed", False),
    ("required_legacy", True), ("optional_legacy", False), ("annotation_only_optional", True),
    ("no_verifier", False)])
def test_pkce_metadata_uses_the_selected_contract_required_default_not_annotations(monkeypatch, contract, expected):
    async def required_ticketed(code, redirect_uri, scopes, context, *, code_verifier):
        raise AssertionError("metadata only")
    async def optional_ticketed(code, redirect_uri, scopes, context, *, code_verifier=None):
        raise AssertionError("metadata only")
    async def required_legacy(code, redirect_uri, code_verifier):
        raise AssertionError("metadata only")
    async def optional_legacy(code, redirect_uri, code_verifier=None):
        raise AssertionError("metadata only")
    async def annotation_only_optional(code, redirect_uri, code_verifier: str | None):
        raise AssertionError("metadata only")
    async def no_verifier(code, redirect_uri):
        raise AssertionError("metadata only")
    functions = {"required_ticketed": required_ticketed, "optional_ticketed": optional_ticketed,
        "required_legacy": required_legacy, "optional_legacy": optional_legacy,
        "annotation_only_optional": annotation_only_optional, "no_verifier": no_verifier}
    key = "exchange_credential" if "ticketed" in contract else "exchange_code_for_tokens"
    _module(monkeypatch, "fixture", **{key: functions[contract]})
    assert routes._is_pkce_provider("fixture") is expected
    assert routes._pkce_cache["fixture"] is expected


def test_ticketed_contract_precedence_never_uses_a_different_legacy_requirement(monkeypatch):
    async def optional_ticketed(code, redirect_uri, scopes, context, *, code_verifier=None):
        raise AssertionError("metadata only")
    async def required_legacy(code, redirect_uri, code_verifier):
        raise AssertionError("metadata only")
    _module(monkeypatch, "fixture", exchange_credential=optional_ticketed,
            exchange_code_for_tokens=required_legacy)
    assert routes._is_pkce_provider("fixture") is False


def test_malformed_non_none_ticketed_contract_refuses_metadata_without_legacy_fallthrough(monkeypatch):
    async def required_legacy(code, redirect_uri, code_verifier):
        raise AssertionError("metadata only")
    _module(monkeypatch, "fixture", exchange_credential="not callable",
            exchange_code_for_tokens=required_legacy)
    assert routes._is_pkce_provider("fixture") is False


def test_absent_ticketed_contract_preserves_optional_legacy_provider(monkeypatch):
    async def optional_legacy(code, redirect_uri, code_verifier=None):
        raise AssertionError("metadata only")
    _module(monkeypatch, "fixture", exchange_credential=None, exchange_code_for_tokens=optional_legacy)
    assert routes._is_pkce_provider("fixture") is False


def test_unavailable_exchange_contract_has_no_positive_pkce_metadata(monkeypatch):
    _module(monkeypatch, "fixture")
    assert routes._is_pkce_provider("fixture") is False

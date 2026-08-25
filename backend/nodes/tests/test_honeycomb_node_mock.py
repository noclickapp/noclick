"""
Mock tests for the Honeycomb node (no live API calls).

Honeycomb is a region-scoped REST API with two auth surfaces (v1
``X-Honeycomb-Team`` and v2 Management ``Authorization: Bearer id:secret``) and
native webhook triggers (verified by a plaintext ``X-Honeycomb-Webhook-Token``,
NOT HMAC). These tests patch ``httpx.AsyncClient.request`` and let the real
``honeycomb_request`` run, so auth/region/content-type/error-handling and every
handler's method+path building are what's under test. EVERY typed operation plus
the raw passthrough is executed once with required fields auto-filled.
"""

import json
import types
import typing
from typing import get_args, get_origin
from unittest.mock import Mock, patch

import pytest

import nodes.honeycomb_node as T
from nodes.honeycomb_node import (
    HoneycombNode, CONFIGS_BY_OP, HANDLERS, OP_META, TRIGGER_OPS, HoneycombNodeConfig,
    HoneycombApiKeyCredential, HoneycombManagementKeyCredential, HoneycombCredential,
    honeycomb_request,
)


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"x"
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _patch_request(payload=None, status_code=200, capture=None):
    payload = payload if payload is not None else {"ok": True}

    async def fake_request(self, method, url, headers=None, params=None, json=None):
        if capture is not None:
            capture["method"] = method
            capture["url"] = url
            capture["headers"] = headers or {}
            capture["params"] = params
            capture["json"] = json
        return _FakeResponse(payload, status_code=status_code)

    return patch("httpx.AsyncClient.request", new=fake_request)


# A credential dict carrying BOTH v1 and v2 material so any op's version works.
FULL_CRED = {"api_key": "k1", "key_id": "kid", "secret": "sec", "region": "us"}


def make_node(config_dict, credentials=None):
    node_data = {"config": config_dict}
    if credentials is not None:
        node_data["credentials"] = credentials
    return HoneycombNode(
        node_id="hc", node_type="automation-honeycomb", node_data=node_data,
        config=HoneycombNodeConfig(config=config_dict, credentials=credentials),
        sio=Mock(), sid="s", workflow_id="w", user_id="u",
    )


def _placeholder(field, name=""):
    if name.endswith("_json"):
        return "{}"
    ann = field.annotation
    origin = get_origin(ann)
    if origin is typing.Union or origin is getattr(types, "UnionType", None):
        args = [a for a in get_args(ann) if a is not type(None)]
        ann = args[0] if args else str
        origin = get_origin(ann)
    if origin in (list, tuple, set):
        return []
    if origin is dict:
        return {}
    if ann is bool:
        return False
    if ann is int:
        return 1
    if ann is float:
        return 1.0
    return "hc"


def build_config(op):
    cls = CONFIGS_BY_OP[op]
    kwargs = {}
    for name, field in cls.model_fields.items():
        if name == "operation":
            continue
        if field.is_required():
            kwargs[name] = _placeholder(field, name)
    return cls(**kwargs)


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------
def test_operation_inventory():
    action_ops = [op for op in HANDLERS if op != "rest_request"]
    assert len(action_ops) == 85, f"expected 85 typed ops, got {len(action_ops)}"
    assert "rest_request" in HANDLERS
    assert TRIGGER_OPS == {"on_trigger_fired", "on_burn_alert"}
    for op in HANDLERS:
        assert op in CONFIGS_BY_OP and op in OP_META
    for op in TRIGGER_OPS:
        assert op in CONFIGS_BY_OP and op not in HANDLERS


def test_schema_shape():
    schema = HoneycombNode.get_config_schema()
    props = schema["properties"]
    variants = props["config"].get("oneOf") or props["config"].get("anyOf") or []
    assert len(variants) == 88  # 85 typed + passthrough + 2 triggers
    cred_refs = [v for v in (props["credentials"].get("oneOf") or props["credentials"].get("anyOf") or [])
                 if v.get("$ref")]
    assert len(cred_refs) == 2


# ---------------------------------------------------------------------------
# Request layer / auth branches
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_v1_auth_and_region():
    cap = {}
    with _patch_request(capture=cap):
        res = await honeycomb_request({"api_key": "k1", "region": "eu"}, "GET", "/1/datasets", action_name="list_datasets")
    assert res["status"] == "success"
    assert cap["url"] == "https://api.eu1.honeycomb.io/1/datasets"
    assert cap["headers"]["X-Honeycomb-Team"] == "k1"
    assert cap["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_v2_auth_and_content_type():
    cap = {}
    with _patch_request(capture=cap):
        await honeycomb_request(FULL_CRED, "GET", "/2/environments", version="2", action_name="list_environments")
    assert cap["url"] == "https://api.honeycomb.io/2/environments"
    assert cap["headers"]["Authorization"] == "Bearer kid:sec"
    assert cap["headers"]["Content-Type"] == "application/vnd.api+json"


@pytest.mark.asyncio
async def test_extra_headers_forwarded():
    cap = {}
    with _patch_request(capture=cap):
        await honeycomb_request({"api_key": "k"}, "POST", "/1/events/ds", json_body={"a": 1},
                                extra_headers={"X-Honeycomb-Samplerate": 5, "X-Skip": None}, action_name="send_event")
    assert cap["headers"]["X-Honeycomb-Samplerate"] == "5"
    assert "X-Skip" not in cap["headers"]  # None dropped


@pytest.mark.asyncio
async def test_v1_missing_key_clean_error():
    res = await honeycomb_request({"region": "us"}, "GET", "/1/datasets", action_name="x")
    assert res["status"] == "error" and res["status_code"] == 401


@pytest.mark.asyncio
async def test_v2_missing_management_key_clean_error():
    res = await honeycomb_request({"api_key": "only_v1"}, "GET", "/2/environments", version="2", action_name="x")
    assert res["status"] == "error" and res["status_code"] == 401


@pytest.mark.asyncio
async def test_error_bodies():
    with _patch_request(payload={"title": "bad", "detail": "nope"}, status_code=422):
        r1 = await honeycomb_request({"api_key": "k"}, "GET", "/1/x", action_name="x")
    assert r1["status"] == "error" and r1["error"] == "nope"
    with _patch_request(payload={"errors": [{"detail": "jsonapi err"}]}, status_code=400):
        r2 = await honeycomb_request(FULL_CRED, "GET", "/2/x", version="2", action_name="x")
    assert r2["error"] == "jsonapi err"


# ---------------------------------------------------------------------------
# Every typed operation + passthrough executes and hits the right version/path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_every_action_op_executes():
    failures = []
    for op, entry in list(HANDLERS.items()):
        cap = {}
        cfg = build_config(op)
        with _patch_request(capture=cap):
            res = await entry(None, cfg, FULL_CRED)  # handler(node, config, cred)
        if res.get("status") != "success":
            failures.append((op, res.get("error")))
            continue
        version = OP_META[op].get("version", "1")
        url = cap.get("url", "")
        if op != "rest_request" and version in ("1", "2") and f"/{version}/" not in url:
            failures.append((op, f"path/version mismatch: {url}"))
    assert not failures, f"ops failed: {failures[:20]}"


@pytest.mark.asyncio
async def test_passthrough_rest_request():
    cap = {}
    cfg = {"operation": "rest_request", "method": "POST", "path": "/1/markers/ds",
           "version": "1", "body_json": '{"message": "deploy"}', "params_json": '{"limit": 5}'}
    node = make_node(cfg, credentials={"credential_type": "honeycomb_api_key", "api_key": "k", "region": "us"})
    with _patch_request(capture=cap):
        res = await node.execute({})
    assert res["status"] == "success"
    assert cap["method"] == "POST" and cap["url"].endswith("/1/markers/ds")
    assert cap["json"] == {"message": "deploy"}
    assert cap["params"] == {"limit": 5}


@pytest.mark.asyncio
async def test_execute_missing_credentials_raises():
    node = make_node({"operation": "list_datasets"}, credentials=None)
    with pytest.raises(ValueError):
        await node.execute({})


# ---------------------------------------------------------------------------
# Webhook triggers
# ---------------------------------------------------------------------------
def test_verify_webhook_token():
    assert T.verify_webhook_token({"x-honeycomb-webhook-token": "s3cret"}, "s3cret") is True
    assert T.verify_webhook_token({"x-honeycomb-webhook-token": "wrong"}, "s3cret") is False
    assert T.verify_webhook_token({}, "s3cret") is False
    assert T.verify_webhook_token({}, None) is True  # no secret configured → accept


@pytest.mark.asyncio
async def test_register_and_verify_webhook():
    cap = {}
    with _patch_request(payload={"id": "recip-123"}, capture=cap):
        result = await HoneycombNode._register_external_webhook(
            webhook_url="https://x.hooks.example.test/abc",
            credential={"api_key": "k", "region": "us"},
            config={"operation": "on_trigger_fired"}, node_id="node1",
        )
    assert result["external_webhook_id"] == "recip-123"
    secret = result["signing_secret"]
    # recipient body shape
    assert cap["json"]["type"] == "webhook"
    assert cap["json"]["details"]["webhook_url"] == "https://x.hooks.example.test/abc"
    # the returned secret verifies an incoming delivery
    assert HoneycombNode.verify_webhook_signature(
        b"{}", {"x-honeycomb-webhook-token": secret}, {"signing_secret": secret}) is True


@pytest.mark.asyncio
async def test_trigger_execute_passes_payload_through():
    node = make_node({"operation": "on_trigger_fired"}, credentials=None)
    res = await node.execute({"name": "High latency", "status": "TRIGGERED"})
    assert res["status"] == "success"
    assert res["action"] == "on_trigger_fired"
    assert res["data"]["name"] == "High latency"


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def test_credential_union_parses_both():
    from pydantic import TypeAdapter
    adapter = TypeAdapter(HoneycombCredential)
    v1 = adapter.validate_python({"credential_type": "honeycomb_api_key", "api_key": "k", "region": "eu"})
    assert isinstance(v1, HoneycombApiKeyCredential) and v1.region == "eu"
    v2 = adapter.validate_python({"credential_type": "honeycomb_management_key", "key_id": "i", "secret": "s"})
    assert isinstance(v2, HoneycombManagementKeyCredential)


# ---------------------------------------------------------------------------
# Kinesis auth header (live E2E found the endpoint needs Firehose auth)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_kinesis_sends_firehose_access_key():
    cap = {}
    cfg = {"operation": "send_kinesis_events", "dataset": "ds",
           "body_json": "{}", "firehose_request_id": "req-1"}
    node = make_node(cfg, credentials={"credential_type": "honeycomb_api_key", "api_key": "K", "region": "us"})
    with _patch_request(capture=cap):
        res = await node.execute({})
    assert res["status"] == "success"
    # Kinesis Firehose auth header (NOT just X-Honeycomb-Team)
    assert cap["headers"]["X-Amz-Firehose-Access-Key"] == "K"
    assert cap["headers"]["X-Amz-Firehose-Request-Id"] == "req-1"


# ---------------------------------------------------------------------------
# Dynamic dropdowns
# ---------------------------------------------------------------------------
def test_dropdown_registry_marked_in_schema():
    """Every _DROPDOWNS field must carry an x-dynamic-options marker on at least
    one config field (so the FE renders a dropdown), and vice versa."""
    from nodes.honeycomb_node import _DROPDOWNS
    marked = set()
    for cls in CONFIGS_BY_OP.values():
        for name, field in cls.model_fields.items():
            extra = field.json_schema_extra or {}
            if isinstance(extra, dict) and "x-dynamic-options" in extra:
                marked.add(extra["x-dynamic-options"]["field_name"])
    # every registry key is marked on some field
    assert set(_DROPDOWNS) <= marked, f"registry fields not marked: {set(_DROPDOWNS) - marked}"
    # every marked field is in the registry (no orphan dropdowns)
    assert marked <= set(_DROPDOWNS), f"marked fields with no loader: {marked - set(_DROPDOWNS)}"


@pytest.mark.asyncio
async def test_dropdown_dependent_without_parent_is_empty():
    # A dataset-scoped dropdown returns nothing (no error) until dataset is set.
    res = await HoneycombNode.load_field_options("trigger_id", {"api_key": "k"}, context={})
    assert res == {"options": [], "next_page_token": None}


@pytest.mark.asyncio
async def test_dropdown_dispatch_builds_scoped_path():
    cap = {}
    with _patch_request(payload=[{"id": "T1", "name": "My Trigger"}], capture=cap):
        res = await HoneycombNode.load_field_options("trigger_id", {"api_key": "k", "region": "us"}, context={"dataset": "myds"})
    assert cap["url"].endswith("/1/triggers/myds")
    assert res["options"] == [{"label": "My Trigger", "value": "T1"}]


@pytest.mark.asyncio
async def test_dropdown_v2_uses_management_key():
    cap = {}
    with _patch_request(payload={"data": [{"id": "E1", "attributes": {"name": "prod"}}]}, capture=cap):
        res = await HoneycombNode.load_field_options(
            "environment_id", {"key_id": "i", "secret": "s", "region": "us"}, context={"team_slug": "acme"})
    assert cap["url"].endswith("/2/teams/acme/environments")
    assert cap["headers"]["Authorization"] == "Bearer i:s"
    assert res["options"] == [{"label": "prod", "value": "E1"}]

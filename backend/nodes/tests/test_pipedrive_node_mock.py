"""
Contract tests for the Pipedrive REST API node (no live API calls).

The node exposes ~294 v1+v2 operations generated from ``pipedrive_ops.json`` and
dispatched through one generic, version-aware handler. These tests verify, for
EVERY operation, that the node dispatches the correct HTTP method + path (params
substituted) + API version + auth scheme and sends the required body fields —
plus type coercion, dual auth (API token vs OAuth Bearer), the webhook trigger
with HTTP Basic-auth verification, event filtering (v1/v2 payloads), error
handling, and dynamic-option dropdowns.
"""

import base64

import pytest
from unittest.mock import Mock, patch

from nodes.pipedrive_node import (
    PipedriveNode,
    PipedriveNodeConfig,
    PipedriveAPITokenCredential,
    PipedriveOAuthCredential,
    _TRIGGER_EVENTS,
    _TRIGGER_MODELS,
    OP_SPECS,
    _OP_RUNTIME,
    _safe_attr,
    _REQUIRED_QUERY,
    _ONE_OF_REQUIRED,
)


@pytest.fixture
def credentials():
    return PipedriveAPITokenCredential(company_domain="acme", api_token="test_token_12345")


def create_pipedrive_node(config):
    return PipedriveNode(
        node_id="test-pipedrive-node",
        node_type="automation-pipedrive",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


async def _run(node, status_code, payload):
    mock_client = create_mock_client(status_code, payload)
    with patch("nodes.pipedrive_node.httpx.AsyncClient", return_value=mock_client):
        return await node.execute({})


def _envelope(data):
    """Pipedrive wraps results in {success, data, additional_data}."""
    return {"success": True, "data": data}


def _dummy_for(ftype: str) -> str:
    return {"integer": "1", "number": "1", "boolean": "true", "object": "{}", "array": "[]"}.get(ftype, "x")


def _minimal_config(spec) -> dict:
    op = spec["operation"]
    cfg = {"operation": op}
    for p in spec.get("path_params", []):
        cfg[_safe_attr(p)] = "999"
    for bf in spec.get("body", []):
        api, required, ftype, _desc = bf
        if required:
            cfg[_safe_attr(api)] = _dummy_for(ftype)
    # required query params (API-required, enforced by the node)
    for (op_name, qname) in _REQUIRED_QUERY:
        if op_name == op:
            cfg[_safe_attr(qname)] = "x"
    # one-of-required: satisfy the group so the pre-flight passes
    grp = _ONE_OF_REQUIRED.get(op)
    if grp:
        cfg[_safe_attr(grp[0])] = "1"
    return cfg


# ============================================================================
# Comprehensive per-operation contract test
# ============================================================================


class TestPipedriveOperationContracts:
    def test_registry_integrity(self):
        names = [s["operation"] for s in OP_SPECS]
        assert len(names) == len(set(names)), "duplicate operation names"
        for n in names:
            assert n in _OP_RUNTIME
        assert len(names) >= 280, f"expected >=280 ops, got {len(names)}"
        # every op is v1 or v2 (no oauth/removed leftovers)
        for r in _OP_RUNTIME.values():
            assert r["version"] in ("v1", "v2")
            assert r["path"].startswith("/")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("spec", OP_SPECS, ids=[s["operation"] for s in OP_SPECS])
    async def test_operation_dispatch(self, spec, credentials):
        captured = {}

        async def fake_request(company_domain, api_token, method, endpoint, version="v2",
                               params=None, json_body=None, action_name="request", auth_bearer=False):
            captured.update(company_domain=company_domain, api_token=api_token, method=method,
                            endpoint=endpoint, version=version, params=params, json_body=json_body,
                            action_name=action_name, auth_bearer=auth_bearer)
            return {"status": "success", "action": action_name, "data": {}}

        cfg = _minimal_config(spec)
        node = create_pipedrive_node(PipedriveNodeConfig(config=cfg, credentials=credentials))
        with patch("nodes.pipedrive_node._pipedrive_request", fake_request):
            result = await node.execute({})

        assert result["status"] == "success"
        assert captured["method"] == spec["method"], spec["operation"]
        assert captured["version"] == spec["version"], spec["operation"]
        assert captured["action_name"] == spec["operation"]
        # API-token auth: x-api-token scheme (not bearer), company domain threaded
        assert captured["auth_bearer"] is False
        assert captured["company_domain"] == "acme"
        assert captured["api_token"] == "test_token_12345"
        # path fully substituted
        expected = spec["path"]
        for p in spec.get("path_params", []):
            expected = expected.replace("{" + p + "}", "999")
        assert captured["endpoint"] == expected, spec["operation"]
        assert "{" not in captured["endpoint"], f"unsubstituted param in {spec['operation']}"
        # raw-array-body ops send a JSON list, not a {field: value} object
        from nodes.pipedrive_node import _RAW_ARRAY_BODY
        if spec["operation"] in _RAW_ARRAY_BODY:
            assert isinstance(captured["json_body"], list), spec["operation"]
        else:
            # required body fields present
            body = captured["json_body"] or {}
            for bf in spec.get("body", []):
                api, required, _ftype, _desc = bf
                if required:
                    assert api in body, f"{spec['operation']} missing required body {api}"


# ============================================================================
# Dispatch details: version routing, coercion, dual auth
# ============================================================================


class TestPipedriveDispatchDetails:
    @pytest.mark.asyncio
    async def test_v2_create_deal(self, credentials):
        node = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "create_deal", "title": "Big deal"}, credentials=credentials))
        result = await _run(node, 201, _envelope({"id": 5, "title": "Big deal"}))
        assert result["status"] == "success" and result["action"] == "create_deal"
        assert result["data"]["id"] == 5

    @pytest.mark.asyncio
    async def test_integer_and_object_body_coercion(self, credentials):
        captured = {}

        async def fake_request(company_domain, api_token, method, endpoint, version="v2",
                               params=None, json_body=None, action_name="request", auth_bearer=False):
            captured["body"] = json_body
            return {"status": "success", "action": action_name, "data": {}}

        node = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "create_deal", "title": "D", "value": "1000",
                    "person_id": "42", "custom_fields": '{"hash123": "x"}'},
            credentials=credentials))
        with patch("nodes.pipedrive_node._pipedrive_request", fake_request):
            await node.execute({})
        assert captured["body"]["value"] == 1000.0            # number
        assert captured["body"]["person_id"] == 42            # integer
        assert captured["body"]["custom_fields"] == {"hash123": "x"}  # object

    @pytest.mark.asyncio
    async def test_query_params_passthrough(self, credentials):
        captured = {}

        async def fake_request(company_domain, api_token, method, endpoint, version="v2",
                               params=None, json_body=None, action_name="request", auth_bearer=False):
            captured["params"] = params
            return {"status": "success", "action": action_name, "data": {}}

        node = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "list_deals", "status": "won", "limit": "50"}, credentials=credentials))
        with patch("nodes.pipedrive_node._pipedrive_request", fake_request):
            await node.execute({})
        assert captured["params"]["status"] == "won"
        assert captured["params"]["limit"] == "50"

    @pytest.mark.asyncio
    async def test_oauth_uses_bearer_and_api_domain(self):
        captured = {}

        async def fake_request(company_domain, api_token, method, endpoint, version="v2",
                               params=None, json_body=None, action_name="request", auth_bearer=False):
            captured.update(company_domain=company_domain, api_token=api_token, auth_bearer=auth_bearer)
            return {"status": "success", "action": action_name, "data": {}}

        oauth = PipedriveOAuthCredential(access_token="oauth_abc", api_domain="https://acme.pipedrive.com")
        node = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "get_deal", "deal_id": "7"}, credentials=oauth))
        with patch("nodes.pipedrive_node._pipedrive_request", fake_request):
            await node.execute({})
        assert captured["auth_bearer"] is True
        assert captured["api_token"] == "oauth_abc"
        assert captured["company_domain"] == "https://acme.pipedrive.com"

    @pytest.mark.asyncio
    async def test_one_of_required_preflight(self, credentials):
        # create_lead needs person_id OR organization_id — clear error, no API call
        node = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "create_lead", "title": "x"}, credentials=credentials))
        called = {"n": 0}

        async def fake(*a, **k):
            called["n"] += 1
            return {"status": "success", "action": "create_lead", "data": {}}

        with patch("nodes.pipedrive_node._pipedrive_request", fake):
            with pytest.raises(ValueError, match="at least one of: person_id, organization_id"):
                await node.execute({})
        assert called["n"] == 0  # never hit the API
        # with a person_id it dispatches
        node2 = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "create_lead", "title": "x", "person_id": "5"}, credentials=credentials))
        with patch("nodes.pipedrive_node._pipedrive_request", fake):
            await node2.execute({})
        assert called["n"] == 1

    def test_required_query_enforced(self, credentials):
        # search ops require `term` — config validation must reject it missing
        with pytest.raises(Exception):
            PipedriveNodeConfig(config={"operation": "search_deals"}, credentials=credentials)
        # present -> valid
        PipedriveNodeConfig(config={"operation": "search_deals", "term": "acme"}, credentials=credentials)

    @pytest.mark.asyncio
    async def test_missing_required_path_param_rejected(self, credentials):
        with pytest.raises(Exception):
            PipedriveNodeConfig(config={"operation": "get_deal"}, credentials=credentials)


# ============================================================================
# Webhook trigger + HTTP Basic-auth verification (the fix)
# ============================================================================


class TestPipedriveTrigger:
    def test_triggers_decomposed_per_event(self):
        # 10 objects x 3 actions + 1 wildcard = 31 distinct trigger operations
        assert len(_TRIGGER_EVENTS) == 31
        assert len(_TRIGGER_MODELS) == 31
        assert _TRIGGER_EVENTS["on_deal_created"] == ("deal", "create")
        assert _TRIGGER_EVENTS["on_person_changed"] == ("person", "change")
        assert _TRIGGER_EVENTS["on_product_deleted"] == ("product", "delete")
        assert _TRIGGER_EVENTS["on_pipedrive_any_event"] == ("*", "*")
        # every trigger model has no event-selection field (fixed by operation)
        for op, model in _TRIGGER_MODELS.items():
            assert "event_types" not in model.model_fields, op

    @pytest.mark.asyncio
    async def test_trigger_passthrough(self):
        node = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "on_deal_created", "webhook_url": "https://x.hooks.example.test"},
            credentials=None))
        result = await node.execute({"meta": {"entity": "deal", "action": "create"}, "data": {"id": 1}})
        assert result["status"] == "success" and result["action"] == "on_deal_created"
        assert result["data"]["data"]["id"] == 1

    @pytest.mark.asyncio
    async def test_register_provisions_basic_auth(self):
        captured = {}

        async def fake_request(company_domain, api_token, method, endpoint, version="v2",
                               params=None, json_body=None, action_name="request", auth_bearer=False):
            captured["body"] = json_body
            return {"status": "success", "data": {"id": 777}}

        with patch("nodes.pipedrive_node._pipedrive_request", fake_request):
            extra = await PipedriveNode._register_external_webhook(
                webhook_url="https://x.hooks.example.test",
                credential={"company_domain": "acme", "api_token": "t"},
                config={"operation": "on_deal_created"},
                node_id="node-1234abcd",
            )
        # Subscribes to exactly this trigger's (object, action) + HTTP Basic auth
        assert captured["body"]["http_auth_user"] == "noclick"
        assert captured["body"]["http_auth_password"]
        assert captured["body"]["version"] == "2.0"
        assert captured["body"]["event_object"] == "deal"
        assert captured["body"]["event_action"] == "create"
        assert extra["external_webhook_id"] == "777"
        assert extra["signing_secret"] == f"noclick:{captured['body']['http_auth_password']}"

    @pytest.mark.asyncio
    async def test_any_event_registers_wildcard(self):
        captured = {}

        async def fake_request(company_domain, api_token, method, endpoint, version="v2",
                               params=None, json_body=None, action_name="request", auth_bearer=False):
            captured["body"] = json_body
            return {"status": "success", "data": {"id": 1}}

        with patch("nodes.pipedrive_node._pipedrive_request", fake_request):
            await PipedriveNode._register_external_webhook(
                webhook_url="https://x.hooks.example.test",
                credential={"company_domain": "acme", "api_token": "t"},
                config={"operation": "on_pipedrive_any_event"},
                node_id="n1",
            )
        assert captured["body"]["event_object"] == "*"
        assert captured["body"]["event_action"] == "*"

    def test_verify_basic_auth_signature(self):
        secret = "noclick:s3cret"
        good = "Basic " + base64.b64encode(secret.encode()).decode()
        bad = "Basic " + base64.b64encode(b"noclick:wrong").decode()
        assert PipedriveNode.verify_webhook_signature(b"{}", {"authorization": good}, {"signing_secret": secret})
        assert not PipedriveNode.verify_webhook_signature(b"{}", {"authorization": bad}, {"signing_secret": secret})
        assert not PipedriveNode.verify_webhook_signature(b"{}", {}, {"signing_secret": secret})
        # no secret stored yet -> accept (trigger not armed)
        assert PipedriveNode.verify_webhook_signature(b"{}", {}, {})

    def test_filter_trigger_payload_v1_and_v2(self):
        cfg = {"operation": "on_deal_created"}
        # v2 payload vocab
        assert PipedriveNode.filter_trigger_payload({"meta": {"entity": "deal", "action": "create"}}, cfg)
        # v1 payload vocab (added -> create)
        assert PipedriveNode.filter_trigger_payload({"meta": {"object": "deal", "action": "added"}}, cfg)
        # wrong object
        assert not PipedriveNode.filter_trigger_payload({"meta": {"entity": "person", "action": "create"}}, cfg)
        # wrong action
        assert not PipedriveNode.filter_trigger_payload({"meta": {"entity": "deal", "action": "delete"}}, cfg)
        # the any-event trigger passes everything
        assert PipedriveNode.filter_trigger_payload(
            {"meta": {"entity": "note", "action": "delete"}}, {"operation": "on_pipedrive_any_event"})

    @pytest.mark.asyncio
    async def test_unregister(self):
        with patch("nodes.pipedrive_node._pipedrive_request",
                   return_value={"status": "success", "data": {}}) as mock_req:
            await PipedriveNode._unregister_external_webhook(
                credential={"company_domain": "acme", "api_token": "t"},
                config={"external_webhook_id": "777"}, node_id="n1")
        assert mock_req.called


class TestPipedriveErrorsAndOptions:
    @pytest.mark.asyncio
    async def test_api_error(self, credentials):
        node = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "get_deal", "deal_id": "404"}, credentials=credentials))
        result = await _run(node, 404, {"success": False, "error": "Deal not found"})
        assert result["status"] == "error" and result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        node = create_pipedrive_node(PipedriveNodeConfig(
            config={"operation": "list_deals"}, credentials=None))
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_dynamic_pipeline_options(self):
        # Canonical dropdown contract: (field_name, credential_data, context, ...).
        # credential_data arrives already decrypted + freshened by the handler.
        with patch("nodes.pipedrive_node._pipedrive_request",
                   return_value={"status": "success", "data": [{"id": 1, "name": "Sales"}, {"id": 2, "name": "Support"}]}):
            result = await PipedriveNode.load_field_options(
                "pipeline_id", {"company_domain": "acme", "api_token": "t"}, context={})
        assert result["options"][0] == {"label": "Sales", "value": "1"}

    def test_dynamic_loader_coverage(self):
        from nodes.pipedrive_node import _DYNAMIC_LOADERS
        for f in ("pipeline_id", "stage_id", "owner_id", "user_id", "person_id",
                  "org_id", "organization_id", "deal_id", "filter_id"):
            assert f in _DYNAMIC_LOADERS, f

    def test_static_enums_present_in_schema(self):
        import json, inspect, os
        from nodes.pipedrive_node import PipedriveNode
        schema = PipedriveNode.get_config_schema()
        blob = json.dumps(schema)
        # filter type + deal status enums rendered as searchable dropdowns
        assert '"deals"' in blob and '"leads"' in blob   # add_filter type enum
        assert '"won"' in blob and '"lost"' in blob        # deal status enum
        assert "x-enum-searchable" in blob

    @pytest.mark.asyncio
    async def test_search_short_term_falls_back_to_list(self):
        calls = []

        async def fake_request(base, token, method, endpoint, version="v2", params=None,
                               json_body=None, action_name="request", auth_bearer=False):
            calls.append(endpoint)
            return {"status": "success", "data": [{"id": 1, "name": "X"}]}

        with patch("nodes.pipedrive_node._pipedrive_request", fake_request):
            # 1-char search must NOT hit /persons/search (min 2 chars) -> lists instead
            await PipedriveNode.load_field_options(
                "person_id", {"company_domain": "acme", "api_token": "t"}, context={}, search="A")
        assert calls == ["/persons"], calls

    @pytest.mark.asyncio
    async def test_dynamic_options_signature_matches_handler(self):
        """Guard against the signature regressing to the non-canonical form that
        broke dropdowns in the UI (handler calls with keyword args)."""
        import inspect
        params = list(inspect.signature(PipedriveNode.load_field_options).parameters)
        assert params[:3] == ["field_name", "credential_data", "context"], params

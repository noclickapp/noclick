"""
Mock tests for the GoHighLevel (LeadConnector) REST API v2 node.

Exercises operations with mocked HTTP responses (no live API calls), the request
layer (auth + Version header + error shape), and registry integrity across the
full generated op set.
"""

import typing

import pytest
from unittest.mock import Mock, patch

from nodes.gohighlevel_node import (
    GoHighLevelNode,
    GoHighLevelNodeConfig,
    GoHighLevelConfig,
    GoHighLevelPitCredential,
    GHL_OPERATION_CONFIGS,
    GHL_OPERATION_HANDLERS,
    GHL_DEFAULT_VERSION,
)


@pytest.fixture
def credentials():
    return GoHighLevelPitCredential(token="pit-test-secret-123")


def create_ghl_node(config):
    return GoHighLevelNode(
        node_id="test-ghl-node",
        node_type="automation-gohighlevel",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None, content=b"{}"):
    r = Mock()
    r.status_code = status_code
    r.text = ""
    r.content = content
    r.json = lambda: (json_data if json_data is not None else {})
    return r


def create_mock_client(status_code=200, json_data=None, capture=None):
    resp = create_mock_response(status_code, json_data)
    client = Mock()

    async def async_request(*args, **kwargs):
        if capture is not None:
            capture.update(kwargs)
        return resp

    client.request = async_request

    async def aenter(self):
        return client

    async def aexit(self, *a):
        return None

    client.__aenter__ = aenter
    client.__aexit__ = aexit
    return client


def _configs():
    return typing.get_args(typing.get_args(GoHighLevelConfig)[0])


def _op_names():
    return [c.model_fields["operation"].default for c in _configs()]


async def _run(config_obj, creds, status_code=200, json_data=None, capture=None):
    config = GoHighLevelNodeConfig(config=config_obj, credentials=creds)
    node = create_ghl_node(config)
    client = create_mock_client(status_code, json_data, capture)
    with patch("nodes.gohighlevel_node.httpx.AsyncClient", return_value=client):
        return await node.execute({})


# ============================================================================
# Request layer
# ============================================================================


class TestGHLRequestLayer:
    async def test_auth_and_version_headers(self, credentials):
        cap = {}
        result = await _run(
            _cfg("get_business", business_id="b1"), credentials,
            200, {"business": {"id": "b1"}}, capture=cap,
        )
        assert result["status"] == "success"
        assert cap["headers"]["Authorization"] == "Bearer pit-test-secret-123"
        assert cap["headers"]["Version"] == GHL_DEFAULT_VERSION
        assert cap["url"].startswith("https://services.leadconnectorhq.com")

    async def test_error_shape(self, credentials):
        result = await _run(
            _cfg("get_business", business_id="b1"), credentials,
            401, {"statusCode": 401, "message": "Invalid token", "error": "Unauthorized"},
        )
        assert result["status"] == "error"
        assert result["status_code"] == 401
        assert "Invalid token" in result["error"]

    async def test_error_message_list(self, credentials):
        result = await _run(
            _cfg("create_business", name="x", location_id="L1"), credentials,
            422, {"statusCode": 422, "message": ["name should not be empty", "bad email"]},
        )
        assert result["status"] == "error"
        assert "name should not be empty" in result["error"]


def _cfg(op_name, **kw):
    cls = {c.model_fields["operation"].default: c for c in _configs()}[op_name]
    return cls(**kw)


# ============================================================================
# Businesses (gold-standard block)
# ============================================================================


class TestGHLBusinesses:
    async def test_create_business_body(self, credentials):
        cap = {}
        result = await _run(
            _cfg("create_business", name="Acme", location_id="L1", email="a@x.com"),
            credentials, 201, {"business": {"id": "b1"}}, capture=cap,
        )
        assert result["status"] == "success"
        body = cap["json"]
        assert body["name"] == "Acme"
        assert body["locationId"] == "L1"
        assert body["email"] == "a@x.com"
        # None fields stripped
        assert "phone" not in body

    async def test_list_businesses_query(self, credentials):
        cap = {}
        await _run(_cfg("get_businesses_by_location", location_id="L1", limit="10"),
                   credentials, 200, {"businesses": []}, capture=cap)
        assert cap["params"]["locationId"] == "L1"
        assert cap["params"]["limit"] == "10"

    async def test_delete_business(self, credentials):
        result = await _run(_cfg("delete_business", business_id="b1"), credentials, 200, {"success": True})
        assert result["status"] == "success"
        assert result["action"] == "delete_business"


# ============================================================================
# Registry integrity
# ============================================================================


class TestGHLRegistryIntegrity:
    def test_operation_names_unique(self):
        ops = _op_names()
        assert len(set(ops)) == len(ops), "duplicate operation discriminators"

    def test_config_class_names_unique(self):
        names = [c.__name__ for c in _configs()]
        assert len(set(names)) == len(names), "duplicate config class names"

    def test_every_action_op_has_a_handler(self):
        """Every action op dispatches via the registry; trigger ops (x-is-trigger)
        are handled specially in execute() and are exempt."""
        for c in _configs():
            extra = c.model_fields["operation"].json_schema_extra or {}
            op = c.model_fields["operation"].default
            if extra.get("x-is-trigger"):
                continue
            assert op in GHL_OPERATION_HANDLERS, f"operation {op} has no handler"

    def test_registry_balanced(self):
        assert len(GHL_OPERATION_CONFIGS) == len(GHL_OPERATION_HANDLERS)

    def test_handler_signature(self):
        import inspect
        for op, fn in list(GHL_OPERATION_HANDLERS.items())[:50]:
            params = list(inspect.signature(fn).parameters)
            assert params[:3] == ["node", "c", "token"], (op, params)

    def test_config_schema_builds(self):
        schema = GoHighLevelNode.get_config_schema()
        assert isinstance(schema, dict) and schema

    def test_full_coverage_size(self):
        """Full v2 API coverage — 500+ operations across ~40 resource groups."""
        assert len(GHL_OPERATION_CONFIGS) > 500
        assert len(_op_names()) > 500

    def test_representative_ops_present(self):
        ops = set(_op_names())
        for expected in [
            "add_contact_tags", "add_contact_to_workflow", "create_opportunity",
            "get_opportunity_pipelines", "create_appointment", "get_appointment",
            "create_calendar", "get_surveys", "create_invoice", "list_orders",
            "create_product", "get_forms", "create_object_record",
            "search_object_records", "create_custom_object_schema", "create_location",
            "get_user_by_location", "send_a_new_message",
        ]:
            assert expected in ops, f"missing expected op {expected}"


# ============================================================================
# Webhook trigger
# ============================================================================


class TestGHLWebhookTrigger:
    async def test_webhook_trigger_passthrough(self, credentials):
        """The on_webhook trigger passes the inbound payload through."""
        from nodes.gohighlevel_node import GHLOnWebhookConfig
        config = GoHighLevelNodeConfig(
            config=GHLOnWebhookConfig(webhook_url="https://abc.hooks.example.test"),
            credentials=None,
        )
        node = create_ghl_node(config)
        payload = {"type": "ContactCreate", "contactId": "c1"}
        result = await node.execute(payload)
        assert result["status"] == "success"
        assert result["action"] == "on_webhook"
        assert result["data"]["contactId"] == "c1"

    def test_trigger_is_marked(self):
        from nodes.gohighlevel_node import GHLOnWebhookConfig
        extra = GHLOnWebhookConfig.model_fields["operation"].json_schema_extra
        assert extra.get("x-is-trigger") is True
        assert GHLOnWebhookConfig.model_config.get("json_schema_extra", {}).get("x-requires-webhook") is True

    def test_decomposed_triggers_present(self):
        """One trigger per HighLevel webhook event type + a catch-all."""
        from nodes.gohighlevel_node import GHL_TRIGGER_CONFIGS, _GHL_TRIGGER_EVENT_BY_OP
        assert len(GHL_TRIGGER_CONFIGS) >= 70
        ops = set(_op_names())
        for expected in [
            "on_contact_create", "on_contact_tag_update", "on_inbound_message",
            "on_opportunity_status_update", "on_appointment_create", "on_task_complete",
            "on_invoice_paid", "on_order_status_update", "on_record_create", "on_webhook",
        ]:
            assert expected in ops, f"missing trigger {expected}"
        # every event trigger is x-is-trigger + x-requires-webhook
        for c in GHL_TRIGGER_CONFIGS:
            op = c.model_fields["operation"].default
            assert c.model_fields["operation"].json_schema_extra.get("x-is-trigger") is True
            assert op in _GHL_TRIGGER_EVENT_BY_OP
            assert c.model_config.get("json_schema_extra", {}).get("x-requires-webhook") is True

    def test_type_filter(self):
        """A per-event trigger drops non-matching marketplace webhooks, passes
        matching ones, and passes typeless workflow-webhook deliveries."""
        r = GoHighLevelNode.resolve_trigger_payload
        assert r({"type": "ContactCreate"}, {"operation": "on_contact_create"}) is not None
        assert r({"type": "OpportunityCreate"}, {"operation": "on_contact_create"}) is None
        assert r({"contactId": "c1"}, {"operation": "on_contact_create"}) is not None  # no type
        assert r({"type": "Anything"}, {"operation": "on_webhook"}) is not None  # catch-all
        assert r({"x": 1}, {"operation": "create_contact"}) == {"x": 1}  # non-trigger

    async def test_event_trigger_action_name(self, credentials):
        from nodes.gohighlevel_node import GHL_TRIGGER_CONFIGS
        cls = {c.model_fields["operation"].default: c for c in GHL_TRIGGER_CONFIGS}["on_invoice_paid"]
        config = GoHighLevelNodeConfig(config=cls(webhook_url="https://x.hooks.example.test"), credentials=None)
        node = create_ghl_node(config)
        result = await node.execute({"type": "InvoicePaid", "_id": "inv1"})
        assert result["status"] == "success"
        assert result["action"] == "on_invoice_paid"
        assert result["data"]["_id"] == "inv1"

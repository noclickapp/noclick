"""Regression test for the webhook auto-provisioning schema-resolution bug.

update_workflow auto-mints a trigger's webhook_url. For a node added WITHOUT an
explicit operation, the code path derives the schema from get_config_schema() and
must resolve $refs before checking for the ui:widget="webhook" field — a single-
config trigger's `config` is a $ref to its $def, so the UNRESOLVED schema hides the
webhook field and provisioning is silently skipped (webhook_url stays None).

This pins the invariant the fix (resolve_schema_refs) relies on.
"""
from nodes.core.registry import NODE_REGISTRY
from utils.webhook_manager import WebhookManager
from coder.workflow.workflow_schema import resolve_schema_refs


def _config_schema(node_type, *, resolved):
    full = NODE_REGISTRY[node_type].get_config_schema()
    if resolved:
        full = resolve_schema_refs(full)
    return full.get("properties", {}).get("config", full)


def test_unresolved_schema_misses_webhook_field():
    # The bug: without resolving $refs the webhook field is invisible.
    raw = _config_schema("trigger-webhook", resolved=False)
    assert WebhookManager.schema_requires_webhook(raw) is False
    assert WebhookManager.get_webhook_field(raw) is None


def test_resolved_schema_detects_webhook_field():
    # The fix: resolving $refs surfaces the ui:widget="webhook" field.
    res = _config_schema("trigger-webhook", resolved=True)
    assert WebhookManager.schema_requires_webhook(res) is True
    assert WebhookManager.get_webhook_field(res) == "webhook_url"

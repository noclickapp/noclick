"""An operation's catalog markers live on its ``operation`` Field, where every reader looks.

The operation catalog (``operation_catalog.get_operations_for_node_type``), the agent-tool filters
(``node_op_tools.is_trigger_operation``), the generated catalog and the frontend read ``x-is-trigger``,
``x-display-name`` and ``x-category`` off the operation discriminator's ``json_schema_extra``. Set on the config
class (``model_config``) they reach the JSON schema but none of those readers: MightyCall's two poll triggers read
as ordinary operations (agent-tool allowlists offered them, the Debug tab derived no trigger cell) and Printify's
operations lost their names and groups.

``x-requires-webhook`` is not one of them: ``WebhookManager.schema_requires_webhook`` reads it on the class, where
the trigger config bases declare it.
"""

import functools
import inspect
import os

import pytest

from coder.workflow.operation_catalog import get_operations_for_node_type
from nodes.core.poll_trigger import PollTriggerConfigBase
from nodes.core.registry import NODE_REGISTRY
from nodes.core.webhook_subscriptions import AppEventTriggerMixin
from nodes.core.webhook_trigger import WebhookTriggerConfigBase
from utils.webhook_manager import fires_on_schedule

pytestmark = pytest.mark.every_integration

FIELD_MARKERS = ("x-is-trigger", "x-display-name", "x-category")

# Nodes that still set FIELD_MARKERS on their operation classes, every one ``x-is-trigger: False`` (no trigger
# hides there; their names and groups don't reach the catalog). Only shrink.
_CLASS_MARKED_ALLOWED = frozenset({
    "automation-cliniko", "automation-cyclr", "automation-landbot", "automation-oracle-hcm",
    "automation-signalwire", "automation-sling", "automation-veryfi",
})

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(node_type):
    return os.path.relpath(inspect.getsourcefile(NODE_REGISTRY[node_type]), _BACKEND)


@functools.cache
def _class_marked():
    """{node type: sorted "operation: markers"} for operation classes whose schema carries FIELD_MARKERS at its top
    level, from the member schemas the readers walk (config → $defs)."""
    found = {}
    for node_type, node_cls in NODE_REGISTRY.items():
        schema = node_cls.get_config_schema() or {}
        config = schema.get("properties", {}).get("config", {})
        defs = schema.get("$defs", {})
        refs = config.get("oneOf") or config.get("anyOf") or ([config] if "$ref" in config else [])
        for ref in refs:
            member = defs.get(ref.get("$ref", "").split("/")[-1]) or {}
            op = member.get("properties", {}).get("operation", {})
            name = op.get("const") or (op.get("enum") or [None])[0]
            markers = [m for m in FIELD_MARKERS if m in member]
            if name and markers:
                found.setdefault(node_type, []).append(f"{name}: {', '.join(markers)}")
    return {node_type: sorted(ops) for node_type, ops in found.items()}


def test_no_operation_class_carries_the_operation_fields_markers():
    wrong = {t: ops for t, ops in _class_marked().items() if t not in _CLASS_MARKED_ALLOWED}
    assert not wrong, (
        "Operation classes carrying operation markers in model_config, where no reader looks. Move them onto the "
        "class's `operation` Field's json_schema_extra:\n"
        + "\n".join(f"  {_source(t)} ({t}): {'; '.join(ops)}" for t, ops in sorted(wrong.items()))
    )


def test_class_marked_allowlist_only_shrinks():
    fixed = sorted(_CLASS_MARKED_ALLOWED - set(_class_marked()))
    assert not fixed, f"Now marked on their fields; remove from _CLASS_MARKED_ALLOWED: {fixed}"


def test_every_trigger_operation_marks_its_operation_field():
    """An operation NoClick fires runs from (a poll or schedule trigger, an app event) marks ``x-is-trigger: True``
    on its Field; one with its own webhook registration states it there either way (Telegram's guided channel
    setup registers the bot's webhook and is no trigger)."""
    wrong = []
    for node_type, node_cls in sorted(NODE_REGISTRY.items()):
        app_event = isinstance(node_cls, type) and issubclass(node_cls, AppEventTriggerMixin)
        app_events = node_cls._trigger_event_map if app_event else {}
        for op in get_operations_for_node_type(node_type):
            cls = op.config_class if isinstance(op.config_class, type) else None
            field = cls.model_fields.get("operation") if cls else None
            if field is None:
                continue
            stated = "x-is-trigger" in (field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {})
            fires = issubclass(cls, PollTriggerConfigBase) or fires_on_schedule(node_type, op.name) or bool(
                app_events.get(op.name))
            if (fires and not op.is_trigger) or (issubclass(cls, WebhookTriggerConfigBase) and not stated):
                wrong.append(f"  {_source(node_type)} ({node_type}): {op.name}")
    assert not wrong, "Trigger operations whose `operation` Field doesn't mark x-is-trigger:\n" + "\n".join(wrong)


def test_mightycalls_triggers_read_as_triggers_and_still_register():
    from nodes.agent.node_op_tools import is_trigger_operation
    from utils.webhook_manager import WebhookManager

    node_type = "automation-mightycall"
    triggers = {op.name for op in get_operations_for_node_type(node_type) if op.is_trigger}
    assert triggers == {"on_new_call", "on_new_voicemail"}
    for op in triggers:
        assert is_trigger_operation(node_type, op)
        assert WebhookManager.operation_requires_webhook(node_type, op)
        assert fires_on_schedule(node_type, op)
    assert not WebhookManager.operation_requires_webhook(node_type, "list_calls")

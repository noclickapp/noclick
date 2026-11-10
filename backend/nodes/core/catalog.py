"""Facts about every node type, read without importing its integration.

Each registered type has a generated file, ``nodes/catalog/<type without "automation-">.json``
(``scripts/generate_socket_types.py``), holding:
- its canvas definition's words: ``label``, ``description``, ``category``, ``keywords``
  (``scripts/node_definitions.py``);
- its credential methods, in the order its config accepts them: ``type``, ``title``,
  ``oauth_provider``, ``method`` (``x-credential-type``), ``hidden`` and whether the
  schema ``pinned`` the type as a constant;
- its operations, as ``coder.workflow.operation_catalog.get_operations_for_node_type``
  lists them: ``name``, ``display_name``, ``category``, ``description``, ``is_trigger``;
- ``agent_tool_provider`` (``node_op_tools.node_supports_op_tools``), ``credentialed`` (its config
  takes a credential), ``output_handles``, ``registers`` (a step can hold a webhook, subscription or
  schedule registration) and its ``app_event_provider``.

A lookup that needs a fact about every type reads these instead of walking
NODE_REGISTRY's classes, which imports every integration: ~25 s of CPU and ~1 GB in
the process that does it. A type without a file (an integration merged before its
file was generated) is read from its class and logged, so it costs that type's
import, never a wrong answer. ``tests/test_node_catalog.py`` holds every file equal
to what its class and definition give. Callers share the dicts: never mutate them.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"


def catalog_path(node_type: str, directory: Path = CATALOG_DIR) -> Path:
    return directory / f"{node_type.removeprefix('automation-')}.json"


def class_facts(node_type: str, node_class: Any) -> Dict[str, Any]:
    """The facts ``node_class`` itself gives: credential methods, operations, tool-provider flag."""
    from coder.workflow.operation_catalog import get_operations_for_node_type
    from nodes.agent.node_op_tools import node_supports_op_tools
    from nodes.core.credential_connect import credential_classes_for_node, credential_type_of
    from nodes.core.schedule_registration import CronScheduleTriggerMixin
    from nodes.core.webhook_subscriptions import AppEventTriggerMixin
    from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin

    schema = node_class.get_config_schema() or {}
    defs = schema.get("$defs", {})
    # A real credential class renders ``credentials`` as a $ref/anyOf; a credential-less node as "type": "null".
    credentials_property = (schema.get("properties", {}) or {}).get("credentials") or {}
    pinned = {
        definition.get("properties", {}).get("credential_type", {}).get("const")
        for definition in defs.values()
    }
    credentials = []
    for credential_class in credential_classes_for_node(node_class):
        credential_type = credential_type_of(credential_class)
        if not credential_type:
            continue
        credential_schema = credential_class.model_json_schema()
        credential = {
            "type": credential_type,
            "title": credential_schema.get("title"),
            "oauth_provider": credential_schema.get("x-oauth-provider"),
            "method": credential_schema.get("x-credential-type"),
            "hidden": bool(credential_schema.get("x-credential-hidden")),
            "pinned": credential_type in pinned,
        }
        if getattr(credential_class, "linked_fields", ()):
            credential["linked_fields"] = list(credential_class.linked_fields)
        credentials.append(credential)
    return {
        "credentials": credentials,
        "operations": [
            {
                "name": op.name,
                "display_name": op.display_name,
                "category": op.category,
                "description": op.description,
                "is_trigger": op.is_trigger,
            }
            for op in get_operations_for_node_type(node_type)
        ],
        "agent_tool_provider": node_supports_op_tools(node_type),
        "credentialed": bool(isinstance(credentials_property, dict)
                             and (credentials_property.get("$ref") or credentials_property.get("anyOf"))),
        "output_handles": [dict(handle) for handle in node_class.get_output_handles() or ()],
        # A step of this type can hold a registration (WebhookManager reconciles it).
        "registers": bool(
            issubclass(node_class, (ExternalWebhookTriggerMixin, AppEventTriggerMixin, CronScheduleTriggerMixin))
            or getattr(node_class, "self_registering_triggers", None)
        ),
        "app_event_provider": node_class._app_provider if issubclass(node_class, AppEventTriggerMixin) else None,
    }


@lru_cache(maxsize=None)
def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def node_facts(node_type: str) -> Dict[str, Any]:
    """``node_type``'s facts (its canonical type), from its file."""
    from nodes.core.registry import NODE_REGISTRY

    facts = _read(catalog_path(node_type))
    if facts is not None:
        return facts
    logger.error("[catalog] %s has no catalog file; reading its class (run scripts/generate_socket_types.py)",
                 node_type)
    return {"type": node_type, **class_facts(node_type, NODE_REGISTRY[node_type])}


def every_node_facts() -> Dict[str, Dict[str, Any]]:
    """Every registered type's facts, in registry order."""
    from nodes.core.registry import NODE_REGISTRY

    return {node_type: node_facts(node_type) for node_type in NODE_REGISTRY}


@lru_cache(maxsize=4)
def _credential_index(node_types: Tuple[str, ...]) -> Dict[str, Tuple[Tuple[str, Dict[str, Any]], ...]]:
    index: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
    for node_type in node_types:
        for credential in node_facts(node_type)["credentials"]:
            index.setdefault(credential["type"], []).append((node_type, credential))
    return {credential_type: tuple(holders) for credential_type, holders in index.items()}


def credential_holders(credential_type: Optional[str]) -> Tuple[Tuple[str, Dict[str, Any]], ...]:
    """``(node type, its credential method)`` for each type whose config accepts ``credential_type``, in
    registry order."""
    from nodes.core.registry import NODE_REGISTRY

    return _credential_index(tuple(NODE_REGISTRY)).get(credential_type or "", ())


def credential_types() -> Tuple[str, ...]:
    """Every credential type any node accepts, in registry order."""
    from nodes.core.registry import NODE_REGISTRY

    return tuple(_credential_index(tuple(NODE_REGISTRY)))

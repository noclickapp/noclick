"""Facts about every node type, read without importing its integration.

Each registered type has a generated file, ``nodes/catalog/<type without "automation-">.json``
(``scripts/generate_socket_types.py``), holding:
- its canvas definition's words: ``label``, ``description``, ``category``, ``keywords``
  (``scripts/node_definitions.py``);
- its credential methods, in the order its config accepts them: ``type``, ``title``,
  ``oauth_provider``, ``method`` (``x-credential-type``), ``hidden``, whether the
  schema ``pinned`` the type as a constant, and whether the node ``borrowed`` it from
  the type's owner (``borrowed_credential_types``);
- its operations, as ``coder.workflow.operation_catalog.get_operations_for_node_type``
  lists them: ``name``, ``display_name``, ``category``, ``description``, ``is_trigger``;
  ``needs_account``, false where it runs with no credential (the node takes none, or its schema
  says so: ``run_op.declares_no_account``, on NoClick's keys); and on each push trigger its schema
  offers (an app event, not a poll), ``registered_with``: the node's credential types NoClick
  registers it with by itself (``WebhookManager.registers_itself``), none where its provider is
  pointed at a URL by hand, and its ``event``: the ``description`` an agent reads of it and the
  ``filters`` narrowing it (each field it can be narrowed by -> what it matches; ``required``, those
  it must be), so an event catalog lists every integration's events without importing one;
- ``agent_tool_provider`` (``node_op_tools.node_supports_op_tools``), ``credentialed`` (its config
  takes a credential), ``output_handles``, ``registers`` (a step can hold a webhook, subscription or
  schedule registration) and its ``app_event_provider``;
- ``summary``, its class docstring's first line (what the node search reads of it), and ``retired``,
  its ``Retirement`` while its service is gone (``registry.is_listed``).

A lookup that needs a fact about every type reads these instead of walking
NODE_REGISTRY's classes, which imports every integration: ~25 s of CPU and ~1 GB in
the process that does it. A type without a file (an integration merged before its
file was generated), or with one written before a fact was added, is read from its
class and logged once, so it costs that type's import, never a wrong answer.
``tests/test_node_catalog.py`` holds every file equal to what its class and
definition give. Callers share the dicts: never mutate them.
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


# The keys ``class_facts`` gives, and each of its operations has: a file without one of them predates it.
CLASS_FACTS = frozenset({"credentials", "operations", "agent_tool_provider", "credentialed", "output_handles",
                         "registers", "app_event_provider", "summary", "retired"})
OPERATION_FACTS = frozenset({"name", "display_name", "category", "description", "is_trigger", "needs_account"})
# A push trigger's ``event``, beside its ``registered_with``.
EVENT_FACTS = frozenset({"description", "filters", "required"})
# Fields of a trigger operation that are its own plumbing, not something to narrow it by.
_LIFECYCLE_WIDGETS = frozenset({"webhook", "subscription_status", "readonly", "nextRun", "password"})


def class_facts(node_type: str, node_class: Any) -> Dict[str, Any]:
    """The facts ``node_class`` itself gives: credential methods, operations, tool-provider flag."""
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
            "borrowed": credential_type in node_class.borrowed_credential_types,
        }
        if getattr(credential_class, "linked_fields", ()):
            credential["linked_fields"] = list(credential_class.linked_fields)
        credentials.append(credential)
    return {
        "credentials": credentials,
        "operations": _operation_facts(node_type, node_class, [credential["type"] for credential in credentials]),
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
        "summary": _summary(node_class),
        "retired": node_class.retired.as_json() if node_class.retired else None,
    }


def _operation_facts(node_type: str, node_class: Any, credential_types: List[str]) -> List[Dict[str, Any]]:
    """Each operation's facts (the module's docstring), in ``get_operations_for_node_type``'s order."""
    from coder.workflow.operation_catalog import get_operations_for_node_type
    from nodes.agent.node_op_tools import _iter_operation_defs
    from nodes.core.credential_connect import credential_classes_for_node
    from nodes.core.run_op import declares_no_account
    from nodes.core.schedule_registration import CronScheduleTriggerMixin
    from utils.webhook_manager import WebhookManager

    takes_account = bool(credential_classes_for_node(node_class))
    # Each operation's member of the node's schema, which carries its markers; one with no operation const has none.
    members = {entry["operation"]: entry["member"] for entry in _iter_operation_defs(node_class)}
    # A trigger the schema leaves out (Google Calendar's legacy one, kept runnable for saved steps) is no event.
    triggers = {entry["operation"]: entry["member"] for entry in _iter_operation_defs(node_class, triggers=True)}
    polls = node_class if issubclass(node_class, CronScheduleTriggerMixin) else None
    out = []
    for op in get_operations_for_node_type(node_type):
        facts = {
            "name": op.name,
            "display_name": op.display_name,
            "category": op.category,
            "description": op.description,
            "is_trigger": op.is_trigger,
            "needs_account": takes_account and not declares_no_account(
                members.get(op.name) or triggers.get(op.name) or op.config_class.model_json_schema()),
        }
        if op.name in triggers and not (polls and polls._is_schedule_operation(op.name)):
            facts["registered_with"] = [t for t in credential_types
                                        if WebhookManager.registers_itself(node_type, op.name, t)]
            facts["event"] = _event_facts(op.name, op.display_name, triggers[op.name])
        out.append(facts)
    return out


def _event_facts(operation: str, display_name: Optional[str], member: Dict[str, Any]) -> Dict[str, Any]:
    """A push trigger's ``event`` (the module's docstring), from its member of the node's schema."""
    schema = (member.get("properties") or {}).get("operation") or {}
    # Pydantic titles a field named ``operation`` "Operation" unless told otherwise: no description of anything.
    title = schema.get("title") if schema.get("title") != "Operation" else None
    required = set(member.get("required") or [])
    filters: Dict[str, str] = {}
    for name, prop in (member.get("properties") or {}).items():
        if name == "operation" or prop.get("ui:hidden") or prop.get("ui:widget") in _LIFECYCLE_WIDGETS:
            continue
        filters[name] = prop.get("description") or prop.get("title") or name
    words = operation[3:] if operation.startswith("on_") else operation
    return {"description": schema.get("description") or display_name or title or words.replace("_", " "),
            "filters": filters, "required": sorted(required & set(filters))}


def _summary(node_class: Any) -> str:
    """The first line of ``node_class``'s own docstring, or ""."""
    doc = (node_class.__doc__ or "").strip().splitlines()
    return doc[0].strip() if doc else ""


@lru_cache(maxsize=None)
def _read(node_type: str) -> Optional[Dict[str, Any]]:
    """Its file's facts; None without a file, or with one from before a fact was added. Keyed by the type, not its
    path: ``registry.is_listed`` asks once per type a search scores."""
    try:
        facts = json.loads(catalog_path(node_type).read_text())
    except FileNotFoundError:
        return None
    current = CLASS_FACTS <= facts.keys() and all(
        OPERATION_FACTS <= op.keys() and ("registered_with" not in op or EVENT_FACTS <= op.get("event", {}).keys())
        for op in facts["operations"])
    return facts if current else None


@lru_cache(maxsize=None)
def _from_class(node_type: str, node_class: Any) -> Dict[str, Any]:
    logger.error("[catalog] %s has no up-to-date catalog file; reading its class "
                 "(run scripts/generate_socket_types.py)", node_type)
    return {"type": node_type, **class_facts(node_type, node_class)}


def node_facts(node_type: str) -> Dict[str, Any]:
    """``node_type``'s facts (its canonical type), from its file, else from its class."""
    from nodes.core.registry import NODE_REGISTRY

    facts = _read(node_type)
    return facts if facts is not None else _from_class(node_type, NODE_REGISTRY[node_type])


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
    return {credential_type: tuple(sorted(holders, key=lambda holder: holder[1]["borrowed"]))
            for credential_type, holders in index.items()}


def credential_holders(credential_type: Optional[str]) -> Tuple[Tuple[str, Dict[str, Any]], ...]:
    """``(node type, its credential method)`` for each type whose config accepts ``credential_type``: the
    type's owner first, then the nodes borrowing it, each in registry order."""
    from nodes.core.registry import NODE_REGISTRY

    return _credential_index(tuple(NODE_REGISTRY)).get(credential_type or "", ())


def credential_types() -> Tuple[str, ...]:
    """Every credential type any node accepts, in registry order."""
    from nodes.core.registry import NODE_REGISTRY

    return tuple(_credential_index(tuple(NODE_REGISTRY)))


def borrows(node_type: str, credential_type: str) -> bool:
    """Whether ``node_type`` uses ``credential_type`` as another node's (its ``borrowed_credential_types``)."""
    return any(credential["type"] == credential_type and credential["borrowed"]
               for credential in node_facts(node_type)["credentials"])


@lru_cache(maxsize=4)
def _linked_index(node_types: Tuple[str, ...]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for credential_type, holders in _credential_index(node_types).items():
        for _, credential in holders:
            for name in credential.get("linked_fields", ()):
                index.setdefault(name, credential_type)
    return index


def linked_fields() -> Dict[str, str]:
    """Each field only NoClick's own linking flow sets -> the first credential type, in registry order, declaring it."""
    from nodes.core.registry import NODE_REGISTRY

    return _linked_index(tuple(NODE_REGISTRY))

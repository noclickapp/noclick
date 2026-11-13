"""The node catalog says what every class says, and the lookups built on it answer as the class walks did.

Every lookup that needs a fact about every node type (credential types, the
connections catalog, OAuth providers, provide-link methods, linked fields, the
rehearsal fence, which types a listing offers, the node search's index) reads
``nodes/catalog/<type>.json`` instead of importing every integration. These tests:
- hold each generated file to what its class and canvas definition give;
- hold each lookup to the answer the whole-registry class walk it replaced gave (each
  credential type's owner before the nodes borrowing it), for every credential type and
  node type there is;
- check that a fresh process answers them without importing any other integration.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nodes.core import catalog
from nodes.core.credential_connect import credential_classes_for_node, credential_type_of
from nodes.core.registry import NODE_REGISTRY
from scripts.generate_socket_types import catalog_entry
from scripts.node_definitions import every_definition_facts

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def classes():
    return dict(NODE_REGISTRY.items())


def _owners_first(classes, entries):
    """``(node_type, credential_type, ...)`` entries, each type's owner before the nodes borrowing it, as the
    class walks order them (``credential_connect.owners_first``), read from the classes themselves."""
    return sorted(entries, key=lambda entry: entry[1] in classes[entry[0]].borrowed_credential_types)


@pytest.fixture(scope="module")
def schemas(classes):
    return {node_type: cls.get_config_schema() or {} for node_type, cls in classes.items()}


def test_every_catalog_file_says_what_its_class_and_definition_say(classes):
    definitions = every_definition_facts()
    stale = []
    for node_type, cls in classes.items():
        expected = catalog_entry(node_type, cls, definitions.get(node_type))
        if json.loads(catalog.catalog_path(node_type).read_text()) != expected:
            stale.append(node_type)
    assert stale == [], f"run scripts/generate_socket_types.py: stale catalog files for {stale[:10]}"


def test_there_is_one_file_per_registered_type():
    files = {path.name for path in catalog.CATALOG_DIR.glob("*.json")}
    assert files == {catalog.catalog_path(node_type).name for node_type in NODE_REGISTRY}


def test_known_credential_types_are_every_schemas(schemas):
    from coder.workflow.operation_catalog import known_credential_types
    from nodes.agent.config.providers import agent_credential_types

    expected = set(agent_credential_types())
    for schema in schemas.values():
        for definition in schema.get("$defs", {}).values():
            field = definition.get("properties", {}).get("credential_type", {})
            if field.get("const") or field.get("default"):
                expected.add(field.get("const") or field.get("default"))
    assert known_credential_types() == expected


def test_connection_catalog_is_the_class_walks(classes):
    from nodes.agent.node_op_tools import node_supports_op_tools
    from utils.credential_operations import connection_catalog

    candidates, providers = [], {}
    for node_type, cls in classes.items():
        types = []
        for credential_cls in credential_classes_for_node(cls):
            kind = credential_type_of(credential_cls)
            schema = credential_cls.model_json_schema() if kind else {}
            if not kind or schema.get("x-credential-hidden"):
                continue
            candidates.append((node_type, kind, {"credential_type": kind, "name": schema.get("title", kind),
                                                 "oauth_provider": schema.get("x-oauth-provider"),
                                                 "connection_method": schema.get("x-credential-type")}))
            types.append(kind)
        if node_supports_op_tools(node_type) and types:
            providers[node_type] = tuple(types)
    methods = {}
    for _, kind, method in _owners_first(classes, candidates):
        methods.setdefault(kind, method)
    assert connection_catalog() == (methods, providers)
    assert list(connection_catalog()[1]) == list(providers)


def test_resolved_credential_classes_are_the_class_walks(classes):
    from nodes.core.credential_connect import resolve_credential_class

    index = {}
    candidates = [(node_type, credential_type_of(credential_cls), credential_cls)
                  for node_type, cls in classes.items() for credential_cls in credential_classes_for_node(cls)]
    for node_type, kind, credential_cls in _owners_first(classes, [c for c in candidates if c[1]]):
        index.setdefault(kind, (node_type, credential_cls))
    assert {t: resolve_credential_class(t) for t in index} == index
    assert resolve_credential_class("not_a_credential_type") is None


def test_linked_fields_are_the_class_walks(classes):
    from nodes.core import credential_connect

    linked = {}
    for cls in classes.values():
        for credential_cls in credential_classes_for_node(cls):
            for name in getattr(credential_cls, "linked_fields", ()):
                linked.setdefault(name, credential_cls)
    assert linked
    index = credential_connect._linked_index()
    assert {name: credential_connect.resolve_credential_class(t)[1] for name, t in index.items()} == linked


def test_provide_link_lookups_are_the_schema_sweeps(classes, schemas):
    from utils import credential_request_routes as routes

    providers, fields, methods, siblings = {}, {}, {}, {}
    oauth, definitions, groups, hidden_groups = [], [], [], []
    for node_type, schema in schemas.items():
        defs = schema.get("$defs", {})
        for title, definition in defs.items():
            credential_type = routes._resolve_credential_type(title, definition)
            if credential_type and definition.get("x-oauth-provider"):
                oauth.append((node_type, credential_type, definition["x-oauth-provider"]))
            if credential_type:
                definitions.append((node_type, credential_type, title, definition))
        refs = [e for e in schema.get("properties", {}).get("credentials", {}).get("anyOf", []) if "$ref" in e]
        if len(refs) <= 1:
            continue
        group = [routes._method_dict_from_defn(ref["$ref"].split("/")[-1], defs.get(ref["$ref"].split("/")[-1], {}))
                 for ref in refs if not defs.get(ref["$ref"].split("/")[-1], {}).get("x-credential-hidden")]
        group = [method for method in group if method]
        groups.extend((node_type, method["credential_type"], group) for method in group)
        if group:
            hidden_groups.extend(
                (node_type, routes._resolve_credential_type(title, defs[title]), group)
                for title in (ref["$ref"].split("/")[-1] for ref in refs)
                if defs.get(title, {}).get("x-credential-hidden") and routes._resolve_credential_type(title, defs[title])
            )
    for _, credential_type, provider in _owners_first(classes, oauth):
        providers.setdefault(credential_type, provider)
    assert routes._oauth_providers_by_type() == providers

    for _, credential_type, title, definition in _owners_first(classes, definitions):
        if credential_type in methods:
            continue
        if definition.get("x-credential-type") != "oauth":
            fields[credential_type] = routes._extract_fields_from_schema(definition)
        methods[credential_type] = routes._method_dict_from_defn(title, definition)
    for _, credential_type, group in _owners_first(classes, groups):
        siblings.setdefault(credential_type, group)
    # A way in hidden wherever it's declared is answered by the ways in its node offers.
    for _, credential_type, group in _owners_first(classes, hidden_groups):
        siblings.setdefault(credential_type, group)
    for credential_type in sorted(set(fields) | set(methods) | set(siblings) | set(catalog.credential_types())):
        assert routes._get_credential_fields(credential_type) == fields.get(credential_type, []), credential_type
        assert routes._get_credential_method(credential_type) == methods.get(credential_type), credential_type
        assert routes._get_sibling_methods(credential_type) == siblings.get(credential_type, []), credential_type


def test_the_rehearsal_fence_is_every_credentialed_node(schemas):
    from nodes.agent.rehearsal import rehearsal_excluded_node_types

    credentialed = {
        node_type for node_type, schema in schemas.items()
        if isinstance(c := (schema.get("properties", {}) or {}).get("credentials") or {}, dict)
        and (c.get("$ref") or c.get("anyOf"))
    } - {"agent"}
    assert rehearsal_excluded_node_types() == frozenset(
        credentialed | {"automation-send-email", "automation-http-request", "noclick", "automation-table"})


_LOOKUPS = """
import json, sys
from nodes.core.discovery import Declaration
from nodes.core.registry import DISCOVERED_NODE_ENTRIES
from coder.workflow.operation_catalog import known_credential_types
from nodes.agent.rehearsal import rehearsal_excluded_node_types
from nodes.core.credential_connect import linked_field_names, resolve_credential_class
from utils.credential_operations import connection_catalog
from utils import credential_request_routes as routes
from utils.webhook_manager import WebhookManager
from coder.workflow.agentic.node_types import _get_multi_output_nodes_info

from nodes.core.registry import NODE_REGISTRY, is_listed
from utils import node_search

known_credential_types(); connection_catalog(); rehearsal_excluded_node_types(); linked_field_names()
WebhookManager._registerable_types(); _get_multi_output_nodes_info()
[is_listed(t) for t in NODE_REGISTRY]; node_search.search("send sms")
routes._oauth_providers_by_type()
resolved = resolve_credential_class("2chat_api_key")[0]
routes._get_credential_method("2chat_api_key"); routes._get_sibling_methods("2chat_api_key")
print(json.dumps({"resolved": resolved, "imported": sorted(
    e.integration_type for e in DISCOVERED_NODE_ENTRIES.values()
    if isinstance(e, Declaration) and e.module in sys.modules)}))
"""


def test_the_lookups_import_no_integration_but_the_one_they_name():
    # A fresh interpreter: this suite has imported every integration already.
    done = subprocess.run([sys.executable, "-c", _LOOKUPS], cwd=BACKEND, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-4000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result == {"resolved": "automation-2chat", "imported": ["automation-2chat"]}


def test_registration_lookups_are_the_class_walks(classes):
    from nodes.core.schedule_registration import CronScheduleTriggerMixin
    from nodes.core.webhook_subscriptions import AppEventTriggerMixin
    from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin
    from utils.webhook_manager import WebhookManager, _app_event_class_for_provider

    registerable = sorted(
        t for t, c in classes.items()
        if issubclass(c, (ExternalWebhookTriggerMixin, AppEventTriggerMixin, CronScheduleTriggerMixin))
        or getattr(c, "self_registering_triggers", None)
    )
    assert WebhookManager._registerable_types() == registerable
    providers = {}
    for c in classes.values():
        if issubclass(c, AppEventTriggerMixin):
            providers.setdefault(c._app_provider, c)
    assert providers
    assert {p: _app_event_class_for_provider(p) for p in providers} == providers
    assert _app_event_class_for_provider("not-a-provider") is None


def test_the_builders_multi_output_list_is_the_class_walks(classes):
    from coder.workflow.agentic.node_types import _get_multi_output_nodes_info

    lines = []
    for node_type, cls in classes.items():
        handles = None if node_type.startswith("test-") else cls.get_output_handles()
        if handles:
            lines.append(f"- {node_type}: handles are " + ", ".join(f'"{h["id"]}" ({h["description"]})' for h in handles))
    assert lines
    assert _get_multi_output_nodes_info() == "\n".join(lines)


def test_listings_and_the_node_search_read_what_the_classes_say(classes, monkeypatch):
    """Which types a listing offers (``registry.is_listed``) and what the node search indexes of each (its class's
    docstring line, its operations) are what the classes said, for every type."""
    from coder.workflow.operation_catalog import get_operations_for_node_type
    from nodes.core.registry import is_listed, retirement_of
    from utils import node_search

    assert {t: retirement_of(t) for t in classes} == {t: cls.retired for t, cls in classes.items()}
    assert [t for t in classes if not is_listed(t)] == [t for t, cls in classes.items() if cls.retired]
    read = {t: (node_search._facts(t), node_search._operations(t)) for t in classes}

    def from_class(node_type):
        doc = (classes[node_type].__doc__ or "").strip().splitlines()
        return {"summary": doc[0].strip() if doc else "", "operations": [
            {"name": op.name, "display_name": op.display_name, "category": op.category, "description": op.description}
            for op in get_operations_for_node_type(node_type)]}

    monkeypatch.setattr(catalog, "node_facts", from_class)
    assert read == {t: (node_search._facts(t), node_search._operations(t)) for t in classes}


def test_a_type_whose_file_predates_a_fact_is_read_from_its_class(classes, tmp_path, monkeypatch):
    """An integration generated before a fact was added and merged after has a file without it: its class answers,
    never a missing key."""
    from nodes.core.registry import is_listed, retirement_of

    assert set(catalog.class_facts("automation-humanloop", classes["automation-humanloop"])) == catalog.CLASS_FACTS
    written = json.loads(catalog.catalog_path("automation-humanloop").read_text())
    (tmp_path / "humanloop.json").write_text(json.dumps({k: v for k, v in written.items() if k != "retired"}))
    monkeypatch.setattr(catalog, "catalog_path", lambda node_type, real=catalog.catalog_path: real(node_type, tmp_path))
    catalog._read.cache_clear()
    try:
        assert retirement_of("automation-humanloop") == classes["automation-humanloop"].retired
        assert not is_listed("automation-humanloop")
    finally:
        catalog._read.cache_clear()

"""
Tests for resource scoping on agent_tool_operations: the {operation,
field_scopes} entry shape, x-resource-type + x-creates-resource +
x-resource-id-path schema markers, and their downstream effects on
build_node_op_tools, run_node_lookup, and the per-call scope check.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from coder.workflow.workflow_ops import validate_agent_tool_operations
from nodes.agent.node_op_tools import (
    build_node_op_tools,
    build_provider_output,
    extract_resource_id_from_output,
    normalize_allowed_operations,
    resource_creators,
    resource_field_index,
    scopable_fields_for_operation,
)
from nodes.agent.tool_execution import execute_tool
from nodes.core.run_op import run_node_lookup


# Google Docs is the reference annotated node: document_id has x-resource-type
# "google_doc"; create_new_document is the creator with response path
# document.documentId.
NT = "automation-google-docs"


# ============================================================================
# Validation: shape acceptance
# ============================================================================


def test_validate_accepts_legacy_string_list():
    ok, err = validate_agent_tool_operations(
        NT, ["create_new_document", "fetch_document_content"]
    )
    assert err is None, err
    assert ok == ["create_new_document", "fetch_document_content"]


def test_validate_accepts_mixed_scoped_and_unscoped():
    ok, err = validate_agent_tool_operations(
        NT,
        [
            "create_new_document",
            {
                "operation": "fetch_document_content",
                "field_scopes": {"document_id": ["doc_abc", "doc_xyz"]},
            },
        ],
    )
    assert err is None, err
    assert ok[0] == "create_new_document"
    assert ok[1]["operation"] == "fetch_document_content"
    assert ok[1]["field_scopes"] == {"document_id": ["doc_abc", "doc_xyz"]}


def test_validate_dedupes_ids_within_scope():
    ok, err = validate_agent_tool_operations(
        NT,
        [{"operation": "fetch_document_content",
          "field_scopes": {"document_id": ["a", "b", "a"]}}],
    )
    assert err is None
    assert ok[0]["field_scopes"]["document_id"] == ["a", "b"]


def test_validate_rejects_unknown_scopable_field():
    _, err = validate_agent_tool_operations(
        NT,
        [{"operation": "fetch_document_content",
          "field_scopes": {"nonsuch_field": ["a"]}}],
    )
    assert err is not None and "not scopable" in err


def test_validate_rejects_scope_on_unscopable_op():
    # create_new_document has no x-resource-type-tagged fields.
    _, err = validate_agent_tool_operations(
        NT,
        [{"operation": "create_new_document",
          "field_scopes": {"title": ["x"]}}],
    )
    assert err is not None


def test_validate_rejects_non_string_ids():
    _, err = validate_agent_tool_operations(
        NT,
        [{"operation": "fetch_document_content",
          "field_scopes": {"document_id": [42]}}],
    )
    assert err is not None
    assert "non-empty arrays" in err


def test_validate_rejects_duplicate_operation_entries():
    _, err = validate_agent_tool_operations(
        NT,
        [
            "fetch_document_content",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["a"]}},
        ],
    )
    assert err is not None and "Duplicate" in err


# ============================================================================
# Schema introspection
# ============================================================================


def test_scopable_fields_for_operation():
    assert scopable_fields_for_operation(NT, "fetch_document_content") == frozenset({"document_id"})
    # create_new_document carries no x-resource-type fields.
    assert scopable_fields_for_operation(NT, "create_new_document") == frozenset()


def test_resource_creators_picks_up_creator_marker():
    creators = resource_creators(NT)
    assert creators == (("create_new_document", "google_doc", "document.documentId"),)


def test_resource_field_index_lists_all_scopable_fields():
    idx = resource_field_index(NT)
    ops_with_doc_id = {op for op, field, rt in idx if field == "document_id" and rt == "google_doc"}
    # Every read/edit op for Google Docs should have document_id tagged.
    assert {"fetch_document_content", "append_text_to_document",
            "insert_text_in_document", "replace_document_text"}.issubset(ops_with_doc_id)


def test_extract_resource_id_from_output_walks_dotted_path():
    assert extract_resource_id_from_output(
        {"document": {"documentId": "doc_xyz"}}, "document.documentId"
    ) == "doc_xyz"
    assert extract_resource_id_from_output(
        {"document": {}}, "document.documentId"
    ) is None
    assert extract_resource_id_from_output({}, "document.documentId") is None
    assert extract_resource_id_from_output(
        {"document": {"documentId": ""}}, "document.documentId"
    ) is None


# ============================================================================
# build_node_op_tools: schema-level enum injection
# ============================================================================


def _find_tool(configs, suffix):
    return next(cfg for name, cfg in configs.items() if name.endswith(suffix))


def test_scoped_field_renders_as_enum_in_tool_schema():
    _, configs = build_node_op_tools(
        NT,
        [{"operation": "fetch_document_content",
          "field_scopes": {"document_id": ["doc_abc", "doc_xyz"]}}],
        node_id="gd1",
    )
    fetch = _find_tool(configs, "__fetch_document_content")
    doc_schema = fetch["_parameters"]["properties"]["document_id"]
    assert doc_schema.get("enum") == ["doc_abc", "doc_xyz"]
    # Server-side enforcement stash mirrors the same allowlist.
    assert fetch["field_scopes"] == {"document_id": ["doc_abc", "doc_xyz"]}


def test_unscoped_op_omits_enum():
    _, configs = build_node_op_tools(
        NT, ["fetch_document_content"], node_id="gd1",
    )
    fetch = _find_tool(configs, "__fetch_document_content")
    assert "enum" not in fetch["_parameters"]["properties"]["document_id"]
    assert "field_scopes" not in fetch


# ============================================================================
# Lookup tool: field_scopes union and unscoped-collapse
# ============================================================================


def test_lookup_locks_when_all_ops_scoped():
    _, configs = build_node_op_tools(
        NT,
        [
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
            {"operation": "append_text_to_document",
             "field_scopes": {"document_id": ["doc_xyz"]}},
        ],
        node_id="gd1",
    )
    lookup = _find_tool(configs, "__lookup_options")
    # Both consumers of document_id are scoped → lookup filters to the union.
    assert set(lookup["field_scopes"]["document_id"]) == {"doc_abc", "doc_xyz"}


def test_lookup_unlocks_when_any_consumer_is_unscoped():
    _, configs = build_node_op_tools(
        NT,
        [
            "fetch_document_content",  # unscoped consumer of document_id
            {"operation": "append_text_to_document",
             "field_scopes": {"document_id": ["doc_xyz"]}},
        ],
        node_id="gd1",
    )
    lookup = _find_tool(configs, "__lookup_options")
    # An unscoped consumer would still see all IDs — the lookup MUST stay open.
    assert lookup["field_scopes"].get("document_id") is None or \
        "document_id" not in lookup["field_scopes"]


def test_creator_alone_does_not_lock_lookup():
    # create_new_document doesn't touch document_id; its presence shouldn't
    # collapse the lookup filter (already absent from the field map).
    _, configs = build_node_op_tools(
        NT,
        [
            "create_new_document",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
        ],
        node_id="gd1",
    )
    lookup = _find_tool(configs, "__lookup_options")
    assert lookup["field_scopes"].get("document_id") == ["doc_abc"]


# ============================================================================
# Per-call enforcement (defense in depth behind the schema-level enum)
# ============================================================================


@pytest.mark.asyncio
async def test_offlist_id_rejected_by_in_process_enforcement():
    _, configs = build_node_op_tools(
        NT,
        [{"operation": "fetch_document_content",
          "field_scopes": {"document_id": ["doc_abc"]}}],
        node_id="gd1",
    )
    fetch_name = next(n for n in configs if n.endswith("__fetch_document_content"))
    fake_node = SimpleNamespace(
        user_id="u1", organization_id=None, workflow_id="wf1",
        node_id="agent1", conversation_id=None, _effective_model=None,
        execution_id=None,
    )
    result = await execute_tool(
        fake_node, fetch_name,
        {"document_id": "doc_NOT_ALLOWED"},
        configs,
    )
    assert result["success"] is False
    assert "restricted" in result["error"].lower()


# ============================================================================
# Lookup filtering — allowed_values intersects loaded options
# ============================================================================


@pytest.mark.asyncio
async def test_lookup_filters_to_allowed_values(monkeypatch):
    from nodes.core import run_op as run_op_module

    async def fake_load_field_options(**_kwargs):
        return {
            "options": [
                {"value": "doc_abc", "label": "Allowed"},
                {"value": "doc_off", "label": "Off-list"},
            ],
            "next_page_token": None,
        }

    from nodes.google_docs_node import GoogleDocsNode

    monkeypatch.setattr(GoogleDocsNode, "load_field_options", fake_load_field_options)
    # Stub the runtime pool out of the path — we don't pass a credential_id
    # so resolve_operation_credential never runs.
    result = await run_node_lookup(
        node_type=NT,
        field_name="document_id",
        user_id="u1",
        allowed_values=["doc_abc"],
    )
    values = [o["value"] for o in result["options"]]
    assert values == ["doc_abc"]


@pytest.mark.asyncio
async def test_lookup_returns_everything_when_unscoped(monkeypatch):
    from nodes.google_docs_node import GoogleDocsNode

    async def fake_load_field_options(**_kwargs):
        return {"options": [
            {"value": "doc_abc", "label": "A"},
            {"value": "doc_xyz", "label": "B"},
        ], "next_page_token": None}

    monkeypatch.setattr(GoogleDocsNode, "load_field_options", fake_load_field_options)
    result = await run_node_lookup(
        node_type=NT, field_name="document_id", user_id="u1",
    )
    assert {o["value"] for o in result["options"]} == {"doc_abc", "doc_xyz"}


# ============================================================================
# normalize_allowed_operations — the runtime reader
# ============================================================================


def test_normalize_drops_garbage_keeps_valid():
    op_names, scopes = normalize_allowed_operations(
        [
            "good_op",
            None,                                       # dropped
            {"operation": "scoped_op",
             "field_scopes": {"f": ["a", "b"]}},
            {"missing_op_key": True},                   # dropped
            {"operation": "empty_scoped",
             "field_scopes": {"f": []}},                # cleans to unscoped
            42,                                         # dropped
        ]
    )
    assert op_names == ["good_op", "scoped_op", "empty_scoped"]
    assert scopes == {"scoped_op": {"f": ["a", "b"]}}


# ============================================================================
# Provider output passes the mixed allowlist through verbatim
# ============================================================================


def test_provider_output_passes_mixed_allowlist_through():
    raw_cfg = {
        "agent_tool_operations": [
            "create_new_document",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
        ],
    }
    out = build_provider_output(NT, raw_cfg)
    assert out["allowed_operations"][0] == "create_new_document"
    assert out["allowed_operations"][1]["field_scopes"] == {"document_id": ["doc_abc"]}


# ============================================================================
# Enum-drop when a same-type creator is allowlisted (so the agent can read
# what it just created via the auto-extended allowlist)
# ============================================================================


def test_enum_dropped_when_creator_allowlisted():
    # create_new_document creates google_doc → fetch's document_id scope
    # must NOT lock to enum (else agent's own newly-created ID gets rejected
    # by the model's frozen-for-the-run JSON schema).
    _, configs = build_node_op_tools(
        NT,
        [
            "create_new_document",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
        ],
        node_id="gd1",
    )
    fetch = _find_tool(configs, "__fetch_document_content")
    schema = fetch["_parameters"]["properties"]["document_id"]
    assert "enum" not in schema, schema
    # field_scopes stash remains — server-side enforcement is the source of
    # truth in this mode (it grows via extend_node_field_scopes at runtime).
    assert fetch["field_scopes"] == {"document_id": ["doc_abc"]}


def test_enum_kept_when_no_creator_allowlisted():
    _, configs = build_node_op_tools(
        NT,
        [{"operation": "fetch_document_content",
          "field_scopes": {"document_id": ["doc_abc"]}}],
        node_id="gd1",
    )
    fetch = _find_tool(configs, "__fetch_document_content")
    assert fetch["_parameters"]["properties"]["document_id"]["enum"] == ["doc_abc"]


# ============================================================================
# Auto-extend on resource creation (pure logic — no DB)
# ============================================================================


def test_extend_allowlist_appends_new_id_to_matching_scopes():
    from utils.workflow_node_writeback import _extend_allowlist_in_place

    new, changed = _extend_allowlist_in_place(
        node_type=NT,
        allowlist=[
            "create_new_document",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
            {"operation": "append_text_to_document",
             "field_scopes": {"document_id": ["doc_abc"]}},
        ],
        new_resource_ids_by_type={"google_doc": "doc_NEW"},
    )
    assert changed is True
    # Both scoped ops grow; the unscoped create stays unscoped.
    assert new[0] == "create_new_document"
    assert "doc_NEW" in new[1]["field_scopes"]["document_id"]
    assert "doc_NEW" in new[2]["field_scopes"]["document_id"]


def test_extend_allowlist_idempotent_when_id_already_present():
    from utils.workflow_node_writeback import _extend_allowlist_in_place

    seeded = [
        {"operation": "fetch_document_content",
         "field_scopes": {"document_id": ["doc_abc", "doc_NEW"]}},
    ]
    _, changed = _extend_allowlist_in_place(
        node_type=NT,
        allowlist=seeded,
        new_resource_ids_by_type={"google_doc": "doc_NEW"},
    )
    assert changed is False


def test_extend_allowlist_never_creates_scopes_from_nothing():
    """The runtime never INVENTS a scope on a previously unscoped op —
    only expands an allowlist the user already established."""
    from utils.workflow_node_writeback import _extend_allowlist_in_place

    new, changed = _extend_allowlist_in_place(
        node_type=NT,
        allowlist=["fetch_document_content"],
        new_resource_ids_by_type={"google_doc": "doc_NEW"},
    )
    assert changed is False
    assert new == ["fetch_document_content"]


def test_apply_new_id_to_live_tool_configs_mutates_in_place():
    from utils.workflow_node_writeback import apply_new_id_to_live_tool_configs

    _, configs = build_node_op_tools(
        NT,
        [
            "create_new_document",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
            {"operation": "append_text_to_document",
             "field_scopes": {"document_id": ["doc_abc"]}},
        ],
        node_id="gd1",
    )
    apply_new_id_to_live_tool_configs(
        configs, "gd1", NT, {"google_doc": "doc_NEW"},
    )
    fetch = _find_tool(configs, "__fetch_document_content")
    append = _find_tool(configs, "__append_text_to_document")
    lookup = _find_tool(configs, "__lookup_options")
    assert "doc_NEW" in fetch["field_scopes"]["document_id"]
    assert "doc_NEW" in append["field_scopes"]["document_id"]
    # Lookup tool wasn't locked (creator unscoped → lookup unscoped on its
    # field; nothing to extend on the lookup side).
    assert lookup.get("field_scopes", {}).get("document_id") in (None, [], ["doc_abc"]) or \
        "doc_NEW" in lookup["field_scopes"]["document_id"]


def test_apply_new_id_extends_locked_lookup_too():
    """When every consumer is scoped, the lookup's per-field scope IS locked.
    Auto-extend must also update it so a follow-up search includes the new ID."""
    from utils.workflow_node_writeback import apply_new_id_to_live_tool_configs

    _, configs = build_node_op_tools(
        NT,
        [
            # Even though create's resource_type matches, the test setup keeps
            # both consumers scoped so the lookup locks.
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
            {"operation": "append_text_to_document",
             "field_scopes": {"document_id": ["doc_xyz"]}},
        ],
        node_id="gd1",
    )
    lookup = _find_tool(configs, "__lookup_options")
    assert set(lookup["field_scopes"]["document_id"]) == {"doc_abc", "doc_xyz"}
    apply_new_id_to_live_tool_configs(
        configs, "gd1", NT, {"google_doc": "doc_NEW"},
    )
    assert "doc_NEW" in lookup["field_scopes"]["document_id"]


@pytest.mark.asyncio
async def test_autoextend_triggers_on_successful_create(monkeypatch):
    """End-to-end: a successful create_new_document call extends the
    in-memory tool_configs (the DB path is mocked — we're checking the
    auto-extend pipeline fires + targets the right resource type)."""
    _, configs = build_node_op_tools(
        NT,
        [
            "create_new_document",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
        ],
        node_id="gd1",
    )
    create_name = next(n for n in configs if n.endswith("__create_new_document"))

    # Stub run_node_operation to return a fake successful create output.
    async def fake_run_node_operation(**_kwargs):
        return {
            "type": "google_docs",
            "operation": "create_new_document",
            "document": {"documentId": "doc_NEW", "title": "fresh"},
            "status": "success",
        }
    monkeypatch.setattr(
        "nodes.core.run_op.run_node_operation", fake_run_node_operation,
    )
    monkeypatch.setattr(
        "nodes.agent.tool_execution.run_node_operation",
        fake_run_node_operation,
        raising=False,
    )

    # Stub the DB writeback (no real pool in unit tests).
    extend_calls = []

    async def fake_extend(*, pool=None, workflow_id, provider_node_id, new_resource_ids_by_type):
        extend_calls.append({
            "workflow_id": workflow_id,
            "provider_node_id": provider_node_id,
            "ids": new_resource_ids_by_type,
        })
        return ["create_new_document",
                {"operation": "fetch_document_content",
                 "field_scopes": {"document_id": ["doc_abc", "doc_NEW"]}}]

    monkeypatch.setattr(
        "utils.workflow_node_writeback.extend_node_field_scopes", fake_extend,
    )

    fake_node = SimpleNamespace(
        user_id="u1", organization_id=None, workflow_id="wf1",
        node_id="agent1", conversation_id=None, _effective_model=None,
        execution_id=None,
    )
    result = await execute_tool(
        fake_node, create_name, {"title": "hello"}, configs,
    )
    assert result.get("status") == "success"
    assert extend_calls and extend_calls[0]["ids"] == {"google_doc": "doc_NEW"}
    # Live tool_configs mirror: fetch's scope grew.
    fetch_cfg = configs[next(n for n in configs if n.endswith("__fetch_document_content"))]
    assert "doc_NEW" in fetch_cfg["field_scopes"]["document_id"]


@pytest.mark.asyncio
async def test_autoextend_skipped_on_failed_create(monkeypatch):
    _, configs = build_node_op_tools(
        NT,
        [
            "create_new_document",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
        ],
        node_id="gd1",
    )
    create_name = next(n for n in configs if n.endswith("__create_new_document"))

    async def fake_run_node_operation(**_kwargs):
        return {"success": False, "error": "API down"}

    monkeypatch.setattr(
        "nodes.core.run_op.run_node_operation", fake_run_node_operation,
    )
    monkeypatch.setattr(
        "nodes.agent.tool_execution.run_node_operation",
        fake_run_node_operation,
        raising=False,
    )

    extend_called = []

    async def fake_extend(**kwargs):
        extend_called.append(kwargs)
        return None

    monkeypatch.setattr(
        "utils.workflow_node_writeback.extend_node_field_scopes", fake_extend,
    )
    fake_node = SimpleNamespace(
        user_id="u1", organization_id=None, workflow_id="wf1",
        node_id="agent1", conversation_id=None, _effective_model=None,
        execution_id=None,
    )
    result = await execute_tool(fake_node, create_name, {"title": "x"}, configs)
    assert result["success"] is False
    assert extend_called == [], "auto-extend must not run on failed create"


# ============================================================================
# Multi-level dependent fields (e.g. Google Sheets sheet_name depends on
# spreadsheet_id; Linear stateId depends on teamId)
# ============================================================================


def test_dependent_scopable_fields_carry_depends_on_annotation():
    """The FE picker reads depends_on from the schema to know when to gate a
    dependent field on its parent's scope. If this stops emitting, the gating
    logic silently breaks."""
    SHEETS = "automation-google-sheets"
    from nodes.agent.node_op_tools import _iter_operation_defs
    from nodes.core.registry import NODE_REGISTRY

    cls = NODE_REGISTRY[SHEETS]
    sheet_name_fields = []
    for entry in _iter_operation_defs(cls):
        for f, p in entry["member"].get("properties", {}).items():
            if not isinstance(p, dict):
                continue
            dyn = p.get("x-dynamic-options")
            if isinstance(dyn, dict) and dyn.get("depends_on") and p.get("x-resource-type"):
                sheet_name_fields.append((entry["operation"], f, dyn["depends_on"]))
    # Sheets has many sheet_name-on-spreadsheet_id ops.
    assert any(dep == "spreadsheet_id" for _, _, dep in sheet_name_fields), \
        f"google-sheets must carry depends_on=spreadsheet_id on sheet_name fields, got {sheet_name_fields}"


@pytest.mark.asyncio
async def test_lookup_passes_parent_context_for_dependent_fields():
    """The FE doesn't expose multi-level context through field_scopes (flat),
    but the lookup tool's individual calls should accept context from the
    agent at runtime — the loader machinery is unchanged for dependent fields."""
    from nodes.core import run_op as run_op_module
    from nodes.core.registry import NODE_REGISTRY
    SHEETS = "automation-google-sheets"
    cls = NODE_REGISTRY[SHEETS]

    captured = {}

    async def fake_load_field_options(*, field_name, credential_data, context, page_token, search):
        captured["field_name"] = field_name
        captured["context"] = context
        return {"options": [{"value": "Sheet1", "label": "Sheet1"}], "next_page_token": None}

    # Stub the loader directly on the node class.
    original = getattr(cls, "load_field_options", None)
    try:
        cls.load_field_options = classmethod(lambda c, **kw: fake_load_field_options(**kw))
        result = await run_node_lookup(
            node_type=SHEETS,
            field_name="sheet_name",
            user_id="u1",
            context={"spreadsheet_id": "spread_123"},
        )
        assert captured["field_name"] == "sheet_name"
        assert captured["context"]["spreadsheet_id"] == "spread_123"
        assert captured["context"]["_user_id"] == "u1"
        assert result["options"][0]["value"] == "Sheet1"
    finally:
        if original is not None:
            cls.load_field_options = original


# ============================================================================
# Validation edge cases
# ============================================================================


def test_validate_drops_empty_field_scopes_collapses_to_unscoped():
    """`{"document_id": []}` (empty array) is the runtime equivalent of
    unscoped; the validator drops the empty entry and emits the bare string."""
    ok, err = validate_agent_tool_operations(
        NT,
        [{"operation": "fetch_document_content",
          "field_scopes": {"document_id": []}}],
    )
    assert err is None, err
    # An empty field_scopes collapses to the unscoped string form.
    assert ok == ["fetch_document_content"]


def test_validate_drops_only_empty_fields_keeps_others():
    """Within a scoped op, a per-field empty array is dropped but other
    fields with content survive. Only useful if a node has >1 scopable
    field on the same op; harmless on single-field ops."""
    ok, err = validate_agent_tool_operations(
        "automation-linear",
        [{"operation": "create_issue",
          "field_scopes": {"teamId": ["team_a"], "stateId": []}}],
    )
    assert err is None, err
    assert ok[0]["field_scopes"] == {"teamId": ["team_a"]}


# ============================================================================
# Google Calendar miss caught in the audit (calendar_id source field) —
# guard against schema regressions where a creator/scopable miss creeps in.
# ============================================================================


def test_google_calendar_move_event_source_calendar_id_is_scopable():
    """A previous mass-annotation pass missed move_event_to_calendar's
    source calendar_id; this regression test fires loud if a future
    refactor drops it again."""
    fields = scopable_fields_for_operation(
        "automation-google-calendar", "move_event_to_calendar",
    )
    assert "calendar_id" in fields, fields
    assert "destination_calendar_id" in fields, fields


# ============================================================================
# Annotation completeness: every node with x-dynamic-options ID fields that
# was intended to be annotated must have at least one scopable field. Catches
# accidental schema deletions in a future refactor.
# ============================================================================


def test_annotated_nodes_keep_their_scopable_fields():
    """Spot-check the headline integrations to ensure resource-scoping
    survives node refactors. Any of these regressing fires this test."""
    expected_scopable = {
        "automation-google-docs": "google_doc",
        "automation-google-sheets": "google_spreadsheet",
        "automation-google-calendar": "google_calendar",
        "automation-google-drive": "google_drive_file",
        "automation-slack": "slack_channel",
        "automation-linear": "linear_issue",
        "automation-notion": "notion_database",
        "automation-stripe": "stripe_customer",
        "automation-asana": "asana_project",
    }
    for node_type, expected_resource in expected_scopable.items():
        idx = resource_field_index(node_type)
        resource_types = {rt for _, _, rt in idx}
        assert expected_resource in resource_types, (
            f"{node_type} lost resource type {expected_resource!r}; "
            f"found {sorted(resource_types)}"
        )


def test_creator_ops_present_for_headline_nodes():
    """At least one creator op survives the mass-annotation for every
    integration that has create-style operations."""
    must_have_creators = [
        "automation-google-docs",
        "automation-google-sheets",
        "automation-slack",
        "automation-linear",
        "automation-stripe",
        "automation-notion",
        "automation-asana",
    ]
    for node_type in must_have_creators:
        creators = resource_creators(node_type)
        assert creators, f"{node_type} lost all its creator markers"


# ============================================================================
# build_provider_output → build_node_op_tools handoff: the mixed allowlist
# round-trips correctly through the runtime collection seam.
# ============================================================================


def test_provider_output_to_tool_build_roundtrip():
    """Reproduces the real path: a node's saved config -> build_provider_output
    (provider mode at execute time) -> build_node_op_tools (agent's tool
    collection). The field_scopes must survive both hops intact."""
    raw_cfg = {
        "agent_tool_operations": [
            "create_new_document",
            {"operation": "fetch_document_content",
             "field_scopes": {"document_id": ["doc_abc"]}},
        ],
        "credentialIds": {"google_docs_oauth": "cred_xyz"},
    }
    provider_output = build_provider_output(NT, raw_cfg)
    assert provider_output["type"] == "node_op_tool_provider"
    assert provider_output["credential_id"] == "cred_xyz"
    # Now feed it into build_node_op_tools the way _collect_node_op_provider would.
    _, configs = build_node_op_tools(
        NT,
        provider_output["allowed_operations"],
        node_id="gd1",
        credential_id=provider_output["credential_id"],
    )
    fetch = _find_tool(configs, "__fetch_document_content")
    # field_scopes preserved end-to-end.
    assert fetch["field_scopes"] == {"document_id": ["doc_abc"]}
    # Creator allowlisted → enum dropped (auto-extend path).
    assert "enum" not in fetch["_parameters"]["properties"]["document_id"]


# ============================================================================
# resource_field_index must enumerate by both op and field — used by the
# auto-extend writeback to find every place a new ID should land.
# ============================================================================


def test_resource_field_index_covers_every_scoped_field():
    """If a node's resource_field_index returns nothing for a tagged field,
    the auto-extend writeback would skip it. Pin this for headline nodes."""
    idx = resource_field_index(NT)
    google_doc_fields = {(op, f) for op, f, rt in idx if rt == "google_doc"}
    # All read/write doc ops must be enumerable.
    expected = {
        ("fetch_document_content", "document_id"),
        ("append_text_to_document", "document_id"),
        ("insert_text_in_document", "document_id"),
        ("replace_document_text", "document_id"),
    }
    assert expected.issubset(google_doc_fields), (
        f"google-docs lost fields from index: {expected - google_doc_fields}"
    )

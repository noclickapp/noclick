"""Actual lookup dispatchers must enforce scoped parent context before I/O.

Native schema/tool metadata is real; only resolver/admission/freshen/loader I/O
boundaries are synthetic. This is not a live provider or DB permission test.
"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nodes.agent import rehearsal, tool_execution
from nodes.agent.node_op_tools import build_node_op_tools
from nodes.core import run_op
from nodes.core.registry import NODE_REGISTRY
from utils import credential_approval

USER = "synthetic-runner"
ORG = "synthetic-organization"
WORKFLOW = "synthetic-workflow"
CREDENTIAL_ID = "synthetic-credential"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    """No global DB fixture is needed for this isolated --noconftest gate."""
    yield


def native_lookup(node_type, operation, scopes=None, additional_operations=None):
    allowed = [{"operation": operation, "field_scopes": scopes}] if scopes else [operation]
    allowed.extend(additional_operations or [])
    _, configs = build_node_op_tools(node_type, allowed, node_id="synthetic-provider", credential_id=CREDENTIAL_ID)
    name = next(name for name, info in configs.items() if info["tool_type"] == "node_op_lookup")
    return name, configs[name]


def io_boundaries(monkeypatch, node_type):
    credential = {"credential_type": "synthetic-provider", "access_token": "synthetic-token"}
    resolved = AsyncMock(return_value=deepcopy(credential))
    admission = AsyncMock(return_value=None)
    freshen = AsyncMock(return_value=deepcopy(credential))
    loader = AsyncMock(return_value={"options": [{"label": "Allowed", "value": "allowed-child"}, {"label": "Other", "value": "other-child"}], "next_page_token": "synthetic-next"})
    monkeypatch.setattr(run_op, "resolve_credential_with_owner_fallback", resolved)
    monkeypatch.setattr(credential_approval, "admit_lookup", admission)
    monkeypatch.setattr(NODE_REGISTRY[node_type], "freshen_credential", freshen)
    monkeypatch.setattr(NODE_REGISTRY[node_type], "load_field_options", loader)
    monkeypatch.setattr(rehearsal, "is_rehearsing", AsyncMock(return_value=False))
    return resolved, admission, freshen, loader


async def dispatch(entry, name, info, arguments):
    if entry == "agent_tool":
        node = SimpleNamespace(user_id=USER, organization_id=ORG, workflow_id=WORKFLOW)
        return await tool_execution._execute_node_op_lookup(node, name, arguments, info)
    return await run_op.run_node_op_tool(info, arguments, user_id=USER, organization_id=ORG, workflow_id=WORKFLOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["agent_tool", "cross_container"])
@pytest.mark.parametrize("value", ["other-parent", ["allowed-parent", "other-parent"], {"id": "other-parent"}, True])
async def test_real_native_parent_scope_refuses_before_every_io_boundary(monkeypatch, entry, value):
    node_type = "automation-google-sheets"
    name, info = native_lookup(node_type, "read_sheet_data", {"spreadsheet_id": ["allowed-parent"]})
    assert info["fields"]["sheet_name"] == "sheet_name"
    assert info["field_dependencies"]["sheet_name"] == "spreadsheet_id"
    assert "sheet_name" not in info["field_scopes"]
    boundaries = io_boundaries(monkeypatch, node_type)
    arguments = {"field": "sheet_name", "context": {"spreadsheet_id": value, "field_scopes": {"spreadsheet_id": ["other-parent"]}, "organization_id": "caller-spoof", "workflow_id": "caller-spoof"}}
    result = await dispatch(entry, name, info, arguments)
    assert result["success"] is False and "context scope" in result["error"].lower()
    assert "spreadsheet_id" in result["error"]
    for boundary in boundaries:
        boundary.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["agent_tool", "cross_container"])
@pytest.mark.parametrize("context", [{"team_id": "other-parent"}, {"teamId": "allowed-parent", "team_id": "other-parent"}, {"teamId": "other-parent", "team_id": "allowed-parent"}, {"teamId": "", "team_id": "other-parent"}])
async def test_real_native_declared_parent_alias_cannot_bypass_scope(monkeypatch, entry, context):
    node_type = "automation-linear"
    name, info = native_lookup(node_type, "create_issue", {"teamId": ["allowed-parent"]})
    assert info["fields"]["teamId"] == "team_id"
    assert info["fields"]["stateId"] == "state_id"
    boundaries = io_boundaries(monkeypatch, node_type)
    result = await dispatch(entry, name, info, {"field": "stateId", "context": context})
    assert result["success"] is False and "context scope" in result["error"].lower()
    for boundary in boundaries:
        boundary.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["agent_tool", "cross_container"])
@pytest.mark.parametrize("context", [{"spreadsheet_id": "allowed-parent"}, {"spreadsheet_id": "allowed-parent", "_user_id": "caller-spoof", "organization_id": "caller-spoof", "workflow_id": "caller-spoof"}])
async def test_real_allowed_parent_preserves_requested_child_filter_and_trusted_caller(monkeypatch, entry, context):
    node_type = "automation-google-sheets"
    name, info = native_lookup(node_type, "read_sheet_data", {"spreadsheet_id": ["allowed-parent"], "sheet_name": ["allowed-child"]})
    resolved, admission, freshen, loader = io_boundaries(monkeypatch, node_type)
    result = await dispatch(entry, name, info, {"field": "sheet_name", "context": context, "page_token": "incoming-cursor", "search": "  Child  ", "user_id": "caller-spoof", "organization_id": "caller-spoof", "workflow_id": "caller-spoof"})
    assert result == {"options": [{"label": "Allowed", "value": "allowed-child"}], "next_page_token": "synthetic-next"}
    assert resolved.await_count == 2
    for call in resolved.await_args_list:
        assert call.args[:2] == (CREDENTIAL_ID, USER)
        assert call.kwargs == {"org_id": ORG, "workflow_id": WORKFLOW}
    admission.assert_awaited_once()
    assert admission.await_args.kwargs["organization_id"] == ORG
    assert admission.await_args.kwargs["workflow_id"] == WORKFLOW
    assert admission.await_args.kwargs["user_id"] == USER
    freshen.assert_awaited_once()
    assert freshen.await_args.kwargs["user_id"] == USER
    loader.assert_awaited_once()
    assert loader.await_args.kwargs["field_name"] == "sheet_name"
    assert loader.await_args.kwargs["context"]["spreadsheet_id"] == "allowed-parent"
    assert loader.await_args.kwargs["context"]["_user_id"] == USER
    assert loader.await_args.kwargs["page_token"] == "incoming-cursor"
    assert loader.await_args.kwargs["search"] == "Child"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["agent_tool", "cross_container"])
@pytest.mark.parametrize("context", [{"teamId": "allowed-parent"}, {"team_id": "allowed-parent"}, {"teamId": "allowed-parent", "team_id": "allowed-parent"}])
async def test_real_allowed_parent_aliases_preserve_dependent_loader(monkeypatch, entry, context):
    node_type = "automation-linear"
    name, info = native_lookup(node_type, "create_issue", {"teamId": ["allowed-parent"]})
    _, _, _, loader = io_boundaries(monkeypatch, node_type)
    result = await dispatch(entry, name, info, {"field": "stateId", "context": context})
    assert len(result["options"]) == 2
    assert loader.await_args.kwargs["field_name"] == "state_id"
    assert all(loader.await_args.kwargs["context"][key] == value for key, value in context.items())


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["agent_tool", "cross_container"])
@pytest.mark.parametrize("mode", ["unrestricted", "one_unrestricted_consumer", "no_context", "empty_context"])
async def test_real_unrestricted_and_missing_context_keep_native_semantics(monkeypatch, entry, mode):
    node_type = "automation-google-sheets"
    additional = ["write_sheet_data"] if mode == "one_unrestricted_consumer" else None
    scopes = {"spreadsheet_id": ["allowed-parent"]} if mode == "one_unrestricted_consumer" else None
    name, info = native_lookup(node_type, "read_sheet_data", scopes, additional)
    context = None if mode == "no_context" else {} if mode == "empty_context" else {"spreadsheet_id": "manual-other-parent"}
    if mode == "one_unrestricted_consumer":
        assert "spreadsheet_id" not in info["field_scopes"]
    _, _, _, loader = io_boundaries(monkeypatch, node_type)
    result = await dispatch(entry, name, info, {"field": "sheet_name", "context": context})
    assert len(result["options"]) == 2
    loader.assert_awaited_once()
    assert loader.await_args.kwargs["context"]["_user_id"] == USER


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["agent_tool", "cross_container"])
@pytest.mark.parametrize("context", [None, {}, {"teamId": ""}, {"issueId": "other-parent-issue"}, {"issue_id": "other-parent-issue"}, {"field_dependencies": {"stateId": None}, "field_scopes": {"teamId": []}}])
async def test_declared_scoped_parent_cannot_be_omitted_or_inferred_from_another_resource(monkeypatch, entry, context):
    node_type = "automation-linear"
    name, info = native_lookup(node_type, "create_issue", {"teamId": ["allowed-parent"]})
    assert info["field_dependencies"]["stateId"] == "teamId"
    boundaries = io_boundaries(monkeypatch, node_type)
    result = await dispatch(entry, name, info, {"field": "stateId", "context": context})
    assert result["success"] is False and "explicit allowed value" in result["error"]
    for boundary in boundaries:
        boundary.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["agent_tool", "cross_container"])
@pytest.mark.parametrize("parent", [None, "other-parent", "allowed-parent"])
async def test_declared_dependency_chain_enforces_locked_ancestor_before_loader(monkeypatch, entry, parent):
    """A trusted two-level metadata fixture exercises both real dispatchers."""
    node_type = "automation-google-sheets"
    name, info = native_lookup(node_type, "read_sheet_data", {"spreadsheet_id": ["allowed-parent"]})
    info["fields"]["dependent_field"] = "dependent_loader"
    info["field_dependencies"]["dependent_field"] = "sheet_name"
    context = {"sheet_name": "allowed-child"}
    if parent is not None:
        context["spreadsheet_id"] = parent
    boundaries = io_boundaries(monkeypatch, node_type)
    result = await dispatch(entry, name, info, {"field": "dependent_field", "context": context})
    if parent == "allowed-parent":
        assert len(result["options"]) == 2
        assert boundaries[-1].await_args.kwargs["field_name"] == "dependent_loader"
    else:
        assert result["success"] is False and "context scope" in result["error"].lower()
        for boundary in boundaries:
            boundary.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["agent_tool", "cross_container"])
async def test_unknown_requested_field_is_still_refused_before_io(monkeypatch, entry):
    node_type = "automation-google-sheets"
    name, info = native_lookup(node_type, "read_sheet_data", {"spreadsheet_id": ["allowed-parent"]})
    boundaries = io_boundaries(monkeypatch, node_type)
    result = await dispatch(entry, name, info, {"field": "undeclared_field", "context": {"spreadsheet_id": "allowed-parent"}})
    assert result["success"] is False and "Unknown field" in result["error"]
    for boundary in boundaries:
        boundary.assert_not_awaited()

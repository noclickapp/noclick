"""
Tests for the Submit External Form node.

Validates registration, config/schema shape, the workflow/form/form_fields
dropdowns (forms-only filtering + field metadata), and execute() — which submits
the selected form on another flow (form-submission-shaped payload, required-field
validation, recursion guard) and returns the triggered run's node outputs.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tests.mocks.mock_asyncpg import MockNativePool

from nodes.submit_external_form_node import (
    SubmitExternalFormNode,
    SubmitExternalFormConfig,
    SubmitExternalFormNodeConfig,
    _SUBMIT_FORM_DEPTH,
    _MAX_SUBMIT_FORM_DEPTH,
)
from nodes.core.registry import NODE_REGISTRY
from wss.handlers.workflow_execution_handler import WorkflowExecutionResult

WF_A = "11111111-1111-1111-1111-111111111111"
WF_B = "22222222-2222-2222-2222-222222222222"


def _make_node(workflow="wf-target", form="form-1", inputs=None, user_id="user-1"):
    config = SubmitExternalFormNodeConfig(
        config=SubmitExternalFormConfig(workflow=workflow, form=form, inputs=inputs or {})
    )
    node = SubmitExternalFormNode(
        node_id="sef-node",
        node_type="automation-submit-external-form",
        node_data={},
        config=config,
        sio=None,
        sid=None,
        workflow_id="wf-source",
        user_id=user_id,
    )
    node.emit = AsyncMock()
    return node


def _result(success=True, error=None, node_outputs=None, last_output_node_id=None):
    return WorkflowExecutionResult(
        execution_id="exec-1",
        workflow_id="wf-target",
        success=success,
        nodes_executed=3,
        duration=0.1,
        error=error,
        node_outputs=node_outputs or {},
        last_output_node_id=last_output_node_id,
    )


def _access(has_access):
    return SimpleNamespace(has_access=has_access)


FORM_NODE = {
    "id": "form-1",
    "type": "interface-form",
    "config": {
        "title": "Intake",
        "fields": [
            {"name": "email", "label": "Email", "type": "string", "required": True},
            {
                "name": "plan",
                "label": "Plan",
                "type": "select",
                "options": [{"label": "Pro", "value": "pro"}],
            },
            {"name": "api_key", "label": "Key", "type": "credential"},
        ],
    },
}


class TestRegistration:
    def test_registered_under_expected_key(self):
        assert NODE_REGISTRY["automation-submit-external-form"] is SubmitExternalFormNode

    def test_old_key_removed(self):
        assert "automation-trigger-flow" not in NODE_REGISTRY

    def test_config_model(self):
        assert SubmitExternalFormNode.get_config_model() is SubmitExternalFormNodeConfig

    def test_schema_shape(self):
        schema = SubmitExternalFormNode.get_config_schema()
        props = schema["$defs"]["SubmitExternalFormConfig"]["properties"]
        assert props["form"]["x-dynamic-options"]["depends_on"] == "workflow"
        assert props["inputs"]["ui:widget"] == "external_form_inputs"


class TestExecute:
    @pytest.mark.asyncio
    async def test_submits_form_with_submission_shaped_payload(self):
        node = _make_node(inputs={"email": "a@b.com", "plan": "pro", "blank": ""})
        node._load_form_node = AsyncMock(return_value=FORM_NODE)
        handler = MagicMock()
        handler.handle_execute = AsyncMock(
            return_value=_result(node_outputs={"n-last": {"ok": True}}, last_output_node_id="n-last")
        )
        node._build_execution_handler = AsyncMock(return_value=handler)

        out = await node.execute({"upstream": {"x": 1}})

        kwargs = handler.handle_execute.call_args.kwargs
        request = kwargs["request"]
        assert request.workflow_id == "wf-target"
        assert request.start_node_id == "form-1"  # starts at the form node
        assert kwargs["caller_user_id"] == "user-1"
        # Payload reproduces FormInputNode.execute()'s triggered output exactly:
        # metadata + fields schema + values spread at top level AND under "values".
        payload = request.inputs
        assert payload["type"] == "form_triggered"
        assert payload["status"] == "triggered"
        assert "timestamp" in payload
        assert payload["fields"] == FORM_NODE["config"]["fields"]
        assert payload["values"] == {"email": "a@b.com", "plan": "pro"}  # empty dropped
        assert payload["email"] == "a@b.com" and payload["plan"] == "pro"

        assert out["status"] == "completed"
        assert out["form"] == "form-1"
        assert out["submitted"] == {"email": "a@b.com", "plan": "pro"}
        assert out["output"] == {"ok": True}
        assert out["outputs"] == {"n-last": {"ok": True}}

    @pytest.mark.asyncio
    async def test_missing_required_field_blocks_submission(self):
        node = _make_node(inputs={"plan": "pro"})  # email (required) absent
        node._load_form_node = AsyncMock(return_value=FORM_NODE)
        handler = MagicMock()
        handler.handle_execute = AsyncMock(return_value=_result())
        node._build_execution_handler = AsyncMock(return_value=handler)

        with pytest.raises(ValueError, match="email"):
            await node.execute({})
        handler.handle_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_workflow_raises(self):
        node = _make_node(workflow="")
        with pytest.raises(ValueError):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_missing_form_raises(self):
        node = _make_node(form="")
        with pytest.raises(ValueError):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_missing_user_raises(self):
        node = _make_node(user_id=None)
        with pytest.raises(ValueError):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_failed_run_propagates_error(self):
        node = _make_node(inputs={"email": "a@b.com"})
        node._load_form_node = AsyncMock(return_value=None)
        handler = MagicMock()
        handler.handle_execute = AsyncMock(return_value=_result(success=False, error="boom"))
        node._build_execution_handler = AsyncMock(return_value=handler)
        with pytest.raises(RuntimeError, match="boom"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_recursion_limit_blocks_invocation(self):
        node = _make_node(inputs={"email": "a@b.com"})
        node._load_form_node = AsyncMock(return_value=None)
        handler = MagicMock()
        handler.handle_execute = AsyncMock(return_value=_result())
        node._build_execution_handler = AsyncMock(return_value=handler)

        token = _SUBMIT_FORM_DEPTH.set(_MAX_SUBMIT_FORM_DEPTH)
        try:
            with pytest.raises(RuntimeError, match="recursion limit"):
                await node.execute({})
        finally:
            _SUBMIT_FORM_DEPTH.reset(token)
        handler.handle_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_depth_incremented_during_nested_run_and_restored(self):
        node = _make_node(inputs={"email": "a@b.com"})
        node._load_form_node = AsyncMock(return_value=None)
        seen = {}

        async def fake_execute(**kwargs):
            seen["depth"] = _SUBMIT_FORM_DEPTH.get()
            return _result()

        handler = MagicMock()
        handler.handle_execute = AsyncMock(side_effect=fake_execute)
        node._build_execution_handler = AsyncMock(return_value=handler)

        await node.execute({})
        assert seen["depth"] == 1
        assert _SUBMIT_FORM_DEPTH.get() == 0


class TestRequiredFieldDetection:
    def test_missing_required_pure(self):
        fields = SubmitExternalFormNode._extract_form_fields(FORM_NODE)
        assert SubmitExternalFormNode._missing_required(fields, {"plan": "pro"}) == ["email"]
        assert SubmitExternalFormNode._missing_required(fields, {"email": "a@b.com"}) == []

    @pytest.mark.asyncio
    async def test_load_form_node_finds_form(self):
        node = _make_node()
        node._load_accessible_workflow_nodes = AsyncMock(
            return_value=[FORM_NODE, {"id": "x", "type": "automation-slack"}]
        )
        with patch("utils.database_pool.get_native_pool", return_value=MockNativePool()):
            found = await node._load_form_node(WF_A, "form-1")
        assert found is FORM_NODE

    @pytest.mark.asyncio
    async def test_load_form_node_none_when_inaccessible(self):
        node = _make_node()
        node._load_accessible_workflow_nodes = AsyncMock(return_value=None)
        with patch("utils.database_pool.get_native_pool", return_value=MockNativePool()):
            found = await node._load_form_node(WF_A, "form-1")
        assert found is None


class TestLoadFieldOptions:
    @pytest.mark.asyncio
    async def test_without_user_returns_empty(self):
        res = await SubmitExternalFormNode.load_field_options("workflow", {}, context={})
        assert res == {"options": [], "next_page_token": None}

    @pytest.mark.asyncio
    async def test_lists_accessible_workflows(self):
        pool = MockNativePool({"SELECT id, name FROM workflows": [{"id": WF_A, "name": "Flow One"}]})
        with patch("utils.access_control.get_accessible_resources",
                   AsyncMock(return_value=[{"resource_id": WF_A}])), \
                patch("utils.database_pool.get_native_pool", return_value=pool):
            res = await SubmitExternalFormNode.load_field_options("workflow", {}, context={"_user_id": "u1"})
        assert res["options"] == [{"value": WF_A, "label": "Flow One"}]

    @pytest.mark.asyncio
    async def test_form_list_only_form_triggers(self):
        pool = MockNativePool({"SELECT workflow FROM workflows": {"workflow": {"nodes": [
            FORM_NODE,
            {"id": "wh", "type": "trigger-webhook", "config": {}},
            {"id": "a1", "type": "automation-slack", "config": {}},
        ]}}})
        with patch("utils.access_control.check_resource_access", AsyncMock(return_value=_access(True))), \
                patch("utils.database_pool.get_native_pool", return_value=pool):
            res = await SubmitExternalFormNode.load_field_options(
                "form", {}, context={"_user_id": "u1", "workflow": WF_A}
            )
        assert res["options"] == [{"value": "form-1", "label": "Intake"}]  # only the form, labeled by title

    @pytest.mark.asyncio
    async def test_form_list_blocked_without_access(self):
        pool = MockNativePool()
        with patch("utils.access_control.check_resource_access", AsyncMock(return_value=_access(False))), \
                patch("utils.database_pool.get_native_pool", return_value=pool):
            res = await SubmitExternalFormNode.load_field_options(
                "form", {}, context={"_user_id": "u1", "workflow": WF_A}
            )
        assert res["options"] == []
        pool.fetchrow.assert_not_called()

    @pytest.mark.asyncio
    async def test_form_fields_carry_metadata_and_skip_credentials(self):
        pool = MockNativePool({"SELECT workflow FROM workflows": {"workflow": {"nodes": [FORM_NODE]}}})
        with patch("utils.access_control.check_resource_access", AsyncMock(return_value=_access(True))), \
                patch("utils.database_pool.get_native_pool", return_value=pool):
            res = await SubmitExternalFormNode.load_field_options(
                "form_fields", {}, context={"_user_id": "u1", "workflow": WF_A, "form": "form-1"}
            )
        opts = {o["value"]: o for o in res["options"]}
        assert set(opts) == {"email", "plan"}  # credential field skipped
        assert opts["email"]["metadata"]["required"] is True
        assert opts["email"]["metadata"]["type"] == "string"
        assert opts["plan"]["metadata"]["type"] == "select"
        assert opts["plan"]["metadata"]["options"] == [{"label": "Pro", "value": "pro"}]

    @pytest.mark.asyncio
    async def test_form_fields_parse_json_string_fields(self):
        import json
        # Legacy pre-merge type — pins that _is_form_node resolves the alias.
        form_node = {
            "id": "form-1",
            "type": "trigger-form-input",
            "config": {"fields": json.dumps([{"name": "x", "label": "X", "type": "string"}])},
        }
        pool = MockNativePool({"SELECT workflow FROM workflows": {"workflow": {"nodes": [form_node]}}})
        with patch("utils.access_control.check_resource_access", AsyncMock(return_value=_access(True))), \
                patch("utils.database_pool.get_native_pool", return_value=pool):
            res = await SubmitExternalFormNode.load_field_options(
                "form_fields", {}, context={"_user_id": "u1", "workflow": WF_A, "form": "form-1"}
            )
        assert [o["value"] for o in res["options"]] == ["x"]

    @pytest.mark.asyncio
    async def test_form_fields_need_workflow_and_form(self):
        res = await SubmitExternalFormNode.load_field_options(
            "form_fields", {}, context={"_user_id": "u1", "workflow": WF_A}
        )
        assert res == {"options": [], "next_page_token": None}

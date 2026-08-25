"""
Submit External Form node.

Triggers a *different* NoClick flow by submitting one of its form triggers — the
node renders the target form's fields, the user fills them (values may contain
{{references}} to upstream data), and on execute the filled values are injected
at the form node exactly as a real form submission would be. The triggered flow
then runs from that form, and this node returns the run's node outputs.

Why forms specifically: a form node (``interface-form``) already declares
a typed, named field signature, so it *is* the input contract. Reusing it means
the triggered flow's existing ``{{form.field}}`` references resolve identically
whether the form was submitted by a user or by this node — no new payload shape
to invent. This is the same mechanism the agent workflow-tool uses (inject named
arguments as the entry node's output, return the subgraph's outputs).

Config fields:
- ``workflow`` — the target flow (owned / shared / org-shared).
- ``form`` — an ``interface-form`` node in that flow (the dropdown lists forms
  only); execution starts here.
- ``inputs`` — ``{field_name: value}`` for that form's fields, edited via the
  ``external_form_inputs`` widget which loads the field list from the selected form.

All three are literal references stored in config, so the node stays copy-pastable
across canvases (the clipboard parser only rewrites ``{{nodeId.path}}`` templates).
"""

import logging
import time
from contextvars import ContextVar
from typing import Dict, Any, List, Optional, Type

from pydantic import BaseModel, Field

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

# The only node type this node targets: a form declares named fields. Compare
# stored graph types via _is_form_node — saved graphs may carry the legacy
# trigger-form-input type, which resolves here through the registry aliases.
FORM_TRIGGER_TYPE = "interface-form"


def _is_form_node(node: Dict[str, Any]) -> bool:
    from nodes.core.registry import resolve_node_type
    return resolve_node_type(node.get("type")) == FORM_TRIGGER_TYPE

# Credential-type form fields are owner-scoped and not meaningfully forwardable
# across flows, so they're excluded from the rendered inputs.
_SKIP_FIELD_TYPE = "credential"

# Depth of nested Submit External Form invocations within a single run chain. A
# flow that submits a form on a flow that submits a form… would otherwise recurse
# without bound and burn credits. asyncio.create_task (used by the executor's
# spawn()) copies the current context, so this propagates from a node into the
# flow it triggers.
_SUBMIT_FORM_DEPTH: ContextVar[int] = ContextVar("submit_external_form_depth", default=0)
_MAX_SUBMIT_FORM_DEPTH = 8


class SubmitExternalFormConfig(BaseModel):
    """Configuration for the Submit External Form node."""

    workflow: str = Field(
        "",
        title="Workflow",
        description="The flow whose form to submit",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "workflow",
                "placeholder": "Select a flow...",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a workflow ID",
            }
        },
    )

    form: str = Field(
        "",
        title="Form",
        description="The form (trigger) in that flow to submit",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "form",
                "placeholder": "Select a form...",
                "depends_on": "workflow",
                "searchable": True,
                "allow_custom": True,
                "custom_placeholder": "Or paste a form node ID",
            }
        },
    )

    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        title="Form Inputs",
        description="Values for the selected form's fields",
        json_schema_extra={"ui:widget": "external_form_inputs"},
    )


class SubmitExternalFormNodeConfig(NodeConfig[SubmitExternalFormConfig, None]):
    """Full configuration for the Submit External Form node (no credentials needed)."""

    pass


class SubmitExternalFormNode(WorkflowNode):
    """
    Submit a form belonging to another flow, triggering that flow.

    Fills the target form's fields with the configured values and runs the
    target flow from the form node (forward-only, exactly like a real submission),
    then returns the triggered run's node outputs.
    """

    edit_examples = [
        "Submit the 'New lead' form in my CRM flow",
        "Trigger the onboarding flow by submitting its intake form",
        "Run another flow by filling in its form",
        "Change which flow's form this submits",
        "Map the email field to the form's email input",
        "Hand off to the enrichment flow's form and use its result",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return SubmitExternalFormNodeConfig

    # ------------------------------------------------------------------
    # Dynamic dropdown / widget options
    # ------------------------------------------------------------------

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Populate the ``workflow`` / ``form`` dropdowns and the form field list.

        ``context["_user_id"]`` scopes results to accessible flows; ``form`` and
        ``form_fields`` additionally read ``context["workflow"]`` (and, for fields,
        ``context["form"]``) so they reflect the current selection.
        """
        ctx = context or {}
        user_id = ctx.get("_user_id")
        if not user_id:
            return {"options": [], "next_page_token": None}

        from utils.database_pool import get_native_pool

        if field_name == "workflow":
            async with get_native_pool().acquire() as conn:
                options = await cls._list_accessible_workflows(conn, user_id, search)
            return {"options": options, "next_page_token": None}

        workflow_id = (ctx.get("workflow") or "").strip()

        if field_name == "form":
            if not workflow_id:
                return {"options": [], "next_page_token": None}
            async with get_native_pool().acquire() as conn:
                options = await cls._list_forms(conn, user_id, workflow_id, search)
            return {"options": options, "next_page_token": None}

        if field_name == "form_fields":
            form_id = (ctx.get("form") or "").strip()
            if not workflow_id or not form_id:
                return {"options": [], "next_page_token": None}
            async with get_native_pool().acquire() as conn:
                options = await cls._list_form_fields(conn, user_id, workflow_id, form_id)
            return {"options": options, "next_page_token": None}

        return {"options": [], "next_page_token": None}

    @classmethod
    async def _list_accessible_workflows(
        cls, conn, user_id: str, search: Optional[str]
    ) -> List[Dict[str, str]]:
        """List flows the user can access as {value: id, label: name}.

        Access (owned + direct/org shares) comes from the canonical
        utils.access_control.get_accessible_resources.
        """
        import uuid as uuid_module
        from utils.access_control import get_accessible_resources

        accessible = await get_accessible_resources(conn, user_id, "workflow")
        ids = []
        for entry in accessible:
            try:
                ids.append(uuid_module.UUID(str(entry["resource_id"])))
            except (ValueError, AttributeError, KeyError):
                continue
        if not ids:
            return []

        params: List[Any] = [ids]
        search_clause = ""
        if search:
            params.append(f"%{search}%")
            search_clause = " AND name ILIKE $2"

        rows = await conn.fetch(
            f"""
            SELECT id, name FROM workflows
            WHERE id = ANY($1::uuid[]) AND deleted_at IS NULL{search_clause}
            ORDER BY updated_at DESC
            LIMIT 50
            """,
            *params,
        )
        return [
            {"value": str(row["id"]), "label": row["name"] or str(row["id"])}
            for row in rows
        ]

    @classmethod
    async def _load_accessible_workflow_nodes(
        cls, conn, user_id: str, workflow_id: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Return the target flow's nodes if the user can access it, else None.

        Gated by the canonical check_resource_access (owned + direct + org +
        folder shares) so node ids never leak from flows the user can't see.
        """
        import uuid as uuid_module
        from utils.access_control import check_resource_access

        try:
            wf_uuid = uuid_module.UUID(str(workflow_id))
        except (ValueError, AttributeError):
            return None

        access = await check_resource_access(conn, user_id, "workflow", str(wf_uuid))
        if not access.has_access:
            return None

        row = await conn.fetchrow(
            "SELECT workflow FROM workflows WHERE id = $1 AND deleted_at IS NULL",
            wf_uuid,
        )
        if not row:
            return None
        workflow_data = row["workflow"] or {}
        return workflow_data.get("nodes", []) if isinstance(workflow_data, dict) else []

    @classmethod
    async def _list_forms(
        cls, conn, user_id: str, workflow_id: str, search: Optional[str]
    ) -> List[Dict[str, str]]:
        """List the form-trigger nodes of an accessible flow."""
        nodes = await cls._load_accessible_workflow_nodes(conn, user_id, workflow_id)
        if not nodes:
            return []

        search_lower = search.lower() if search else None
        options: List[Dict[str, str]] = []
        for node in nodes:
            if not _is_form_node(node):
                continue
            node_id = node.get("id")
            if not node_id:
                continue
            config = node.get("config") or node.get("data") or {}
            label = cls._form_label(config)
            if search_lower and search_lower not in label.lower():
                continue
            options.append({"value": str(node_id), "label": label})
        return options

    @classmethod
    async def _list_form_fields(
        cls, conn, user_id: str, workflow_id: str, form_id: str
    ) -> List[Dict[str, Any]]:
        """Return the selected form's fields as options carrying field metadata.

        Each option is {value: field_name, label, metadata: {type, required,
        description, options}} so the external_form_inputs widget can render the
        right input per field.
        """
        nodes = await cls._load_accessible_workflow_nodes(conn, user_id, workflow_id)
        if not nodes:
            return []

        form_node = next(
            (
                n
                for n in nodes
                if n.get("id") == form_id and _is_form_node(n)
            ),
            None,
        )
        if not form_node:
            return []

        options: List[Dict[str, Any]] = []
        for field in cls._extract_form_fields(form_node):
            name = field.get("name")
            if not name or field.get("type") == _SKIP_FIELD_TYPE:
                continue
            options.append(
                {
                    "value": str(name),
                    "label": str(field.get("label") or name),
                    "metadata": {
                        "type": field.get("type", "string"),
                        "required": bool(field.get("required", False)),
                        "description": field.get("description") or "",
                        "options": field.get("options") or [],
                    },
                }
            )
        return options

    @staticmethod
    def _form_label(config: Dict[str, Any]) -> str:
        """Best-effort human label for a form node (title, else node label, else 'Form')."""
        if not isinstance(config, dict):
            return "Form"
        for key in ("title", "label"):
            value = config.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return "Form"

    @staticmethod
    def _extract_form_fields(form_node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse a form node's ``fields`` (stored as a list, or a JSON string)."""
        config = form_node.get("config") or form_node.get("data") or {}
        fields = config.get("fields") if isinstance(config, dict) else None
        if isinstance(fields, str):
            import json

            try:
                fields = json.loads(fields)
            except (ValueError, TypeError):
                return []
        if not isinstance(fields, list):
            return []
        return [f for f in fields if isinstance(f, dict)]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _build_execution_handler(self):
        """Build a WorkflowExecutionHandler to run the target flow.

        Mirrors the webhook entry point (utils.webhook_routes
        ._execute_workflow_with_relay): a fresh handler is context-independent,
        so it works in the api container or the webhook worker. Events for the
        triggered run are delivered via its own ExecutionRelay.
        """
        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

        handler = WorkflowExecutionHandler(self.sio)
        await handler.setup_user("")  # initialize the shared DB pool (no socket session)
        return handler

    async def _load_form_node(self, workflow_id: str, form_id: str) -> Optional[Dict[str, Any]]:
        """Load the target form node (access-gated), or None if it can't be loaded —
        in which case handle_execute later surfaces the access/not-found error."""
        from utils.database_pool import get_native_pool

        pool = get_native_pool()
        async with pool.acquire() as conn:
            nodes = await self._load_accessible_workflow_nodes(conn, self.user_id, workflow_id)
        if not nodes:
            return None
        return next(
            (n for n in nodes if n.get("id") == form_id and _is_form_node(n)),
            None,
        )

    @classmethod
    def _missing_required(cls, fields: List[Dict[str, Any]], values: Dict[str, Any]) -> List[str]:
        """Names of required (non-credential) fields with no value."""
        missing = []
        for field in fields:
            name = field.get("name")
            if not name or field.get("type") == _SKIP_FIELD_TYPE:
                continue
            if field.get("required") and values.get(name) in (None, ""):
                missing.append(str(name))
        return missing

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"[SubmitExternalFormNode] Executing node {self.node_id}")

        node_config = self.config
        if not node_config or not isinstance(node_config, SubmitExternalFormNodeConfig):
            raise ValueError(f"[SubmitExternalFormNode] Configuration required for node {self.node_id}")

        config = node_config.config
        target_workflow_id = (config.workflow or "").strip()
        target_form_id = (config.form or "").strip()

        if not target_workflow_id:
            raise ValueError("[SubmitExternalFormNode] No target flow selected")
        if not target_form_id:
            raise ValueError("[SubmitExternalFormNode] No form selected in the target flow")
        if not self.user_id:
            raise ValueError("[SubmitExternalFormNode] An authenticated user is required to submit a form")

        # Filled field values — references inside them were already resolved by the
        # engine before execute(). Drop empties so required-field checks are honest.
        raw_values = config.inputs if isinstance(config.inputs, dict) else {}
        values = {k: v for k, v in raw_values.items() if v not in (None, "")}

        # Load the form node once: for required-field validation AND its field
        # schema (carried in the payload so the form node's output is identical to
        # a real submission). None means the user can't access it — handle_execute
        # then surfaces the access/not-found error.
        form_node = await self._load_form_node(target_workflow_id, target_form_id)
        fields_schema = self._extract_form_fields(form_node) if form_node else []

        missing = self._missing_required(fields_schema, values)
        if missing:
            raise ValueError(
                f"[SubmitExternalFormNode] Missing required form field(s): {', '.join(missing)}"
            )

        depth = _SUBMIT_FORM_DEPTH.get()
        if depth >= _MAX_SUBMIT_FORM_DEPTH:
            raise RuntimeError(
                f"[SubmitExternalFormNode] recursion limit ({_MAX_SUBMIT_FORM_DEPTH}) reached — "
                "a Submit External Form chain is cycling"
            )

        from wss.receiver.client_events import WorkflowExecuteRequest

        handler = await self._build_execution_handler()

        # Reproduce FormInterfaceNode.execute()'s triggered output exactly. The form
        # node is the start node, so _inject_inputs sets its mockedOutput to this
        # payload (execute is bypassed); matching the shape keys means the form
        # node's output panel, reference suggestions, and both {{form.field}} and
        # {{form.values.field}} references behave like a real submission.
        payload = {
            "type": "form_triggered",
            "status": "triggered",
            "timestamp": time.time(),
            "fields": fields_schema,
            "values": values,
            **values,
        }

        request = WorkflowExecuteRequest(
            workflow_id=target_workflow_id,
            start_node_id=target_form_id,
            inputs=payload,
        )

        await self.emit({
            "type": "submit-external-form",
            "status": "submitting",
            "workflow_id": target_workflow_id,
            "form": target_form_id,
            "submitted": values,
        })

        token = _SUBMIT_FORM_DEPTH.set(depth + 1)
        try:
            result = await handler.handle_execute(
                sid=self.sid or "",
                request=request,
                caller_user_id=self.user_id,
            )
        finally:
            _SUBMIT_FORM_DEPTH.reset(token)

        if not result.success:
            raise RuntimeError(
                result.error or f"[SubmitExternalFormNode] triggered flow {target_workflow_id} failed"
            )

        node_outputs = result.node_outputs or {}
        primary = node_outputs.get(result.last_output_node_id) if result.last_output_node_id else None

        output = {
            "type": "submit-external-form",
            "status": "completed",
            "workflow_id": target_workflow_id,
            "form": target_form_id,
            "execution_id": result.execution_id,
            "nodes_executed": result.nodes_executed,
            "submitted": values,
            "output": primary,
            "outputs": node_outputs,
        }

        logger.info(
            f"[SubmitExternalFormNode] Submitted form {target_form_id} on flow {target_workflow_id} "
            f"(execution {result.execution_id}, {result.nodes_executed} nodes)"
        )
        await self.emit(output)
        return output

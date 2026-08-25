# The unified form node: an interface block, a workflow entry point, and a
# persistent value store in one. Renders as a form on the canvas/interface grid,
# mints a public webhook URL (https://{id}.hooks.example.test) serving a standalone form
# page whose POST starts the workflow, and persists in-editor edits to
# config.values so every run outputs them to downstream nodes (both
# {{nodeId.field}} and {{nodeId.values.field}} resolve). Absorbed the former
# trigger-form-input and interface-config-form nodes (2026-07 merges) — those
# types now resolve here via LEGACY_NODE_TYPE_ALIASES.

import json
import time
import logging
from typing import Dict, Any, Optional, Union, Type, List, Literal
from pydantic import BaseModel, Field, field_validator

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


def parse_form_fields(v: Any) -> Any:
    """Normalize a form `fields` value to a list.

    Frontend/MCP/AI-builder write paths may store `fields` as a JSON-encoded
    string rather than an array. Returns the parsed list, [] if the string
    isn't valid JSON list, or the value unchanged when it isn't a string.
    """
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
        return []
    return v


class FormField(BaseModel):
    """Definition of a single form input field."""
    name: str = Field(
        ...,
        min_length=1,
        pattern=r'^[a-zA-Z_][a-zA-Z0-9_]*$',
        title="Field Name",
        description="Field identifier (must be valid identifier, used in workflow references)"
    )
    type: Literal['string', 'number', 'boolean', 'object', 'array', 'list', 'select', 'schedule', 'credential', 'file'] = Field(
        default='string',
        title="Type",
        description="Data type of the field. 'file' collects an uploaded file (any type — PDF, image, audio, video, arbitrary data) and yields its public URL in the submission payload. 'list' is a multi-value string list; 'schedule' renders the schedule builder."
    )
    label: str = Field(
        default="",
        title="Label",
        description="Display label shown to users"
    )
    description: str = Field(
        default="",
        title="Description",
        description="Help text shown below the field"
    )
    required: bool = Field(
        default=False,
        title="Required",
        description="Whether this field must be provided"
    )
    options: Optional[List[Union[str, Dict[str, str]]]] = Field(
        default=None,
        title="Options",
        description="Available options for select/dropdown fields. Either strings or {label, value} objects."
    )

    @field_validator('options', mode='before')
    @classmethod
    def normalize_options(cls, v: Any) -> Any:
        """Accept both string[] and {label, value}[] formats for options."""
        if v is None:
            return v
        if not isinstance(v, list):
            return v
        result = []
        for opt in v:
            if isinstance(opt, str):
                result.append(opt)
            elif isinstance(opt, dict):
                # Keep as-is; serialized as {label, value} for frontend
                result.append(opt)
            else:
                result.append(str(opt))
        return result
    credential_type: Optional[str] = Field(
        default=None,
        title="Credential Type",
        description="Credential type to collect (e.g., 'google_sheets_oauth'). Only used when type is 'credential'."
    )
    default: Optional[str] = Field(
        default=None,
        title="Default Value",
        description="Default value if no persisted value exists"
    )

    @field_validator('default', mode='before')
    @classmethod
    def coerce_default_to_str(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            return v
        # Arrays/dicts (e.g. list-type field defaults stored as JSON arrays) → JSON string
        return json.dumps(v)


class FormConfig(BaseModel):
    """Configuration for the form node."""

    # Webhook fields (auto-populated when node is loaded)
    webhook_id: Optional[str] = Field(
        default=None,
        title="Webhook ID",
        description="Auto-generated webhook ID (read-only)",
        json_schema_extra={"ui:widget": "readonly", "ui:hidden": True}
    )
    webhook_url: Optional[str] = Field(
        default=None,
        title="Form URL",
        description="Public URL where the form is accessible",
        # ui:widget="webhook" tells the system to use WebhookManager for this field
        # ui:loadValue triggers the backend to load the value on field render
        # ui:copyable adds a copy button to the field
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True}
    )
    relay_connected: Optional[bool] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True}
    )
    is_production: Optional[bool] = Field(
        default=None,
        json_schema_extra={"ui:hidden": True}
    )
    # Form configuration
    title: Optional[str] = Field(
        default="",
        title="Form Title",
        description="Title shown at the top of the form"
    )
    description: Optional[str] = Field(
        default="",
        title="Form Description",
        description="Describe what this form is for (shown to users)"
    )
    fields: List[FormField] = Field(
        default_factory=list,
        title="Form Fields",
        description="Input fields shown in the form",
        json_schema_extra={"ui:widget": "form_fields"}
    )
    # Persistent central value store (absorbed from interface-config-form):
    # in-editor edits to the form block write here (Valtio/YJS, auto-saved with
    # the workflow) and every run outputs these values to downstream nodes.
    values: Optional[Dict[str, Any]] = Field(
        default=None,
        title="Stored Values",
        description="Persisted field values, editable in the form block",
        json_schema_extra={"ui:hidden": True}
    )

    @field_validator('fields', mode='before')
    @classmethod
    def parse_fields_json(cls, v: Any) -> Any:
        """Parse JSON string to list — frontend/MCP may store fields as a JSON string."""
        return parse_form_fields(v)

    @field_validator('values', mode='before')
    @classmethod
    def parse_values_json(cls, v: Any) -> Any:
        """Accept a JSON-string dict — some write paths serialize values."""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            return None
        return v


class FormInterfaceNodeConfig(NodeConfig[FormConfig, None]):
    """Full configuration for the form node (no credentials)."""
    pass


def persisted_form_values(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    """The node's central value store: stored config.values over field defaults.

    Works on the RAW config dict (handles both nested {config: {...}} and flat
    shapes, JSON-string tolerance) so both execute() and the classmethod
    resolve_trigger_payload() hook can share it.
    """
    raw = raw_config or {}
    inner = raw.get('config', raw) if isinstance(raw, dict) else {}
    if not isinstance(inner, dict):
        return {}

    stored = inner.get('values', {})
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except (json.JSONDecodeError, ValueError):
            stored = {}
    if not isinstance(stored, dict):
        stored = {}

    values: Dict[str, Any] = {}
    for field in parse_form_fields(inner.get('fields', [])) or []:
        if not isinstance(field, dict):
            continue
        name = field.get('name')
        if not name:
            continue
        if name in stored:
            values[name] = stored[name]
        elif field.get('default') is not None:
            values[name] = field['default']
    return values


class FormInterfaceNode(WorkflowNode):
    """Unified form node — interface block, public-link entry point, and
    persistent value store in one.

    Submissions reach it three ways, all yielding the same flattened output so
    downstream nodes reference ``{{nodeId.fieldName}}`` regardless of path:
    1. In-editor/interface FormBlock submit (socket; values injected as
       mockedOutput, execute is bypassed)
    2. Public form URL POST (webhook route sets ``_triggerPayload``;
       resolve_trigger_payload folds the persisted store under the payload)
    3. SDK ``workflow.execute`` with inputs targeted at this node

    Independent of submissions, in-editor edits persist to ``config.values``
    (absorbed from interface-config-form) and every run outputs them — both
    ``{{nodeId.field}}`` and the legacy ``{{nodeId.values.field}}`` resolve.
    """

    grid_layout = {"defaultW": 5, "defaultH": 5, "minW": 3, "minH": 3}
    edit_examples = [
        "Add fields to collect user email and company name",
        "Make this form publicly accessible with a shareable link",
        "Change the form title and description for clarity",
        "Add a dropdown select field with predefined options",
        "Make all fields required for form submission",
        "Add a schedule or multi-value list field with a default value",
        "Create a settings form whose values feed downstream nodes",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return FormInterfaceNodeConfig

    def _get_fields_schema(self) -> List[Dict[str, Any]]:
        """Field definitions from config, for display in the output panel."""
        if not self.config or not self.config.config:
            return []
        return [f.model_dump() for f in self.config.config.fields]

    @classmethod
    def resolve_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Public-URL POST: fold the persisted value store under the submission.

        With no persisted values (every pre-merge form) the payload passes
        through untouched. With a store, submission keys win on conflicts and
        the merged set is also nested under ``values`` for legacy references.
        """
        persisted = persisted_form_values(config)
        if not persisted:
            return payload
        submission = payload if isinstance(payload, dict) else {}
        return {**persisted, "values": {**persisted, **submission}, **submission}

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Output the persisted value store merged with any submitted values.

        With neither (schema mode) the field definitions still go out so the
        output panel can display expected variables pre-run.
        """
        fields_schema = self._get_fields_schema()
        persisted = persisted_form_values(self.node_data or {})
        has_inputs = bool(inputs)

        # When triggered via SDK config overrides (e.g. execution.runNodesInBackground
        # with config: { domain: "..." }), field values land flat in the node's config,
        # not in the execution inputs dict. Fall back to reading them from raw config.
        if not has_inputs and self.config and self.config.config:
            field_names = {f.name for f in self.config.config.fields}
            raw = self.node_data or {}
            config_values = {k: v for k, v in raw.items() if k in field_names and v}
            if config_values:
                inputs = {"values": config_values, **config_values}
                has_inputs = True

        # Nested `values`: persisted store overlaid with what was submitted, so
        # legacy {{nodeId.values.field}} references resolve on every path.
        input_values = inputs.get("values") if isinstance(inputs.get("values"), dict) else None
        submitted = input_values if input_values is not None else {
            k: v for k, v in inputs.items()
            if k not in ("type", "status", "timestamp", "fields", "values")
        }
        values_out = {**persisted, **submitted}

        output = {
            "type": "form_triggered" if has_inputs else "form_schema",
            "status": "triggered" if has_inputs else "schema",
            "timestamp": time.time(),
            # Include field definitions for output panel display
            "fields": fields_schema,
            "values": values_out,
            # Flat keys so downstream nodes reference {{nodeId.fieldName}} directly;
            # submitted values win over the persisted store on conflicts.
            **persisted,
            **inputs,
        }

        await self.emit(output)
        logger.info(
            f"[FormInterfaceNode] Form {'triggered' if has_inputs else 'schema'} "
            f"with {len(fields_schema)} fields, {len(persisted)} persisted values"
        )
        return output

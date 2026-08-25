"""
Abstract base class for workflow nodes.

Defines the interface that all workflow nodes must implement.
Each node type (Telegram, Agent, etc.) should inherit from this class.
"""

import json
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import (
    TYPE_CHECKING,
    Callable,
    ClassVar,
    Dict,
    Any,
    Optional,
    List,
    TypedDict,
    Type,
    Union,
    TypeVar,
    Generic,
)
from pydantic import BaseModel, TypeAdapter, Field, ValidationError
import logging

if TYPE_CHECKING:
    from nodes.core.connection_evidence import ConnectionEvidence
    from nodes.core.oauth_scopes import ScopeRegistry

logger = logging.getLogger(__name__)


def clean_config_empty_strings(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize empty-string config values to None — the transform every
    execution path applies before parsing (an empty text input means "unset").
    Validation layers must apply the same transform, so they judge the value
    the runtime will actually parse; otherwise an empty optional field can pass
    validation and become an invalid ``None`` at execution time."""
    return {k: (None if v == '' else v) for k, v in (config or {}).items()}


def _config_target_and_members(config_data: Dict[str, Any], config_model: Any):
    """Resolve where the operation fields live (flat dict, or nested under
    'config' for NodeConfig wrappers) and which model(s) describe them —
    a plain BaseModel, Union members, or Annotated[Union, Discriminator]."""
    import typing

    inner = config_data.get('config') if isinstance(config_data.get('config'), dict) else None
    if inner is not None and hasattr(config_model, 'model_fields'):
        config_field = config_model.model_fields.get('config')
        if not config_field:
            return config_data, []
        annotation = config_field.annotation
        target = inner
    else:
        annotation = config_model
        target = config_data

    models: list = []
    if hasattr(annotation, 'model_fields'):
        models = [annotation]
    else:
        if typing.get_origin(annotation) is typing.Annotated:
            annotation = typing.get_args(annotation)[0]
        if typing.get_origin(annotation) is typing.Union:
            models = [a for a in typing.get_args(annotation) if hasattr(a, 'model_fields')]
    return target, models


@lru_cache(maxsize=None)
def _rejected_unset_fields(model: Any):
    """Among a config model's DEFAULTED fields: (names rejecting None, names
    rejecting ""). A defaulted field that rejects an unset marker can only
    crash on it — the runtime reading of that marker is "use the default"."""
    rejects_none, rejects_empty = set(), set()
    for name, finfo in model.model_fields.items():
        if finfo.is_required():
            continue
        try:
            adapter = TypeAdapter(finfo.annotation)
        except Exception:
            continue
        for marker, bucket in ((None, rejects_none), ('', rejects_empty)):
            try:
                adapter.validate_python(marker)
            except Exception:
                bucket.add(name)
    return frozenset(rejects_none), frozenset(rejects_empty)


def _coerce_str_fields(config_data: Dict[str, Any], config_model: type) -> None:
    """
    In-place coerce non-str values to str for fields typed as str.

    YJS/JSON/XML layers often convert string values to native types
    (e.g., "5" → 5, "" → None, "" → false). Pydantic v2 rejects
    non-str values for str fields, so we coerce them before validation.

    Handles both flat dicts and nested {"config": {...}} structures
    used by NodeConfig subclasses, including discriminated unions.
    """
    target, models = _config_target_and_members(config_data, config_model)
    if not models:
        return

    # Collect str fields and their defaults across all union members
    str_field_defaults: Dict[str, str] = {}
    # Collect int/float fields with concrete defaults (to restore None → default)
    # Handles '' from frontend that _resolve_credentials converts to None
    num_field_defaults: Dict[str, Any] = {}
    for model in models:
        for name, f in model.model_fields.items():
            if f.annotation is str and name not in str_field_defaults:
                str_field_defaults[name] = f.default if isinstance(f.default, str) else ""
            elif f.annotation in (int, float) and name not in num_field_defaults:
                if isinstance(f.default, (int, float)):
                    num_field_defaults[name] = f.default

    for key, default in str_field_defaults.items():
        if key not in target:
            continue
        v = target[key]
        if v is None:
            target[key] = default
        elif isinstance(v, bool):
            target[key] = str(v).lower()
        elif isinstance(v, float) and v == int(v):
            target[key] = str(int(v))
        elif isinstance(v, (int, float)):
            target[key] = str(v)

    for key, default in num_field_defaults.items():
        if key in target and target[key] is None:
            target[key] = default


def _drop_rejected_unset_markers(target: Dict[str, Any], models: list) -> None:
    """Drop None/"" values that the resolved field annotation rejects but has
    a default for. Only values that would otherwise FAIL parsing are touched,
    so this can only turn a guaranteed error into the field's default — a
    field that accepts the marker keeps it byte-for-byte.

    With multiple candidate members (undiscriminated union), a key is dropped
    only when EVERY member declaring it rejects the value — a value some
    member accepts must survive for that member to receive."""
    if not target or not models:
        return
    op = target.get('operation')
    if op is not None and len(models) > 1:
        matched = [
            m for m in models
            if m.model_fields.get('operation') is not None
            and m.model_fields['operation'].default == op
        ]
        models = matched or models
    for key in list(target.keys()):
        v = target.get(key)
        if v is not None and v != '':
            continue
        declaring = [m for m in models if key in m.model_fields]
        if not declaring:
            continue
        idx = 0 if v is None else 1
        if all(key in _rejected_unset_fields(m)[idx] for m in declaring):
            del target[key]


def runtime_config_view(config_data: Dict[str, Any], config_model: Any) -> Dict[str, Any]:
    """The config exactly as the runtime parse sees it: empty strings cleaned
    to None, str fields coerced back, and rejected unset markers dropped so
    defaulted fields fall back to their defaults instead of dying on a
    None/"" they can't hold. ``parse_config`` and every validator judge THIS
    view, so build-time verdicts and run-time behavior cannot diverge
    (Gmail validation regression class). Pure — never mutates the input."""
    out = dict(config_data or {})
    if isinstance(out.get('config'), dict):
        out['config'] = dict(out['config'])
    target, models = _config_target_and_members(out, config_model)
    cleaned = clean_config_empty_strings(target)
    target.clear()
    target.update(cleaned)
    _coerce_str_fields(out, config_model)
    _drop_rejected_unset_markers(target, models)
    return out


@lru_cache(maxsize=None)
def _cached_type_adapter(config_model: Any) -> TypeAdapter:
    """Return a process-cached TypeAdapter for a node config model.

    Constructing a TypeAdapter triggers full Pydantic core-schema generation.
    For nodes whose config is a large discriminated union (100+ operations)
    this costs seconds and runs synchronously on the event loop. Config models
    are defined once at import and never change, so the adapter is built once
    per model and reused across schema generation, validation, and parsing.
    """
    return TypeAdapter(config_model)


def _hoist_optional_enums(schema: Any) -> None:
    """Surface enums that Pydantic nests inside Optional[Literal[...]] anyOf wrappers.

    The frontend only renders a dropdown from a top-level `enum` key, so an
    Optional[Literal] field silently falls through to a plain text input.
    Hoist the enum (and mark it searchable, which keeps {{reference}} drops
    and free typing working) for the exact two-member string|null pattern.
    Validation is unaffected: the nested anyOf enum was already enforced.
    """
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            for prop in props.values():
                if not isinstance(prop, dict) or "enum" in prop:
                    continue
                any_of = prop.get("anyOf")
                if not isinstance(any_of, list) or len(any_of) != 2:
                    continue
                nulls = [o for o in any_of if isinstance(o, dict) and o.get("type") == "null"]
                enums = [
                    o for o in any_of
                    if isinstance(o, dict)
                    and o.get("type") == "string"
                    and isinstance(o.get("enum"), list)
                    and all(isinstance(v, str) for v in o["enum"])
                ]
                if len(nulls) == 1 and len(enums) == 1:
                    prop["enum"] = enums[0]["enum"]
                    prop.setdefault("x-enum-searchable", True)
        for value in schema.values():
            _hoist_optional_enums(value)
    elif isinstance(schema, list):
        for value in schema:
            _hoist_optional_enums(value)


def _mark_sole_option_autofill(schema: Any) -> None:
    """Let a required resource pick answer itself when there is only one answer.

    Most accounts have exactly one Shopify location, one GA4 property, one
    Typeform workspace. Asking someone to choose from a list of one is pure
    friction on the step where they are most likely to give up, and every such
    question measurably lowers the odds an agent ever runs.

    Stamped here rather than declared per field so it covers the whole catalogue
    (~4,000 dynamic-option fields) and applies to nodes nobody has written yet.

    Two deliberate limits:

    * **Required fields only.** A required field has to be answered regardless,
      so filling it with the only possible value takes nothing away. An OPTIONAL
      field left empty means something ("no filter"), and auto-filling it would
      silently change what the node does.
    * **Independent fields only.** A ``depends_on`` field cannot be resolved
      until its parent is chosen, so there is nothing to auto-fill yet.

    This is NOT ``auto_select_first``, which takes ``options[0]`` whatever the
    length — fine for the sheet-tab case it was written for, but on a paginated
    list that is an arbitrary row, and silently attaching an agent to an
    arbitrary channel is far worse than asking.
    """
    if not isinstance(schema, dict):
        return
    for value in schema.values():
        if isinstance(value, (dict, list)):
            _mark_sole_option_autofill(value)

    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        return
    for name in required:
        prop = properties.get(name)
        if not isinstance(prop, dict):
            continue
        dyn = prop.get("x-dynamic-options")
        if isinstance(dyn, dict) and not dyn.get("depends_on"):
            dyn["auto_select_sole_option"] = True


@lru_cache(maxsize=None)
def _cached_base_schema_json(node_cls: Any) -> str:
    """Build a node class's JSON Schema once and keep it serialized.

    ``_cached_type_adapter`` took the core-schema rebuild off the hot path,
    but ``TypeAdapter.json_schema()`` still regenerates the whole document on
    every call — 40-125ms for a large discriminated union and ~2.8s to sweep
    the registry, all synchronous on the event loop.

    Config models are import-time constants, so the document is built once per
    class. It is stored as JSON text rather than a dict because callers own
    what they get back: node subclasses layer their own edits on top (Slack
    stamps tier markers into ``$defs``, Google Calendar pops a legacy
    operation out of the discriminator), so every caller needs an independent
    copy. Re-parsing the text is ~55x cheaper than regenerating the schema and
    keeps less memory resident than caching the dict tree.
    """
    adapter = _cached_type_adapter(node_cls.get_config_model())
    schema = adapter.json_schema(mode='validation')

    # Convert anyOf to oneOf for mutual exclusivity
    # Pydantic generates anyOf for Union types, but we want oneOf
    # to enforce that exactly one option matches (not multiple)
    if 'anyOf' in schema:
        schema['oneOf'] = schema.pop('anyOf')

    _hoist_optional_enums(schema)
    _mark_sole_option_autofill(schema)

    # Surface the node's edit-tab example prompts so the frontend
    # can render them without a separate registry.
    if node_cls.edit_examples:
        schema['x-edit-examples'] = list(node_cls.edit_examples)

    return json.dumps(schema)


class ValidationResult(TypedDict):
    """Type definition for validation result."""
    valid: bool
    errors: List[str]
    satisfied_set: Optional[str]  # Name of the parameter set that was satisfied


class OutputHandle(TypedDict):
    """Definition for a node output handle.

    Used by nodes with multiple outputs (e.g., iteration with 'loop' and 'done' handles).
    """
    id: str  # Handle identifier used in edge connections (e.g., 'loop', 'done')
    label: str  # Human-readable label for the handle
    description: str  # Description of what this output handle does


# Generic type variables for config and credentials
ConfigT = TypeVar('ConfigT', bound=BaseModel)
CredentialT = TypeVar('CredentialT', bound=BaseModel)


class NodeConfig(BaseModel, Generic[ConfigT, CredentialT]):
    """
    Generic base class for node configuration with config and credentials.

    All workflow nodes should define their specific config model by subclassing this.
    This ensures a consistent structure across all nodes.

    Example:
        class TelegramNodeConfig(NodeConfig[TelegramConfig, TelegramBotTokenCredential]):
            pass
    """
    config: ConfigT = Field(
        ...,
        description="Node-specific configuration"
    )
    credentials: Optional[CredentialT] = Field(
        default=None,
        description="Credentials for this node (optional if using environment variables)"
    )


# Sentinel: distinguishes "no expected_version passed" (plain upsert) from an
# explicit expected_version of None (CAS insert-or-lose).
_UNSET_VERSION = object()

# Sentinel: default for _update_node_state(skip_result=...) meaning "propagate
# state failures" rather than skipping the tick with a caller-supplied result.
_RAISE_ON_CONTENTION = object()


class ConfigValidationError(ValueError):
    """Node config failed Pydantic parsing at execution time — a deterministic
    config/build defect, never transient. Kept as a distinct type so the run
    failure path can tag it in telemetry (config_validation_error span attr):
    a regression in the build→run config contract surfaces as a queryable
    signal instead of an anonymous run failure."""


class NodeStateConflict(Exception):
    """A CAS write to ``workflow_node_state`` lost to a concurrent writer.

    ``_update_node_state`` retries on this transparently; it only surfaces after
    the retries are exhausted (pathological contention). Dedup callers pass
    ``skip_result`` so that case yields no event rather than double-firing —
    the concurrent poll already advanced the watermark and emitted.
    """


class WorkflowNode(ABC):
    """
    Abstract base class for all workflow nodes.

    All workflow node implementations must inherit from this class and implement
    the execute() method.
    """

    # SDK-based nodes override this to True — edges to/from them are rejected.
    connectionless: bool = False

    # Pure event triggers (webhook, inbound email) override this to True: they
    # cannot produce an event by executing, so a MANUAL run replays the node's
    # last persisted output instead of executing it — downstream
    # {{ $('trigger').field }} refs resolve to the last real event while the
    # user iterates. A trigger that has never fired still executes as before.
    # Poll triggers must NOT set this — their execute() fetches on demand.
    manual_run_replays_last_event: ClassVar[bool] = False

    # Short example prompts shown in the FlowHelper "Edit" tab to suggest what
    # the user can ask the agent to do for this node. Kept node-level (not
    # per-operation) because users typically open the Edit tab before picking
    # an operation. Surfaced on the JSON schema as `x-edit-examples` and
    # consumed by EditPromptView; falls back to a generic list when empty.
    edit_examples: ClassVar[List[str]] = []

    # OAuth scope requirements for this node's API surface. When set, the
    # credential's `x-oauth-scopes` is DERIVED from it rather than hand-written,
    # so the scopes the app requests cannot drift from the ones its operations
    # need — the failure mode that shipped 131 unusable Slack operations. See
    # nodes/core/oauth_scopes.py; coverage is enforced by
    # tests/test_oauth_scope_coverage.py.
    scope_registry: ClassVar[Optional["ScopeRegistry"]] = None

    # What to show a user to prove this node's credential really works — the
    # recognisable nouns from their own account ("#sales, #gtm"), not a green
    # tick. Declarative: see nodes/core/connection_evidence.py for the contract
    # and resolution order. Coverage is a ratchet enforced by
    # tests/test_connection_evidence_coverage.py, so a new credentialed node
    # must declare this (or land on the shrinking allowlist) to merge.
    connection_evidence: ClassVar[Optional["ConnectionEvidence"]] = None

    def __init__(
        self,
        node_id: str,
        node_type: str,
        node_data: Dict[str, Any],
        config: Optional[BaseModel] = None,
        sio=None,
        sid: Optional[str] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        execution_id: Optional[str] = None
    ):
        """
        Initialize the workflow node.

        Args:
            node_id: Unique identifier for this node instance
            node_type: Type of the node (e.g., 'automation-telegram', 'agent')
            node_data: Node-specific configuration data (raw dict from frontend)
            config: Parsed and validated Pydantic config model (parsed from node_data)
            sio: Socket.io server instance for emitting events
            sid: Session ID for sending events to specific client
            workflow_id: UUID of the workflow containing this node (for event routing)
            user_id: User ID of the workflow owner (for sandboxing/auth)
            conversation_id: Conversation ID for agent memory persistence (workflow chat only)
            organization_id: Organization ID if workflow belongs to an org (for org billing)
            execution_id: UUID of the current workflow execution (for DB persistence)
        """
        self.node_id = node_id
        self.node_type = node_type
        self.node_data = node_data
        self._config = config  # Pre-parsed config (no longer lazy-loaded)
        self.sio = sio
        self.sid = sid
        self.workflow_id = workflow_id
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.organization_id = organization_id
        self.execution_id = execution_id

    async def emit(self, output: Dict[str, Any]) -> None:
        """Publish a structured snapshot of in-flight node activity.

        Lands on the progress slot (snapshot field) — not the canonical
        output slot. The canonical output is the value returned from
        execute(), which WorkflowExecutionHandler publishes exactly once
        via WorkflowNodeOutputEvent. See WorkflowNodeProgressEvent for
        the rationale behind the split slot.
        """
        if not self.sio or not self.sid or not self.workflow_id:
            # Debug-level: standalone runs (agent node_op tools) pass sio=None
            # by design to suppress orphan canvas events — this fires per call.
            logger.debug(f"[{self.node_id}] Cannot emit output: sio/sid/workflow_id missing")
            return

        from wss.sender import send_event, WorkflowNodeProgressEvent
        from nodes.core.binary_output import snapshot_safe

        # Redact any in-flight BinaryOutput markers to a no-bytes descriptor — the
        # real R2 store happens in run() on the returned output, not here.
        snapshot = snapshot_safe(output)
        await send_event(self.sio, self.sid, WorkflowNodeProgressEvent(
            workflow_id=self.workflow_id,
            node_id=self.node_id,
            node_type=self.node_type,
            snapshot=snapshot,
        ))
        logger.debug(f"[{self.node_id}] Emitted progress snapshot: {snapshot}")

    async def emit_progress(self, text: str) -> None:
        """Append a streaming-text fragment to the node's progress slot.

        Used by streaming handlers (agent_node, others) to show live
        text accumulating in the workflow output panel. See ``emit`` for
        the structured-snapshot equivalent and WorkflowNodeProgressEvent
        for the rationale behind the split slot.
        """
        if not text:
            return
        if not self.sio or not self.sid or not self.workflow_id:
            return
        from wss.sender import send_event, WorkflowNodeProgressEvent

        await send_event(self.sio, self.sid, WorkflowNodeProgressEvent(
            workflow_id=self.workflow_id,
            node_id=self.node_id,
            node_type=self.node_type,
            append=text,
        ))
        logger.debug(f"[{self.node_id}] Emitted progress: {text}")

    @abstractmethod
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the node's logic.

        Args:
            inputs: Output data from upstream nodes (keyed by node_id)

        Returns:
            Dict containing the node's output data

        Raises:
            Exception: If node execution fails
        """
        pass

    async def run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the node and resolve durable media inputs and binary output.

        This is the entry point executors call (not ``execute`` directly): it runs
        the node's ``execute`` with a fresh URL for every persisted media resource
        ID, then replaces every ``BinaryOutput`` marker in the output with a stored
        ``{url, mime_type, name, size_bytes}`` file reference. Both transforms are
        cheap no-ops for nodes without those values."""
        from nodes.core.binary_output import resolve_binary_outputs
        from nodes.core.media_resolver import renewable_media_urls

        async with renewable_media_urls(self._config, self.workflow_id):
            output = await self.execute(inputs)
        return await resolve_binary_outputs(
            output,
            user_id=self.user_id,
            workflow_id=self.workflow_id,
            node_id=self.node_id,
            organization_id=self.organization_id,
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.node_id}, type={self.node_type})"

    @classmethod
    def resolve_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Called when a webhook fires this node. Return the payload to use as
        node output (skipping execute), or ``None`` to execute the node normally.

        The default implementation returns *payload* unchanged, which is correct
        for push-based triggers (webhook, Telegram, cron) where the payload IS
        the meaningful output.  Poll-based triggers (e.g. Gmail trigger) should
        override and return ``None`` so that their ``execute()`` method runs.
        """
        return payload

    def trigger_produced_no_event(self, output: Dict[str, Any]) -> bool:
        """Whether this trigger, having just polled, found no new data — in
        which case the executor skips all downstream nodes instead of running
        them on empty input. Applies to EVERY run source (scheduled ticks,
        manual, MCP): an empty poll envelope is not an event, and testing
        downstream without new data is what mockedOutput is for.

        Default ``False``: every other node always flows downstream. Scheduled
        poll triggers override this — the ``ScheduledPollTriggerMixin`` reports it
        from its dedup set, and nodes that dedup differently (e.g. Gmail, via its
        arrival-time watermark) inspect their own output shape.
        """
        return False

    def trigger_emitted_event(self, output: Dict[str, Any]) -> bool:
        """The positive counterpart: this trigger just polled AND emitted fresh
        items. When true, the executor stamps the node's in-run config with
        ``_pollFired`` so a directly-wired agent receives the emission as its
        trigger event on ANY run source — a manual run's fresh poll used to
        run the agent with no event at all ("no payload was available",
        2026-08-04), because event delivery keyed solely on the
        ``_triggerPayload`` the webhook routes inject. Stamping happens only
        right after execute(), so preloaded outputs from previous runs can
        never masquerade as a fresh event.

        Default ``False``: non-poll nodes never stamp (push triggers deliver
        via ``_triggerPayload`` as before).
        """
        return False

    @staticmethod
    def no_event_output(action: str, detail: str = "") -> Dict[str, Any]:
        """Output for a push-trigger operation executed WITHOUT a live delivery.

        Real firings short-circuit through ``resolve_trigger_payload`` (execute
        is never called), so a push trigger's execute() only ever runs on
        manual/test/chat-context runs where there IS no event. Say so — a
        success-shaped empty envelope here incorrectly reads as "the trigger fired
        with empty data" to users and in-product agents alike.
        ``data`` stays present (empty) so templated references don't break.
        """
        message = (
            f"No live event: '{action}' only carries data when a real delivery "
            f"fires the workflow — this run was not started by one."
        )
        if detail:
            message = f"{message} {detail}"
        return {"status": "no_event", "action": action, "data": {}, "message": message}

    @classmethod
    def filter_trigger_payload(cls, payload: Dict[str, Any], config: Dict[str, Any]) -> bool:
        """Return False to silently skip this webhook delivery without executing the workflow.

        Called for ExternalWebhookTrigger nodes after signature verification, before
        workflow execution. Override in granular trigger nodes to filter by action.
        Default: always process (True).
        """
        return True

    @classmethod
    async def transform_trigger_payload(
        cls,
        payload: Dict[str, Any],
        config: Dict[str, Any],
        *,
        pool,
        workflow_id: Optional[str],
        node_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Rewrite a webhook delivery's payload before it becomes the run's
        ``_triggerPayload``.

        The seam for providers whose payloads reference resources the RUN
        cannot use — WhatsApp media URLs are authed with the shared platform
        key and expire on the provider's worker, so they must be eagerly
        rehosted and swapped for run-usable references at delivery time.
        Return the replacement payload, or ``None`` to leave the delivery
        untouched. Runs after filter/fire-budget in both per-node delivery
        paths; implementations must be best-effort — a failed transform must
        never block the delivery (return None and let the run see the
        original). Default: no transform.
        """
        return None

    @classmethod
    async def handle_control_event(
        cls,
        payload: Dict[str, Any],
        config: Dict[str, Any],
        *,
        pool,
        workflow_id: Optional[str],
        node_id: Optional[str],
    ) -> Optional[str]:
        """Provider CONTROL-PLANE events arriving on a data webhook (e.g. a
        WAHooks ``session.status`` push on a WhatsApp per-node webhook).

        Return a short message when the event is CONSUMED — the delivery is
        acked 200 and the workflow is NOT executed (same response shape as a
        filter_trigger_payload drop, so the provider never retries). Return
        ``None`` for data events, which proceed through the normal
        filter/budget/execute pipeline. Runs before filter_trigger_payload in
        both per-node delivery paths; implementations must be best-effort and
        never raise (a broken control handler must not break data delivery).
        Default: nothing is a control event.
        """
        return None

    @classmethod
    def trigger_fire_budget_channel(
        cls, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Optional[str]:
        """Channel key for the per-(node, channel) fire budget, or None to skip it.

        Channel-like triggers (a chat/thread a workflow can also reply INTO)
        override this so runaway two-party loops are bounded by
        utils.fire_budget.over_fire_budget — the same cap app-webhook providers
        opt into via APP_PROVIDERS. Default None: no budget.
        """
        return None

    @classmethod
    def should_propagate_output(
        cls, output: Dict[str, Any], config: Dict[str, Any]
    ) -> bool:
        """Return False when a successful node output should not fan out downstream.

        Most nodes should always propagate on success. Trigger-like polling/watch
        nodes can override this to suppress downstream execution when the wake-up
        produced no actionable items (for example, an empty Drive changes batch).
        The output is still persisted/emitted; only dependency completion changes.
        """
        return True

    @classmethod
    def resolve_agent_event(cls, output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Translate this node's fired-trigger OUTPUT into the event delivered
        to a directly wired AI agent: ``{"text": str, "conversation_key":
        Optional[str]}``.

        Called only for the trigger that started the run (see
        ``AgentNode._resolve_trigger_event``); ``output`` is what landed in
        node_outputs — the ``resolve_trigger_payload`` short-circuit for push
        triggers, the poll result for poll triggers. The default delivers the
        whole output as JSON, which is always safe since trigger shapes differ
        per provider. Channel-like triggers (Telegram, Slack, Alarm) override
        to extract the message text and the medium's native thread/chat key so
        the agent resumes the right conversation. Return ``None`` to deliver
        nothing.
        """
        import json

        try:
            text = json.dumps(output, indent=2, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(output)
        return {"text": text, "conversation_key": None}

    # Grid layout constraints for interface nodes (defaultW, defaultH, minW, minH).
    # Only relevant for interface-* nodes; ignored for automation/agent nodes.
    grid_layout: Optional[Dict[str, int]] = None

    # Skip provider-side teardown when the workflow is TRASHED (soft delete).
    # Set True for nodes whose teardown surrenders a scarce, user-claimed
    # resource that a later restore cannot reliably re-acquire (e.g. the
    # inbound-email address reservation) — trash must stay reversible.
    preserve_registration_on_trash: bool = False

    @classmethod
    async def cleanup_external_webhook(
        cls, pool, workflow_id: str, node_id: str,
        config: Dict[str, Any], credentials: Optional[Dict[str, Any]] = None
    ) -> None:
        """Override to clean up external webhooks when this node is removed. No-op by default."""
        pass

    @classmethod
    async def freshen_credential(
        cls,
        credential_data: Optional[Dict[str, Any]],
        *,
        pool=None,
        user_id: Optional[str] = None,
        credential_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Refresh expiring OAuth tokens in a freshly-decrypted credential dict.

        Opt-in hook. Called right after a credential is loaded for a node's
        non-execute paths — dynamic-option dropdowns, trigger registration, and
        trigger tests. The default is a no-op; OAuth nodes whose access tokens
        expire (Slack/HubSpot/Linear/Typeform token rotation) MUST override it,
        typically as a one-liner delegating to
        ``oauth_refresh.freshen_oauth_credential`` with the provider's refresh
        fn. This moves refresh ownership to credential *loading*: a read path
        that gets its credential from a freshening loader can't serve a stale
        token. Non-rotating credentials (bot tokens, PATs) pass through
        untouched. Implementations mutate and return *credential_data*.
        """
        return credential_data

    async def _brand_email_body(self, body: str, *, html: bool = True) -> str:
        """Free-plan "Sent from NoClick" footer for emails composed by this node
        and sent from the user's own mailbox (Gmail/Outlook send/reply/forward).
        No-op when the run's billing pool is on a paid effective tier."""
        from nodes.core.email_branding import maybe_brand_email_body

        return await maybe_brand_email_body(
            body,
            user_id=self.user_id,
            organization_id=self.organization_id,
            html=html,
        )

    @classmethod
    def get_sandbox_setup(
        cls,
        *,
        repo: str,
        branch: Optional[str],
        credential_data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Build a sandbox environment contribution for provider mode.

        Opt-in hook. When this node type is wired into an agent as a tool
        provider AND its config requests a sandbox mount
        (``agent_sandbox_repo``), the agent runtime calls this with the
        freshly-resolved credential to derive the boot-time setup (e.g. an
        authenticated git clone). Returning None means this node type cannot
        contribute sandbox environment — the agent run fails loudly rather
        than silently skipping a configured mount.
        """
        return None

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify the authenticity of an inbound webhook request.

        Called by the webhook receiver before a trigger node fires its workflow.
        Webhook-trigger nodes override this to check the provider's signature
        header against a shared secret stored in *config*. *headers* keys are
        lowercased. The default returns ``True`` (no verification).
        """
        return True

    @classmethod
    def handle_webhook_handshake(
        cls, body: bytes, headers: Dict[str, str], config: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Handle a provider verification/handshake request.

        Some providers send a one-off request that must be answered
        synchronously rather than triggering a workflow run (e.g. Slack's
        ``url_verification`` challenge, a GitHub ``ping``, Zoom's
        ``endpoint.url_validation`` CRC). Return a dict to send back as the HTTP
        response body, or ``None`` to proceed with normal workflow dispatch.
        *headers* keys are lowercased; *config* is the trigger node's config
        (used when the handshake response must be keyed by a stored secret). The
        default returns ``None``.
        """
        return None

    @classmethod
    def webhook_ack_response(cls) -> Optional[Dict[str, str]]:
        """Shape the HTTP response returned to the provider after a webhook is
        accepted and the workflow dispatched.

        Some providers expect a specific response body and content type rather
        than NoClick's default JSON acknowledgement (e.g. Twilio expects TwiML
        XML). Return a dict ``{"content": ..., "media_type": ...}`` to override,
        or ``None`` for the default JSON ack.
        """
        return None

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type[BaseModel], type]]:
        """
        Get the Pydantic model for this node's configuration.

        Subclasses should override this to return their config model,
        or return None if they don't have a config model.

        Returns:
            Pydantic model type (can be Union of models for oneOf), or None
        """
        return None

    @classmethod
    def get_output_handles(cls) -> Optional[List['OutputHandle']]:
        """
        Get output handles for nodes with multiple outputs.

        Subclasses should override this if they have multiple output handles.
        For example, IterationNode has 'loop' and 'done' handles.

        Returns:
            List of OutputHandle definitions, or None for single-output nodes
        """
        return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """
        Generate JSON Schema from Pydantic config model.

        Built once per class by :func:`_cached_base_schema_json`; each call
        returns a fresh copy that the caller is free to mutate.

        Returns:
            JSON Schema dictionary (Draft 2020-12), or empty dict if no model defined
        """
        config_model = cls.get_config_model()

        if not config_model:
            logger.warning(f"No config model defined for {cls.__name__}")
            return {}

        try:
            return json.loads(_cached_base_schema_json(cls))
        except Exception as e:
            logger.error(f"Failed to generate schema for {cls.__name__}: {e}")
            return {}

    @classmethod
    def validate_config(cls, config_data: Dict[str, Any]) -> ValidationResult:
        """
        Validate node configuration using Pydantic models.

        Uses the same TypeAdapter validation as parse_config() for consistency.

        Args:
            config_data: Configuration data to validate

        Returns:
            ValidationResult with valid flag and error messages
        """
        from pydantic import ValidationError

        # Get config model
        config_model = cls.get_config_model()

        # If no config model defined, consider config valid
        if not config_model:
            return {
                "valid": True,
                "errors": [],
                "satisfied_set": None
            }

        try:
            # Validate the canonical runtime view (see runtime_config_view) —
            # judging raw values here reported verdicts the runtime parse
            # contradicted (Gmail validation regression).
            adapter = _cached_type_adapter(config_model)
            adapter.validate_python(runtime_config_view(config_data, config_model))

            return {
                "valid": True,
                "errors": [],
                "satisfied_set": "default"
            }

        except ValidationError as e:
            # A field holding a {{ ... }} reference/expression is resolved at runtime;
            # its type is unknown now, so skip validation errors on it (mirrors the
            # frontend AJV relaxation). Navigate config_data by the error loc.
            def _raw_value_at(data: Any, loc: tuple) -> Any:
                cur = data
                for part in loc:
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    elif isinstance(cur, list) and isinstance(part, int) and 0 <= part < len(cur):
                        cur = cur[part]
                    else:
                        return None
                return cur

            # Convert Pydantic validation errors to readable messages
            error_messages = []
            for error in e.errors():
                raw_value = _raw_value_at(config_data, error.get('loc') or ())
                if isinstance(raw_value, str) and '{{' in raw_value:
                    continue

                error_type = error['type']
                field_path = '.'.join(str(loc) for loc in error['loc']) if error['loc'] else 'config'

                if error_type == 'missing':
                    field = error['loc'][-1] if error['loc'] else 'field'
                    error_messages.append(f"{field} is required")
                elif error_type == 'string_too_short':
                    error_messages.append(f"{field_path} is required")
                elif error_type == 'string_pattern_mismatch':
                    error_messages.append(f"{field_path} has invalid format")
                elif error_type in ('union_tag_invalid', 'union_tag_not_found'):
                    error_messages.append("Must match exactly one of the allowed configuration patterns")
                else:
                    # Use Pydantic's error message as fallback
                    error_messages.append(error.get('msg', 'Invalid value'))

            # Every error was on a reference/expression field — treat as valid pending
            # runtime resolution.
            if not error_messages:
                return {"valid": True, "errors": [], "satisfied_set": "default"}

            return {
                "valid": False,
                "errors": error_messages,
                "satisfied_set": None
            }

    @classmethod
    def validate_saved_config(cls, flat_config: Dict[str, Any]) -> ValidationResult:
        """Validate a node's config as stored in the workflow graph (flat,
        schema fields only). Wraps it into the ``{config: …}`` shape when the
        model uses the NodeConfig wrapper — the same shape the execution
        handler's credential resolution produces — so this verdict matches
        what ``parse_config`` will do at run time (credentials are Optional on
        the wrapper, so they never fail this check).
        """
        config_model = cls.get_config_model()
        data = flat_config
        if config_model is not None:
            try:
                if issubclass(config_model, NodeConfig):
                    data = {"config": flat_config}
            except TypeError:
                pass  # config_model may be a Union / non-class type
        return cls.validate_config(data)

    @classmethod
    def parse_config(cls, config_data: Dict[str, Any]) -> Optional[BaseModel]:
        """
        Parse configuration data into the appropriate Pydantic model.

        For Union types (oneOf), this will automatically determine which
        subclass matches and return the correctly typed instance.

        Args:
            config_data: Configuration data from frontend

        Returns:
            Parsed Pydantic model instance, or None if no config model defined

        Raises:
            ValueError: If config_data doesn't match any of the expected models
        """
        config_model = cls.get_config_model()

        if not config_model:
            return None

        # The canonical runtime view: ""→None cleanup, str-field coercions,
        # rejected unset markers dropped to their defaults. Validators judge
        # the same view, so their verdicts match what happens here.
        config_data = runtime_config_view(config_data, config_model)

        try:
            # Use TypeAdapter to handle Union types
            # This will automatically parse into the correct subclass
            adapter = _cached_type_adapter(config_model)
            parsed = adapter.validate_python(config_data)
            logger.debug(f"[{cls.__name__}] Parsed config into {type(parsed).__name__}")
            return parsed
        except Exception as e:
            # When validation fails on a discriminated union, Pydantic tries ALL union members
            # and reports failures for each one (e.g., 167 errors for YouTube node).
            # Extract the most relevant error to provide a clear, actionable message.
            error_msg = cls._extract_actionable_validation_error(e, config_data)
            logger.error(f"[{cls.__name__}] Failed to parse config: {error_msg}")
            raise ConfigValidationError(f"Invalid configuration: {error_msg}")

    @classmethod
    def _list_discriminator_options(cls, discriminator_field: str) -> List[str]:
        """Return the literal values of `discriminator_field` across the config
        union members, in declaration order. Used to build clear error messages
        when the discriminator is missing or invalid."""
        from typing import Annotated, get_args, get_origin, Union, Literal

        config_model = cls.get_config_model()
        if not config_model:
            return []
        inner = config_model.model_fields.get('config')
        if not inner:
            return []
        annotation = inner.annotation
        # Unwrap Annotated[Union[...], Discriminator(...)]
        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            if args:
                annotation = args[0]
        members = get_args(annotation) if get_origin(annotation) is Union else (annotation,)
        options: List[str] = []
        for member in members:
            field = getattr(member, 'model_fields', {}).get(discriminator_field)
            if not field:
                continue
            if get_origin(field.annotation) is Literal:
                for lit in get_args(field.annotation):
                    if lit not in options:
                        options.append(str(lit))
        return options

    @classmethod
    def _extract_actionable_validation_error(cls, error: Exception, config_data: Dict[str, Any]) -> str:
        """
        Extract the most relevant validation error from a Pydantic ValidationError.

        When Pydantic validates a discriminated union and no member matches, it tries ALL
        union members and returns ALL errors (e.g., 167 errors for YouTube node with 167 operations).
        This method extracts only the most actionable error to provide a clear message.

        Strategy:
        1. If there's a discriminator field (e.g., 'operation'), find the union member that matches it
        2. Show only the errors from that specific member (e.g., missing required fields)
        3. If no discriminator or multiple errors, summarize the key issues

        Args:
            error: The exception raised during validation (usually ValidationError)
            config_data: The configuration dict that failed validation

        Returns:
            A concise, actionable error message
        """
        # If it's not a Pydantic ValidationError, return as-is
        if not isinstance(error, ValidationError):
            return str(error)

        # Get the list of validation errors
        errors = error.errors()

        # Common discriminator fields in our nodes
        discriminator_fields = ['type', 'operation']

        # Try to find the discriminator value in the config
        discriminator_value = None
        discriminator_field = None
        for field in discriminator_fields:
            # Handle nested config structures (e.g., NodeConfig has a 'config' field containing the actual config)
            if field in config_data:
                discriminator_value = config_data[field]
                discriminator_field = field
                break
            elif 'config' in config_data and isinstance(config_data['config'], dict):
                if field in config_data['config']:
                    discriminator_value = config_data['config'][field]
                    discriminator_field = field
                    break

        # Detect missing/invalid discriminator (e.g. operation field not set or
        # set to an unknown value). Pydantic's default message — "Unable to
        # extract tag using discriminator 'operation'" — gives the caller no
        # way to recover. Surface the field name and the valid options instead.
        for err in errors:
            err_type = err.get('type', '')
            if err_type in ('union_tag_not_found', 'union_tag_invalid'):
                ctx = err.get('ctx', {}) or {}
                disc_field = ctx.get('discriminator', '').strip("'\"") or discriminator_field or 'operation'
                valid_options = cls._list_discriminator_options(disc_field)
                options_str = ', '.join(valid_options) if valid_options else '(none)'
                bad_value = ctx.get('tag') if ctx.get('tag') is not None else discriminator_value
                # Treat None / empty / 'None' string as "not set" — they happen
                # when the discriminator key exists but was never written.
                missing = (
                    err_type == 'union_tag_not_found'
                    or bad_value in (None, '', 'None')
                )
                if missing:
                    return (
                        f"'{disc_field}' field is required. "
                        f"Set it to one of: {options_str}"
                    )
                return (
                    f"'{disc_field}' = {bad_value!r} is not a valid option. "
                    f"Use one of: {options_str}"
                )

        if discriminator_value and discriminator_field:
            # Filter errors to only those from the union member matching the discriminator
            # These errors have a path like: config.YouTubeListVideosConfig.field_name
            # We want to find errors where the config type contains the discriminator value
            relevant_errors = []
            for err in errors:
                # Get the location path (e.g., ['config', 'YouTubeListVideosConfig', 'video_ids'])
                loc = err.get('loc', ())

                # Skip discriminator field errors (we already know the operation is correct)
                if discriminator_field in loc:
                    continue

                relevant_errors.append(err)

            # If we found relevant errors, use only those
            if relevant_errors:
                errors = relevant_errors[:5]  # Limit to first 5 errors to keep message concise

        # If still too many errors, limit to first 5
        if len(errors) > 5:
            errors = errors[:5]

        # Format the errors in a readable way
        if len(errors) == 1:
            err = errors[0]
            field_path = '.'.join(str(loc) for loc in err.get('loc', ()))
            msg = err.get('msg', 'Validation failed')
            return f"{field_path}: {msg}"
        else:
            # Multiple errors - show a summary
            error_summary = []
            for err in errors:
                field_path = '.'.join(str(loc) for loc in err.get('loc', ()))
                msg = err.get('msg', 'Validation failed')
                # Clean up the path to remove redundant parts
                field_path = field_path.replace('config.', '').replace('Config.', '.')
                error_summary.append(f"  • {field_path}: {msg}")

            summary = f"{len(error.errors())} validation errors" if len(error.errors()) > len(errors) else f"{len(errors)} validation errors"

            if discriminator_value:
                return f"{summary} for {discriminator_field}='{discriminator_value}':\n" + "\n".join(error_summary)
            else:
                return f"{summary}:\n" + "\n".join(error_summary)

    @property
    def config(self) -> Optional[BaseModel]:
        """
        Get the parsed and validated configuration as a Pydantic model.

        The config is parsed during node construction (in NodeFactory) and
        passed to __init__, so this property simply returns the pre-parsed config.
        For Union types (oneOf), this returns the correct subclass instance.

        Returns:
            Parsed Pydantic model instance, or None if no config model defined
        """
        return self._config

    async def _load_node_state(self) -> Dict[str, Any]:
        """
        Load persistent state for this node instance from the database.

        State is scoped to (workflow_id, node_id) so each node instance has its
        own isolated state that persists across workflow executions. The row's
        CAS ``version`` is stashed on ``self`` so a subsequent
        ``_update_node_state`` write can detect a concurrent modification.

        Raises on a DB error rather than swallowing it — a poll that can't read
        its watermark must abort and retry, NOT silently re-baseline (which
        would drop every event that arrived since the last successful read).

        Returns:
            The node's persisted state, or an empty dict if no row exists yet.
        """
        if not self.workflow_id or not self.node_id:
            logger.warning(f"[{self.__class__.__name__}] Cannot load state: workflow_id or node_id not set")
            self._node_state_version = None
            return {}

        from utils.database_pool import get_native_pool

        row = await get_native_pool().fetchrow(
            "SELECT state, version FROM workflow_node_state WHERE workflow_id = $1 AND node_id = $2",
            self.workflow_id, self.node_id
        )

        if row is None:
            self._node_state_version = None  # no row yet → insert on write
            return {}

        self._node_state_version = row['version']
        raw = row['state']
        if raw is None:
            return {}
        # asyncpg returns jsonb columns as strings; parse to dict
        if isinstance(raw, str):
            import json
            return json.loads(raw)
        return raw

    async def _save_node_state(
        self, state: Dict[str, Any], *, expected_version: Any = _UNSET_VERSION
    ) -> None:
        """
        Persist state for this node instance.

        Default (``expected_version`` omitted): a simple version-bumping upsert
        (last-writer-wins). It bumps ``version`` so a concurrent CAS writer
        notices the change, but does not itself guard against a lost update.

        With ``expected_version`` (used by ``_update_node_state``): a
        compare-and-swap — the write only lands if the row's ``version`` still
        matches, else ``NodeStateConflict`` is raised. Pass ``None`` when the row
        was absent at load (insert-or-lose). On success the stashed version is
        advanced so a subsequent CAS write in the same instance uses it.

        Raises on a DB error rather than swallowing it.
        """
        if not self.workflow_id or not self.node_id:
            logger.warning(f"[{self.__class__.__name__}] Cannot save state: workflow_id or node_id not set")
            return

        from utils.database_pool import get_native_pool

        pool = get_native_pool()

        if expected_version is _UNSET_VERSION:
            await pool.execute(
                """
                INSERT INTO workflow_node_state (workflow_id, node_id, state, version, updated_at)
                VALUES ($1, $2, $3, 0, NOW())
                ON CONFLICT (workflow_id, node_id)
                DO UPDATE SET state = $3, version = workflow_node_state.version + 1, updated_at = NOW()
                """,
                self.workflow_id, self.node_id, state,
            )
            return

        if expected_version is None:
            # No row at load — insert, but lose to any racing insert.
            row = await pool.fetchrow(
                """
                INSERT INTO workflow_node_state (workflow_id, node_id, state, version, updated_at)
                VALUES ($1, $2, $3, 0, NOW())
                ON CONFLICT (workflow_id, node_id) DO NOTHING
                RETURNING version
                """,
                self.workflow_id, self.node_id, state,
            )
        else:
            row = await pool.fetchrow(
                """
                UPDATE workflow_node_state
                SET state = $3, version = version + 1, updated_at = NOW()
                WHERE workflow_id = $1 AND node_id = $2 AND version = $4
                RETURNING version
                """,
                self.workflow_id, self.node_id, state, expected_version,
            )
        if row is None:
            raise NodeStateConflict(
                f"node {self.node_id}: state changed under CAS (expected v{expected_version})"
            )
        self._node_state_version = row['version']

    async def _update_node_state(
        self,
        mutator: "Callable[[Dict[str, Any]], tuple]",
        *,
        max_retries: int = 4,
        skip_result: Any = _RAISE_ON_CONTENTION,
    ) -> Any:
        """Optimistic read-modify-write of node state with CAS + retry.

        ``mutator(state)`` receives the freshly-loaded state and returns
        ``(new_state, result)``. If ``new_state`` is ``None`` no write happens
        (the state was already up to date) and ``result`` is returned as-is.
        Otherwise the new state is written under compare-and-swap; on a
        concurrent modification the loop re-reads and re-applies the mutator so
        the write always lands on top of the latest state — never clobbering a
        racing writer. Keep ``mutator`` pure and side-effect-free: it may run
        several times. Any external fetch (API call) must happen BEFORE this so
        it isn't repeated per retry. A mutator exception always propagates (it's
        a real bug, not a transient condition).

        If node state can't be read/written this call — a transient DB error, or
        CAS contention that outlasts ``max_retries`` — behavior depends on
        ``skip_result``: by default the failure propagates (the caller aborts).
        A dedup poller instead passes its "no new items" value as ``skip_result``
        so the tick is skipped cleanly: state is left UNTOUCHED (no re-baseline,
        so no events are lost), nothing is emitted, and the scheduled run neither
        fails nor alerts the owner — it simply retries on the next tick.
        """
        skip = skip_result is not _RAISE_ON_CONTENTION
        for _ in range(max_retries):
            try:
                state = await self._load_node_state()
            except Exception as e:
                if not skip:
                    raise
                logger.warning(
                    f"[{self.__class__.__name__}] node {self.node_id}: state read "
                    f"failed, skipping this tick (state intact): {e}"
                )
                return skip_result
            new_state, result = mutator(state)
            if new_state is None:
                return result
            try:
                await self._save_node_state(
                    new_state, expected_version=getattr(self, "_node_state_version", None)
                )
                return result
            except NodeStateConflict:
                continue
            except Exception as e:
                if not skip:
                    raise
                logger.warning(
                    f"[{self.__class__.__name__}] node {self.node_id}: state write "
                    f"failed, skipping this tick (state intact): {e}"
                )
                return skip_result
        if not skip:
            raise NodeStateConflict(
                f"node {self.node_id}: state contended for {max_retries} attempts"
            )
        logger.warning(
            f"[{self.__class__.__name__}] node {self.node_id}: state contended for "
            f"{max_retries} attempts, skipping this tick"
        )
        return skip_result

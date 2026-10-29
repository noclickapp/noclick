"""Typed edits to a workflow's graph: the JSON form of the vocabulary the AI
builder and the workflow MCP share (``workflow_xml.ALL_TAGS``), one ``op``
each, applied in order by ``GraphEditor`` through the same functions those
writers use (``workflow_ops``), so an edit is judged as a builder or MCP write
of the same change is: the step's operation model with the run engine's lens,
the provider, trigger and MCP-hosting conflicts, an agent's harness switch.

Refused, so nothing of the batch lands: what can't be written as asked (an
unknown step, type or operation, a runtime key, a value of the wrong type, a
conflict, a connection the caller can't use). Canonicalized and reported: what
the shared post-write pass rewrites (a model id resolved, a placeholder auth
header or an agent's trigger reference stripped). Judged and reported, never
refused: a step that isn't ready to run yet (``steps``), as on the canvas.

The editor is pure but for an inbound-email address, which it claims inside the
caller's transaction (``EditContext.conn``)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence, Set, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter

from utils.graph_nodes import graph_edges, graph_nodes, is_trigger_node, node_config, node_label

STEP_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$"
MAX_NAME_CHARS = 200
# Config keys a ``settings`` write never sets: each has an op of its own (``set_connection`` checks the caller may
# use the connection).
_OWN_OP = {"operation": "operation", "credentialIds": "set_connection"}
# On a trigger, NoClick's records of its registration (the webhooks row and the scheduler are the truth; these only
# mirror them): what a step is doesn't change with them. On another step a field may share one of these names.
REGISTRATION_MIRRORS = frozenset({
    "webhook_id", "webhook_url", "external_webhook_id", "signing_secret", "schedule_id", "schedule_ids", "next_run",
    "trigger_registered", "trigger_error", "trigger_action", "subscription_status", "paused_by", "paused_reason",
    "is_active", "relay_connected", "is_production",
})


# ── the ops ─────────────────────────────────────────────────────────────────

class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class AddStep(_Op):
    op: Literal["add_step"]
    type: str = Field(..., description="The step's type (e.g. 'automation-gmail', 'agent', 'trigger-cron').")
    operation: Optional[str] = Field(None, description="What it does, one of its type's operations.")
    settings: Dict[str, Any] = Field(default_factory=dict, description="Its settings, by field name.")
    name: Optional[str] = Field(None, max_length=MAX_NAME_CHARS, description="Its name in the app.")
    id: Optional[str] = Field(None, pattern=STEP_ID, description=(
        "Its id, chosen by the caller (later ops in the batch name it by this); omitted, NoClick makes one."))
    position: Optional[Position] = Field(None, description="Where it sits on the canvas; omitted, it's laid out.")


class UpdateStep(_Op):
    op: Literal["update_step"]
    id: str
    settings: Optional[Dict[str, Any]] = Field(None, description=(
        "Settings to change, deep-merged into the step's (a nested object merges, anything else replaces)."))
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_NAME_CHARS)
    operation: Optional[str] = None
    enabled: Optional[StrictBool] = Field(None, description="false switches the step off; true back on.")


class PatchStep(_Op):
    op: Literal["patch_step"]
    id: str
    field: str = Field(..., description="The long text field to patch (code, instructions).")
    patch: str = Field(..., description="A unified-diff-style patch: @@ anchor lines, then -old/+new lines.")


class RemoveStep(_Op):
    op: Literal["remove_step"]
    id: str


class Connect(_Op):
    op: Literal["connect"]
    from_: str = Field(..., alias="from")
    to: str
    kind: Literal["data", "tools"] = Field("data", description=(
        "data: the step feeds the next; tools: its operations become tools of the agent (or MCP step) it joins."))
    handle: Optional[str] = Field(None, description="Which output of a step with several (an iteration's 'loop').")


class Disconnect(_Op):
    op: Literal["disconnect"]
    from_: str = Field(..., alias="from")
    to: str
    handle: Optional[str] = None


class SetConnection(_Op):
    op: Literal["set_connection"]
    id: str
    connection: Optional[str] = Field(..., description=(
        "A connected account's id the caller may use; null takes the one in slot off the step."))
    slot: Optional[str] = Field(None, description=(
        "The connection's type, which a step keys its connections by; omitted, the connection's own."))


class MockStep(_Op):
    op: Literal["mock_step"]
    id: str
    output: Any = Field(..., description="What the step outputs on test runs instead of running.")


class UnmockStep(_Op):
    op: Literal["unmock_step"]
    id: str


class UpdateWorkflow(_Op):
    op: Literal["update_workflow"]
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_NAME_CHARS)
    description: Optional[str] = None
    settings: Optional[Dict[str, Any]] = Field(None, description=(
        "The workflow's settings to change, by top-level key; only its owner may."))


class Move(_Op):
    op: Literal["move"]
    id: str
    position: Position


class Layout(_Op):
    op: Literal["layout"]


class AddNote(_Op):
    op: Literal["add_note"]
    content: str
    id: Optional[str] = Field(None, pattern=STEP_ID)
    color: int = Field(8, ge=0, le=20)
    near: Optional[List[str]] = Field(None, description="Steps it sits beside.")
    direction: Literal["above", "below", "left", "right"] = "above"
    after: Optional[str] = Field(None, description="With before: the first step of the stretch it covers.")
    before: Optional[str] = Field(None, description="With after: the last step of the stretch it covers.")
    width: Optional[int] = Field(None, ge=50, le=5000)
    height: Optional[int] = Field(None, ge=50, le=5000)


class DefineVariable(_Op):
    op: Literal["define_variable"]
    name: str
    value: str = ""
    description: Optional[str] = None
    per_user: StrictBool = False


class AddTestRun(_Op):
    op: Literal["add_test_run"]
    trigger: str = Field(..., description="The trigger step (its id, or its type) the run stages an event on.")
    name: str
    body: str = Field(..., description="The staged message's body.")
    title: Optional[str] = None
    author: Optional[str] = None
    handle: Optional[str] = None


GraphOp = Annotated[Union[AddStep, UpdateStep, PatchStep, RemoveStep, Connect, Disconnect, SetConnection, MockStep,
                          UnmockStep, UpdateWorkflow, Move, Layout, AddNote, DefineVariable, AddTestRun],
                    Field(discriminator="op")]
_OPS = TypeAdapter(List[GraphOp])
# Ops that change only where things sit: a batch of them alone is no version and needs no reconcile.
LAYOUT_OPS = frozenset({"move", "layout"})


class EditRefused(Exception):
    """Op ``index`` can't be applied: nothing of its batch lands."""

    def __init__(self, index: int, message: str, *, field: Optional[str] = None):
        super().__init__(message)
        self.index = index
        self.message = message
        self.field = field


def parse_ops(ops: Sequence[Any]) -> List[Any]:
    """``ops`` as typed ops (dicts are validated; typed ops pass through); raises ``EditRefused`` naming the
    first op that isn't one."""
    from pydantic import ValidationError

    try:
        return _OPS.validate_python([o.model_dump(by_alias=True) if isinstance(o, BaseModel) else o for o in ops])
    except ValidationError as e:
        first = e.errors()[0]
        loc = list(first["loc"])
        index = loc[0] if loc and isinstance(loc[0], int) else 0
        where = ".".join(str(p) for p in loc[2:])
        raise EditRefused(index, f"ops[{index}]{'.' + where if where else ''}: {first['msg']}",
                          field=where or None)


# ── applying them ───────────────────────────────────────────────────────────

@dataclass
class EditContext:
    """What applying edits needs beyond the graph: who edits (``is_owner``: may change the workflow's settings),
    the connections they may use by id (``credential_types``: id -> its type) and the transaction's
    connection, which claims an inbound-email address."""

    workflow_id: str
    user_id: str
    is_owner: bool
    credential_types: Dict[str, str] = field(default_factory=dict)
    conn: Any = None


class GraphEditor:
    """Applies typed ops to a copy of a workflow's graph and its own fields, in order. Once ``finish`` has run:
    ``graph``, the workflow's ``name``/``description`` when an op changed them, ``settings`` (the top-level keys
    an op wrote), ``results`` (one per op), ``steps`` (each touched step's verdict) and ``connections`` (the
    connection ids placed)."""

    def __init__(self, graph: Any, *, name: str, settings: Optional[Dict[str, Any]], context: EditContext):
        self.graph = copy.deepcopy(graph) if isinstance(graph, dict) else {}
        self.graph["nodes"] = graph_nodes(self.graph)
        self.graph["edges"] = graph_edges(self.graph)
        self._stored_name = name
        self._stored_settings = dict(settings or {})
        self.ctx = context
        self.name: Optional[str] = None
        self.description: Optional[str] = None
        self.settings: Dict[str, Any] = {}
        self.results: List[Dict[str, Any]] = []
        self.steps: Dict[str, Dict[str, Any]] = {}
        self.connections: Set[str] = set()
        self._touched: List[str] = []
        self._unplaced: List[str] = []
        self._harness_switches: List[tuple] = []

    @property
    def nodes(self) -> List[Dict[str, Any]]:
        return self.graph["nodes"]

    @property
    def edges(self) -> List[Dict[str, Any]]:
        return self.graph["edges"]

    async def apply(self, ops: Sequence[Any]) -> None:
        for index, op in enumerate(ops):
            handler = getattr(self, f"_{op.op}")
            self.results.append({"op": op.op, **(await handler(index, op) or {})})
        self._finish()

    # ── helpers ──

    def _node(self, index: int, step_id: str, *, field_name: str = "id") -> Dict[str, Any]:
        found = next((n for n in self.nodes if n.get("id") == step_id), None)
        if found is None:
            raise EditRefused(index, f"No step '{step_id}' in this workflow.", field=field_name)
        return found

    def _touch(self, step_id: str) -> None:
        if step_id not in self._touched:
            self._touched.append(step_id)

    def _is_provider(self, step_id: str) -> bool:
        from .workflow_ops import PROVIDER_TARGET_HANDLE

        return any(e.get("source") == step_id and e.get("targetHandle") == PROVIDER_TARGET_HANDLE for e in self.edges)

    def _upstream_triggers(self, step_id: str) -> Set[str]:
        from .workflow_ops import is_trigger_source

        by_id = {n.get("id"): n for n in self.nodes}
        return {e.get("source") for e in self.edges
                if e.get("target") == step_id and (src := by_id.get(e.get("source")))
                and is_trigger_source(src.get("type", ""), node_config(src).get("operation"))}

    def _new_id(self, index: int, wanted: Optional[str], minted: str) -> str:
        step_id = wanted or minted
        if any(n.get("id") == step_id for n in self.nodes):
            raise EditRefused(index, f"A step '{step_id}' already exists in this workflow.", field="id")
        return step_id

    def _check_operation(self, index: int, node_type: str, operation: Optional[str]) -> None:
        if operation is None:
            return
        from .operation_catalog import get_operations_for_node_type

        names = sorted({o.name for o in get_operations_for_node_type(node_type)})
        if operation not in names:
            raise EditRefused(index, f"'{operation}' isn't an operation of {node_type} (its operations: "
                                     f"{', '.join(names) or 'none'}).", field="operation")

    def _check_settings(self, index: int, node_type: str, settings: Dict[str, Any]) -> None:
        """Refuse what no settings write may carry; normalize the canvas-level fields, in place."""
        from utils.runtime_keys import runtime_key_refusal

        from .workflow_ops import misplaced_agent_model, normalize_canvas_fields

        for key in settings:
            refused = runtime_key_refusal(key)
            if refused:
                raise EditRefused(index, refused, field=f"settings.{key}")
            if key in _OWN_OP:
                raise EditRefused(index, f"'{key}' isn't set through settings: use {_OWN_OP[key]}.",
                                  field=f"settings.{key}")
            if str(key).endswith("__label"):
                raise EditRefused(index, f"'{key}' is the app's display cache; set "
                                         f"'{key[:-len('__label')]}' and the app shows its label.",
                                  field=f"settings.{key}")
        if node_type == "agent":
            misplaced = misplaced_agent_model(settings)
            if misplaced:
                raise EditRefused(index, misplaced, field="settings")
        try:
            normalize_canvas_fields(node_type, settings)
        except ValueError as e:
            raise EditRefused(index, str(e), field="settings") from None

    async def _reserve_email(self, index: int, node_type: str, step_id: str, updates: Dict[str, Any]) -> None:
        """An inbound-email trigger's address is claimed as it's written: one inbox is one step's."""
        if node_type != "trigger-email" or "local_part" not in updates:
            return
        from utils.email_reservation_manager import EmailReservationManager, get_inbound_email_domain

        if get_inbound_email_domain() is None:
            raise EditRefused(index, "This installation receives no email, so an inbox can't be given an address.",
                              field="settings.local_part")
        try:
            updates.update(await EmailReservationManager.reserve_from_config(
                None, self.ctx.user_id, self.ctx.workflow_id, step_id, updates, conn=self.ctx.conn))
        except ValueError as e:
            raise EditRefused(index, f"local_part: {e}. Choose another inbox name.", field="settings.local_part") \
                from None

    def _postprocess(self, index: int, node: Dict[str, Any], config: Dict[str, Any], *, changed: Set[str],
                     prior: Dict[str, Any], harness_prior: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """The shared post-write pass, its verdict left for the end of the batch; a value of the wrong type is
        refused rather than dropped."""
        from .workflow_ops import postprocess_config

        notes = postprocess_config(
            node["type"], config.get("operation"), config, is_provider=self._is_provider(node["id"]),
            upstream_trigger_ids=self._upstream_triggers(node["id"]) if node["type"] == "agent" else None,
            changed_keys=changed, prior_config=prior, harness_prior=harness_prior, judge=False,
        ) or {}
        rejected = notes.pop("rejected_values", None)
        if rejected:
            first = rejected["fields"][0]
            raise EditRefused(index, f"settings.{first['field']}: {first['error']}", field=f"settings.{first['field']}")
        switch = notes.get("harness_switch")
        if switch and switch["from"] != switch["to"]:
            self._harness_switches.append((switch["from"], switch["to"]))
        return notes

    @staticmethod
    def _set_config(node: Dict[str, Any], config: Dict[str, Any]) -> None:
        if isinstance(node.get("data"), dict):
            node["data"]["config"] = config
        else:
            node["config"] = config

    # ── steps ──

    async def _add_step(self, index: int, op: AddStep) -> Dict[str, Any]:
        from nodes.core.registry import NODE_REGISTRY

        from .workflow_ops import new_node

        if op.type not in NODE_REGISTRY:
            raise EditRefused(index, f"'{op.type}' isn't a step type NoClick has.", field="type")
        self._check_operation(index, op.type, op.operation)
        settings = copy.deepcopy(op.settings)
        self._check_settings(index, op.type, settings)
        if op.operation:
            settings["operation"] = op.operation
        node = new_node(op.type, settings, op.position.model_dump() if op.position else {"x": 0, "y": 0},
                        label=op.name)
        node["id"] = self._new_id(index, op.id, node["id"])
        await self._reserve_email(index, op.type, node["id"], node["config"])
        self.nodes.append(node)
        notes = self._postprocess(index, node, node["config"], changed=set(node["config"]), prior={},
                                  harness_prior=None)
        if op.position is None:
            self._unplaced.append(node["id"])
        self._touch(node["id"])
        return {"id": node["id"], **notes}

    async def _update_step(self, index: int, op: UpdateStep) -> Dict[str, Any]:
        from utils.webhook_manager import _WEBHOOK_CONFIG_FIELDS, WebhookManager

        from .workflow_ops import (
            deep_merge_config, drop_stale_agent_discriminator, mcp_server_url_conflict, set_node_disabled,
            trigger_provider_conflict,
        )

        node = self._node(index, op.id)
        node_type = node.get("type", "")
        existing = copy.deepcopy(node_config(node))
        updates = copy.deepcopy(op.settings or {})
        self._check_settings(index, node_type, updates)
        if op.name is not None:
            updates["label"] = op.name
        if op.operation is not None:
            self._check_operation(index, node_type, op.operation)
            updates["operation"] = op.operation
            if self._is_provider(op.id):
                conflict = trigger_provider_conflict(node_type, op.operation)
                if conflict:
                    raise EditRefused(index, conflict, field="operation")
        if "server_url" in updates:
            conflict = mcp_server_url_conflict(op.id, node_type, updates["server_url"], self.edges)
            if conflict:
                raise EditRefused(index, conflict, field="settings.server_url")
        await self._reserve_email(index, node_type, op.id, updates)
        merged = deep_merge_config(existing, updates)
        drop_stale_agent_discriminator(node_type, updates, merged)
        notes = self._postprocess(index, node, merged, changed=set(updates), prior=existing,
                                  harness_prior=existing if node_type == "agent" else None)
        if op.enabled is not None:
            set_node_disabled(merged, not op.enabled)
        old_op, new_op = existing.get("operation"), merged.get("operation")
        # A trigger switched to an operation that needs no webhook keeps none of its registration's mirrors.
        if old_op and new_op != old_op and WebhookManager.operation_requires_webhook(node_type, old_op) \
                and not WebhookManager.operation_requires_webhook(node_type, new_op):
            for key in _WEBHOOK_CONFIG_FIELDS:
                merged.pop(key, None)
        self._set_config(node, merged)
        self._touch(op.id)
        return {"id": op.id, "changed": merged != existing, **notes}

    async def _patch_step(self, index: int, op: PatchStep) -> Dict[str, Any]:
        from utils.runtime_keys import runtime_key_refusal

        from .workflow_ops import apply_config_patch

        node = self._node(index, op.id)
        refused = runtime_key_refusal(op.field)
        if refused:
            raise EditRefused(index, refused, field="field")
        existing = copy.deepcopy(node_config(node))
        config = copy.deepcopy(existing)
        err = apply_config_patch(config, op.field, op.patch)
        if err:
            raise EditRefused(index, err, field="patch")
        prior = {op.field: existing[op.field]} if op.field in existing else {}
        notes = self._postprocess(index, node, config, changed={op.field}, prior=prior, harness_prior=None)
        self._set_config(node, config)
        self._touch(op.id)
        return {"id": op.id, **notes}

    async def _remove_step(self, index: int, op: RemoveStep) -> Dict[str, Any]:
        self._node(index, op.id)
        self.graph["nodes"] = [n for n in self.nodes if n.get("id") != op.id]
        self.graph["edges"] = [e for e in self.edges if op.id not in (e.get("source"), e.get("target"))]
        self._touched = [t for t in self._touched if t != op.id]
        self._unplaced = [u for u in self._unplaced if u != op.id]
        return {"id": op.id}

    # ── edges ──

    async def _connect(self, index: int, op: Connect) -> Dict[str, Any]:
        from .workflow_ops import PROVIDER_TARGET_HANDLE, check_edge, new_edge

        self._node(index, op.from_, field_name="from")
        self._node(index, op.to, field_name="to")
        try:
            source_handle, target_handle = check_edge(
                {n.get("id"): n for n in self.nodes}, self.edges, op.from_, op.to,
                edge_type="tools" if op.kind == "tools" else None, handle=op.handle)
        except ValueError as e:
            raise EditRefused(index, str(e), field="kind" if op.kind == "tools" else "to") from None
        kind = "tools" if target_handle == PROVIDER_TARGET_HANDLE else "data"
        found = next((e for e in self.edges if e.get("source") == op.from_ and e.get("target") == op.to
                      and e.get("sourceHandle") == source_handle), None)
        if found is None:
            found = new_edge(op.from_, op.to, source_handle, target_handle)
            self.edges.append(found)
        self._touch(op.to)
        return {"from": op.from_, "to": op.to, "kind": kind, "edge_id": found["id"]}

    async def _disconnect(self, index: int, op: Disconnect) -> Dict[str, Any]:
        found = next((e for e in self.edges if e.get("source") == op.from_ and e.get("target") == op.to
                      and (op.handle is None or e.get("sourceHandle") == op.handle)), None)
        if found is None:
            raise EditRefused(index, f"'{op.from_}' isn't connected to '{op.to}'.", field="to")
        self.graph["edges"] = [e for e in self.edges if e is not found]
        if any(n.get("id") == op.to for n in self.nodes):
            self._touch(op.to)
        return {"from": op.from_, "to": op.to, "edge_id": found.get("id")}

    # ── connections and mocks ──

    async def _set_connection(self, index: int, op: SetConnection) -> Dict[str, Any]:
        from .operation_catalog import node_accepted_credential_types
        from .workflow_ops import merge_credentials

        node = self._node(index, op.id)
        config = copy.deepcopy(node_config(node))
        held = dict(config.get("credentialIds") or {}) if isinstance(config.get("credentialIds"), dict) else {}
        if op.connection is None:
            if not op.slot:
                raise EditRefused(index, "To take a connection off a step, name its slot.", field="slot")
            held.pop(op.slot, None)
            config["credentialIds"] = held
        else:
            kind = self.ctx.credential_types.get(op.connection)
            if kind is None:
                raise EditRefused(index, f"No connection '{op.connection}' that this account can use.",
                                  field="connection")
            if op.slot and op.slot != kind:
                raise EditRefused(index, f"'{op.connection}' is a {kind} connection, not {op.slot}.", field="slot")
            accepted = node_accepted_credential_types(node.get("type", ""), config.get("operation"), config)
            if accepted and kind not in accepted:
                raise EditRefused(index, f"'{op.id}' takes no {kind} connection (it takes: "
                                         f"{', '.join(sorted(accepted))}).", field="connection")
            merge_credentials(config, {kind: op.connection})
            self.connections.add(op.connection)
        self._set_config(node, config)
        self._touch(op.id)
        return {"id": op.id, "slot": op.slot or self.ctx.credential_types.get(op.connection or "")}

    async def _mock_step(self, index: int, op: MockStep) -> Dict[str, Any]:
        node = self._node(index, op.id)
        config = copy.deepcopy(node_config(node))
        config["mockedOutput"] = copy.deepcopy(op.output)
        self._set_config(node, config)
        return {"id": op.id}

    async def _unmock_step(self, index: int, op: UnmockStep) -> Dict[str, Any]:
        from .workflow_ops import set_mock_output

        node = self._node(index, op.id)
        config = copy.deepcopy(node_config(node))
        set_mock_output(config, None)
        node.pop("mockedOutput", None)
        self._set_config(node, config)
        return {"id": op.id}

    # ── the workflow's own fields ──

    def _require_owner(self, index: int, what: str) -> None:
        if not self.ctx.is_owner:
            raise EditRefused(index, f"Only the workflow's owner can change its {what}.")

    def _write_settings(self, key: str, value: Any) -> None:
        self.settings[key] = value

    def _current_setting(self, key: str) -> Any:
        return self.settings.get(key, self._stored_settings.get(key))

    async def _update_workflow(self, index: int, op: UpdateWorkflow) -> Dict[str, Any]:
        from utils.system_workflows import client_settings

        if op.name is not None:
            self.name = op.name.strip()
            if not self.name:
                raise EditRefused(index, "A workflow's name can't be empty.", field="name")
        if op.description is not None:
            from .agentic.commands import MAX_DESCRIPTION_CHARS

            line = " ".join(op.description.split())
            if len(line) > MAX_DESCRIPTION_CHARS:
                raise EditRefused(index, f"A description is one line of at most {MAX_DESCRIPTION_CHARS} characters.",
                                  field="description")
            self.description = line
        if op.settings is not None:
            self._require_owner(index, "settings")
            allowed = client_settings(op.settings)
            kept = sorted(set(op.settings) - set(allowed))
            if kept:
                raise EditRefused(index, f"'{kept[0]}' is a setting only NoClick writes.", field=f"settings.{kept[0]}")
            for key, value in allowed.items():
                self._write_settings(key, value)
        return {}

    async def _define_variable(self, index: int, op: DefineVariable) -> Dict[str, Any]:
        from .workflow_ops import parse_define_variable, upsert_variable_definitions
        from .workflow_xml import XmlOp

        self._require_owner(index, "variables")
        attrs = {"name": op.name, **({"description": op.description} if op.description else {}),
                 **({"per_user": ""} if op.per_user else {})}
        definition, err = parse_define_variable(XmlOp(tag="define_variable", attrs=attrs, body=op.value))
        if err:
            raise EditRefused(index, err, field="name")
        self._write_settings("variable_definitions", upsert_variable_definitions(
            self._current_setting("variable_definitions"), [definition]))
        return {"name": definition["name"]}

    async def _add_test_run(self, index: int, op: AddTestRun) -> Dict[str, Any]:
        from nodes.agent.rehearsal_scenarios import base_scenario_key_for_type, can_stage_trigger

        from .workflow_ops import append_rehearsal_run, parse_add_test_run
        from .workflow_xml import XmlOp

        self._require_owner(index, "test runs")
        attrs = {k: v for k, v in {"trigger": op.trigger, "name": op.name, "title": op.title, "author": op.author,
                                   "handle": op.handle}.items() if v}
        parsed, err = parse_add_test_run(XmlOp(tag="add_test_run", attrs=attrs, body=op.body))
        if err:
            raise EditRefused(index, err)
        ref = parsed["trigger_ref"]
        node = next((n for n in self.nodes if n.get("id") == ref), None) or \
            next((n for n in self.nodes if n.get("type") == ref), None)
        if node is None:
            raise EditRefused(index, f"No step '{ref}' in this workflow.", field="trigger")
        if not can_stage_trigger(node, self.nodes, self.edges):
            raise EditRefused(index, f"'{ref}' can't stage a test run: it must be a trigger (not a step wired in as "
                                     "a tool) with an agent after it.", field="trigger")
        node_type = node.get("type") or ""
        authoring, slug = append_rehearsal_run(self._current_setting("rehearsal_authoring"), node_type,
                                               parsed["name"], parsed["lead"], base_scenario_key_for_type(node_type))
        self._write_settings("rehearsal_authoring", authoring)
        return {"name": parsed["name"], "slug": slug, "trigger_type": node_type}

    # ── layout and notes ──

    async def _move(self, index: int, op: Move) -> Dict[str, Any]:
        node = self._node(index, op.id)
        node["position"] = op.position.model_dump()
        self._unplaced = [u for u in self._unplaced if u != op.id]
        return {"id": op.id}

    async def _layout(self, index: int, op: Layout) -> Dict[str, Any]:
        from .layout import compute_incremental_layout

        compute_incremental_layout(self.nodes, self.edges, pin_existing=False)
        self._unplaced = []
        return {}

    async def _add_note(self, index: int, op: AddNote) -> Dict[str, Any]:
        from .workflow_ops import create_sticky_note_dict, resolve_sticky_note_position

        config: Dict[str, Any] = {"content": op.content, "color": op.color}
        if (op.after is None) != (op.before is None):
            raise EditRefused(index, "A note covers a stretch with both after and before, or sits near steps.",
                              field="after" if op.after is None else "before")
        if op.after is not None:
            self._node(index, op.after, field_name="after")
            self._node(index, op.before, field_name="before")
            config.update({"_anchor_after": op.after, "_anchor_before": op.before})
        elif op.near:
            for ref in op.near:
                self._node(index, ref, field_name="near")
            config.update({"_anchor_near": list(op.near), "_anchor_direction": op.direction})
        if op.width is not None:
            config["_anchor_width"] = op.width
        if op.height is not None:
            config["_anchor_height"] = op.height
        placed = resolve_sticky_note_position(self.nodes, self.edges, config)
        node = create_sticky_note_dict(config, placed["position"], placed["width"], placed["height"])
        node["id"] = self._new_id(index, op.id, node["id"])
        self.nodes.append(node)
        return {"id": node["id"]}

    # ── the end of the batch ──

    def _finish(self) -> None:
        from .layout import compute_incremental_layout
        from .workflow_ops import (
            CANVAS_ONLY_CONFIG_KEYS, agent_trigger_fed, judge_config, recompute_sticky_positions,
            rename_workflow_for_harness_switches, strip_agent_trigger_message_refs,
        )

        if self._unplaced:
            placed = compute_incremental_layout(copy.deepcopy(self.nodes), self.edges,
                                                newly_added_ids=self._unplaced)["positions"]
            for node in self.nodes:
                if node.get("id") in self._unplaced and node["id"] in placed:
                    node["position"] = placed[node["id"]]
        recompute_sticky_positions(self.nodes, self.edges)
        by_id = {n.get("id"): n for n in self.nodes}
        for step_id in self._touched:
            node = by_id.get(step_id)
            if node is None or node.get("type") == "stickyNote":
                continue
            config = copy.deepcopy(node_config(node))
            node_type = node.get("type", "")
            # A trigger the batch wired in later than it wrote the message: its event is the turn, not a template.
            stripped = node_type == "agent" and strip_agent_trigger_message_refs(
                config, self._upstream_triggers(step_id))
            if stripped:
                self._set_config(node, config)
            if self._is_provider(step_id) or CANVAS_ONLY_CONFIG_KEYS & set(config):
                continue
            self.steps[step_id] = judge_config(node_type, config.get("operation"), config,
                                               trigger_fed=agent_trigger_fed(step_id, self.nodes, self.edges))
            if stripped:
                self.steps[step_id]["stripped_trigger_refs"] = {"node_ids": stripped, "message": config["message"]}
        if self._harness_switches and self.name is None:
            self.name = rename_workflow_for_harness_switches(self._stored_name, self._harness_switches)


async def apply_ops(graph: Any, ops: Sequence[Any], *, name: str, settings: Optional[Dict[str, Any]],
                    context: EditContext) -> GraphEditor:
    editor = GraphEditor(graph, name=name, settings=settings, context=context)
    await editor.apply(ops)
    return editor


# ── what a write changed ────────────────────────────────────────────────────

# Described on their own, not as a changed field.
_OWN_LINES = frozenset({"label", "operation", "disabled", "credentialIds"})
_SHOWN_FIELDS = 3


def _title(node: Dict[str, Any]) -> str:
    if node.get("type") == "stickyNote":
        return "a note"
    return f"'{node_label(node) or node.get('type') or node.get('id')}'"


def _edge_key(edge: Dict[str, Any]) -> tuple:
    return (edge.get("source") or edge.get("sourceId"), edge.get("target") or edge.get("targetId"),
            edge.get("sourceHandle"), edge.get("targetHandle"))


def describe_changes(old: Any, new: Any) -> List[str]:
    """What a write changed, one line each: steps added, removed, renamed,
    switched on or off, given another operation or connection, or
    reconfigured (the fields named), and steps connected or disconnected.
    Where things sit and NoClick's own trigger records aren't changes: a write
    of only those describes nothing."""
    old_nodes = {n.get("id"): n for n in graph_nodes(old) if n.get("id")}
    new_nodes = {n.get("id"): n for n in graph_nodes(new) if n.get("id")}
    lines: List[str] = [f"added {_title(n)}" for i, n in new_nodes.items() if i not in old_nodes]
    lines += [f"removed {_title(n)}" for i, n in old_nodes.items() if i not in new_nodes]
    for step_id in [i for i in new_nodes if i in old_nodes]:
        before, after = node_config(old_nodes[step_id]), node_config(new_nodes[step_id])
        if before == after:
            continue
        title = _title(new_nodes[step_id])
        if (before.get("label") or "") != (after.get("label") or ""):
            lines.append(f"renamed {_title(old_nodes[step_id])} to {title}")
        if bool(before.get("disabled")) != bool(after.get("disabled")):
            lines.append(f"turned {'off' if after.get('disabled') else 'on'} {title}")
        if before.get("operation") != after.get("operation"):
            lines.append(f"switched {title} to {after.get('operation')}")
        if (before.get("credentialIds") or {}) != (after.get("credentialIds") or {}):
            lines.append(f"changed the connections of {title}")
        ignored = _OWN_LINES | (REGISTRATION_MIRRORS if is_trigger_node(new_nodes[step_id]) else frozenset())
        fields = sorted(k for k in set(before) | set(after) if k not in ignored and before.get(k) != after.get(k))
        if fields:
            shown = ", ".join(fields[:_SHOWN_FIELDS]) + (f" and {len(fields) - _SHOWN_FIELDS} more"
                                                         if len(fields) > _SHOWN_FIELDS else "")
            lines.append(f"changed {title} ({shown})")
    names = {**{i: _title(n) for i, n in old_nodes.items()}, **{i: _title(n) for i, n in new_nodes.items()}}
    old_edges, new_edges = {_edge_key(e) for e in graph_edges(old)}, {_edge_key(e) for e in graph_edges(new)}
    lines += [f"connected {names.get(e[0], e[0])} to {names.get(e[1], e[1])}" for e in new_edges - old_edges]
    # A removed step's edges go with it, said already.
    lines += [f"disconnected {names.get(e[0], e[0])} from {names.get(e[1], e[1])}" for e in old_edges - new_edges
              if e[0] in new_nodes and e[1] in new_nodes]
    if isinstance(new, dict) and ((old or {}).get("variables") or {}) != (new.get("variables") or {}):
        lines.append("changed its variables")
    return lines


def summary(changes: Sequence[str], *, limit: int = 280) -> str:
    """One line from a version's changes."""
    text = "; ".join(changes)
    return text if len(text) <= limit else text[:limit - 1].rsplit(";", 1)[0] + "; …"


def merge_changes(earlier: Sequence[str], later: Sequence[str]) -> List[str]:
    return list(dict.fromkeys([*earlier, *later]))

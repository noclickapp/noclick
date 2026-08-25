"""Community conversational workflow builder.

The community controller deliberately has a small public contract: a brain
emits documented XML operations, graph changes are applied, and every new node
is completed by the registered node drafter.  The built-in drafter uses one
model call per node.  Installations can replace it through
``register_node_drafter`` without changing this controller.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from ..builder_events import BuilderStreamEvent
from ..graph_state import GraphState
from ..node_drafter import create_node_drafter
from ..schema import BuilderInput, BuilderOutput
from ..session_logger import SessionLogger
from ..workflow_xml import XmlOp, parse_xml
from utils.cancellation import (
    CancelScope,
    CancelledByUser,
    bind_scope,
    reset_scope,
)
from .brain import BrainProtocol, BrainResponse, make_default_brain
from .commands import (
    AGENTIC_TAGS,
    NODE_OPS_TAGS,
    PLATFORM_TAGS,
    WORKFLOW_CONTENT_TAGS,
    PlatformOps,
    build_execution_summary,
    execute_field_ops,
    execute_graph_mutations,
    execute_node_ops,
    execute_platform_ops,
    execute_query_operations,
    execute_query_schema,
    execute_read,
    execute_read_config,
    execute_settings_ops,
    execute_sticky_note_ops,
    execute_workflow_content_ops,
    extract_ask_requests,
)
from .config import AgenticBuilderConfig, DEFAULT_AGENTIC_CONFIG
from .prompts import build_system_prompt
from .state import ExecutionEffects, PendingAsk, TurnResult

logger = logging.getLogger(__name__)

EXEC_RESULT_MARKER = "[System: Execution Result]"
USER_INPUT_MARKER = "[System: User Input Response]"

# Metadata lives at the top level of frontend node data rather than inside the
# editable config object.  The handler uses this set when translating events.
NODE_METADATA_KEYS = frozenset({
    "credentialIds",
    "disabled",
    "mockedOutput",
    "label",
    "goal",
    "operationReason",
    "userFields",
    "loopConcurrency",
    "credentials",
})

_OBSERVATION_TAGS = frozenset(
    {"query_operations", "query_schema", "read", "read_config", "get_output"}
)
_GRAPH_TAGS = frozenset({"add_node", "add_edge", "remove_node", "remove_edge"})


def _visible_text(response: str) -> str:
    """Remove recognized command elements while preserving conversational text."""

    text = response
    for tag in sorted(AGENTIC_TAGS, key=len, reverse=True):
        escaped = re.escape(tag)
        text = re.sub(
            rf"<{escaped}\b[^>]*>.*?</{escaped}\s*>", "", text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(
            rf"<{escaped}\b[^>]*/\s*>", "", text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(rf"</?{escaped}\b[^>]*>", "", text, flags=re.IGNORECASE)
    return text.strip()


class AgenticBuilder:
    """Small community controller backed by the public one-call node drafter."""

    def __init__(
        self,
        config: Optional[AgenticBuilderConfig] = None,
        generation_id: Optional[str] = None,
        debug_callback=None,
        platform_ops: Optional[PlatformOps] = None,
        conversation_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[str] = None,
        brain: Optional[BrainProtocol] = None,
        cancel_scope: Optional[CancelScope] = None,
    ) -> None:
        self.config = config or DEFAULT_AGENTIC_CONFIG
        self.generation_id = generation_id or str(uuid.uuid4())
        self.debug_callback = debug_callback
        self.platform_ops = platform_ops
        self.conversation_id = conversation_id
        self.workflow_id = workflow_id
        self.user_id = user_id
        self.cancel_scope = cancel_scope or CancelScope()
        self.brain = brain or make_default_brain(self.config)

        self.graph_state = GraphState()
        self._initial_graph_fingerprint = self._graph_fingerprint()
        self.messages: List[Dict[str, str]] = []
        self._user_prompt = ""
        self._host_theme: Optional[str] = None
        self._viewport_width: Optional[float] = None
        self._viewport_height: Optional[float] = None
        self._turn_count = 0
        self._attempt: Optional[int] = None
        self._total_cost = 0.0
        self._total_tokens = 0
        self._emitted_text = False
        self._last_turn_result = TurnResult(next_action="continue")
        self._execution_effects: List[ExecutionEffects] = []
        self.session_log = SessionLogger(
            self.generation_id,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            user_id=user_id,
        )

    @property
    def emitted_text(self) -> bool:
        return self._emitted_text

    async def generate(self, input: BuilderInput) -> None:
        """Seed a new workflow; ``run_one_turn`` drives generation."""

        self.graph_state = GraphState()
        if self.platform_ops and hasattr(self.platform_ops, "_graph_state"):
            self.platform_ops._graph_state = self.graph_state
        self._initial_graph_fingerprint = self._graph_fingerprint()
        self._user_prompt = input.prompt
        self._host_theme = (input.context or {}).get("theme")
        self._viewport_width = (input.context or {}).get("viewport_width")
        self._viewport_height = (input.context or {}).get("viewport_height")
        self.messages = [
            {"role": "system", "content": build_system_prompt(self.graph_state)},
            {"role": "user", "content": input.prompt},
        ]
        self.session_log.log_session_start(
            mode="generate",
            prompt=input.prompt,
            brain_model=self.config.brain_model,
            node_drafter_model=self.config.node_drafter.model,
            max_turns=self.config.max_turns,
            workflow_id=self.workflow_id,
        )

    async def edit(
        self,
        current_graph: Dict[str, Any],
        edit_prompt: str,
        target_node_ids: Optional[List[str]] = None,
        selected_node_id: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        silent: bool = False,
        user_context: Optional[Dict[str, Any]] = None,
        viewport_width: Optional[float] = None,
        viewport_height: Optional[float] = None,
        n8n_workflow: Optional[Dict[str, Any]] = None,
        edit_scope: Optional[str] = None,
    ) -> None:
        """Seed an edit from the saved graph and optional conversation history."""

        self.graph_state = GraphState.from_dict(current_graph or {})
        if self.platform_ops and hasattr(self.platform_ops, "_graph_state"):
            self.platform_ops._graph_state = self.graph_state
        self._initial_graph_fingerprint = self._graph_fingerprint()
        self._user_prompt = edit_prompt
        self._host_theme = (user_context or {}).get("theme")
        self._viewport_width = viewport_width
        self._viewport_height = viewport_height
        if n8n_workflow:
            nodes = n8n_workflow.get("nodes") or []
            self.graph_state._n8n_context = {
                str(node.get("id") or node.get("name")): node
                for node in nodes
                if node.get("id") or node.get("name")
            }
        system = build_system_prompt(
            self.graph_state,
            silent=silent,
            user_context=user_context,
            n8n_context=self.graph_state._n8n_context or None,
            edit_scope=edit_scope,
            scoped_node_id=selected_node_id,
        )
        user_content = edit_prompt
        if selected_node_id and selected_node_id in self.graph_state.nodes:
            node = self.graph_state.nodes[selected_node_id]
            user_content += (
                f'\nThe selected node is "{selected_node_id}" '
                f'({node.label}, type: {node.type}). References such as '
                '"this node" or "it" refer to that node.'
            )
        self.messages = [{"role": "system", "content": system}]
        if conversation_history:
            self.messages.extend(conversation_history)
        self.messages.append({"role": "user", "content": user_content})
        self.session_log.log_session_start(
            mode="edit",
            prompt=edit_prompt,
            brain_model=self.config.brain_model,
            node_drafter_model=self.config.node_drafter.model,
            max_turns=self.config.max_turns,
            current_graph_summary=(
                f"{len(self.graph_state.nodes)} nodes, "
                f"{len(self.graph_state.edges)} edges"
            ),
            workflow_id=self.workflow_id,
        )

    async def run_one_turn(self) -> AsyncIterator[BuilderStreamEvent]:
        """Run one turn with cooperative cancellation and clean message rollback."""

        message_count = len(self.messages)
        cancel_token = bind_scope(self.cancel_scope)
        try:
            async for event in self._run_one_turn_inner():
                yield event
        except CancelledByUser:
            self.messages = self.messages[:message_count]
            self._last_turn_result = TurnResult(
                next_action="cancelled",
                cancel_reason=getattr(self.cancel_scope, "reason", None) or "user",
            )
        finally:
            reset_scope(cancel_token)

    async def _run_one_turn_inner(self) -> AsyncIterator[BuilderStreamEvent]:
        """Run the model and apply its public workflow operations."""

        self._turn_count += 1
        turn = self._turn_count
        response_text = ""
        final: Optional[BrainResponse] = None
        try:
            async for item in self.brain.step(
                self.messages,
                turn=turn,
                generation_id=self.generation_id,
                workflow_id=self.workflow_id,
            ):
                if isinstance(item, BrainResponse):
                    final = item
                else:
                    response_text += str(item)
        except CancelledByUser:
            raise
        except Exception as exc:
            logger.exception("Community builder brain failed")
            self.session_log.log_error(error=str(exc), turn=turn)
            yield BuilderStreamEvent(type="error", data={"error": str(exc)})
            self._last_turn_result = TurnResult(
                next_action="incomplete", incomplete_reason="brain_error"
            )
            return

        if final is not None:
            response_text = final.text or response_text
            self._total_cost += final.cost
            self._total_tokens += final.total_tokens

        visible = _visible_text(response_text)
        if visible:
            self._emitted_text = True
            yield BuilderStreamEvent(type="text_chunk", data={"text": visible})

        self.messages.append({"role": "assistant", "content": response_text})
        ops = parse_xml(response_text, allowed_tags=AGENTIC_TAGS)
        if len(ops) > self.config.max_ops_per_turn_kill:
            self._last_turn_result = TurnResult(
                next_action="incomplete", incomplete_reason="operation_limit"
            )
            yield BuilderStreamEvent(
                type="error", data={"error": "Too many workflow operations in one turn."}
            )
            return

        if self.conversation_id:
            from .. import resume_checkpoint

            await resume_checkpoint.save_plan(
                self.conversation_id,
                turn=turn,
                prompt=self._user_prompt,
                ops=ops,
            )

        actionable = [op for op in ops if op.tag not in {"done", "message", "ask"}]
        graph_before = self._graph_fingerprint()
        summary = ""
        if actionable:
            async for item in self._execute_operations(actionable):
                if isinstance(item, str):
                    summary = item
                else:
                    yield item

        message_text = "\n".join(
            (op.body or op.attrs.get("text", "")).strip()
            for op in ops
            if op.tag == "message" and (op.body or op.attrs.get("text"))
        ).strip()
        if message_text and message_text not in visible:
            self._emitted_text = True
            yield BuilderStreamEvent(type="text_chunk", data={"text": message_text})

        effects = ExecutionEffects(
            turn=turn,
            observation_ops=[op.tag for op in actionable if op.tag in _OBSERVATION_TAGS],
            material_ops_attempted=[op.tag for op in actionable if op.tag not in _OBSERVATION_TAGS],
            graph_changed=self._graph_fingerprint() != graph_before,
        )
        self._execution_effects.append(effects)
        self.session_log.log_execution_effects(**effects.to_dict())

        if summary:
            self.messages.append({
                "role": "user",
                "content": (
                    f"{EXEC_RESULT_MARKER}\n{summary}\n\n"
                    "Review the result. If the request is complete, summarize it and "
                    "include <done/>. Otherwise continue with the next public XML operations."
                ),
            })

        ask_requests, rejections = extract_ask_requests(
            [op for op in ops if op.tag == "ask"], self.graph_state
        )
        if rejections:
            self.messages.append({
                "role": "user", "content": "[System: Error]\n" + "\n".join(rejections)
            })
        if ask_requests:
            ask_id = str(uuid.uuid4())
            yield BuilderStreamEvent(
                type="input_request", data={"ask_id": ask_id, "inputs": ask_requests}
            )
            self._last_turn_result = TurnResult(
                next_action="ask",
                pending_ask=PendingAsk(ask_id=ask_id, inputs=ask_requests),
            )
            return

        if any(op.tag == "done" for op in ops) and not rejections:
            # A completion marker bundled with mutations cannot confirm their
            # outcome.  Feed the execution summary back first, then accept a
            # later no-action completion after checking the resulting graph.
            if actionable:
                self._last_turn_result = TurnResult(next_action="continue")
            elif (
                not self._gate_on_missing_credentials("Done")
                and not self._gate_on_invalid_configs("Done")
            ):
                self._last_turn_result = TurnResult(next_action="done")
        else:
            self._last_turn_result = TurnResult(next_action="continue")

    _CONFIG_NUDGE_MARKER = "[System: Configuration check]"
    _CONFIG_NUDGE_LIMIT = 2

    def _config_done_nudge(self) -> Optional[str]:
        """Return bounded repair guidance when an executable node is invalid."""

        did_work = any(
            message.get("role") == "user"
            and EXEC_RESULT_MARKER in (message.get("content") or "")
            for message in self.messages
        )
        if not did_work:
            return None
        attempts = sum(
            self._CONFIG_NUDGE_MARKER in (message.get("content") or "")
            for message in self.messages
            if message.get("role") == "user"
        )
        if attempts >= self._CONFIG_NUDGE_LIMIT:
            return None
        from ..operation_catalog import validate_node_config

        problems: List[str] = []
        for node in self.graph_state.nodes.values():
            config = node.config or {}
            if config.get("disabled") or not node.operation:
                continue
            allowlist = config.get("agent_tool_operations")
            if isinstance(allowlist, list) and allowlist:
                continue
            error = validate_node_config(node.type, node.operation, config)
            if error:
                problems.append(
                    f"- {node.id} ({node.type}:{node.operation}): {error}"
                )
        if not problems:
            return None
        return (
            f"{self._CONFIG_NUDGE_MARKER}\n"
            "Before finishing, repair these invalid node configurations with "
            "public <field> operations or ask the user for unknown values:\n"
            + "\n".join(problems)
        )

    def _gate_on_invalid_configs(self, _where: str = "done") -> bool:
        """Keep the conversation open when the current graph cannot execute."""

        nudge = self._config_done_nudge()
        if not nudge:
            return False
        self.messages.append({"role": "user", "content": nudge})
        self._last_turn_result = TurnResult(next_action="continue")
        return True

    _CRED_NUDGE_MARKER = "[System: Credential check]"

    def _credential_done_nudge(self) -> Optional[str]:
        """Return one reminder when executable nodes still need credentials."""

        did_work = any(
            message.get("role") == "user"
            and EXEC_RESULT_MARKER in (message.get("content") or "")
            for message in self.messages
        )
        if not did_work:
            return None
        if any(
            self._CRED_NUDGE_MARKER in (message.get("content") or "")
            for message in self.messages
            if message.get("role") == "user"
        ):
            return None
        from .commands import nodes_missing_credentials

        missing = nodes_missing_credentials(self.graph_state)
        if not missing:
            return None
        listing = ", ".join(
            f"{node.id} ({node.type}:{node.operation or 'default'})"
            for node in missing
        )
        return (
            f"{self._CRED_NUDGE_MARKER}\n"
            f"Before finishing, {listing} still require credentials. Search and "
            "attach an accessible credential, or ask the user to connect one. "
            "If they decline, finish only after clearly explaining the limitation."
        )

    def _gate_on_missing_credentials(self, _where: str = "done") -> bool:
        """Keep the conversation open once for missing required credentials."""

        nudge = self._credential_done_nudge()
        if not nudge:
            return False
        self.messages.append({"role": "user", "content": nudge})
        self._last_turn_result = TurnResult(next_action="continue")
        return True

    async def _execute_operations(
        self,
        ops: List[XmlOp],
        draft_node_ids: Optional[Set[str]] = None,
    ) -> AsyncIterator[BuilderStreamEvent | str]:
        mutation_results: List[str] = []
        field_results: List[str] = []
        query_results: List[str] = []
        new_node_ids: List[str] = []

        graph_ops = [op for op in ops if op.tag in _GRAPH_TAGS]
        removed = {
            op.attrs.get("name", ""): self.graph_state.get_node(op.attrs.get("name", ""))
            for op in graph_ops
            if op.tag == "remove_node"
        }
        if graph_ops:
            results, new_node_ids = execute_graph_mutations(graph_ops, self.graph_state)
            mutation_results.extend(results)
            for op in graph_ops:
                if op.tag == "add_node" and op.attrs.get("name") in new_node_ids:
                    node = self.graph_state.get_node(op.attrs["name"])
                    if node:
                        yield BuilderStreamEvent(type="node_added", data={"node": node.to_dict()})
                elif op.tag == "add_edge":
                    edge_id = f"e_{op.attrs.get('from', '')}_{op.attrs.get('to', '')}"
                    edge = self.graph_state.edges.get(edge_id)
                    if edge:
                        yield BuilderStreamEvent(type="edge_added", data={"edge": edge.to_dict()})
                elif op.tag == "remove_node":
                    node_id = op.attrs.get("name", "")
                    old = removed.get(node_id)
                    data: Dict[str, Any] = {"nodeId": node_id}
                    if old:
                        data.update({"nodeType": old.type, "nodeLabel": old.label})
                    yield BuilderStreamEvent(type="node_removed", data=data)
                elif op.tag == "remove_edge":
                    yield BuilderStreamEvent(
                        type="edge_removed",
                        data={"edgeId": f"e_{op.attrs.get('from', '')}_{op.attrs.get('to', '')}"},
                    )

        sticky_ops = [op for op in ops if op.tag == "add_sticky_note"]
        notes: List[Dict[str, Any]] = []
        if sticky_ops:
            results, notes = execute_sticky_note_ops(sticky_ops, self.graph_state)
            mutation_results.extend(results)
            for note in notes:
                yield BuilderStreamEvent(type="node_added", data={"node": note})

        # Keep placement as one public graph operation.  The layout helper
        # receives snapshots, then the resulting positions are written back to
        # the mutable state before the next model turn or final persistence.
        if graph_ops or sticky_ops:
            from ..layout import compute_incremental_layout

            added_ids = set(new_node_ids) | {
                str(note["id"]) for note in notes if note.get("id")
            }
            just_connected: Set[str] = set()
            for op in graph_ops:
                if op.tag != "add_edge":
                    continue
                for endpoint in ("from", "to"):
                    node_id = op.attrs.get(endpoint)
                    if node_id and node_id not in added_ids:
                        just_connected.add(node_id)
            layout_data = await asyncio.to_thread(
                compute_incremental_layout,
                self.graph_state.get_nodes_list(),
                self.graph_state.get_edges_list(),
                newly_added_ids=added_ids,
                just_connected_ids=just_connected,
                viewport_width=self._viewport_width,
                viewport_height=self._viewport_height,
            )
            for node_id, position in layout_data.get("positions", {}).items():
                node = self.graph_state.get_node(node_id)
                if node:
                    node.position = position
            yield BuilderStreamEvent(type="layout_applied", data=layout_data)

        nodes_to_draft = (
            set(new_node_ids) if draft_node_ids is None else set(draft_node_ids)
        )
        if nodes_to_draft:
            drafter = create_node_drafter(
                config=self.config.node_drafter,
                generation_id=self.generation_id,
                debug_callback=self.debug_callback,
            )
            drafter.graph_state = self.graph_state
            drafter.session_log = self.session_log
            drafter.user_prompt = self._user_prompt
            drafter.host_theme = self._host_theme
            async for event in drafter.draft_nodes(nodes_to_draft):
                if (
                    event.type == "node_updated"
                    and event.data.get("nodeId") in nodes_to_draft
                    and self.conversation_id
                ):
                    from .. import resume_checkpoint

                    await resume_checkpoint.mark_node_completed(
                        self.conversation_id, event.data["nodeId"]
                    )
                yield event
            self._total_cost += getattr(drafter, "accumulated_cost", 0.0)
            self._total_tokens += getattr(drafter, "accumulated_tokens", 0)

        field_ops = [op for op in ops if op.tag == "field"]
        if field_ops:
            operation_changes: Dict[str, tuple] = {}
            for op in field_ops:
                if op.attrs.get("name") != "operation":
                    continue
                node_id = op.attrs.get("node", "")
                node = self.graph_state.get_node(node_id)
                if node and node_id not in operation_changes:
                    operation_changes[node_id] = (
                        node.operation,
                        dict(node.config or {}),
                    )
            field_results.extend(execute_field_ops(field_ops, self.graph_state))
            await self._self_heal_operation_changes(
                operation_changes, field_results
            )
            touched: Set[str] = {
                op.attrs.get("node", "") or op.attrs.get("id", "") for op in field_ops
            }
            for node_id in sorted(touched - {""}):
                node = self.graph_state.get_node(node_id)
                if node:
                    yield BuilderStreamEvent(
                        type="node_updated",
                        data={
                            "nodeId": node.id,
                            "operation": node.operation,
                            "config": node.config,
                        },
                    )

        credential_ops = [op for op in ops if op.tag == "set_credentials"]
        if credential_ops:
            from ..operation_catalog import (
                get_credential_info,
                node_accepted_credential_types,
            )
            from ..workflow_ops import merge_credentials
            from utils.credentials import resolve_accessible_credential_types
            from utils.database_pool import get_runtime_database_url

            placed_credential_ids: Set[str] = set()
            for op in credential_ops:
                explicit_node = bool(op.attrs.get("node"))
                node_id = op.attrs.get("node", "") or op.attrs.get("id", "")
                node = self.graph_state.get_node(node_id)
                if not node:
                    field_results.append(
                        f"Credentials error: node '{node_id}' not found"
                    )
                    continue
                explicit_map = {
                    key: value
                    for key, value in op.attrs.items()
                    if key not in {"node", "id"} and value
                }
                simplified_id = (
                    op.attrs.get("id")
                    if explicit_node and not explicit_map
                    else None
                )
                candidate_ids = list(explicit_map.values())
                if simplified_id:
                    candidate_ids.append(simplified_id)
                if not candidate_ids:
                    field_results.append(
                        f"Credentials error: no credential ID provided for '{node_id}'"
                    )
                    continue

                credential_map: Dict[str, str] = {}
                if self.user_id and get_runtime_database_url():
                    actual_types = await resolve_accessible_credential_types(
                        candidate_ids, self.user_id
                    )
                    accepted_types = node_accepted_credential_types(
                        node.type, node.operation, node.config
                    )
                    for credential_id in candidate_ids:
                        actual_type = actual_types.get(credential_id)
                        if not actual_type:
                            field_results.append(
                                f"Credentials error: '{credential_id}' is not accessible"
                            )
                            continue
                        if accepted_types and actual_type not in accepted_types:
                            field_results.append(
                                f"Credentials error: '{actual_type}' is not accepted "
                                f"by node '{node_id}'"
                            )
                            continue
                        credential_map[actual_type] = credential_id
                elif explicit_map:
                    credential_map = explicit_map
                elif simplified_id:
                    info = get_credential_info(
                        node.type, node.operation, node.config
                    )
                    credential_type = (
                        info.credential_type
                        if info and info.credential_type
                        else node.type.removeprefix("automation-").replace("-", "_")
                    )
                    credential_map[credential_type] = simplified_id
                if not credential_map:
                    continue
                old_credential_ids = dict(
                    node.config.get("credentialIds") or {}
                )
                merge_credentials(node.config, credential_map)
                placed_credential_ids.update(credential_map.values())
                field_results.append(f"Set credentials on {node_id}")
                await self._self_heal_credential_change(
                    node, old_credential_ids, field_results
                )
                yield BuilderStreamEvent(
                    type="node_updated",
                    data={
                        "nodeId": node.id,
                        "operation": node.operation,
                        "config": node.config,
                    },
                )
            if placed_credential_ids and self.platform_ops:
                await self.platform_ops.authorize_credentials(
                    sorted(placed_credential_ids)
                )

        setting_ops = [op for op in ops if op.tag == "update_settings"]
        if setting_ops:
            field_results.extend(execute_settings_ops(setting_ops, self.graph_state))
            touched = {
                op.attrs.get("node", "") or op.attrs.get("id", "")
                for op in setting_ops
            }
            for node_id in sorted(touched - {""}):
                node = self.graph_state.get_node(node_id)
                if node:
                    yield BuilderStreamEvent(
                        type="node_updated",
                        data={
                            "nodeId": node.id,
                            "operation": node.operation,
                            "config": node.config,
                        },
                    )

        async for event in self._provision_trigger_webhooks(
            ops, new_node_ids, field_results
        ):
            yield event

        query_results.extend(execute_query_operations([op for op in ops if op.tag == "query_operations"]))
        query_results.extend(execute_query_schema([op for op in ops if op.tag == "query_schema"]))
        query_results.extend(execute_read([op for op in ops if op.tag == "read"]))
        query_results.extend(execute_read_config([op for op in ops if op.tag == "read_config"], self.graph_state))

        authored_runs: List[Dict[str, str]] = []
        if self.platform_ops:
            node_ops = [op for op in ops if op.tag in NODE_OPS_TAGS]
            if node_ops:
                query_results.extend(
                    await execute_node_ops(node_ops, self.platform_ops, self.graph_state)
                )
            platform_ops = [
                op for op in ops
                if op.tag in PLATFORM_TAGS and op.tag not in NODE_OPS_TAGS
            ]
            if platform_ops:
                platform_results = await execute_platform_ops(
                    platform_ops, self.platform_ops, self.graph_state
                )
                query_results.extend(platform_results)
                for op in platform_ops:
                    if op.tag != "open_workflow" or not op.attrs.get("id"):
                        continue
                    prefix = f'[open_workflow id={op.attrs["id"]}]'
                    if any(
                        result.startswith(prefix) and " Error:" not in result
                        for result in platform_results
                    ):
                        yield BuilderStreamEvent(
                            type="open_workflow",
                            data={"workflow_id": op.attrs["id"]},
                        )
            content_ops = [op for op in ops if op.tag in WORKFLOW_CONTENT_TAGS]
            if content_ops:
                results, authored_runs = await execute_workflow_content_ops(
                    content_ops, self.platform_ops, self.graph_state
                )
                query_results.extend(results)
                if any(not result.startswith("ERROR") for result in results):
                    yield BuilderStreamEvent(
                        type="settings_updated",
                        data={"workflow_id": self.workflow_id},
                    )
        else:
            unsupported = [
                op.tag
                for op in ops
                if op.tag in PLATFORM_TAGS or op.tag in WORKFLOW_CONTENT_TAGS
            ]
            if unsupported:
                query_results.append(
                    "Platform access is unavailable for: "
                    + ", ".join(sorted(set(unsupported)))
                )

        run_test_ops = [op for op in ops if op.tag == "run_test"]
        if run_test_ops:
            op = run_test_ops[-1]
            trigger_ref = (op.attrs.get("trigger") or "").strip()
            node = self.graph_state.get_node(trigger_ref) if trigger_ref else None
            trigger_type = node.type if node else (trigger_ref or None)
            run_ref = (op.attrs.get("run") or "").strip() or None
            for authored in reversed(authored_runs):
                if run_ref in {authored["name"], authored["slug"]} or (
                    not run_ref and not trigger_ref
                ):
                    trigger_type = authored["node_type"]
                    run_ref = authored["slug"]
                    break
            yield BuilderStreamEvent(
                type="run_test",
                data={
                    "workflow_id": self.workflow_id,
                    **({"trigger": trigger_type} if trigger_type else {}),
                    **({"run": run_ref} if run_ref else {}),
                },
            )

        yield build_execution_summary(
            self.graph_state,
            mutation_results,
            new_node_ids,
            field_results,
            query_results,
            new_node_ids,
        )

    async def _self_heal_operation_changes(
        self,
        previous: Dict[str, tuple],
        field_results: List[str],
    ) -> None:
        """Reconcile webhook registrations after an operation field changes."""

        changed: Dict[str, tuple] = {}
        for node_id, (old_operation, old_config) in previous.items():
            node = self.graph_state.get_node(node_id)
            if old_operation and node and node.operation != old_operation:
                changed[node_id] = (old_operation, old_config)
        if (
            not changed
            or not self.platform_ops
            or not self.user_id
            or not self.workflow_id
        ):
            return

        from utils.database_pool import get_native_pool
        from utils.webhook_manager import WebhookManager, _WEBHOOK_CONFIG_FIELDS

        try:
            pool = get_native_pool()
        except RuntimeError:
            return

        for node_id, (old_operation, old_config) in changed.items():
            node = self.graph_state.get_node(node_id)
            if not node:
                continue
            try:
                cleaned = await WebhookManager.handle_operation_change(
                    pool,
                    node.type,
                    self.workflow_id,
                    node_id,
                    old_operation,
                    node.operation,
                    old_config=old_config,
                    user_id=self.user_id,
                    nodes_override=[{
                        "id": node_id,
                        "type": node.type,
                        "config": {
                            **(node.config or {}),
                            "operation": node.operation,
                        },
                    }],
                )
            except Exception as exc:
                logger.warning(
                    "Webhook operation refresh failed for %s: %s", node_id, exc
                )
                field_results.append(
                    f"Webhook refresh failed for {node_id}: {exc}"
                )
                continue
            if not cleaned:
                continue
            if WebhookManager.operation_requires_webhook(
                node.type, node.operation
            ):
                field_results.append(
                    f"Re-registered {node_id}'s webhook for operation "
                    f"'{node.operation}'."
                )
            else:
                for field_name in _WEBHOOK_CONFIG_FIELDS:
                    node.config.pop(field_name, None)
                field_results.append(
                    f"Deregistered {node_id}'s '{old_operation}' webhook; "
                    f"'{node.operation}' does not use one."
                )

    async def _self_heal_credential_change(
        self,
        node: Any,
        old_credential_ids: Dict[str, Any],
        field_results: List[str],
    ) -> None:
        """Reconcile a webhook when the credential attached to its node changes."""

        new_credential_ids = dict(node.config.get("credentialIds") or {})
        if (
            old_credential_ids == new_credential_ids
            or not self.platform_ops
            or not self.user_id
            or not self.workflow_id
        ):
            return

        from utils.database_pool import get_native_pool
        from utils.webhook_manager import WebhookManager

        try:
            pool = get_native_pool()
        except RuntimeError:
            return
        try:
            await WebhookManager.handle_credential_change(
                pool,
                node.type,
                self.workflow_id,
                node.id,
                {"credentialIds": old_credential_ids},
                {"credentialIds": new_credential_ids},
                self.user_id,
            )
        except Exception as exc:
            logger.warning(
                "Webhook credential refresh failed for %s: %s", node.id, exc
            )
            field_results.append(
                f"Webhook credential refresh failed for {node.id}: {exc}"
            )

    async def _provision_trigger_webhooks(
        self,
        ops: List[XmlOp],
        new_node_ids: List[str],
        field_results: List[str],
    ) -> AsyncIterator[BuilderStreamEvent]:
        """Provision endpoints for newly executable trigger nodes."""

        if not self.platform_ops or not self.user_id or not self.workflow_id:
            return

        candidate_ids: List[str] = list(dict.fromkeys(new_node_ids))
        for op in ops:
            node_id = ""
            if op.tag == "field":
                node_id = op.attrs.get("node", "")
            elif op.tag == "set_credentials":
                node_id = op.attrs.get("node", "") or op.attrs.get("id", "")
            if node_id and node_id not in candidate_ids:
                candidate_ids.append(node_id)

        from utils.webhook_manager import WebhookManager

        candidate_ids = [
            node_id
            for node_id in candidate_ids
            if (node := self.graph_state.get_node(node_id))
            and WebhookManager.node_webhook_field_for(node.type, node.operation)
        ]
        if not candidate_ids:
            return

        from utils.database_pool import get_native_pool

        try:
            pool = get_native_pool()
        except RuntimeError:
            return

        for node_id in candidate_ids:
            node = self.graph_state.get_node(node_id)
            if not node:
                continue
            try:
                updates = await WebhookManager.provision_node_webhook(
                    pool,
                    user_id=self.user_id,
                    workflow_id=self.workflow_id,
                    node_id=node_id,
                    node_type=node.type,
                    operation=node.operation,
                    config=node.config,
                )
            except Exception as exc:
                logger.warning(
                    "Webhook provisioning failed for %s: %s", node_id, exc
                )
                field_results.append(
                    f"Webhook provisioning failed for {node_id}: {exc}"
                )
                continue
            if not updates:
                continue
            node.config.update(updates)
            url = updates.get("webhook_url") or node.config.get("webhook_url")
            line = f"Webhook provisioned for {node_id}"
            if url:
                line += f": {url}"
            provider_error = next(
                (
                    value
                    for key, value in updates.items()
                    if key.endswith("_error") and value
                ),
                None,
            )
            if provider_error:
                line += (
                    f" — provider registration incomplete: {provider_error}. "
                    "It completes automatically once credentials are attached."
                )
            field_results.append(line)
            yield BuilderStreamEvent(
                type="node_updated",
                data={
                    "nodeId": node_id,
                    "operation": node.operation,
                    "config": node.config,
                },
            )

    async def replay_checkpoint(
        self, ops_data: List[Dict[str, Any]], completed_node_ids: List[str]
    ) -> AsyncIterator[BuilderStreamEvent]:
        """Replay a saved public operation batch after an interrupted process."""

        ops = [
            XmlOp(tag=item.get("tag"), attrs=item.get("attrs") or {}, body=item.get("body"))
            for item in ops_data
            if item.get("tag") in AGENTIC_TAGS
        ]
        planned_node_ids = {
            str(op.attrs.get("name"))
            for op in ops
            if op.tag == "add_node" and op.attrs.get("name")
        }
        pending_node_ids = planned_node_ids - set(completed_node_ids)
        execution_summary = ""
        async for item in self._execute_operations(
            ops, draft_node_ids=pending_node_ids
        ):
            if not isinstance(item, str):
                yield item
            else:
                execution_summary = item
        if execution_summary:
            self.messages.append({
                "role": "user",
                "content": f"{EXEC_RESULT_MARKER}\n{execution_summary}",
            })
        self._last_turn_result = TurnResult(next_action="continue")

    def get_result(self) -> BuilderOutput:
        return BuilderOutput.model_validate({
            **self.graph_state.to_dict(), "generation_id": self.generation_id
        })

    def get_result_dict(self) -> Dict[str, Any]:
        return self.graph_state.to_dict()

    def last_turn_result(self) -> TurnResult:
        return self._last_turn_result

    @property
    def graph_changed(self) -> bool:
        return self._graph_fingerprint() != self._initial_graph_fingerprint

    @property
    def execution_effects(self) -> List[ExecutionEffects]:
        return list(self._execution_effects)

    def effect_summary(self) -> Dict[str, Any]:
        return {
            "observation_ops": sum(
                len(effect.observation_ops) for effect in self._execution_effects
            ),
            "material_ops_attempted": sum(
                len(effect.material_ops_attempted)
                for effect in self._execution_effects
            ),
            "graph_changed": self.graph_changed,
        }

    async def log_session_end(self, success: bool, terminal_reason: str = "") -> None:
        await self.session_log.log_session_end(
            success=success,
            terminal_reason=terminal_reason,
            total_cost=self._total_cost,
            total_tokens=self._total_tokens,
            node_count=len(self.graph_state.nodes),
            edge_count=len(self.graph_state.edges),
            turn_count=self._turn_count,
            effect_summary=self.effect_summary(),
        )

    def _graph_fingerprint(self) -> str:
        return json.dumps(
            self.graph_state.to_workflow_data(),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

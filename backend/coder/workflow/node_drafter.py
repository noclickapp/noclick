"""Draft each new node's operation and configuration with one model call.

The community implementation uses the open operation catalog and validators,
and exposes a small registration seam for operator-provided alternatives.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Protocol, Set

from .builder_events import BuilderStreamEvent

logger = logging.getLogger(__name__)


def _node_kind(node: Any) -> str:
    """Read the public node type from compatible graph adapters."""
    value = getattr(node, "type", None) or getattr(node, "node_type", None)
    if not value:
        raise ValueError("Node type is required for drafting")
    return str(value)

# Bounded so one pathological node can't stall a build.
_DRAFT_TIMEOUT_S = 120
_MAX_CONCURRENT_NODES = 4


class NodeDrafter(Protocol):
    """Structural interface implemented by every node drafter."""

    graph_state: Any
    user_prompt: str
    accumulated_cost: float
    accumulated_tokens: int

    def draft_nodes(self, node_ids: Set[str]) -> AsyncIterator[BuilderStreamEvent]:
        """Fill operation + config for each node id, streaming progress."""
        ...

    def autofill_node(
        self, node_id: str, mode: str = "full", target_field: Optional[str] = None,
    ) -> AsyncIterator[BuilderStreamEvent]:
        """Re-draft ONE node on demand (the canvas autofill button).

        Modes: 'full' (operation + fields), 'operation', 'fields',
        'single_field' (restricted to target_field)."""
        ...

    def autofill_prompt(
        self, node_id: str, mode: str, target_field: Optional[str],
    ) -> str:
        """Instructions for autofilling this one node, or "" to fall back to the
        node's own goal. Reads self.graph_state."""
        ...


_factory: Optional[Callable[..., NodeDrafter]] = None
_initialized = False


def register_node_drafter(factory: Callable[..., NodeDrafter]) -> None:
    global _factory
    _factory = factory


def create_node_drafter(**kwargs) -> NodeDrafter:
    _ensure_initialized()
    assert _factory is not None
    return _factory(**kwargs)


def _ensure_initialized() -> None:
    global _initialized
    if _initialized or _factory is not None:
        return
    _initialized = True
    register_node_drafter(SinglePassNodeDrafter)
    logger.info("[NodeDrafter] Using single-pass node drafter")


def clear() -> None:
    """Reset registration state (tests)."""
    global _factory, _initialized
    _factory = None
    _initialized = False


class SinglePassNodeDrafter:
    """One LLM call per node: choose the operation and fill the config.

    It uses the shared catalog and validators and improves as the configured
    model improves.
    """

    def __init__(
        self,
        config: Any = None,
        generation_id: Optional[str] = None,
        debug_callback: Optional[Callable] = None,
        **_ignored,
    ) -> None:
        self.config = config
        self.generation_id = generation_id
        self.debug_callback = debug_callback
        self.graph_state: Any = None
        self.session_log: Any = None
        self.user_prompt: str = ""
        self.host_theme: Any = None
        self.accumulated_cost: float = 0.0
        self.accumulated_tokens: int = 0
        self.accumulated_output_tokens: int = 0

    def get_total_cost(self) -> float:
        """Return model cost accumulated by this drafter."""
        return self.accumulated_cost

    def get_total_tokens(self) -> int:
        """Return tokens accumulated by this drafter."""
        return self.accumulated_tokens

    # ── prompt ───────────────────────────────────────────────────────────

    def _node_prompt(self, node: Any, operations: List[Dict[str, Any]]) -> str:
        catalog = "\n\n".join(
            (f"- {op['name']}: {op.get('description', '')}".strip()
             + f"\nConfiguration fields:\n{op.get('schema') or '(none)'}")
            for op in operations
        )
        imported = getattr(self.graph_state, "_n8n_context", {}) or {}
        source_context = [
            imported[reference]
            for reference in (getattr(node, "n8n_refs", None) or [])
            if reference in imported
        ]
        source_note = ""
        if source_context:
            source_note = (
                "Imported source-node context supplied by the user:\n"
                + json.dumps(source_context, default=str)
                + "\n\n"
            )
        return (
            "You are configuring one node in an automation workflow.\n\n"
            f"The user asked for: {self.user_prompt}\n\n"
            f"This node is a `{_node_kind(node)}` and its purpose in the workflow is: "
            f"{getattr(node, 'goal', '') or getattr(node, 'label', '') or 'unspecified'}\n\n"
            f"{source_note}"
            f"Available operations for this node type:\n{catalog}\n\n"
            "Choose the single operation that fits the node's purpose, then provide "
            "values for its configuration fields. Use the exact operation name from "
            "the list. For any field you cannot determine from the request, either "
            "omit it or use a reference to an upstream node's output in the form "
            "{{node_id.field}}.\n\n"
            "Respond with JSON only, no prose:\n"
            '{"operation": "<operation name>", "config": {"<field>": "<value>"}}'
        )

    async def _call_model(self, prompt: str, schema_hint: str) -> Dict[str, Any]:
        """Run one JSON completion and record its cost/token usage."""
        import litellm

        from .builder_config import BRAIN_FALLBACK_MODEL, BRAIN_PRIMARY_MODEL
        from .pass_base import build_provider_extra_body
        from .pass_base import build_provider_extra_body

        config = self.config
        model = getattr(config, "model", None) or BRAIN_PRIMARY_MODEL
        fallback_model = (
            getattr(config, "fallback_model", None) or BRAIN_FALLBACK_MODEL
        )
        temperature = float(getattr(config, "temperature", 0.2))
        timeout = max(1.0, float(getattr(config, "timeout", _DRAFT_TIMEOUT_S)))
        messages = [
            {"role": "system", "content": "You output only valid JSON objects."},
            {"role": "user", "content": f"{prompt}\n\n{schema_hint}"},
        ]
        candidates = [(
            model,
            getattr(config, "provider_order", None),
        )]
        if fallback_model and fallback_model != model:
            candidates.append((
                fallback_model,
                getattr(config, "fallback_provider_order", None),
            ))
        for candidate, provider_order in candidates:
            try:
                request = {
                    "model": candidate,
                    "messages": messages,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                }
                extra_body = build_provider_extra_body(
                    candidate,
                    provider_order=provider_order,
                    provider_sort=getattr(config, "provider_sort", None),
                )
                if extra_body:
                    request["extra_body"] = extra_body
                response = await asyncio.wait_for(
                    litellm.acompletion(**request), timeout=timeout
                )
                usage = getattr(response, "usage", None)
                if usage:
                    self.accumulated_tokens += getattr(usage, "total_tokens", 0) or 0
                    self.accumulated_output_tokens += getattr(usage, "completion_tokens", 0) or 0
                cost = getattr(response, "_hidden_params", {}) or {}
                self.accumulated_cost += float(cost.get("response_cost") or 0.0)
                content = response.choices[0].message.content or "{}"
                return json.loads(content)
            except Exception as e:
                logger.warning(f"[NodeDrafter] {candidate} failed: {e}")
        return {}

    # ── drafting ─────────────────────────────────────────────────────────

    async def draft_nodes(self, node_ids: Set[str]) -> AsyncIterator[BuilderStreamEvent]:
        """Draft independent nodes concurrently and stream public progress events."""
        queue: asyncio.Queue = asyncio.Queue()
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_NODES)

        async def draft_one(node_id: str) -> None:
            async with semaphore:
                try:
                    await self._draft_node(node_id, queue)
                except Exception as e:
                    logger.error(f"[NodeDrafter] node {node_id} failed: {e}", exc_info=True)
                finally:
                    await queue.put(None)

        tasks = [asyncio.create_task(draft_one(n)) for n in node_ids]
        remaining = len(tasks)
        try:
            while remaining:
                event = await queue.get()
                if event is None:
                    remaining -= 1
                    continue
                yield event
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

    async def _draft_node(
        self,
        node_id: str,
        queue: asyncio.Queue,
        mode: str = "full",
        target_field: Optional[str] = None,
    ) -> None:
        from .operation_catalog import (
            get_operation_schema,
            get_operations_for_node_type,
            validate_node_config,
        )
        from .workflow_schema import compact_schema, resolve_schema_refs

        node = self.graph_state.nodes.get(node_id) if self.graph_state else None
        if node is None:
            return

        await queue.put(BuilderStreamEvent(
            type="node_processing_start", data={"nodeId": node_id},
        ))

        operations = []
        for op in get_operations_for_node_type(_node_kind(node)):
            schema = resolve_schema_refs(
                get_operation_schema(_node_kind(node), op.name) or {}
            )
            properties = {
                key: value
                for key, value in (schema.get("properties") or {}).items()
                if key not in {"operation", "credentials"}
            }
            required = [
                key for key in (schema.get("required") or [])
                if key in properties
            ]
            operations.append({
                "name": op.name,
                "description": op.description,
                "schema": compact_schema(properties, required),
            })
        if not operations:
            # Nodes without an operation discriminator (sticky notes, canvas-only
            # types) need nothing drafted.
            await queue.put(BuilderStreamEvent(
                type="node_updated", data={"nodeId": node_id, "config": node.config or {}},
            ))
            return

        if mode in ("fields", "single_field") and node.operation:
            # Operation is already chosen; only fields are being (re)filled.
            hint = (
                f"Keep the operation `{node.operation}`. "
                + (f"Provide ONLY the field `{target_field}`. " if target_field else "")
                + "Return only the JSON object."
            )
            drafted = await self._call_model(self._node_prompt(node, operations), hint)
            drafted["operation"] = node.operation
        else:
            drafted = await self._call_model(
                self._node_prompt(node, operations),
                "Return only the JSON object.",
            )
        operation = drafted.get("operation") or ""
        valid_names = {op["name"] for op in operations}
        if operation not in valid_names:
            # A hallucinated operation is worse than none: leave the node
            # unconfigured and let the brain (or the user) resolve it.
            logger.warning(
                f"[NodeDrafter] {node_id}: model chose unknown operation {operation!r}"
            )
            await queue.put(BuilderStreamEvent(
                type="node_updated", data={"nodeId": node_id, "config": node.config or {}},
            ))
            return

        node.operation = operation
        await queue.put(BuilderStreamEvent(
            type="node_operation_selected",
            data={"nodeId": node_id, "operation": operation},
        ))

        config = drafted.get("config")
        if mode == "operation":
            config = None
        elif mode == "single_field" and isinstance(config, dict) and target_field:
            config = {k: v for k, v in config.items() if k == target_field}
        if isinstance(config, dict):
            merged = {**(node.config or {}), **config, "operation": operation}
            # Use the same validator as the canvas — an invalid
            # draft is dropped rather than written onto the node.
            error = validate_node_config(_node_kind(node), operation, merged)
            if error:
                logger.info(f"[NodeDrafter] {node_id}: config rejected ({error[:160]})")
            else:
                node.config = merged

        await queue.put(BuilderStreamEvent(
            type="node_updated",
            data={"nodeId": node_id, "operation": operation, "config": node.config or {}},
        ))

    def autofill_prompt(
        self, node_id: str, mode: str, target_field: Optional[str],
    ) -> str:
        return ""

    async def autofill_node(
        self,
        node_id: str,
        mode: str = "full",
        target_field: Optional[str] = None,
    ) -> AsyncIterator[BuilderStreamEvent]:
        """Single-node autofill — same event stream and modes as the main builder, so the canvas edit handler consumes it unchanged."""
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(
            self._draft_node(node_id, queue, mode=mode, target_field=target_field)
        )
        try:
            while True:
                if task.done() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if event is not None:
                    yield event
        finally:
            if not task.done():
                task.cancel()
            else:
                exc = task.exception()
                if exc:
                    logger.error(f"[NodeDrafter] autofill {node_id} failed: {exc}")

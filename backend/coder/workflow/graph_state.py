"""Mutable graph state shared by the community builder and public DSL."""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List, Set, Tuple

from nodes.core.registry import validate_edge

logger = logging.getLogger(__name__)










@dataclass
class NodeState:
    """Complete public state for one workflow node."""
    # Core identity (from builder)
    id: str
    type: str
    label: str
    goal: str
    description: str = ""

    # Graph position
    level: int = 0
    index: int = 0
    parent_ids: List[str] = field(default_factory=list)

    # Executable operation
    operation: Optional[str] = None
    operation_reason: Optional[str] = None

    # Operation configuration
    config: Dict[str, Any] = field(default_factory=dict)
    user_fields: List[str] = field(default_factory=list)

    # UI state
    status: str = "pending"  # For frontend display
    content: str = ""  # Display content

    # Execution error from last run (if any), used to give node drafter context for fixes
    execution_error: Optional[str] = None

    # Whether this node has execution output available (for brain context)
    has_output: bool = False

    # Canvas position and dimensions (preserved from current_graph for sticky note position resolution)
    position: Optional[Dict[str, float]] = None
    width: Optional[int] = None
    height: Optional[int] = None

    # n8n import: IDs of n8n nodes this node was translated from. Paired with
    # GraphState._n8n_context to give node drafter the full source-node JSON without
    # inflating the brain prompt. Empty outside an n8n import session.
    n8n_refs: List[str] = field(default_factory=list)

    # Queryable-enum resolutions emitted this turn. Populated by
    # execute_field_ops and node drafting when a field with x-queryable-enum is
    # written; consumed by build_node_summary to surface alternatives, then
    # cleared. Per-turn transient state — not serialized.
    pending_resolutions: List[Any] = field(default_factory=list)

    def to_execution_config(self) -> Dict[str, Any]:
        """Build a config dict suitable for workflow execution.

        Merges ``self.config`` with ``label`` and ``operation`` so the
        execution handler has everything it needs in a single dict.

        ``operation`` is only written when ``self.operation`` is set — so a
        loader that left ``operation`` inside ``self.config`` (e.g. a
        resume path that hydrated from the FE's flat saved blob) doesn't
        get its real value silently overwritten with ``None`` here.
        """
        merged: Dict[str, Any] = {**(self.config or {}), "label": self.label}
        if self.operation is not None:
            merged["operation"] = self.operation
        return merged

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'id': self.id,
            'type': self.type,
            'label': self.label,
            'goal': self.goal,
            'description': self.description,
            'level': self.level,
            'index': self.index,
            'parentIds': self.parent_ids,
            'operation': self.operation,
            'operationReason': self.operation_reason,
            'config': self.config,
            'userFields': self.user_fields,
            'status': self.status,
            'content': self.content,
        }
        if self.position:
            result['position'] = self.position
        if self.width is not None:
            result['width'] = self.width
        if self.height is not None:
            result['height'] = self.height
        return result


@dataclass
class EdgeState:
    """State for a graph edge."""
    id: str
    source_id: str
    target_id: str
    status: str = "pending"
    source_handle: Optional[str] = None  # For multi-output nodes (e.g., iteration: 'loop' or 'done')
    target_handle: Optional[str] = None  # 'bottom' marks tool-provider edges into an agent

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'id': self.id,
            'sourceId': self.source_id,
            'targetId': self.target_id,
            'status': self.status,
        }
        if self.source_handle:
            result['sourceHandle'] = self.source_handle
        if self.target_handle:
            result['targetHandle'] = self.target_handle
        return result


@dataclass
class InputRequest:
    """Request for user input (credentials, config fields, selections, etc.)."""
    id: str
    node_id: str
    input_type: str  # "credential", "text", "selection", "config"
    label: str
    description: str = ""
    credential_type: Optional[str] = None  # For credential inputs
    required: bool = True
    # Config field properties (for dynamic options fields)
    node_type: Optional[str] = None  # Node type for loading options
    field_key: Optional[str] = None  # Field name in config schema
    field_schema: Optional[Dict[str, Any]] = None  # JSON schema for the field
    depends_on: Optional[str] = None  # Field this depends on (e.g., sheet_name depends on spreadsheet_id)
    accepted_credential_types: Optional[List[str]] = None  # Credential types that can load options for this field
    node_config: Optional[Dict[str, Any]] = None  # Node config snapshot for config-sensitive credential forms (agent)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'id': self.id,
            'nodeId': self.node_id,
            'type': self.input_type,
            'label': self.label,
            'description': self.description,
            'credentialType': self.credential_type,
            'required': self.required,
        }
        # Add config field properties if present
        if self.node_type:
            result['nodeType'] = self.node_type
        if self.field_key:
            result['fieldKey'] = self.field_key
        if self.field_schema:
            result['fieldSchema'] = self.field_schema
        if self.depends_on:
            result['dependsOn'] = self.depends_on
        if self.accepted_credential_types:
            result['acceptedCredentialTypes'] = self.accepted_credential_types
        if self.node_config is not None:
            result['nodeConfig'] = self.node_config
        return result


class GraphState:
    """Mutable nodes, edges, inputs, and workflow metadata."""

    def __init__(self):
        # Core state
        self.nodes: Dict[str, NodeState] = {}
        self.edges: Dict[str, EdgeState] = {}  # edge_id -> EdgeState
        self.edge_set: Set[Tuple[str, str]] = set()  # (from, to) for quick lookup
        self.inputs: List[InputRequest] = []

        # Level tracking for layout
        self.node_count_at_level: Dict[int, int] = {}

        # Error tracking
        self.errors: List[str] = []

        # Summary and workflow name (from builder done tag)
        self.summary: str = ""
        self.workflow_name: str = ""

        # n8n import context: raw n8n node dicts keyed by n8n node id.
        # Populated by AgenticBuilder.edit() when an n8n workflow is attached.
        # Resolved against NodeState.n8n_refs by node drafter to enrich their prompts.
        self._n8n_context: Dict[str, Dict[str, Any]] = {}

        # Provider-session health for attached credentials, keyed by credential
        # id (utils.credential_health.CredentialHealth). Populated out-of-band
        # by async callers (AgenticBuilder.edit, describe_workflow) before
        # to_xml so the sync renderers can flag attached-but-dead credentials —
        # an attached-but-dead provider session must render as unhealthy to both
        # AI surfaces. Absent id =
        # unknown = healthy.
        self._credential_health: Dict[str, Any] = {}

        # Workflow variables (settings.variable_definitions) — settings-level,
        # not part of the graph blob, so populated out-of-band like
        # _credential_health: the handler loads them before the first snapshot,
        # and the define_variable executor keeps this mirror current so later
        # snapshots in the same conversation see the brain's own declarations.
        self.variable_definitions: List[Dict[str, Any]] = []

    # =========================================================================
    # Node Management
    # =========================================================================

    def add_node(
        self,
        name: str,
        node_type: str,
        label: str,
        goal: str = "",
        description: str = "",
        n8n_refs: Optional[List[str]] = None,
    ) -> Optional[NodeState]:
        """
        Add a node to the graph. Returns NodeState or None if duplicate
        OR if `name` is missing/empty.

        The brain emits `<add_node name="..."/>`; if the attribute is
        missing the XML parser yields `name=None`, and stamping that
        into NodeState.id produces a node that wire-serializes without
        an `id` key (the response sender uses `exclude_none=True`),
        which crashes FE filters that key on `n.id`. Refusing the add
        here keeps the malformed node from ever shipping.
        """
        if not name or not isinstance(name, str):
            logger.warning(
                "[GraphState] add_node refused: name is missing or not a string "
                "(got %r, type=%s)", name, node_type,
            )
            return None
        if name in self.nodes:
            return None  # Idempotent

        # Calculate level (triggers at 0, others at 1 initially)
        is_trigger = node_type.startswith('trigger-')
        level = 0 if is_trigger else 1

        # Calculate index at this level
        index = self.node_count_at_level.get(level, 0)
        self.node_count_at_level[level] = index + 1

        node = NodeState(
            id=name,
            type=node_type,
            label=label,
            goal=goal,
            description=description,
            level=level,
            index=index,
            status='adding',
            content=label,
            n8n_refs=list(n8n_refs) if n8n_refs else [],
        )
        self.nodes[name] = node

        return node

    def get_node(self, node_id: str) -> Optional[NodeState]:
        """Get a node by ID."""
        return self.nodes.get(node_id)



    def mark_node_status(self, node_id: str, status: str) -> None:
        """Update a node's UI status."""
        node = self.nodes.get(node_id)
        if node:
            node.status = status

    def attached_credential_ids(self) -> List[str]:
        """Health-checkable credential ids referenced by any node — the input
        for the out-of-band ``_credential_health`` pre-fetch. Pre-filtered to
        health-checked types so graphs without connection-backed credentials
        cost their callers zero I/O."""
        from utils.credential_health import health_relevant_credential_ids

        ids: List[str] = []
        for node in self.nodes.values():
            ids.extend(health_relevant_credential_ids(node.config))
        return list(dict.fromkeys(ids))

    def is_tool_provider(self, node_id: str) -> bool:
        """Whether this node is wired into an agent's (or a hosting-mode MCP
        node's) bottom handle as a tool provider. Mirrors
        nodes/agent/node_op_tools.is_node_op_provider — targetHandle 'bottom'
        into a consumer node is the defining attribute."""
        from .workflow_ops import PROVIDER_TARGET_HANDLE

        for edge in self.edges.values():
            if edge.source_id == node_id and edge.target_handle == PROVIDER_TARGET_HANDLE:
                target = self.nodes.get(edge.target_id)
                if target and target.type in ('agent', 'mcp-server'):
                    return True
        return False

    def has_wired_providers(self, node_id: str) -> bool:
        """Whether tool providers are wired INTO this node's bottom handle —
        i.e. an mcp-server node in HOSTING mode. Such a node needs no node drafting
        config (server_url must stay empty; the bundle IS its config)."""
        from .workflow_ops import PROVIDER_TARGET_HANDLE

        return any(
            e.target_id == node_id and e.target_handle == PROVIDER_TARGET_HANDLE
            for e in self.edges.values()
        )


    # =========================================================================
    # Edge Management
    # =========================================================================

    def add_edge(
        self,
        from_name: str,
        to_name: str,
        source_handle: Optional[str] = None,
        target_handle: Optional[str] = None,
    ) -> Optional[EdgeState]:
        """
        Add an edge to the graph. Returns EdgeState or None if invalid/duplicate.

        Args:
            from_name: Source node name
            to_name: Target node name
            source_handle: Optional handle for multi-output nodes (e.g., 'loop', 'done' for iteration)
            target_handle: Optional target handle ('bottom' for tool-provider edges into an agent)
        """
        edge_key = (from_name, to_name)
        if edge_key in self.edge_set:
            return None  # Idempotent

        # Validate nodes exist
        if from_name not in self.nodes:
            self.errors.append(f"Edge error: source node '{from_name}' doesn't exist")
            return None
        if to_name not in self.nodes:
            self.errors.append(f"Edge error: target node '{to_name}' doesn't exist")
            return None

        # Reject edges involving connectionless (SDK-based) node types
        edge_err = validate_edge(self.nodes[from_name].type, self.nodes[to_name].type)
        if edge_err:
            self.errors.append(f"Edge error ({from_name} → {to_name}): {edge_err}")
            return None

        self.edge_set.add(edge_key)

        # Update target node's parent IDs and level
        target_node = self.nodes[to_name]
        if from_name not in target_node.parent_ids:
            target_node.parent_ids.append(from_name)

        # Update level based on source
        source_level = self.nodes[from_name].level
        new_level = source_level + 1
        if target_node.level < new_level:
            target_node.level = new_level

        edge_id = f"e_{from_name}_{to_name}"
        edge = EdgeState(
            id=edge_id,
            source_id=from_name,
            target_id=to_name,
            status='animating',
            source_handle=source_handle,
            target_handle=target_handle,
        )
        self.edges[edge_id] = edge

        return edge

    def remove_edge(self, from_name: str, to_name: str) -> bool:
        """
        Remove an edge from the graph. Returns True if removed.
        Called during mutation reconciliation in node drafter.
        """
        edge_key = (from_name, to_name)
        if edge_key not in self.edge_set:
            return False

        self.edge_set.remove(edge_key)

        # Update target node's parent IDs
        target_node = self.nodes.get(to_name)
        if target_node and from_name in target_node.parent_ids:
            target_node.parent_ids.remove(from_name)

        # Remove edge state
        edge_id = f"e_{from_name}_{to_name}"
        if edge_id in self.edges:
            del self.edges[edge_id]

        return True

    def remove_node(self, node_name: str) -> bool:
        """
        Remove a node and all its connected edges from the graph.
        Returns True if the node was removed, False if it didn't exist.
        """
        if node_name not in self.nodes:
            return False

        # Remove all edges connected to this node (both incoming and outgoing)
        edges_to_remove = [
            (from_node, to_node)
            for from_node, to_node in list(self.edge_set)
            if from_node == node_name or to_node == node_name
        ]
        for from_node, to_node in edges_to_remove:
            self.remove_edge(from_node, to_node)

        # Remove any inputs associated with this node
        self.inputs = [inp for inp in self.inputs if inp.node_id != node_name]

        # Remove the node itself
        del self.nodes[node_name]

        return True

    def get_upstream_nodes(self, node_id: str) -> List[NodeState]:
        """Get all direct upstream (parent) nodes for a given node."""
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.nodes[pid] for pid in node.parent_ids if pid in self.nodes]

    def get_downstream_nodes(self, node_id: str) -> List[NodeState]:
        """Get all direct downstream (child) nodes for a given node."""
        children = []
        for edge_key in self.edge_set:
            if edge_key[0] == node_id:
                child = self.nodes.get(edge_key[1])
                if child:
                    children.append(child)
        return children

    # =========================================================================
    # Input Management
    # =========================================================================

    def add_input(
        self,
        node_name: str,
        input_type: str,
        label: str,
        service: str = "",
        description: str = "",
    ) -> Optional[InputRequest]:
        """Add an input request for user-provided values."""
        if node_name not in self.nodes:
            self.errors.append(f"Input error: node '{node_name}' doesn't exist")
            return None

        input_req = InputRequest(
            id=f"inp_{node_name}_{len(self.inputs)}",
            node_id=node_name,
            input_type=input_type,
            label=label,
            description=description,
            credential_type=service if input_type == 'credential' else None,
        )
        self.inputs.append(input_req)
        return input_req

    # =========================================================================
    # Serialization
    # =========================================================================

    def get_nodes_list(self) -> List[Dict[str, Any]]:
        """Get all nodes as a list of dicts."""
        return [node.to_dict() for node in self.nodes.values()]

    def get_edges_list(self) -> List[Dict[str, Any]]:
        """Get all edges as a list of dicts."""
        return [edge.to_dict() for edge in self.edges.values()]

    def get_inputs_list(self) -> List[Dict[str, Any]]:
        """Get all input requests as a list of dicts."""
        return [inp.to_dict() for inp in self.inputs]

    def to_dict(self) -> Dict[str, Any]:
        """Get complete state as a dictionary."""
        return {
            'nodes': self.get_nodes_list(),
            'edges': self.get_edges_list(),
            'inputs': self.get_inputs_list(),
            'name': self.workflow_name,
            'summary': self.summary,
            'errors': self.errors if self.errors else None,
        }

    def to_workflow_data(self) -> Dict[str, Any]:
        """Serialize to the persisted workflow-blob shape (``public.workflows.workflow``).

        This is the SAME shape the frontend's ``buildSaveConfig`` /
        headless-builder ``_saveWorkflow`` produce, so every reader — the
        canvas, the execution engine, and ``from_dict`` on resume-after-ask —
        consumes it identically: node metadata (label/goal/operation) is
        flattened into ``config`` and edges are keyed on ``source``/``target``.
        Note the shape difference from ``to_dict()``, which emits the *brain*
        snapshot (top-level metadata, ``sourceId``/``targetId``) for prompts.

        Having this on GraphState lets the builder persist its OWN mutations at
        each turn boundary instead of delegating persistence to the FE — the FE
        never saves on an ``<ask/>`` pause, so a headless run that paused for
        input used to leave ``public.workflows`` at its pre-edit state and the
        resumed run rehydrated an empty graph ("node not found"). Positions are
        already stamped server-side by the incremental autolayout in
        ``builder.edit()`` before this is called.
        """
        nodes: List[Dict[str, Any]] = []
        for node in self.nodes.values():
            config: Dict[str, Any] = {'label': node.label, 'goal': node.goal}
            if node.operation is not None:
                config['operation'] = node.operation
            # from_dict POPS these out of the config blob onto NodeState, so
            # they must be written back or this whole-blob persist silently
            # REVERTS them on every turn boundary — the FE's next save
            # re-adds them, producing an endless ∅→value persistence loop.
            if node.operation_reason:
                config['operationReason'] = node.operation_reason
            if node.content:
                config['content'] = node.content
            if node.user_fields:
                config['userFields'] = node.user_fields
            # Real config (schema fields + credentialIds) wins over the metadata
            # defaults above — mirrors the FE spreading `...n.config` last.
            config.update(node.config or {})
            node_blob: Dict[str, Any] = {
                'id': node.id,
                'type': node.type,
                'position': node.position or {'x': 0, 'y': 0},
                'config': config,
            }
            if node.width is not None:
                node_blob['width'] = node.width
            if node.height is not None:
                node_blob['height'] = node.height
            nodes.append(node_blob)

        edges: List[Dict[str, Any]] = []
        for edge in self.edges.values():
            edge_blob: Dict[str, Any] = {
                'id': edge.id,
                'source': edge.source_id,
                'target': edge.target_id,
            }
            if edge.source_handle:
                edge_blob['sourceHandle'] = edge.source_handle
            if edge.target_handle:
                edge_blob['targetHandle'] = edge.target_handle
            edges.append(edge_blob)

        return {'nodes': nodes, 'edges': edges}

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_topological_order(self) -> List[str]:
        """
        Get nodes in topological order (parents before children).
        Useful for sequential processing when needed.
        """
        # Kahn's algorithm
        in_degree = {node_id: 0 for node_id in self.nodes}
        for _, target in self.edge_set:
            in_degree[target] += 1

        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_id)

            for edge_from, edge_to in self.edge_set:
                if edge_from == node_id:
                    in_degree[edge_to] -= 1
                    if in_degree[edge_to] == 0:
                        queue.append(edge_to)

        return result

    def get_nodes_by_level(self) -> Dict[int, List[str]]:
        """Group node IDs by their level."""
        by_level: Dict[int, List[str]] = {}
        for node_id, node in self.nodes.items():
            level = node.level
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(node_id)
        return by_level

    def __len__(self) -> int:
        """Return the number of nodes."""
        return len(self.nodes)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GraphState':
        """
        Create a GraphState from a dictionary (e.g., from current_graph in edit request).

        Args:
            data: Dictionary containing 'nodes', 'edges', optionally 'inputs' and 'summary'

        Returns:
            A new GraphState populated with the provided data
        """
        state = cls()

        # Load nodes
        for node_data in data.get('nodes', []):
            node_id = node_data.get('id')
            if not node_id:
                continue

            # The FE's `buildSaveConfig` (applyNodeUpdate.ts) flattens all
            # top-level node metadata — operation, label, goal, userFields,
            # operationReason, content — into the `config` blob on save. The
            # canvas-driven edit path re-elevates these to the top level
            # before sending, but the resume-after-ask path in
            # workflow_builder_handler hands public.workflows.workflow
            # straight to this loader unmodified. Mirror the FE's
            # `rawConfigToPayload` re-elevation here so NodeState.operation /
            # .label / etc. populate from either shape. We *pop* from the
            # config blob so these fields don't double-render in the brain
            # snapshot (once as the <node> attribute, once as a config child).
            config_blob = dict(node_data.get('config') or {})

            def _take(key: str, default: Any = None) -> Any:
                # Always pop the config copy so the metadata field doesn't
                # double-render in the brain snapshot (once as the <node>
                # attribute, once as a config child). Top-level wins when
                # both shapes carry a value.
                from_config = config_blob.pop(key, default)
                top = node_data.get(key)
                if top is not None and top != '':
                    return top
                return from_config

            operation = _take('operation')
            operation_reason = _take('operationReason')
            label = _take('label', '')
            goal = _take('goal', '')
            user_fields = _take('userFields', []) or []
            content = _take('content') or label or ''

            node = NodeState(
                id=node_id,
                type=node_data.get('type', ''),
                label=label,
                goal=goal,
                description=node_data.get('description', ''),
                level=node_data.get('level', 0),
                index=node_data.get('index', 0),
                parent_ids=node_data.get('parentIds', []),
                operation=operation,
                operation_reason=operation_reason,
                config=config_blob,
                user_fields=user_fields,
                status=node_data.get('status', 'complete'),
                content=content,
                execution_error=node_data.get('error'),
                position=node_data.get('position'),
                width=node_data.get('width'),
                height=node_data.get('height'),
            )
            state.nodes[node_id] = node

        # Load edges. Accept BOTH the graph_state shape (sourceId/targetId, from
        # to_dict round-trips) AND the FE/ReactFlow saved-workflow shape
        # (source/target). The builder hydrates from the saved blob, which uses
        # source/target — reading only sourceId/targetId silently dropped EVERY
        # existing edge, so editing a workflow started with zero edges: the brain
        # was blind to existing connections and provider_dataflow_conflict had
        # nothing to check (a node could be wired as both tool provider and
        # dataflow with no feedback). targetHandle ('bottom') carries the
        # tool-provider marker, so it must survive the load for the conflict
        # check to work.
        for edge_data in data.get('edges', []):
            source_id = edge_data.get('sourceId') or edge_data.get('source')
            target_id = edge_data.get('targetId') or edge_data.get('target')
            if source_id and target_id:
                edge_key = (source_id, target_id)
                if edge_key not in state.edge_set:
                    state.edge_set.add(edge_key)
                    edge_id = edge_data.get('id', f"e_{source_id}_{target_id}")
                    state.edges[edge_id] = EdgeState(
                        id=edge_id,
                        source_id=source_id,
                        target_id=target_id,
                        status='complete',
                        source_handle=edge_data.get('sourceHandle'),  # For multi-output nodes
                        target_handle=edge_data.get('targetHandle'),  # Tool-provider edges
                    )

        # Load inputs if present
        for input_data in data.get('inputs', []):
            state.inputs.append(InputRequest(
                id=input_data.get('id', ''),
                node_id=input_data.get('nodeId', ''),
                input_type=input_data.get('type', ''),
                label=input_data.get('label', ''),
                description=input_data.get('description', ''),
                credential_type=input_data.get('credentialType'),
                required=input_data.get('required', True),
                node_type=input_data.get('nodeType'),
                field_key=input_data.get('fieldKey'),
                field_schema=input_data.get('fieldSchema'),
                depends_on=input_data.get('dependsOn'),
            ))

        # Load summary
        state.summary = data.get('summary', '')

        return state

    @staticmethod
    def _get_valid_config_keys(node_type: str, operation: Optional[str] = None) -> Optional[Set[str]]:
        """Return valid config field names from schema, or None if unavailable."""
        # Lazy: operation_catalog pulls the full NODE_REGISTRY at import time
        from .operation_catalog import get_operation_config_class
        config_cls = get_operation_config_class(node_type, operation or 'default')
        if not config_cls:
            return None
        try:
            from pydantic import TypeAdapter
            return set(TypeAdapter(config_cls).json_schema().get('properties', {}).keys())
        except Exception:
            return None

    def to_xml(self) -> str:
        """
        Convert current graph state to a compact XML snapshot for brain context.

        Uses <node> (not <add_node>) to distinguish existing state from commands.
        Inlines operation and config directly on the node to avoid a separate
        "Node details" section and save context tokens.
        """
        lines = ['<workflow>']

        # Lazy: operation_catalog pulls the full NODE_REGISTRY at import time
        from .operation_catalog import (
            credential_status_line,
            missing_required_fields,
            trigger_status_line,
        )

        sorted_nodes = sorted(self.nodes.values(), key=lambda n: (n.level, n.index))
        for node in sorted_nodes:
            if node.type == 'stickyNote':
                continue

            attrs = f'type="{node.type}" name="{node.id}" label="{node.label}"'
            if node.operation and node.operation != 'default':
                attrs += f' operation="{node.operation}"'
            if node.has_output:
                attrs += ' has_output="true"'

            # Build compact config (skip empty/None, clip long values)
            # Filter to only schema-valid fields to exclude metadata like credentialIds
            valid_keys = self._get_valid_config_keys(node.type, node.operation)
            config_parts = []
            if node.config:
                for k, v in node.config.items():
                    if v is None or v == '':
                        continue
                    # agent_tool_operations / agent_env_requested are canvas-level
                    # (no schema entry) but the brain must see them to edit the
                    # allowlist / re-declare the env-var need.
                    if valid_keys is not None and k not in valid_keys and k not in (
                        'agent_tool_operations', 'agent_env_requested'
                    ):
                        continue
                    # Skip meta fields that duplicate attributes
                    if k in ('operation', 'action', 'content') and str(v) in (node.operation or '', node.label or ''):
                        continue
                    # Registration mirrors render as one purposeful
                    # [trigger: ...] line below, not raw fields.
                    if k in ('subscription_status', 'trigger_registered', 'trigger_error'):
                        continue
                    val_str = str(v)
                    if len(val_str) > 80:
                        config_parts.append(f'    {k}="{val_str[:60]}..." ({len(val_str)} chars)')
                    else:
                        config_parts.append(f'    {k}="{val_str}"')

            if node.user_fields:
                config_parts.append(f'    [needs user input: {", ".join(node.user_fields)}]')

            # Provider-wired nodes never execute their operation — required
            # fields don't apply to them.
            if not self.is_tool_provider(node.id):
                missing = missing_required_fields(node.type, node.operation, node.config, node.user_fields)
                if missing:
                    config_parts.append(f'    [missing required: {", ".join(missing)}]')

            cred_status = credential_status_line(
                node.type, node.operation, node.config, node.id,
                health=self._credential_health,
            )
            if cred_status:
                config_parts.append(f'    {cred_status}')

            trig_status = trigger_status_line(node.type, node.operation, node.config)
            if trig_status:
                config_parts.append(f'    {trig_status}')

            if config_parts:
                lines.append(f'  <node {attrs}>')
                lines.extend(config_parts)
                lines.append(f'  </node>')
            else:
                lines.append(f'  <node {attrs}/>')

        # Edges
        from .workflow_ops import PROVIDER_TARGET_HANDLE

        for source_id, target_id in sorted(self.edge_set):
            edge_id = f"e_{source_id}_{target_id}"
            edge = self.edges.get(edge_id)
            if edge and edge.target_handle == PROVIDER_TARGET_HANDLE:
                # Provider edges round-trip in the same form add_edge accepts.
                lines.append(f'  <edge from="{source_id}" to="{target_id}" type="tools"/>')
            elif edge and edge.source_handle:
                lines.append(f'  <edge from="{source_id}" to="{target_id}" handle="{edge.source_handle}"/>')
            else:
                lines.append(f'  <edge from="{source_id}" to="{target_id}"/>')

        # Workflow variables — configs reference them as {{vars.name}}; the
        # brain must see what exists to bind fields and avoid redefining.
        for d in self.variable_definitions:
            if not isinstance(d, dict) or not str(d.get('name') or '').strip():
                continue
            v_attrs = f'name="{d["name"]}"'
            value = d.get('value')
            if value not in (None, ''):
                val_str = str(value)
                v_attrs += f' value="{val_str[:60]}"' + (' (clipped)' if len(val_str) > 60 else '')
            else:
                v_attrs += ' value="" [unset — Setup asks for it]'
            if d.get('per_user'):
                v_attrs += ' per_user="true"'
            if d.get('description'):
                v_attrs += f' description="{str(d["description"])[:100]}"'
            lines.append(f'  <variable {v_attrs}/>')

        lines.append('</workflow>')
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Node-level operation dispatch
    # ------------------------------------------------------------------

    def apply_node_op(self, node_id: str, op) -> Optional[str]:
        """Apply a node-level XML operation to a node's config.

        Bridges the shared ``execute_node_op`` dispatcher to GraphState.
        Graph-level ops (add_node, add_edge, etc.) are handled by their
        respective builder phases, not here.

        Args:
            node_id: The target node ID.
            op: An ``XmlOp`` from the shared XML parser.

        Returns:
            Error string on failure, or ``None`` on success.
        """
        from .workflow_ops import execute_node_op, is_node_op

        node = self.nodes.get(node_id)
        if not node:
            return f"Node {node_id!r} not found in graph state"
        if not is_node_op(op.tag):
            return f"Operation {op.tag!r} is not a node-level op"
        return execute_node_op(op, node.config)

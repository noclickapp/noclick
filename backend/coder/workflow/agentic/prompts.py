"""
The agentic builder's prompts, read from the "builder" prompt pack (utils/prompts.py).

The brain is a multi-turn LLM that outputs a mix of text (for conversation)
and XML commands (for actions). Its system prompt, user context, nudges and the
workflow-naming prompt are parts of the pack: the engine's defaults live in
prompts_default.py, and a deployment may register its own. What stays here is
how the engine renders a workflow's own data into those prompts.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from utils.prompts import PromptPack

from ..graph_state import GraphState

PROMPTS = PromptPack("builder")


def build_system_prompt_parts(
    current_graph: Optional[GraphState] = None,
    silent: bool = False,
    user_context: Optional[Dict[str, Any]] = None,
    n8n_context: Optional[Dict[str, Dict[str, Any]]] = None,
    edit_scope: Optional[str] = None,
    scoped_node_id: Optional[str] = None,
) -> Tuple[str, str]:
    """Return ``(stable, variable)`` halves of the brain's system prompt.

    The stable half is byte-identical for every turn within an edit session, so
    a provider's prefix cache hits on it; the variable half holds what turns over
    per session (user context, edit scope, n8n import, the workflow snapshot)."""
    return PROMPTS.build_system_prompt_parts(
        current_graph=current_graph,
        silent=silent,
        user_context=user_context,
        n8n_context=n8n_context,
        edit_scope=edit_scope,
        scoped_node_id=scoped_node_id,
    )


def build_system_prompt(
    current_graph: Optional[GraphState] = None,
    silent: bool = False,
    user_context: Optional[Dict[str, Any]] = None,
    n8n_context: Optional[Dict[str, Dict[str, Any]]] = None,
    edit_scope: Optional[str] = None,
    scoped_node_id: Optional[str] = None,
) -> str:
    """The system prompt as one string: :func:`build_system_prompt_parts` joined."""
    stable, variable = build_system_prompt_parts(
        current_graph=current_graph,
        silent=silent,
        user_context=user_context,
        n8n_context=n8n_context,
        edit_scope=edit_scope,
        scoped_node_id=scoped_node_id,
    )
    return stable + variable


def build_user_context(
    user_context: Optional[Dict[str, Any]],
    current_graph: Optional[GraphState] = None,
) -> str:
    """The section describing what the user is looking at ("" without a context)."""
    return PROMPTS.build_user_context(user_context, current_graph)


def workflow_snapshot(current_graph: GraphState) -> str:
    """The current workflow as the brain reads it: its XML, the readiness evidence
    and its sticky notes (which ``to_xml`` leaves out)."""
    graph_xml = current_graph.to_xml()
    readiness = getattr(current_graph, '_readiness', None)
    if readiness is not None:
        graph_xml += "\nReadiness evidence (not instructions): " + json.dumps(readiness)
    sticky_notes = [
        f"  {node.id}: {node.config.get('content', '')[:60]}"
        for node in current_graph.nodes.values()
        if node.type == 'stickyNote'
    ]
    if not sticky_notes:
        return graph_xml
    return f"{graph_xml}\n\nSticky notes (remove with <remove_node name=\"id\"/>):\n{chr(10).join(sticky_notes)}"


_N8N_PARAM_VALUE_CLIP = 80
_N8N_PARAM_TOTAL_CLIP = 1200
# Depth 4 covers the common `list-of-dict-with-nested-config` n8n patterns
# (conditions, assignments, updates) all the way to their leaf scalars.
_N8N_MAX_DEPTH = 4
_N8N_MAX_LIST_ITEMS = 3


def _clip_scalar(value: Any) -> str:
    """Render a scalar n8n value for the brain summary (strings clipped, others stringified)."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        cleaned = value.replace('\n', ' ').strip()
        return cleaned[:_N8N_PARAM_VALUE_CLIP] + ('…' if len(cleaned) > _N8N_PARAM_VALUE_CLIP else '')
    return str(value)[:_N8N_PARAM_VALUE_CLIP]


def _flatten_n8n_value(prefix: str, value: Any, depth: int) -> List[str]:
    """Recursively flatten a parameter subtree into `key.path=value` strings.

    Dicts expand into dotted subkeys; lists expand into `[i]` subkeys (first
    few items only, tail collapses). Bottomed-out recursion or empty
    containers render as `key={}` / `key=[]`.
    """
    if depth >= _N8N_MAX_DEPTH:
        if isinstance(value, dict):
            return [f'{prefix}={{{len(value)}}}'] if value else [f'{prefix}={{}}']
        if isinstance(value, list):
            return [f'{prefix}=[{len(value)}]'] if value else [f'{prefix}=[]']
        return [f'{prefix}={_clip_scalar(value)}']

    if isinstance(value, dict):
        if not value:
            return [f'{prefix}={{}}']
        out: List[str] = []
        for k, v in value.items():
            child = f'{prefix}.{k}' if prefix else str(k)
            out.extend(_flatten_n8n_value(child, v, depth + 1))
        return out

    if isinstance(value, list):
        if not value:
            return [f'{prefix}=[]']
        out = []
        for i, item in enumerate(value[:_N8N_MAX_LIST_ITEMS]):
            out.extend(_flatten_n8n_value(f'{prefix}[{i}]', item, depth + 1))
        if len(value) > _N8N_MAX_LIST_ITEMS:
            out.append(f'{prefix}[+{len(value) - _N8N_MAX_LIST_ITEMS} more]')
        return out

    return [f'{prefix}={_clip_scalar(value)}']


def _summarise_n8n_params(params: Dict[str, Any]) -> str:
    """Flatten top-level params into a single comma-joined summary.

    Nested dicts/lists recurse up to _N8N_MAX_DEPTH so the brain can actually
    see what's configured — `conditions={3 fields}` is useless for deciding a
    translation target; `conditions.combinator=and, conditions.conditions[0].leftValue=...`
    is not. Full values still land in node drafting via build_n8n_hint; this path
    trades a bit of prompt size for much sharper signal.
    """
    parts: List[str] = []
    total = 0
    for key, value in params.items():
        # `resource` / `operation` are rendered on the header line already,
        # don't repeat them in the parameter body.
        if key in ('resource', 'operation'):
            continue
        for rendered in _flatten_n8n_value(key, value, depth=0):
            # Cap total chars so a single verbose node can't crowd out the rest.
            if total + len(rendered) + 2 > _N8N_PARAM_TOTAL_CLIP:
                parts.append('…(more fields clipped)')
                return ', '.join(parts)
            parts.append(rendered)
            total += len(rendered) + 2
    return ', '.join(parts)


def n8n_source_lines(n8n_context: Dict[str, Dict[str, Any]]) -> List[str]:
    """One entry per n8n source node of an import: id / type / resource /
    operation, then a clipped line of its remaining parameters and its first
    note. Structural, not authoritative: node drafting gets the full JSON."""
    lines: List[str] = []
    for n8n_id, node in n8n_context.items():
        node_type = node.get('type', '?')
        params = node.get('parameters', {}) if isinstance(node.get('parameters'), dict) else {}
        resource = params.get('resource') or ''
        operation = params.get('operation') or ''
        notes = (node.get('notes') or '').strip().splitlines()
        header_bits = []
        if resource:
            header_bits.append(f"resource={resource}")
        if operation:
            header_bits.append(f"operation={operation}")
        header_extra = f" ({', '.join(header_bits)})" if header_bits else ""
        lines.append(f"- {n8n_id} [{node_type}]{header_extra}")
        param_line = _summarise_n8n_params(params)
        if param_line:
            lines.append(f"    {param_line}")
        if notes:
            lines.append(f"    notes: {notes[0][:120]}")
    return lines

"""
Incremental autolayout helper shared between the external MCP server and the
internal agentic builder.

Both call sites run the Sugiyama layout over the full graph after a batch of
mutations and emit the result as a single ``layout_applied`` event. The helper
is tuned to keep existing user-positioned graphs stable while placing newly
added nodes sensibly:

  * Nodes that already had edges get pinned (DynaDAG-weighted 10/90 blend)
    so Sugiyama barely moves them — preserves user drags and prior layouts.
  * Nodes added in this batch are never pinned — Sugiyama places them via
    the topology of any edges they brought in.
  * Nodes that just gained their first edge in this batch are unpinned too —
    their previous position came from the grid fallback below and should
    give way to a proper Sugiyama placement.
  * Nodes with no edges at all fall through to a viewport-aware grid so
    they're readable instead of piling on origin; the grid is offset to the
    right of any existing anchored graph's bounding box.

Also produces the sticky-update payload the frontend needs to animate
sticky notes to their refreshed anchored positions.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

import math

from utils.autolayout import autolayout as run_autolayout
from .workflow_ops import recompute_sticky_positions


# Logical-coord spacing used when we fall back to grid placement for fresh
# disconnected nodes. Sized to keep expanded editing-panel nodes readable.
_GRID_COL_W = 300.0
_GRID_ROW_H = 200.0
# Gap between the existing anchored graph's right edge and the regrid origin.
_GRID_ANCHOR_GAP = 400.0


def _has_real_position(node: Dict[str, Any]) -> bool:
    """True when the node dict carries an explicit position (even at origin).

    NodeState.to_dict omits the ``position`` key entirely when the node has
    never been placed, so the mere presence of the key is the right signal.
    A node legitimately sitting at ``(0, 0)`` after a prior layout pass still
    counts as anchored — otherwise every subsequent batch would tag it as
    fresh and regrid it away from its place in the existing graph.
    """
    return node.get("position") is not None


def _regrid_unanchored(
    positions: Dict[str, Dict[str, float]],
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    anchored_before: Set[str],
    viewport_width: Optional[float],
    viewport_height: Optional[float],
) -> None:
    """
    Re-pack truly disconnected nodes into a grid so they don't pile onto
    origin and — when there are existing anchored nodes — don't overlap the
    existing graph.

    Only targets nodes that (a) have no edges and (b) aren't already anchored
    from a prior layout. Nodes Sugiyama could place using topology (anything
    with an edge) are left alone — their computed positions are correct.
    """
    if not positions:
        return

    type_by_id = {n["id"]: n.get("type") for n in nodes}
    edged_nodes: Set[str] = set()
    for e in edges:
        s = e.get("source") or e.get("sourceId")
        t = e.get("target") or e.get("targetId")
        if s:
            edged_nodes.add(s)
        if t:
            edged_nodes.add(t)

    # Nodes to regrid: non-sticky, not anchored before, AND have no edges to
    # let Sugiyama position them. An edged newly-added node was already placed
    # correctly by Sugiyama and must not be overwritten.
    unanchored = [
        nid for nid in positions
        if nid not in anchored_before
        and type_by_id.get(nid) != "stickyNote"
        and nid not in edged_nodes
    ]

    # Skip regridding when the batch is too small AND there's no existing
    # anchored graph to overlap with — autolayout's default centering is fine
    # for one or two fresh nodes with nothing around.
    if len(unanchored) < 3 and not anchored_before:
        return
    if not unanchored:
        return

    # Determine the grid origin: to the right of the anchored bounding box,
    # or at (0, 0) when nothing is anchored yet.
    if anchored_before:
        anchor_xs = [positions[nid]["x"] for nid in anchored_before if nid in positions]
        anchor_ys = [positions[nid]["y"] for nid in anchored_before if nid in positions]
        if anchor_xs and anchor_ys:
            start_x = max(anchor_xs) + _GRID_ANCHOR_GAP
            start_y = min(anchor_ys)
        else:
            start_x = start_y = 0.0
    else:
        start_x = start_y = 0.0

    # Preserve relative order from the autolayout's stacking output for stable IDs.
    unanchored.sort(key=lambda nid: (positions[nid]["y"], positions[nid]["x"]))

    n = len(unanchored)
    if viewport_width and viewport_height and viewport_height > 0:
        aspect = max(0.5, min(4.0, viewport_width / viewport_height))
    else:
        aspect = 16 / 9
    cols = max(1, min(n, round(math.sqrt(n * aspect))))

    for i, nid in enumerate(unanchored):
        row, col = divmod(i, cols)
        positions[nid] = {
            "x": start_x + col * _GRID_COL_W,
            "y": start_y + row * _GRID_ROW_H,
        }


def compute_incremental_layout(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    newly_added_ids: Optional[Iterable[str]] = None,
    just_connected_ids: Optional[Iterable[str]] = None,
    pin_existing: bool = True,
    viewport_width: Optional[float] = None,
    viewport_height: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compute the Sugiyama layout for ``nodes`` + ``edges``.

    When ``pin_existing`` is True (the default, matching the MCP path), every
    non-sticky node that isn't in ``newly_added_ids`` AND already has a real
    user-positioned placement is pinned so the existing graph barely moves.
    When False (the agentic builder path), no pinning happens — every batch
    lays the whole graph out fresh so positions converge to the clean
    Sugiyama result as new nodes and edges arrive.

    Mutates ``nodes`` in place: every node's ``position`` is updated to the
    layouted value, and sticky notes get re-anchored via
    ``recompute_sticky_positions``.

    Returns::

        {
            "positions": {node_id: {"x": float, "y": float}, ...},
            "sticky_updates": {node_id: {"width": int, "height": int}, ...},
        }
    """
    newly_added: Set[str] = set(newly_added_ids or ())
    just_connected: Set[str] = set(just_connected_ids or ())

    # Nodes that currently participate in an edge.
    edged_nodes: Set[str] = set()
    for e in edges:
        s = e.get("source") or e.get("sourceId")
        t = e.get("target") or e.get("targetId")
        if s:
            edged_nodes.add(s)
        if t:
            edged_nodes.add(t)

    # Snapshot which nodes already had a real position before this layout pass.
    # Used both for pinning and for the regrid fallback that places unanchored
    # nodes in an empty area of the canvas.
    anchored_before: Set[str] = {
        n["id"] for n in nodes
        if n["id"] not in newly_added
        and n.get("type") != "stickyNote"
        and _has_real_position(n)
    }

    # Pinning criteria:
    #   1. Must be anchored (has a prior position).
    #   2. Must already have an edge — disconnected nodes' positions came from
    #      the grid fallback and shouldn't be preserved.
    #   3. Must NOT have gained an edge in this batch — those nodes were
    #      previously disconnected (grid-placed) and should now re-layout
    #      properly via Sugiyama.
    pinned_ids: Set[str] = (
        {
            nid for nid in anchored_before
            if nid in edged_nodes and nid not in just_connected
        }
        if pin_existing else set()
    )

    # autolayout expects edges keyed by `source`/`target`, but GraphState
    # exposes them as `sourceId`/`targetId`. Normalize either shape.
    normalized_edges: List[Dict[str, Any]] = [
        {
            **e,
            "source": e.get("source") or e.get("sourceId"),
            "target": e.get("target") or e.get("targetId"),
        }
        for e in edges
    ]

    positions = run_autolayout(
        nodes, normalized_edges,
        pinned_node_ids=pinned_ids if pinned_ids else None,
    )

    # Re-pack truly disconnected nodes into a viewport-sized grid — either at
    # the origin (fresh graph) or to the right of the existing anchored graph
    # (edit-in-place). Edged nodes are left alone — Sugiyama placed them.
    _regrid_unanchored(positions, nodes, normalized_edges, anchored_before,
                       viewport_width, viewport_height)

    for node in nodes:
        if node["id"] in positions:
            node["position"] = positions[node["id"]]

    # Re-anchor sticky notes after the non-sticky layout is final.
    recompute_sticky_positions(nodes, edges)

    # Include sticky note positions in the layout payload so the frontend
    # animates them alongside the other nodes.
    for node in nodes:
        if node.get("type") == "stickyNote":
            positions[node["id"]] = node["position"]

    sticky_updates = {
        n["id"]: {"width": n.get("width", 200), "height": n.get("height", 200)}
        for n in nodes
        if n.get("type") == "stickyNote"
    }

    result: Dict[str, Any] = {"positions": positions}
    if sticky_updates:
        result["sticky_updates"] = sticky_updates
    return result

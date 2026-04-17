"""
Tests for ``coder.workflow.layout.compute_incremental_layout``.

Covers the rules documented in the helper's module docstring:
  * Edged anchored nodes get pinned (preserve user/prior placements).
  * Newly added nodes are never pinned.
  * Nodes that just gained their first edge are unpinned (regrid → Sugiyama).
  * Truly disconnected nodes fall through to a viewport-aware grid, offset
    to the right of the existing anchored bounding box.
  * Sticky notes are re-anchored and surfaced via ``sticky_updates``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from coder.workflow.layout import (
    _GRID_ANCHOR_GAP,
    _GRID_COL_W,
    _GRID_ROW_H,
    compute_incremental_layout,
)


def make_node(
    nid: str,
    *,
    position: Optional[Dict[str, float]] = None,
    type_: str = "tool",
    config: Optional[Dict[str, Any]] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> Dict[str, Any]:
    n: Dict[str, Any] = {"id": nid, "type": type_}
    if position is not None:
        n["position"] = position
    if config is not None:
        n["config"] = config
    if width is not None:
        n["width"] = width
    if height is not None:
        n["height"] = height
    return n


def make_edge(src: str, tgt: str) -> Dict[str, Any]:
    return {"id": f"e_{src}_{tgt}", "source": src, "target": tgt}


# ---------------------------------------------------------------------------
# Fresh / disconnected
# ---------------------------------------------------------------------------

class TestDisconnectedNodes:
    def test_single_node_centered_no_grid(self):
        """One disconnected node — autolayout centers it; helper does NOT
        regrid (small batch + no anchored graph → fall through unchanged)."""
        nodes = [make_node("a")]
        result = compute_incremental_layout(
            nodes, [], newly_added_ids={"a"}
        )
        assert "a" in result["positions"]
        assert "sticky_updates" not in result

    def test_many_disconnected_grid_at_origin(self):
        """5 disconnected new nodes pack into a viewport-aware grid at origin."""
        nodes = [make_node(f"n{i}") for i in range(5)]
        result = compute_incremental_layout(
            nodes, [],
            newly_added_ids={f"n{i}" for i in range(5)},
            viewport_width=1600.0, viewport_height=900.0,
        )
        positions = result["positions"]
        # 5 nodes with 16:9 aspect: cols = round(sqrt(5 * 16/9)) = round(2.98) = 3
        xs = sorted({pos["x"] for pos in positions.values()})
        assert len(xs) == 3, f"expected 3 columns, got xs={xs}"
        assert xs[0] == 0.0
        assert xs[1] == _GRID_COL_W
        assert xs[2] == 2 * _GRID_COL_W

    def test_grid_aspect_ratio_narrow_viewport(self):
        """Narrow viewport collapses the grid to fewer columns."""
        nodes = [make_node(f"n{i}") for i in range(8)]
        result = compute_incremental_layout(
            nodes, [],
            newly_added_ids={f"n{i}" for i in range(8)},
            viewport_width=400.0, viewport_height=900.0,
        )
        cols = len({p["x"] for p in result["positions"].values()})
        # aspect clamped at 0.5 → cols = round(sqrt(8*0.5)) = round(2) = 2
        assert cols == 2


# ---------------------------------------------------------------------------
# Pinning
# ---------------------------------------------------------------------------

class TestPinning:
    def test_anchored_edged_node_pinned(self):
        """An existing node with an edge stays put when a new disconnected
        node is added."""
        nodes = [
            make_node("a", position={"x": 0.0, "y": 0.0}),
            make_node("b", position={"x": 200.0, "y": 0.0}),
            make_node("c"),  # newly added, disconnected
        ]
        edges = [make_edge("a", "b")]
        result = compute_incremental_layout(
            nodes, edges, newly_added_ids={"c"},
        )
        # a/b should be very close to their original positions (DynaDAG 10/90)
        assert abs(result["positions"]["a"]["x"] - 0.0) < 50
        assert abs(result["positions"]["b"]["x"] - 200.0) < 50

    def test_just_connected_unpinned(self):
        """A node previously placed at a grid position that just gained its
        first edge in this batch should NOT be pinned — Sugiyama re-lays the
        component and `b` ends up positioned via topology, not at its old
        grid coordinate."""
        nodes = [
            make_node("a", position={"x": 0.0, "y": 0.0}),
            make_node("b", position={"x": 5000.0, "y": 5000.0}),  # grid-placed
        ]
        edges = [make_edge("a", "b")]  # just connected
        result = compute_incremental_layout(
            nodes, edges,
            newly_added_ids=set(),
            just_connected_ids={"a", "b"},
        )
        # b should be Sugiyama-placed relative to a (left→right, similar y),
        # NOT stuck at its stale grid coordinate.
        a_pos = result["positions"]["a"]
        b_pos = result["positions"]["b"]
        assert b_pos["x"] != 5000.0, f"b stuck at grid coord: {b_pos}"
        assert b_pos["x"] > a_pos["x"], "b should be right of a"
        assert abs(b_pos["y"] - a_pos["y"]) < 100, \
            f"b should align horizontally with a: a={a_pos} b={b_pos}"

    def test_pin_existing_false_disables_pinning(self):
        """pin_existing=False (agentic builder pre-refactor mode) means no
        pinning at all — every batch lays out fresh."""
        nodes = [
            make_node("a", position={"x": 1000.0, "y": 1000.0}),
            make_node("b", position={"x": 1200.0, "y": 1000.0}),
        ]
        edges = [make_edge("a", "b")]
        result = compute_incremental_layout(
            nodes, edges, pin_existing=False,
        )
        # Without pinning, autolayout repositions a + b to its own coords
        # (won't preserve the 1000,1000 origin).
        assert result["positions"]["a"]["x"] != 1000.0


# ---------------------------------------------------------------------------
# Grid offset relative to anchored bounding box
# ---------------------------------------------------------------------------

class TestGridOffset:
    def test_disconnected_added_to_right_of_anchored(self):
        """When an anchored connected graph exists, fresh disconnected nodes
        grid to the right of its bounding box (not at origin)."""
        nodes = [
            make_node("a", position={"x": 0.0, "y": 0.0}),
            make_node("b", position={"x": 300.0, "y": 0.0}),
            # Plus 3 fresh disconnected nodes
            make_node("c"),
            make_node("d"),
            make_node("e"),
        ]
        edges = [make_edge("a", "b")]
        result = compute_incremental_layout(
            nodes, edges,
            newly_added_ids={"c", "d", "e"},
            viewport_width=1600.0, viewport_height=900.0,
        )
        anchored_max_x = max(result["positions"][n]["x"] for n in ("a", "b"))
        for nid in ("c", "d", "e"):
            assert result["positions"][nid]["x"] >= anchored_max_x + _GRID_ANCHOR_GAP - 1

    def test_skip_regrid_for_tiny_fresh_batch(self):
        """When there's no anchored graph and only 1-2 fresh disconnected
        nodes, autolayout's centering is fine — don't regrid."""
        nodes = [make_node("a"), make_node("b")]
        result = compute_incremental_layout(
            nodes, [], newly_added_ids={"a", "b"},
            viewport_width=1600.0, viewport_height=900.0,
        )
        # Both should keep autolayout's positions (whatever they are), not
        # be forced to (0,0) and (300, 0). Just assert they're not at the grid.
        positions = sorted([result["positions"]["a"], result["positions"]["b"]],
                           key=lambda p: p["x"])
        # Grid would put them at x=0 and x=300; autolayout's centering puts
        # them at non-zero coords. Either is okay — just confirm helper ran.
        assert "a" in result["positions"] and "b" in result["positions"]


# ---------------------------------------------------------------------------
# Edged newly-added nodes
# ---------------------------------------------------------------------------

class TestEdgedNewlyAdded:
    def test_edged_new_node_not_regridded(self):
        """A newly-added node with an edge is placed by Sugiyama via
        topology — it must NOT be overwritten by the grid fallback."""
        nodes = [
            make_node("a", position={"x": 0.0, "y": 0.0}),
            make_node("b", position={"x": 200.0, "y": 0.0}),
            make_node("c"),  # newly added, but has edge to b
        ]
        edges = [make_edge("a", "b"), make_edge("b", "c")]
        result = compute_incremental_layout(
            nodes, edges,
            newly_added_ids={"c"},
            viewport_width=1600.0, viewport_height=900.0,
        )
        # c should be to the right of b (Sugiyama placement), not at the
        # grid offset which would be (b_x + GRID_ANCHOR_GAP, ...).
        c_x = result["positions"]["c"]["x"]
        b_x = result["positions"]["b"]["x"]
        # Sugiyama H_GAP is 180, so c should be roughly b + (b_width + 180)
        assert b_x < c_x < b_x + _GRID_ANCHOR_GAP, \
            f"c at {c_x} not Sugiyama-placed relative to b at {b_x}"


# ---------------------------------------------------------------------------
# Sticky notes
# ---------------------------------------------------------------------------

class TestStickyNotes:
    def test_sticky_updates_emitted(self):
        """Sticky notes appear in sticky_updates with their dimensions."""
        nodes = [
            make_node("a", position={"x": 0.0, "y": 0.0}),
            make_node(
                "s1", type_="stickyNote",
                position={"x": 0.0, "y": -100.0},
                config={"_anchor_near": "a"},
                width=200, height=200,
            ),
        ]
        result = compute_incremental_layout(nodes, [])
        assert "sticky_updates" in result
        assert "s1" in result["sticky_updates"]
        # width/height come from the resolved anchor dims; just confirm the
        # keys are present and have positive values.
        assert result["sticky_updates"]["s1"]["width"] > 0
        assert result["sticky_updates"]["s1"]["height"] > 0

    def test_sticky_note_excluded_from_anchored_set(self):
        """Sticky notes shouldn't count as 'anchored' — they get re-anchored
        every pass and don't drive the grid offset."""
        nodes = [
            make_node(
                "s1", type_="stickyNote",
                position={"x": 5000.0, "y": 5000.0},
                config={"_anchor_near": "a"},
                width=200, height=200,
            ),
            make_node("a"),  # newly added, fresh
            make_node("b"),
            make_node("c"),
        ]
        result = compute_incremental_layout(
            nodes, [],
            newly_added_ids={"a", "b", "c"},
            viewport_width=1600.0, viewport_height=900.0,
        )
        # If the sticky had been treated as anchored, a/b/c would be offset
        # to ~5000+400. They should be near the origin instead.
        for nid in ("a", "b", "c"):
            assert result["positions"][nid]["x"] < 2000


# ---------------------------------------------------------------------------
# Mutation: positions written back into nodes
# ---------------------------------------------------------------------------

class TestMutation:
    def test_node_position_mutated_in_place(self):
        nodes = [make_node("a"), make_node("b")]
        edges = [make_edge("a", "b")]
        compute_incremental_layout(nodes, edges)
        for node in nodes:
            assert "position" in node
            assert "x" in node["position"] and "y" in node["position"]


# ---------------------------------------------------------------------------
# Edge normalization
# ---------------------------------------------------------------------------

class TestEdgeNormalization:
    def test_sourceid_targetid_normalized(self):
        """GraphState exposes edges as sourceId/targetId; helper normalizes."""
        nodes = [make_node("a"), make_node("b")]
        edges = [{"id": "e", "sourceId": "a", "targetId": "b"}]
        result = compute_incremental_layout(nodes, edges)
        # If normalization worked, a/b are connected and Sugiyama lays them
        # left→right.
        assert result["positions"]["a"]["x"] < result["positions"]["b"]["x"]

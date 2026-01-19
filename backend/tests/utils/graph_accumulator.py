"""
Graph accumulator that calls the frontend TypeScript implementation via CLI.

This ensures Python tests use the exact same graph accumulation logic as the frontend,
preventing drift between implementations. The TypeScript source of truth is located at:
frontend/app/lib/graphAccumulator.ts

Usage:
    from tests.utils.graph_accumulator import GraphAccumulator

    accumulator = GraphAccumulator()
    accumulator.handle_event("node_start", {"node": {...}})
    accumulator.handle_event("edge_add", {"edge": {...}})

    # Get results (calls the CLI)
    final_graph = accumulator.get_final_graph()
    verification = accumulator.verify_iteration_edges()
"""

import subprocess
import json
import os
from typing import Dict, List, Any, Optional
from pathlib import Path


# Path to the frontend directory (relative to backend root)
FRONTEND_DIR = Path(__file__).parent.parent.parent.parent / "frontend"


class GraphAccumulator:
    """
    Accumulates workflow generation events and produces a final graph.

    This is a Python wrapper around the TypeScript GraphAccumulator that calls
    the CLI script to ensure both frontend and tests use the same logic.
    """

    def __init__(self):
        self.events: List[Dict[str, Any]] = []
        self._result_cache: Optional[Dict[str, Any]] = None

    def handle_event(self, event_type: str, event_data: Dict[str, Any]) -> None:
        """
        Handle a workflow generation event.

        Args:
            event_type: The event type (e.g., 'node_start', 'edge_add')
            event_data: The event data payload
        """
        self.events.append({"type": event_type, "data": event_data})
        # Invalidate cache when new events are added
        self._result_cache = None

    def _run_cli(self) -> Dict[str, Any]:
        """
        Run the TypeScript CLI with accumulated events and return the result.
        """
        if self._result_cache is not None:
            return self._result_cache

        # Serialize events to JSON
        events_json = json.dumps(self.events)

        # Run the CLI script
        try:
            result = subprocess.run(
                ["npx", "tsx", "scripts/graph-accumulator-cli.ts"],
                input=events_json,
                capture_output=True,
                text=True,
                cwd=str(FRONTEND_DIR),
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("GraphAccumulator CLI timed out after 30 seconds")
        except FileNotFoundError:
            raise RuntimeError(
                f"Could not find npx. Ensure Node.js is installed and in PATH. "
                f"Frontend dir: {FRONTEND_DIR}"
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"GraphAccumulator CLI failed with exit code {result.returncode}:\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        try:
            self._result_cache = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Failed to parse CLI output as JSON: {e}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        return self._result_cache

    def get_final_graph(self) -> Dict[str, Any]:
        """
        Get the final graph in ReactFlow-compatible format.

        Returns:
            Dict with 'type', 'version', 'nodes', 'edges', 'name', 'summary'
        """
        result = self._run_cli()
        return result["graph"]

    def get_state(self) -> Dict[str, Any]:
        """
        Get the current accumulator state.

        Returns:
            Dict with 'nodes', 'edges', 'inputs', 'workflowName', 'workflowSummary'
        """
        result = self._run_cli()
        return result["state"]

    def verify_iteration_edges(self) -> Dict[str, Any]:
        """
        Verify that edges from iteration nodes have correct sourceHandle values.

        Returns:
            Dict with:
                - iterationNodes: list of iteration node IDs
                - edgesFromIteration: list of edges from iteration nodes
                - missingHandles: edges that should have handles but don't
                - correctHandles: edges with valid 'loop' or 'done' handles
        """
        result = self._run_cli()
        return result["verification"]

    def get_errors(self) -> List[str]:
        """
        Get any errors that occurred during event processing.
        """
        result = self._run_cli()
        return result["errors"]

    def print_summary(self) -> None:
        """
        Print a summary of the accumulated graph for debugging.
        """
        result = self._run_cli()
        state = result["state"]
        verification = result["verification"]
        errors = result["errors"]

        print(f"\n=== Graph Summary ===")
        print(f"Nodes: {len(state['nodes'])}")
        for node in state["nodes"]:
            print(f"  - {node['id']} ({node['type']}): {node['label']}")

        print(f"\nEdges: {len(state['edges'])}")
        for edge in state["edges"]:
            handle_info = f" [handle={edge.get('sourceHandle')}]" if edge.get("sourceHandle") else ""
            print(f"  - {edge['sourceId']} -> {edge['targetId']}{handle_info}")

        if errors:
            print(f"\nErrors: {len(errors)}")
            for error in errors:
                print(f"  - {error}")

        # Verify iteration edges
        if verification["iterationNodes"]:
            print(f"\n=== Iteration Edge Verification ===")
            print(f"Iteration nodes: {verification['iterationNodes']}")
            print(f"Edges from iteration: {len(verification['edgesFromIteration'])}")
            if verification["missingHandles"]:
                print(f"❌ Missing handles: {verification['missingHandles']}")
            if verification["correctHandles"]:
                print(f"✓ Correct handles: {verification['correctHandles']}")

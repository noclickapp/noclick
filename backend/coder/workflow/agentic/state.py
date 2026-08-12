"""
Turn-level signals for the AgenticBuilder.

After the builder_generations collapse, persistence happens entirely through
conversations.events at turn boundaries (complete / incomplete / paused-on-ask /
cancelled).
This module no longer carries any cross-turn serialization shape — only the
in-memory dataclasses that AgenticBuilder uses to communicate the outcome of
one turn to the outer handler loop.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional


@dataclass
class PendingAsk:
    """An <ask/> the brain emitted that terminated the current turn."""
    ask_id: str
    inputs: List[Dict[str, Any]]
    title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"ask_id": self.ask_id, "inputs": self.inputs, "title": self.title}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PendingAsk":
        return cls(ask_id=d["ask_id"], inputs=d.get("inputs", []), title=d.get("title"))


NextAction = Literal["continue", "ask", "done", "incomplete", "cancelled"]


@dataclass(frozen=True)
class ExecutionEffects:
    """What an executed command batch actually accomplished.

    Observation-only commands (schema/operation lookups, reads) are useful
    progress, but they are not a build. Keeping that distinction explicit
    prevents a query result from being mistaken for a completed workflow.
    """
    turn: int
    observation_ops: List[str]
    material_ops_attempted: List[str]
    graph_changed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "observation_ops": list(self.observation_ops),
            "material_ops_attempted": list(self.material_ops_attempted),
            "graph_changed": self.graph_changed,
        }


@dataclass
class TurnResult:
    """Outcome of a single run_one_turn call, instructing the outer loop what to do next."""
    next_action: NextAction
    pending_ask: Optional[PendingAsk] = None
    # On a "cancelled" action, the CancelScope reason that produced it — "user"
    # for an FE Stop (terminal cancel) vs "shutdown" for a container drain
    # (recoverable interrupt). None for every non-cancelled action.
    cancel_reason: Optional[str] = None
    # Machine-readable reason for a run that ended without the explicit
    # completion signal. The handler maps this to user-facing copy and records
    # the generation as failed/incomplete rather than successful.
    incomplete_reason: Optional[str] = None

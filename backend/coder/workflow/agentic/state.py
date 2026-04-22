"""
Serializable snapshot of an AgenticBuilder between turns.

BuilderState is the boundary interface between the turn-driven handler loop
and the builder itself: the handler loads state from Postgres, hands it to
the builder to run one turn, receives an updated state back, and persists it.
On <ask/> the state captures the pending request so a fresh container can
resume the run hours or days later without any in-memory continuity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


STATUS_STREAMING = "streaming"
STATUS_WAITING_FOR_INPUT = "waiting_for_input"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

ALL_STATUSES = frozenset({
    STATUS_STREAMING,
    STATUS_WAITING_FOR_INPUT,
    STATUS_COMPLETED,
    STATUS_FAILED,
})


@dataclass
class BuilderRuntimeState:
    """Loop-scoped bookkeeping that has no query need but must survive resume."""
    viewport_width: Optional[float] = None
    viewport_height: Optional[float] = None
    prev_execution_result: Optional[str] = None
    repeat_count: int = 0
    emitted_text: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "prev_execution_result": self.prev_execution_result,
            "repeat_count": self.repeat_count,
            "emitted_text": self.emitted_text,
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "BuilderRuntimeState":
        if not d:
            return cls()
        return cls(
            viewport_width=d.get("viewport_width"),
            viewport_height=d.get("viewport_height"),
            prev_execution_result=d.get("prev_execution_result"),
            repeat_count=d.get("repeat_count", 0),
            emitted_text=d.get("emitted_text", False),
        )


@dataclass
class PendingAsk:
    """Outstanding <ask/> that halted a builder turn."""
    ask_id: str
    inputs: List[Dict[str, Any]]
    title: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"ask_id": self.ask_id, "inputs": self.inputs, "title": self.title}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PendingAsk":
        return cls(ask_id=d["ask_id"], inputs=d.get("inputs", []), title=d.get("title"))


NextAction = Literal["continue", "ask", "done"]


@dataclass
class TurnResult:
    """Outcome of a single run_one_turn call, instructing the outer loop what to do next."""
    next_action: NextAction
    pending_ask: Optional[PendingAsk] = None


@dataclass
class BuilderState:
    """Full serializable snapshot of one builder run."""
    generation_id: str
    user_id: str
    workflow_id: str
    status: str
    messages: List[Dict[str, Any]]
    graph_snapshot: Dict[str, Any]
    turn_count: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0
    n8n_context: Optional[Dict[str, Any]] = None
    runtime: BuilderRuntimeState = field(default_factory=BuilderRuntimeState)
    conversation_id: Optional[str] = None
    pending_ask: Optional[PendingAsk] = None
    last_event_seq: int = 0

    def to_row_fields(self) -> Dict[str, Any]:
        """Column values for an INSERT/UPDATE on builder_generations."""
        return {
            "id": self.generation_id,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "conversation_id": self.conversation_id,
            "status": self.status,
            "conversation": self.messages,
            "graph_snapshot": self.graph_snapshot,
            "pending_ask": self.pending_ask.to_dict() if self.pending_ask else None,
            "n8n_context": self.n8n_context,
            "runtime_state": self.runtime.to_dict(),
            "turn_count": self.turn_count,
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
            "last_event_seq": self.last_event_seq,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "BuilderState":
        """Reconstruct from a builder_generations row (dict-like, e.g. asyncpg Record)."""
        pending = row.get("pending_ask")
        n8n_ctx = row.get("n8n_context")
        return cls(
            generation_id=str(row["id"]),
            user_id=str(row["user_id"]),
            workflow_id=str(row["workflow_id"]),
            conversation_id=str(row["conversation_id"]) if row.get("conversation_id") else None,
            status=row["status"],
            messages=list(row["conversation"]) if row.get("conversation") else [],
            graph_snapshot=dict(row["graph_snapshot"]) if row.get("graph_snapshot") else {},
            turn_count=row.get("turn_count", 0),
            total_cost=float(row.get("total_cost") or 0.0),
            total_tokens=row.get("total_tokens", 0),
            n8n_context=dict(n8n_ctx) if n8n_ctx else None,
            runtime=BuilderRuntimeState.from_dict(row.get("runtime_state")),
            pending_ask=PendingAsk.from_dict(pending) if pending else None,
            last_event_seq=row.get("last_event_seq", 0),
        )

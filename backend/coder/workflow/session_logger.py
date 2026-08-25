"""Optional community-builder instrumentation seam.

The community edition does not persist model transcripts or stage internals.
Callers can still emit generic lifecycle events through this no-op sink, which
operators may replace locally.
"""

from __future__ import annotations

from typing import Any, Optional


class SessionLogger:
    """No-op implementation of the builder's generic diagnostics sink."""

    def __init__(
        self,
        generation_id: str,
        conversation_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        self.generation_id = generation_id
        self.conversation_id = conversation_id
        self.workflow_id = workflow_id
        self.user_id = user_id
        self.enabled = False

    def close(self) -> None:
        return None

    def log_session_start(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def log_session_end(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_brain_turn_start(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_brain_streaming(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_brain_turn_end(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_ops_parsed(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_execution_effects(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_op_executed(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_frontend_event(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_event(self, *args: Any, **kwargs: Any) -> None:
        return None

    def log_error(self, *args: Any, **kwargs: Any) -> None:
        return None

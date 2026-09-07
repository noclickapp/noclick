"""Small, transport-independent helpers for public CLI protocols."""
from __future__ import annotations


class RpcError(RuntimeError):
    """An explicit JSON-RPC rejection (as distinct from a lost acknowledgement)."""

    def __init__(self, error: dict):
        self.error = error
        super().__init__(str(error.get("message") or error))


def steer_turn_ended(error: RpcError) -> bool:
    """Only a definite invalid-state rejection permits resending as a new turn.

    Never retry a timeout, disconnect, authentication failure, or arbitrary
    server error: the original input may already have been accepted.
    """
    message = str(error).lower()
    return error.error.get("code") == -32600 and (
        "no active turn" in message or "expected turn" in message
        or "turn id mismatch" in message
    )


class ClaudeReceipts:
    """Track consumed inputs, including several inputs merged into one result.

    Current CLIs put user_message_uuids on results. Replay acknowledgements
    cover older streaming CLIs. Tool-result user frames are not input receipts.
    Callers serialize access when their reader runs on another thread.
    """

    def __init__(self):
        self.pending: dict[str, None] = {}
        self.replayed: set[str] = set()

    def add(self, receipt: str):
        self.pending[receipt] = None

    def discard(self, receipt: str):
        self.pending.pop(receipt, None)
        self.replayed.discard(receipt)

    def observe(self, event: dict):
        receipt = event.get("uuid")
        if event.get("isReplay") and receipt in self.pending:
            self.replayed.add(receipt)

    def finish(self, event: dict) -> list[str]:
        ids = event.get("user_message_uuids")
        if ids is None:
            ids = list(self.replayed)
            if not ids and event.get("user_message_uuid"):
                ids = [event["user_message_uuid"]]
            # Older CLIs can fail before emitting the initial replay frame.
            if not ids:
                ids = list(self.pending)[:1]
        matched = [receipt for receipt in self.pending if receipt in ids]
        for receipt in matched:
            self.discard(receipt)
        return matched

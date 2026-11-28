"""What a ``noclick`` command's exit status means, the one table both CLIs (Python's and TypeScript's ``exits.ts``)
follow, so an agent acts on it without reading the words:

- 0 done
- 1 failed
- 2 the command line was wrong (a missing argument or field, an unknown flag), or the API refused its arguments
- 3 waiting on a person (a payment, an approval, a sign-in, an answer): the link where they act is printed
- 4 refused by a limit, a price or a policy (a spending cap, ``--max-usd``, a permission the key lacks)
- 124 a wait ran out (the work goes on: ``noclick wait <id>`` picks it up)
- 130 Ctrl-C
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from ..exceptions import Error

OK = 0
FAILED = 1
USAGE = 2
WAITING = 3
REFUSED = 4
TIMED_OUT = 124
INTERRUPTED = 130

# Each status in a word, as ``noclick help --json`` lists them.
MEANINGS = {
    str(OK): "done", str(FAILED): "failed", str(USAGE): "usage", str(WAITING): "waiting on a person",
    str(REFUSED): "refused by a limit, a price or a policy", str(TIMED_OUT): "a wait ran out",
    str(INTERRUPTED): "interrupted (Ctrl-C)",
}


class Suggests:
    """Mixed into an error of the command line's own: ``run``, the whole command lines that take its next step,
    printed after ``run:`` (``output.suggested``), so none is ever read out of its words."""

    def __init__(self, message: str = "", *, run: Sequence[str] = (), **kwargs: Any) -> None:
        super().__init__(message, **kwargs)  # type: ignore[call-arg]
        self.run = list(run)


class WaitingOnPerson(Suggests, Error):
    """What only a person can do now (approve, pay, answer, sign in): ``link`` is where they do it. The command
    exits 3 rather than wait on them."""

    type = "waiting_on_person"

    def __init__(self, message: str, *, link: Optional[str] = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.details.setdefault("link", link)


class OverLimit(Suggests, Error):
    """A ``--max-usd`` (or another ceiling the command line set) the action would pass: nothing was done."""

    type = "over_limit"


# The error types (the API's ``error.type``, and the CLI's own) by exit status; anything else is FAILED.
WAITING_TYPES = frozenset({
    "waiting_on_person", "payment_required", "plan_required", "approval_required", "action_required",
    "answer_required", "needs_connection", "credential_disconnected",
})
REFUSED_TYPES = frozenset({
    "over_limit", "price_exceeded", "spend_cap_exceeded", "spending_paused", "permission_denied", "policy_denied",
    "quota_exceeded", "plan_limit_reached", "rate_limited",
})
USAGE_TYPES = frozenset({"invalid_request", "not_linked"})
TIMED_OUT_TYPES = frozenset({"operation_timeout"})
# An operation's status that only a person moves on.
WAITING_STATUSES = frozenset({"awaiting_human", "awaiting_approval", "awaiting_payment"})


def exit_code(error_type: Optional[str]) -> int:
    """The exit status an error of ``error_type`` means."""
    if error_type in WAITING_TYPES:
        return WAITING
    if error_type in REFUSED_TYPES:
        return REFUSED
    if error_type in USAGE_TYPES:
        return USAGE
    if error_type in TIMED_OUT_TYPES:
        return TIMED_OUT
    return FAILED


def code_for(err: Any) -> int:
    """The exit status an error (the SDK's, or anything with a ``type``) means."""
    return exit_code(getattr(err, "type", None))


def link_of(err: Any) -> Optional[str]:
    """Where a person acts on an error that waits on them, when it says."""
    details = getattr(err, "details", None) or {}
    for name in ("link", "approve_url", "answer_url", "url", "connect_url", "payment_url", "checkout_url"):
        if isinstance(details.get(name), str) and details[name]:
            return details[name]
    return None


__all__ = ["Suggests", "OK", "FAILED", "USAGE", "WAITING", "REFUSED", "TIMED_OUT", "INTERRUPTED", "MEANINGS", "WaitingOnPerson",
           "OverLimit", "WAITING_TYPES", "REFUSED_TYPES", "USAGE_TYPES", "WAITING_STATUSES", "exit_code", "code_for",
           "link_of"]

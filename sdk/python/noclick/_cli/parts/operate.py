"""``noclick wait <operation>``: wait for long work to finish and print its result, never on a person. When the
work waits on someone (an approval, a payment, an answer, a sign-in), it says who and where and exits 3; a
``--timeout`` that runs out exits 124 and leaves the work running."""

from __future__ import annotations

import argparse
from typing import Any, Dict, Optional

from ... import cli
from ...exceptions import OperationTimeout
from ...operation import Operation
from .. import output as out
from ..exits import WaitingOnPerson


def _person_link(raw: Dict[str, Any]) -> Optional[str]:
    """Where the person acts on work waiting on them, as the operation says."""
    question = raw.get("question") if isinstance(raw.get("question"), dict) else {}
    for found in (question.get("answer_url"), question.get("url"), raw.get("approve_url"), raw.get("connect_url"),
                  raw.get("url")):
        if isinstance(found, str) and found:
            return found
    return None


def _waiting(op: Operation, raw: Dict[str, Any]) -> WaitingOnPerson:
    question = raw.get("question") if isinstance(raw.get("question"), dict) else {}
    what = question.get("text") or question.get("message") or raw.get("summary") or "a person's answer"
    sent = raw.get("sent_to")
    where = f" (sent to {', '.join(sent)})" if isinstance(sent, list) and sent else ""
    return WaitingOnPerson(f"{op.kind} waits on a person: {what}{where}.", link=_person_link(raw) or op.console_url,
                           next_step=f"Once they've answered: noclick wait {op.id}", run=[f"noclick wait {op.id}"])


def cmd_wait(args: argparse.Namespace) -> int:
    op = Operation.from_id(args.operation_id)
    ends = None if args.timeout is None else cli._clock() + args.timeout
    for event in op.events(interval=cli.POLL_S):
        if event.status == "awaiting_human" and not args.people:
            raise _waiting(op, event.raw)
        if event.status not in ("queued", "running", "awaiting_human"):
            break
        if ends is not None and cli._clock() >= ends:
            raise out.run(OperationTimeout(f"{op.kind} is still {event.status} after {args.timeout:g}s.",
                                              next_step=f"Wait again: noclick wait {op.id}",
                                              details={"operation_id": op.id, "operation_status": event.status}),
                             [f"noclick wait {op.id}"])
    op.wait()  # finished: raises the error it failed with
    raw = op.result
    # A deploy or promote that went live but failed its check exits 1, whatever it prints.
    broken = op.kind in ("project.deploy", "deployment.promote") and isinstance(raw, dict) and bool(raw.get("warning"))
    if args.json:
        out.print_json(op)
        return 1 if broken else 0
    out.note(f"{op.kind} {op.status}")
    if isinstance(raw, dict) and isinstance(raw.get("text"), str):
        out.line(raw["text"])
    elif isinstance(raw, dict) and isinstance(raw.get("url"), str):
        out.line(out.dumps(raw))
        out.value_last(raw["url"])
    elif raw is not None:
        out.line(out.dumps(raw))
    if op.kind in ("project.deploy", "deployment.promote") and isinstance(raw, dict):
        cli._said_deployment(raw)
    return 1 if broken else 0


def register(kit: Any) -> None:
    wait = kit.command(kit.commands, "wait", cmd_wait,
                       "Wait for an operation and print its result; exits 3 when it waits on a person.",
                       parents=[kit.as_json])
    wait.epilog = ("Exit 0 done, 1 failed (a deploy or promote that went live but failed its check, too), 3 waiting "
                   "on a person (it prints where they act), 4 refused, 124 --timeout ran out (the work goes on). "
                   "noclick ops wait is its old spelling.")
    wait.add_argument("operation_id", help="The operation's id, as the command that started it printed.")
    wait.add_argument("--timeout", type=float, metavar="SECONDS", help="Give up after this long (exit 124).")
    wait.add_argument("--people", action="store_true",
                      help="Wait through a person's answer too, instead of exiting 3.")

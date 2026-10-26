"""What ends an agent turn before its model answers (``TurnLimits``): its step limit (model calls), its spend
ceiling and its time limit. ``TurnGuard`` is the run's hooks (around the billing hooks, whose cost it reads) and
checks them after every model call and tool call; the first to trip lets the calls in hand finish and stops the run
after them (the SDK's own ``cancel(mode="after_turn")``), and the agent then wraps the turn up once, whichever guard
it was, in a call of at most ``WRAP_UP_S``. A time limit is kept by the clock too: a call still holding the run
``OVERDUE_S`` past it is cancelled where it stands. A call the model repeats with the same arguments and the same
result is a loop: the ``REPEATS``th time its result carries a nudge, and from then on that call is refused for the
rest of the turn (``loop_guardrails``). A call whose result changes, like a poll, never counts.

A tool whose result hands the turn's work on (``ENDS_TURN``: a platform's wake-up set on work still running) stops the
run after the calls in hand the same way, with no wrap-up: once the turn has said something, or at once when the
result says ``SILENTLY`` (nobody waits on its words). Left running, such turns polled the work, set the same wake-up
again after each look and wrote one more line about work their person already knew was under way (2026-10-25).

A tool NoClick's credit gate turned down (``credit_refusal``: its result's error is the gate's
``insufficient_credits_message``) means the account can't pay for the turn's work. A run whose caller says how to wrap
such a turn up (a ``FUNDS`` wrap-up) stops after the calls in hand: it says once what it got done, then fails with the
gate's words, which its platform turns into its own refusal. Left running, a coordinator whose shell the gate refused
tried other tools and told its person it couldn't confirm the work, never that the day's allowance had run out
(2026-10-25).

A turn that keeps calling tools without changing anything is stuck, whatever its arguments: with a ``STALLED`` wrap-up,
the ``QUIET_NUDGE``th call in a row that only read (``progress.only_reads``: no file written, nothing saved, sent or
started) carries a note to act or say what blocks it, and the ``QUIET_STOP``th stops the turn after the calls in hand,
wrapped up as a limit's. A coordinator asked to rework one 8 MB game file re-read it at shifting offsets for over an
hour, with one edit, and the repeat guard never saw it: no two calls were the same (2026-10-26)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Set, Tuple

from agents import RunHooks
from agents.tool_guardrails import (
    ToolGuardrailFunctionOutput, ToolInputGuardrail, ToolInputGuardrailData, ToolOutputGuardrail,
    ToolOutputGuardrailData,
)

from billing.exceptions import match_insufficient_credits
from coder.openai_agent import progress

logger = logging.getLogger(__name__)

STEPS, SPEND, TIME = "steps", "spend", "time"
LIMITS = (STEPS, SPEND, TIME)
FUNDS = "funds"
STALLED = "stalled"
REASONS = LIMITS + (FUNDS, STALLED)
# The time an identical call returns the same result that gets the nudge; one more is refused.
REPEATS = 3
REPEATED_RESULT_CHARS = 2000
NUDGE = ("You've called {tool} with these same arguments {times} times this turn, and it returned the same each "
         "time:\n{result}\n\nCalling it again won't change that, so it won't run again with these arguments this "
         "turn: do something different, or answer.")
REFUSED = ("Not run: {tool} already returned the same result {times} times this turn for these arguments. Do "
           "something different, or answer.")

# Calls in a row that only read (``progress``): the note to act, then the stop. Past nearly every working turn's longest
# such run (an audit that reads one page per topic may pass the stop); each of the game-file loop's turns read on well
# past the stop until a step or time limit ended it, the file unchanged.
QUIET_NUDGE = 30
QUIET_STOP = 60
QUIET_NOTE = ("Your last {calls} calls only read: nothing written, saved, sent or started. Reading more of the same "
              "won't get it done. If you have what you need, act now: make the change (an exact replacement in a "
              "working copy beats reading another slice) or give your answer. If something stops you, say exactly "
              "what it is.")

ENDS_TURN = "ends_turn"
SILENTLY = "silently"
# How long past its time limit a call may hold a run before the run is cancelled where it stands.
OVERDUE_S = 60.0
# The most a turn's one wrap-up call may take; past it the turn ends on its stopped line alone.
WRAP_UP_S = 90.0

# Read through the module so a test can move the clock.
_now = time.monotonic


def ends_turn(output: Any) -> Any:
    """What a tool's result says of handing the turn on: ``ENDS_TURN``'s value (true, or ``SILENTLY``), else None."""
    if isinstance(output, str):
        if ENDS_TURN not in output:
            return None
        try:
            output = json.loads(output)
        except ValueError:
            return None
    return output.get(ENDS_TURN) if isinstance(output, Mapping) else None


def credit_refusal(output: Any) -> Optional[str]:
    """The credit gate's words when a tool's result is its refusal (its ``error``, never what a command printed)."""
    if not match_insufficient_credits(str(output)):
        return None
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            return None
    error = output.get("error") if isinstance(output, Mapping) else None
    found = match_insufficient_credits(error) if isinstance(error, str) else None
    return found.group(0) if found else None


def says_something(response: Any) -> bool:
    """Whether a model response has words in it, beside its calls or alone."""
    return any(getattr(item, "type", None) == "message" and any(
        (getattr(part, "text", None) or "").strip() for part in getattr(item, "content", None) or [])
        for item in getattr(response, "output", None) or [])


@dataclass(frozen=True)
class TurnLimits:
    """How far one turn goes: ``steps`` model calls, ``spend_usd`` of model calls (None: no ceiling) and
    ``minutes`` of wall clock (None: no limit). By default only the steps: a caller with no wrap-up (a workflow's
    agent node, whose run a limit fails) never meets a spend or time limit it didn't ask for."""

    steps: int = 30
    spend_usd: Optional[float] = None
    minutes: Optional[float] = None

    @classmethod
    def of(cls, given: Optional[Mapping[str, Any]]) -> "TurnLimits":
        """From a platform's ``{steps, usd, minutes}``, each one left out at its default."""
        given = given or {}
        default = cls()
        return cls(steps=int(given.get("steps", default.steps)),
                   spend_usd=float(given["usd"]) if given.get("usd") is not None else default.spend_usd,
                   minutes=float(given["minutes"]) if given.get("minutes") is not None else default.minutes)


def stopped_line(reason: str, limits: TurnLimits) -> str:
    """The plain line a person reads for a turn ``reason`` ended; none for one the account couldn't pay for, whose
    platform's refusal says why."""
    if reason == FUNDS:
        return ""
    if reason == STEPS:
        return f"I stopped here: this turn used all {limits.steps} of its steps."
    if reason == SPEND:
        return f"I stopped here: this turn reached its ${limits.spend_usd:.2f} spending limit."
    if reason == STALLED:
        return "I stopped here: I'd spent a long stretch reading without changing anything."
    return f"I stopped here: this turn ran for {limits.minutes:g} minutes, its time limit."


def wrap_ups(wrap_up: Any) -> Dict[str, Dict[str, str]]:
    """``wrap_up`` as ``{reason: {prompt, line?}}``: a string is the prompt for every limit."""
    if isinstance(wrap_up, str) and wrap_up:
        return {reason: {"prompt": wrap_up} for reason in LIMITS}
    if isinstance(wrap_up, Mapping):
        return {reason: dict(entry) for reason, entry in wrap_up.items()
                if reason in REASONS and isinstance(entry, Mapping) and entry.get("prompt")}
    return {}


def _call_key(tool: str, arguments: str) -> Tuple[str, str]:
    try:
        canonical = json.dumps(json.loads(arguments or "{}"), sort_keys=True, default=str)
    except ValueError:
        canonical = arguments or ""
    return tool, canonical


def _digest(output: Any) -> str:
    return hashlib.sha256(str(output).encode()).hexdigest()


class TurnGuard(RunHooks):
    """One turn's limits as it runs. ``inner`` is the run's billing hooks, called first, whose ``spent_usd`` (what
    they priced the calls at) is the turn's spend: hooks that keep no total leave the ceiling unreached. ``tripped``
    is the guard that tripped, once one has; ``handed_on`` that a tool's result ended it instead (``ENDS_TURN``).
    With ``ends_unfunded``, a tool the credit gate turned down trips ``FUNDS``, and ``unfunded`` is the gate's words.
    With ``ends_stalled``, calls in a row that only read are noted, then trip ``STALLED`` (``unchanged``)."""

    def __init__(self, limits: TurnLimits, inner: Optional[RunHooks] = None, *, ends_unfunded: bool = False,
                 ends_stalled: bool = False):
        self.limits = limits
        self._inner = inner
        self._ends_unfunded = ends_unfunded
        self._ends_stalled = ends_stalled
        self.quiet = 0
        self.longest_quiet = 0
        self.quiet_notes = 0
        self.unfunded: Optional[str] = None
        self._started = _now()
        self._spent_from = self._spent_total()
        self._stop: Optional[Callable[[], None]] = None
        self._timers: list = []
        self.model_calls = 0
        self.tripped: Optional[str] = None
        self.paused = False
        self.said = False
        self.handed_on = False
        self._repeats: Dict[Tuple[str, str], Tuple[str, int]] = {}
        self._refused: Set[Tuple[str, str]] = set()
        self.nudges = 0
        self.refusals = 0

    def _spent_total(self) -> float:
        return float(getattr(self._inner, "spent_usd", 0.0) or 0.0)

    @property
    def spent_usd(self) -> float:
        return self._spent_total() - self._spent_from

    @property
    def elapsed_s(self) -> float:
        return _now() - self._started

    def watch(self, result: Any) -> None:
        """The streamed run to stop once a guard trips; with a time limit, stopped by the clock as well, at once,
        when a call still holds it ``OVERDUE_S`` past the limit (``_overdue``)."""
        self._stop = lambda: result.cancel(mode="after_turn")
        if self.limits.minutes is not None:
            left = self.limits.minutes * 60 - self.elapsed_s + OVERDUE_S
            self._timers.append(asyncio.get_running_loop().call_later(max(left, 0.0), self._overdue, result))

    def close(self) -> None:
        """The turn is over: its clock stops."""
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()

    def _overdue(self, result: Any) -> None:
        """A model call that never answers ends no step, so the time limit, checked at each one, never trips: a
        site build's turn hung on one and never said its site was live (2026-10-25)."""
        if result.is_complete:
            return
        logger.warning("agent_turn_overdue: a call held the run %.0fs past its %g-minute limit", OVERDUE_S,
                       self.limits.minutes)
        self.tripped = self.tripped or TIME
        result.cancel(mode="immediate")

    def _check(self) -> None:
        if self.tripped:
            return
        limits = self.limits
        if self.model_calls >= limits.steps:
            self.tripped = STEPS
        elif limits.spend_usd is not None and self.spent_usd >= limits.spend_usd:
            self.tripped = SPEND
        elif limits.minutes is not None and self.elapsed_s >= limits.minutes * 60:
            self.tripped = TIME
        if self.tripped and self._stop is not None:
            self._stop()

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        if self._inner is not None:
            await self._inner.on_llm_start(context, agent, system_prompt, input_items)

    async def on_llm_end(self, context, agent, response) -> None:
        if self._inner is not None:
            await self._inner.on_llm_end(context, agent, response)
        self.model_calls += 1
        self.said = self.said or says_something(response)
        self._check()

    async def on_tool_end(self, context, agent, tool, result) -> None:
        unfunded = self._ends_unfunded and not self.tripped and credit_refusal(result)
        if unfunded:
            self.tripped, self.unfunded = FUNDS, unfunded
            if self._stop is not None:
                self._stop()
        handing_on = ends_turn(result)
        if handing_on and not (self.tripped or self.handed_on) and (handing_on == SILENTLY or self.said):
            self.handed_on = True
            if self._stop is not None:
                self._stop()
        # A long tool can run the clock out between model calls.
        self._check()

    def unchanged(self, tool: str, arguments: str) -> Optional[str]:
        """Counts a call that only read (``progress.only_reads``), or starts the count again after one that may have
        changed something; the note its result carries at ``QUIET_NUDGE`` in a row, and at ``QUIET_STOP`` the turn
        stops after the calls in hand (``STALLED``)."""
        if not self._ends_stalled:
            return None
        if not progress.only_reads(tool, arguments):
            self.quiet = 0
            return None
        self.quiet += 1
        self.longest_quiet = max(self.longest_quiet, self.quiet)
        if self.quiet >= QUIET_STOP and not self.tripped:
            self.tripped = STALLED
            if self._stop is not None:
                self._stop()
        if self.quiet != QUIET_NUDGE:
            return None
        self.quiet_notes += 1
        return QUIET_NOTE.format(calls=self.quiet)

    def refusal(self, tool: str, arguments: str) -> Optional[str]:
        """What a call already nudged for repeating itself gets instead of running."""
        if _call_key(tool, arguments) not in self._refused:
            return None
        self.refusals += 1
        return REFUSED.format(tool=tool, times=REPEATS)

    def repeated(self, tool: str, arguments: str, output: Any) -> Optional[str]:
        """The nudge a call's result carries the ``REPEATS``th time it returns the same for the same arguments."""
        key = _call_key(tool, arguments)
        digest = _digest(output)
        last, times = self._repeats.get(key, ("", 0))
        times = times + 1 if last == digest else 1
        self._repeats[key] = (digest, times)
        if times < REPEATS:
            return None
        self._refused.add(key)
        self.nudges += 1
        shown = str(output)
        if len(shown) > REPEATED_RESULT_CHARS:
            shown = shown[:REPEATED_RESULT_CHARS] + "…"
        return NUDGE.format(tool=tool, times=times, result=shown)


def loop_guardrails(guard_of: Callable[[], Optional[TurnGuard]]) -> Dict[str, list]:
    """A tool's guardrails for the loop detector, reading the running turn's guard."""

    async def refuse(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
        guard = guard_of()
        refused = guard and guard.refusal(data.context.tool_name, data.context.tool_arguments)
        return ToolGuardrailFunctionOutput.reject_content(refused) if refused else ToolGuardrailFunctionOutput.allow()

    async def nudge(data: ToolOutputGuardrailData) -> ToolGuardrailFunctionOutput:
        guard = guard_of()
        if not guard:
            return ToolGuardrailFunctionOutput.allow()
        name, arguments = data.context.tool_name, data.context.tool_arguments
        nudged = guard.repeated(name, arguments, data.output)
        noted = guard.unchanged(name, arguments)
        if noted:
            nudged = f"{nudged or data.output}\n\n{noted}"
        return ToolGuardrailFunctionOutput.reject_content(nudged) if nudged else ToolGuardrailFunctionOutput.allow()

    return {"tool_input_guardrails": [ToolInputGuardrail(refuse, name="repeated_call")],
            "tool_output_guardrails": [ToolOutputGuardrail(nudge, name="repeated_call")]}


def record(guard: TurnGuard, ended_by: Optional[str], *, conversation_id: Optional[str], model: str) -> None:
    """One ``agent.turn`` span over the turn, naming the guard that ended it (``agent.turn.ended_by``), and a log
    line when one did."""
    if ended_by:
        logger.info("agent_turn_guard ended_by=%s conversation=%s model_calls=%d spent_usd=%.4f seconds=%.0f",
                    ended_by, conversation_id, guard.model_calls, guard.spent_usd, guard.elapsed_s)
    try:
        from utils.otel import get_tracer

        start_ns = time.time_ns() - int(guard.elapsed_s * 1e9)
        span = get_tracer("noclick.agent").start_span("agent.turn", start_time=start_ns)
        try:
            span.set_attribute("agent.model", model)
            if conversation_id:
                span.set_attribute("conversation.id", conversation_id)
            span.set_attribute("agent.turn.model_calls", guard.model_calls)
            span.set_attribute("agent.turn.spent_usd", round(guard.spent_usd, 6))
            span.set_attribute("agent.turn.loop_nudges", guard.nudges)
            span.set_attribute("agent.turn.loop_refusals", guard.refusals)
            span.set_attribute("agent.turn.handed_on", guard.handed_on)
            span.set_attribute("agent.turn.longest_read_streak", guard.longest_quiet)
            span.set_attribute("agent.turn.read_notes", guard.quiet_notes)
            if ended_by:
                span.set_attribute("agent.turn.ended_by", ended_by)
        finally:
            span.end()
    except Exception:
        logger.warning("recording the agent.turn span failed", exc_info=True)

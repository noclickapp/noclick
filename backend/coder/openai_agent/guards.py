"""What ends an agent turn before its model answers (``TurnLimits``): its step limit (model calls), its spend
ceiling and its time limit. ``TurnGuard`` is the run's hooks (around the billing hooks, whose cost it reads) and
checks them after every model call and tool call; the first to trip lets the calls in hand finish and stops the run
after them (the SDK's own ``cancel(mode="after_turn")``), and the agent then wraps the turn up once, whichever guard
it was. A call the model repeats with the same arguments and the same result is a loop: the ``REPEATS``th time its
result carries a nudge, and from then on that call is refused for the rest of the turn (``loop_guardrails``). A call
whose result changes, like a poll, never counts."""

from __future__ import annotations

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

logger = logging.getLogger(__name__)

STEPS, SPEND, TIME = "steps", "spend", "time"
REASONS = (STEPS, SPEND, TIME)
# The time an identical call returns the same result that gets the nudge; one more is refused.
REPEATS = 3
REPEATED_RESULT_CHARS = 2000
NUDGE = ("You've called {tool} with these same arguments {times} times this turn, and it returned the same each "
         "time:\n{result}\n\nCalling it again won't change that, so it won't run again with these arguments this "
         "turn: do something different, or answer.")
REFUSED = ("Not run: {tool} already returned the same result {times} times this turn for these arguments. Do "
           "something different, or answer.")

# Read through the module so a test can move the clock.
_now = time.monotonic


@dataclass(frozen=True)
class TurnLimits:
    """How far one turn goes: ``steps`` model calls, ``spend_usd`` of model calls (None: no ceiling) and
    ``minutes`` of wall clock (None: no limit)."""

    steps: int = 30
    spend_usd: Optional[float] = 1.0
    minutes: Optional[float] = 15.0

    @classmethod
    def of(cls, given: Optional[Mapping[str, Any]]) -> "TurnLimits":
        """From a platform's ``{steps, usd, minutes}``, each one left out at its default."""
        given = given or {}
        default = cls()
        return cls(steps=int(given.get("steps", default.steps)),
                   spend_usd=float(given["usd"]) if given.get("usd") is not None else default.spend_usd,
                   minutes=float(given["minutes"]) if given.get("minutes") is not None else default.minutes)


def stopped_line(reason: str, limits: TurnLimits) -> str:
    """The plain line a person reads for a turn ``reason`` ended."""
    if reason == STEPS:
        return f"I stopped here: this turn used all {limits.steps} of its steps."
    if reason == SPEND:
        return f"I stopped here: this turn reached its ${limits.spend_usd:.2f} spending limit."
    return f"I stopped here: this turn ran for {limits.minutes:g} minutes, its time limit."


def wrap_ups(wrap_up: Any) -> Dict[str, Dict[str, str]]:
    """``wrap_up`` as ``{reason: {prompt, line?}}``: a string is the prompt for every guard."""
    if isinstance(wrap_up, str) and wrap_up:
        return {reason: {"prompt": wrap_up} for reason in REASONS}
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
    is the guard that tripped, once one has."""

    def __init__(self, limits: TurnLimits, inner: Optional[RunHooks] = None):
        self.limits = limits
        self._inner = inner
        self._started = _now()
        self._spent_from = self._spent_total()
        self._stop: Optional[Callable[[], None]] = None
        self.model_calls = 0
        self.tripped: Optional[str] = None
        self.paused = False
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
        """The streamed run to stop once a guard trips."""
        self._stop = lambda: result.cancel(mode="after_turn")

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
        self._check()

    async def on_tool_end(self, context, agent, tool, result) -> None:
        # A long tool can run the clock out between model calls.
        self._check()

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
        nudged = guard and guard.repeated(data.context.tool_name, data.context.tool_arguments, data.output)
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
            if ended_by:
                span.set_attribute("agent.turn.ended_by", ended_by)
        finally:
            span.end()
    except Exception:
        logger.warning("recording the agent.turn span failed", exc_info=True)

"""Incremental, token-budgeted context with a visible, editable checkpoint.

Inspired by OpenClaw's summary + intact tail and Hermes's per-call budget:
raw SDK history stays untouched, including tool pairs. Only model input shrinks.
There is no hidden store of goals/preferences and no lossy failure fallback.

A ``Compactor`` runs before every model call of a run (the SDK's
``call_model_input_filter``). Where the conversation's checkpoint lives is a
``CheckpointStore``'s: the coordinator's in its memory library
(``coder.coordinator.compaction``), a platform agent's in its agent memory.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Tuple

from agents.run_config import ModelInputData
from pydantic import BaseModel, Field

from coder.openai_agent.output_limits import CONTEXT_HINT, TOOL_OUTPUT_FLOOR, TOOL_OUTPUT_STUB, clip_text
from utils.prompts import PromptPack

logger = logging.getLogger(__name__)

PROMPTS = PromptPack("compaction")


class ContextBudgetError(RuntimeError):
    pass


class CheckpointConflict(RuntimeError):
    """The conversation or its checkpoint changed while compacting (a person's edit wins); history is intact."""


class Summary(BaseModel):
    # The content's bound is the store's own; the prompt aims well below it.
    description: str = Field(min_length=20, max_length=600)
    content: str = Field(min_length=40)


# Half the memory's cap: merging into a checkpoint already near the cap kept overshooting it.
TARGET_CHARACTERS = 8000


# Tagged plain text, not JSON: a summary quoting the transcript needs no escaping. The whole answer is the two
# sections, so a cut-off checkpoint, a preamble or a trailing note is refused rather than trimmed.
_SECTIONS = re.compile(r"\s*<description>(.*?)</description>\s*<checkpoint>(.*)</checkpoint>\s*", re.S)


def parse_summary(text):
    match = _SECTIONS.fullmatch(text)
    if match is None:
        raise ContextBudgetError("The context summary did not follow the checkpoint format; history is preserved.")
    return Summary(description=match.group(1).strip(), content=match.group(2).strip())


@dataclass(frozen=True)
class Budget:
    # Conservative portable ceiling for a model route reached through OpenRouter.
    # Includes system/tools and reserves room for output; does not assume a
    # provider-specific encrypted compaction format. A view folds once it would
    # pass ``hard``, down to ``target``: every fold rewrites the prompt the
    # provider cached, so none happens before it must.
    target: int = 20000
    hard: int = 48000
    chunk: int = 12000
    recent: int = 6000


# A turn's summary calls at most; past them, older tool results are cut in the model's view instead.
MAX_SUMMARIES = 8
# One image's cost, whatever its size: providers resize before reading. Most charge at most about this for their
# largest (OpenAI's high detail, Gemini's tiles, Claude before Opus 4.7); current Claude reads up to 2576px, ~4,800
# tokens, an undercount the budget absorbs since it sits far below any model's context.
IMAGE_TOKENS = 1600


def fingerprint(items) -> str:
    """A stable hash of history items as the session stores them."""
    from coder.openai_agent.output_limits import clip_history_item
    from coder.openai_agent.session import _strip_runtime_fields

    normalized = [clip_history_item(_strip_runtime_fields(item)) for item in items]
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def image_inputs(value):
    """SDK input images nested in a transcript; do not scan text/tool output for URLs."""
    if isinstance(value, list):
        for item in value:
            yield from image_inputs(item)
    elif isinstance(value, dict):
        if value.get("type") == "input_image" and value.get("image_url"):
            yield value
        elif isinstance(value.get("content"), list):
            yield from image_inputs(value["content"])


def _without_image_urls(value):
    """``value`` with each input image's URL left out: an image the turn inlines as base64 (a fetched image URL)
    costs its vision tokens, never its characters read as text."""
    if isinstance(value, list):
        return [_without_image_urls(item) for item in value]
    if isinstance(value, dict):
        if value.get("type") == "input_image":
            return {**value, "image_url": "(image)"}
        return {key: _without_image_urls(item) for key, item in value.items()}
    return value


def token_count(value, model):
    from litellm import token_counter
    text = value if isinstance(value, str) else json.dumps(_without_image_urls(value), ensure_ascii=False,
                                                           default=str)
    # Counting URL characters alone misses the vision budget.
    vision_tokens = sum(IMAGE_TOKENS for _ in image_inputs(value))
    try:
        return token_counter(model=model, text=text) + vision_tokens
    except Exception:
        # UTF-8 bytes are a conservative upper bound, including non-Latin text.
        return len(text.encode("utf-8")) + vision_tokens


def safe_boundaries(items):
    """Never put a call and its results on different sides of a checkpoint."""
    pending = set()
    boundaries = [0]
    for i, item in enumerate(items):
        if item.get("type") == "function_call":
            pending.add(item["call_id"])
        elif item.get("type") == "function_call_output":
            pending.discard(item["call_id"])
        if not pending and item.get("type") != "reasoning":
            boundaries.append(i + 1)
    return boundaries


def cut_to_floor(item, floor=TOOL_OUTPUT_FLOOR):
    """``item`` with its tool result cut to the least the compactor keeps of one (``TOOL_OUTPUT_FLOOR``, or
    ``TOOL_OUTPUT_STUB`` for one the model already acted on when nothing else makes room), marked as cut: the same
    cut of the same result every time. ``item`` itself when there's nothing to cut."""
    output = item.get("output") if item.get("type") == "function_call_output" else None
    if not isinstance(output, str) or len(output) <= floor:
        return item
    return {**item, "output": clip_text(output, floor, CONTEXT_HINT)}


def cut_tool_results(items, excess, count):
    """``items`` with their tool results cut, oldest first, until ``excess`` tokens (as ``count`` counts
    them) are gone, none below ``TOOL_OUTPUT_FLOOR`` characters. Every call keeps its result, marked
    with what was cut; the stored items are untouched."""
    out = list(items)
    for i, item in enumerate(out):
        if excess <= 0:
            break
        output = item.get("output") if item.get("type") == "function_call_output" else None
        if not isinstance(output, str) or len(output) <= TOOL_OUTPUT_FLOOR:
            continue
        cost = count(item)
        # Its share of the characters it may keep, less the room the marker takes.
        marker = len(clip_text(output, TOOL_OUTPUT_FLOOR, CONTEXT_HINT)) - TOOL_OUTPUT_FLOOR
        keep = max(TOOL_OUTPUT_FLOOR, len(output) * (cost - excess) // cost - marker)
        cut = {**item, "output": clip_text(output, keep, CONTEXT_HINT)}
        saved = cost - count(cut)
        if saved > 0:
            out[i] = cut
            excess -= saved
    return out


async def summarize(previous, items, *, model, user_id, user_email, organization_id):
    # Same provider dispatch, credit gate and billing hooks as normal turns.
    from coder.openai_agent import Agent
    from coder.openai_agent.config import AgentConfiguration
    from wss.sender.events import ChatMessageEvent
    from wss.sender.schema import ContentItem

    pieces, errors = [], []

    async def emit(event):
        if isinstance(event, ChatMessageEvent):
            if event.status == "error":
                errors.append(event.message or "its model gave no reason")
            elif event.message:
                pieces.append(event.message)

    agent = await Agent.create(
        emit_message=emit, user_id=user_id, user_email=user_email, organization_id=organization_id,
        config=AgentConfiguration.from_kwargs(model=model, enable_cmd=False, enable_editor=False,
                                              enable_mcp=False,
                                              system_prompt=PROMPTS.summary_prompt(
                                                  target_characters=TARGET_CHARACTERS)),
    )
    try:
        async with asyncio.timeout(120):
            # Each image in the transcript is "(image)", then follows it as itself: its data URI quoted would be
            # read as text, far past any budget.
            content = [ContentItem(type="text", text=json.dumps(
                {"previous_checkpoint": previous, "previous_checkpoint_characters": len(previous),
                 "new_transcript": _without_image_urls(items)}, ensure_ascii=False))]
            # The checkpoint must actually see the images, not just summarize
            # filenames. The chunk's token budget also bounds image count.
            content.extend(ContentItem(type="image_url", image_url=image["image_url"])
                           for image in image_inputs(items))
            await agent({"content_items": content})
        if errors:
            raise ContextBudgetError(f"Context summarization failed ({errors[0]}); original history is preserved.")
        return parse_summary("".join(pieces))
    finally:
        await agent.cleanup()


class CheckpointStore(Protocol):
    """Where one conversation's checkpoint lives. ``load`` gives the pointer
    (``{covered, fingerprint, ...}``, ``{}`` before the first) and the stored SDK
    history; ``read`` the checkpoint's text (``{content, ...}``), ``None`` once a
    person forgot it; ``commit`` saves a summary of ``prefix`` over ``current``
    (what ``read`` gave) and moves the pointer, atomically, raising
    ``CheckpointConflict`` when either changed meanwhile."""

    async def load(self) -> Tuple[Dict[str, Any], List[Any]]: ...

    async def read(self, checkpoint: Dict[str, Any]) -> Optional[Dict[str, Any]]: ...

    async def commit(self, *, previous: Dict[str, Any], prefix: List[Any], summary: Summary,
                     current: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]: ...


class Compactor:
    """A run's ``call_model_input_filter``: the model sees the checkpoint, the
    latest request and the recent tail once the input passes the budget, and
    older history is folded into the checkpoint in bounded chunks. Tool results
    that can't fold yet (the turn's own, the tail's), and once the turn has made
    ``MAX_SUMMARIES`` every one not folded, are cut in the model's view instead
    when they'd pass the hard ceiling (``cut_to_floor``); and when that still
    leaves the call past it, the ones the model already acted on are cut to a
    stub, so a long turn's next call goes on rather than fails. ``notify``
    hears ``compacting`` before the first summary of a call and ``compacted``
    when that call's folding ends, so a watcher can say why the turn is quiet.

    One instance serves one run, whose calls each extend the prompt the call
    before sent (a run's first call, the last run's), which the provider has
    cached; a fold or a cut rewrites that prompt from the item it touches on.
    So a call folds only past the hard ceiling, and a result cut in the view
    stays cut, the same way, for the rest of the run (``cut``)."""

    def __init__(self, store: CheckpointStore, *, model, user_id, user_email=None, organization_id=None,
                 budget=None, notify: Optional[Callable[[str], None]] = None):
        self.store = store
        self.notify = notify
        self.user_id, self.model = user_id, model
        self.user_email, self.organization_id = user_email, organization_id
        self.budget = budget or Budget()
        self.failed = False
        self.summaries = 0
        # The tool results this run cut in the model's view: each call id, and the floor it was cut to.
        self.cut: Dict[str, int] = {}

    async def __call__(self, data):
        # CPU tokenization stays off the event loop.
        return await self.filter(data)

    async def _summarize(self, previous, items):
        return await summarize(previous, items, model=self.model, user_id=self.user_id, user_email=self.user_email,
                               organization_id=self.organization_id)

    def _count(self, value):
        return token_count(value, self.model)

    async def filter(self, data):
        raw = data.model_data.input
        checkpoint, stored = await self.store.load()
        covered = checkpoint.get("covered", 0)
        if covered > len(raw) or (covered and fingerprint(raw[:covered]) != checkpoint["fingerprint"]):
            raise ContextBudgetError("Context checkpoint no longer matches this conversation; history is preserved.")
        # Forgetting removes semantic context, never replays its old source prefix to reconstruct it.
        memory = await self.store.read(checkpoint) if covered else None

        def shaped():
            items = []
            if memory:  # a forgotten checkpoint takes the requests it covered with it
                items.append({"role": "developer", "content": PROMPTS.CHECKPOINT_HEADER + "\n" + memory["content"]})
                # The request whose turn the history in view goes on with stays ahead of it. It changes only with a
                # fold, so a turn that folds nothing extends the view the turn before it left.
                request = next((i for i in range(covered - 1, -1, -1) if raw[i].get("role") == "user"), None)
                if request is not None and (covered == len(raw) or raw[covered].get("role") != "user"):
                    items.append(raw[request])
            return items + [cut_to_floor(item, self.cut[item["call_id"]]) if item.get("call_id") in self.cut else item
                            for item in raw[covered:]]

        # A cut is made from the result as it was, so the same result reads the same in every call of the run.
        self._results = {item["call_id"]: item for item in raw if item.get("type") == "function_call_output"}

        tool_schemas = [{"name": getattr(t, "name", ""), "description": getattr(t, "description", ""),
                         "parameters": getattr(t, "params_json_schema", {})} for t in data.agent.tools]
        overhead = await asyncio.to_thread(self._count, [data.model_data.instructions, tool_schemas])
        overhead += 6000  # output + framing headroom

        async def size(items):
            return overhead + await asyncio.to_thread(self._count, items)

        effective = shaped()
        total = await size(effective)
        compacting = False
        foldable = len(raw)  # nothing is cut before the history is measured
        if total > self.budget.hard:
            try:
                boundaries = safe_boundaries(raw)
                costs = await asyncio.to_thread(lambda: [self._count(item) for item in raw])
                cumulative = [0]
                for cost in costs:
                    cumulative.append(cumulative[-1] + cost)
                # Keep a useful recent tail even when old tool output is huge.
                tail_start = len(raw)
                tail_tokens = 0
                for i in range(len(raw)-1, covered-1, -1):
                    tail_tokens += costs[i]
                    tail_start = i
                    if tail_tokens >= self.budget.recent:
                        break
                # Stored history before the tail folds, up to its last safe boundary.
                foldable = max(i for i in boundaries if i <= min(tail_start, len(stored)))
                cuts = [i for i in boundaries if covered < i <= foldable]
                # Bounded chunks avoid sending an already overflowing history
                # to the summarizer.
                while cuts and total > self.budget.target and self.summaries < MAX_SUMMARIES and not self.failed:
                    end = None
                    for i in cuts:
                        if cumulative[i] - cumulative[covered] > self.budget.chunk:
                            break
                        end = i
                    if end is None:
                        # One call group outgrows the chunk alone: the summarizer reads it with its results cut.
                        end = cuts[0]
                        chunk = await asyncio.to_thread(
                            cut_tool_results, raw[covered:end],
                            cumulative[end] - cumulative[covered] - self.budget.chunk, self._count)
                    else:
                        chunk = raw[covered:end]
                    if not compacting:
                        compacting = True
                        self._notify("compacting")
                    self.summaries += 1
                    summary = await self._summarize(memory["content"] if memory else "", chunk)
                    checkpoint, memory = await self.store.commit(previous=checkpoint, prefix=raw[:end],
                                                                 summary=summary, current=memory)
                    covered = end
                    effective = shaped()
                    total = await size(effective)
                    cuts = [i for i in cuts if i > covered]
            except CheckpointConflict:
                self.failed = True
                return await self.filter(data)  # respect concurrent user edits/deletion immediately
            except Exception:
                self.failed = True  # one failure per turn; no retry storm
                logger.exception("Compaction failed; preserving context for %s", self.user_id)
                # User edits/deletion may have won a CAS while summarizing.
                # Reload on the next turn, never send the rejected summary.
            finally:
                if compacting:
                    self._notify("compacted")
            # What can't fold (this turn's tool results, the recent tail's) is cut instead, in the model's view;
            # once the turn has spent its summaries or one failed, so is everything past the checkpoint, oldest first.
            capped = self.summaries >= MAX_SUMMARIES or self.failed
            start = len(effective) - (len(raw) - (covered if capped else foldable))
            if total > self.budget.hard:
                effective, total = await self._cut(effective, start, total, size)
        if total > self.budget.hard:
            if covered < foldable:
                raise ContextBudgetError("This conversation needs compaction, but a safe checkpoint could not be "
                                         "saved. Its history is intact; retry after resolving the memory or model "
                                         "error.")
            raise ContextBudgetError("The latest messages are too large for the model's context, even with their "
                                     "tool results cut short. The conversation's history is intact; send a shorter "
                                     "message, or ask for less at a time.")
        return ModelInputData(input=effective, instructions=data.model_data.instructions)

    async def _cut(self, items, start, total, size):
        """``items`` with tool results past ``start`` cut to the floor, oldest first: the older ones down to the
        target, as a fold goes, so the calls after this one extend the cut view until the ceiling comes round
        again; the latest call's own results only while still past the ceiling. Before those, a call still past
        it (a long turn whose summaries are spent: the older results alone outgrow the context at their floor)
        has the older ones, which the model already acted on, cut to a stub, down to the target as before."""
        items = list(items)
        latest = len(items)  # where the latest call's group starts: its calls, then their results
        while latest > start and items[latest - 1].get("type") == "function_call_output":
            latest -= 1
        while latest > start and items[latest - 1].get("type") in ("function_call", "reasoning"):
            latest -= 1
        older, newest = range(start, latest), range(latest, len(items))
        passes = ((older, self.budget.target, TOOL_OUTPUT_FLOOR), (older, self.budget.target, TOOL_OUTPUT_STUB),
                  (newest, self.budget.hard, TOOL_OUTPUT_FLOOR))
        for span, goal, floor in passes:
            if floor == TOOL_OUTPUT_STUB and total <= self.budget.hard:
                break
            for i in span:
                if total <= goal:
                    break
                call_id = items[i].get("call_id")
                if items[i].get("type") != "function_call_output" or self.cut.get(call_id, floor + 1) <= floor:
                    continue
                cut = cut_to_floor(self._results.get(call_id, items[i]), floor)
                if cut is not items[i]:
                    total -= await asyncio.to_thread(lambda: self._count(items[i]) - self._count(cut))
                    items[i] = cut
                    self.cut[call_id] = floor
        return items, await size(items)

    def _notify(self, status: str) -> None:
        if self.notify is None:
            return
        try:
            self.notify(status)
        except Exception:
            logger.exception("Compaction status %s wasn't heard", status)


InputFilter = Callable[[Any], Awaitable[Any]]


def chain(*filters: Optional[InputFilter]) -> Optional[InputFilter]:
    """One ``call_model_input_filter`` running ``filters`` in order, each on the input the one before shaped."""
    present = [f for f in filters if f is not None]
    if len(present) <= 1:
        return present[0] if present else None

    async def run(data):
        for each in present:
            data = dataclasses.replace(data, model_data=await each(data))
        return data.model_data

    return run

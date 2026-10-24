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

from coder.openai_agent.output_limits import (
    CONTEXT_HINT, TOOL_OUTPUT_FLOOR, TOOL_OUTPUT_STUB, clip_arguments, clip_text,
)
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
    # provider-specific encrypted compaction format. A call's view folds once it
    # would pass ``hard``, down to ``target``: every fold rewrites the prompt the
    # provider cached, so none happens mid-run before it must. Once a run is
    # over, a conversation past ``settle`` folds down to ``target`` in the
    # background, so the next run starts with room and rarely waits on a summary.
    target: int = 20000
    hard: int = 48000
    chunk: int = 12000
    recent: int = 6000
    settle: int = 32000


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


_CUTTABLE = {"function_call_output": "output", "function_call": "arguments"}


def _cuttable(item):
    """What a cut shortens in ``item``: a tool result's output, a tool call's arguments (a commit's files); else
    None."""
    field = _CUTTABLE.get(item.get("type"))
    return field if field and isinstance(item.get(field), str) else None


def _message(item):
    """A message of the conversation (the person's, a reply, a note), as against a tool call, its result or the
    model's reasoning."""
    return item.get("role") is not None and item.get("type", "message") == "message"


def _cut_key(item):
    # A call and its result share a call id, and each is cut on its own.
    return item.get("type"), item.get("call_id")


def _clipped(item, field, cap):
    text = item[field]
    cut = clip_text(text, cap, CONTEXT_HINT) if field == "output" else clip_arguments(text, cap)
    return {**item, field: cut} if len(cut) < len(text) else item


def cut_to_floor(item, floor=TOOL_OUTPUT_FLOOR):
    """``item`` with its tool result, or its tool call's arguments, cut to the least the compactor keeps of one
    (``TOOL_OUTPUT_FLOOR``, or ``TOOL_OUTPUT_STUB`` for one the model already acted on when nothing else makes room),
    marked as cut: the same cut of the same item every time. ``item`` itself when there's nothing to cut."""
    field = _cuttable(item)
    if field is None or len(item[field]) <= floor:
        return item
    return _clipped(item, field, floor)


def cut_tool_calls(items, excess, count):
    """``items`` with their tool calls' arguments and results cut, oldest first, until ``excess`` tokens (as
    ``count`` counts them) are gone, none below ``TOOL_OUTPUT_FLOOR`` characters. Every call keeps its shape and its
    result, marked with what was cut; the stored items are untouched."""
    out = list(items)
    for i, item in enumerate(out):
        if excess <= 0:
            break
        field = _cuttable(item)
        if field is None or len(item[field]) <= TOOL_OUTPUT_FLOOR:
            continue
        text, cost = item[field], count(item)
        # Its share of the characters it may keep, less the room the marker takes.
        marker = len(clip_text(text, TOOL_OUTPUT_FLOOR, CONTEXT_HINT)) - TOOL_OUTPUT_FLOOR
        cut = _clipped(item, field, max(TOOL_OUTPUT_FLOOR, len(text) * (cost - excess) // cost - marker))
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
    and tool calls' arguments (a commit's files) that can't fold yet (the turn's
    own, the tail's), and once the turn has made ``MAX_SUMMARIES`` every one not
    folded, are cut in the model's view instead when they'd pass the hard
    ceiling (``cut_to_floor``); and when that still leaves the call past it, the
    ones the model already acted on are cut to a stub, and past that the oldest
    are left out of the view (``_leave_out``), so a long turn's next call, and
    every turn after it, goes on rather than fails. ``notify``
    hears ``compacting`` before the first summary of a call and ``compacted``
    when that call's folding ends, so a watcher can say why the turn is quiet.

    One instance serves one run, whose calls each extend the prompt the call
    before sent (a run's first call, the last run's), which the provider has
    cached; a fold or a cut rewrites that prompt from the item it touches on.
    So a call folds only past the hard ceiling, and a call or result cut or left
    out of the view stays so, the same way, for the rest of the run (``cut``,
    ``left_out``). The fold the next run would otherwise wait on happens once
    this one is over (``settle``), off its reply's path."""

    def __init__(self, store: CheckpointStore, *, model, user_id, user_email=None, organization_id=None,
                 budget=None, notify: Optional[Callable[[str], None]] = None):
        self.store = store
        self.notify = notify
        self.user_id, self.model = user_id, model
        self.user_email, self.organization_id = user_email, organization_id
        self.budget = budget or Budget()
        self.failed = False
        self.summaries = 0
        # What every call's view costs beside its history (instructions, tool schemas, output), as the run's last
        # call measured it; None before its first.
        self.overhead: Optional[int] = None
        # The tool calls and results this run cut in the model's view: by ``_cut_key``, its floor and its cut.
        self.cut: Dict[Tuple[Optional[str], Optional[str]], Tuple[int, Dict[str, Any]]] = {}
        # Where in the history this run's view leaves out the older tool calls ("calls") and, past them, the older
        # messages ("messages"): every one before it, past the checkpoint.
        self.left_out = {"calls": 0, "messages": 0}

    async def __call__(self, data):
        # CPU tokenization stays off the event loop.
        return await self.filter(data)

    async def _summarize(self, previous, items):
        return await summarize(previous, items, model=self.model, user_id=self.user_id, user_email=self.user_email,
                               organization_id=self.organization_id)

    def _count(self, value):
        return token_count(value, self.model)

    async def filter(self, data):
        tool_schemas = [{"name": getattr(t, "name", ""), "description": getattr(t, "description", ""),
                         "parameters": getattr(t, "params_json_schema", {})} for t in data.agent.tools]
        self.overhead = await asyncio.to_thread(self._count, [data.model_data.instructions, tool_schemas])
        self.overhead += 6000  # output + framing headroom
        raw = data.model_data.input
        covered, foldable, effective, total = await self._fold(raw, self.budget.hard)
        if total > self.budget.hard:
            # What can't fold (this turn's tool calls and results, the recent tail's) is cut instead, in the model's
            # view; once the turn has spent its summaries or one failed, so is everything past the checkpoint, oldest
            # first.
            capped = self.summaries >= MAX_SUMMARIES or self.failed
            start = len(effective) - (len(raw) - (covered if capped else foldable))
            effective, total = await self._cut(effective, start, total, len(raw))
        if total > self.budget.hard:
            # All that's left is the request the turn answers and its newest call group.
            raise ContextBudgetError("The latest messages are too large for the model's context, even with their "
                                     "tool calls and results cut short. The conversation's history is intact; send a "
                                     "shorter message, or ask for less at a time.")
        return ModelInputData(input=effective, instructions=data.model_data.instructions)

    async def settle(self) -> None:
        """Once the run is over (its reply sent), fold the conversation down to ``target`` when it passes
        ``budget.settle``, so the next turn starts well under the hard ceiling and its calls don't wait on a summary.
        Bounded by ``MAX_SUMMARIES`` of its own: a run that spent its summaries leaves the most to fold. A person's
        edit or a turn that folds first wins, and this stops."""
        if self.overhead is None or self.failed:
            return
        self.cut = {}  # the run's cuts were its own view; the next run starts from the history
        self.summaries = 0
        await self._fold(None, self.budget.settle, settling=True)

    async def _size(self, items):
        return self.overhead + await asyncio.to_thread(self._count, items)

    async def _fold(self, raw, trigger, *, settling=False):
        """The view of ``raw`` (None: the stored history) past the conversation's checkpoint, folding older history
        into it in bounded chunks once the view passes ``trigger``: ``(covered, foldable, view, size)``. A conflict
        folds no more this run (a call's view reloads the checkpoint); a failed summary leaves the history as it was.
        ``settling``: after the run, where nobody watches and nothing reads the view."""
        checkpoint, stored = await self.store.load()
        raw = stored if raw is None else raw
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
            return items + [self.cut.get(_cut_key(item), (None, item))[1] for item in raw[covered:]]

        # A cut is made from the item as it was, so the same call or result reads the same in every call of the run.
        self._originals = {_cut_key(item): item for item in raw if _cuttable(item)}

        effective = shaped()
        total = await self._size(effective)
        compacting = False
        foldable = len(raw)  # nothing is cut before the history is measured
        if total > trigger:
            try:
                boundaries = safe_boundaries(raw)
                costs = await asyncio.to_thread(lambda: [self._count(item) for item in raw])
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
                # More to fold than the summaries left can read whole (what a long turn of big tool calls leaves):
                # they read it with its tool calls and results cut to the floor, so it folds in the summaries a
                # turn has rather than outgrowing them turn after turn.
                reads = raw
                if total - self.budget.target > (MAX_SUMMARIES - self.summaries) * self.budget.chunk:
                    reads = [*raw[:covered], *(cut_to_floor(item) for item in raw[covered:foldable]), *raw[foldable:]]
                    costs[covered:foldable] = await asyncio.to_thread(
                        lambda: [self._count(item) for item in reads[covered:foldable]])
                cumulative = [0]
                for cost in costs:
                    cumulative.append(cumulative[-1] + cost)
                # Bounded chunks avoid sending an already overflowing history
                # to the summarizer.
                while cuts and total > self.budget.target and self.summaries < MAX_SUMMARIES and not self.failed:
                    end = None
                    for i in cuts:
                        if cumulative[i] - cumulative[covered] > self.budget.chunk:
                            break
                        end = i
                    if end is None:
                        # One call group outgrows the chunk alone: the summarizer reads it with its calls and
                        # results cut.
                        end = cuts[0]
                        chunk = await asyncio.to_thread(
                            cut_tool_calls, reads[covered:end],
                            cumulative[end] - cumulative[covered] - self.budget.chunk, self._count)
                    else:
                        chunk = reads[covered:end]
                    if not compacting and not settling:
                        compacting = True
                        self._notify("compacting")
                    self.summaries += 1
                    summary = await self._summarize(memory["content"] if memory else "", chunk)
                    checkpoint, memory = await self.store.commit(previous=checkpoint, prefix=raw[:end],
                                                                 summary=summary, current=memory)
                    covered = end
                    effective = shaped()
                    total = await self._size(effective)
                    cuts = [i for i in cuts if i > covered]
            except CheckpointConflict:
                self.failed = True
                # Respect concurrent user edits/deletion (or a fold another turn made) immediately.
                return (covered, foldable, effective, total) if settling else await self._fold(raw, trigger)
            except Exception:
                self.failed = True  # one failure per turn; no retry storm
                logger.exception("Compaction failed; preserving context for %s", self.user_id)
                # User edits/deletion may have won a CAS while summarizing.
                # Reload on the next turn, never send the rejected summary.
            finally:
                if compacting:
                    self._notify("compacted")
        return covered, foldable, effective, total

    async def _cut(self, items, start, total, history_length):
        """``items`` with tool calls' arguments and tool results past ``start`` cut to the floor, oldest first: the
        older ones down to the target, as a fold goes, so the calls after this one extend the cut view until the
        ceiling comes round again; the latest call group only while still past the ceiling. Before those, a call
        still past it (a long turn whose summaries are spent: the older ones alone outgrow the context at their
        floor) has the older ones, which the model already acted on, cut to a stub, down to the target as before;
        and one past it even so has the oldest left out (``_leave_out``). ``items`` ends with the history's last
        ``history_length`` items."""
        items = list(items)
        latest = len(items)  # where the latest call's group starts: its response (calls and any text), then results
        while latest > start and items[latest - 1].get("type") == "function_call_output":
            latest -= 1
        while latest > start and (items[latest - 1].get("type") in ("function_call", "reasoning") or (
                items[latest - 1].get("type") == "message" and items[latest - 1].get("role") == "assistant")):
            latest -= 1
        marks = [start + b for b in safe_boundaries(items[start:latest])]
        groups = list(zip(marks, marks[1:]))
        out: set = set()
        offset = history_length - len(items)
        # What the run already left out stays out; the rest is cut only where that still passes the ceiling.
        total = await self._leave_out(items, groups, out, total, offset, more=False)
        older, newest = range(start, latest), range(latest, len(items))
        passes = ((older, self.budget.target, TOOL_OUTPUT_FLOOR), (older, self.budget.target, TOOL_OUTPUT_STUB),
                  (newest, self.budget.hard, TOOL_OUTPUT_FLOOR))
        for span, goal, floor in passes:
            if total <= self.budget.hard:
                break
            for i in span:
                if total <= goal:
                    break
                key = _cut_key(items[i])
                if i in out or not _cuttable(items[i]) or self.cut.get(key, (floor + 1,))[0] <= floor:
                    continue
                cut = cut_to_floor(self._originals.get(key, items[i]), floor)
                if cut is not items[i]:
                    total -= await asyncio.to_thread(lambda: self._count(items[i]) - self._count(cut))
                    items[i] = cut
                    self.cut[key] = (floor, cut)
        if total > self.budget.hard:
            await self._leave_out(items, groups, out, total, offset, more=True)
        if out:  # the note stands where the first item left out did
            first = min(out)
            items = [*items[:first], {"role": "developer", "content": PROMPTS.LEFT_OUT_NOTE},
                     *(item for i, item in enumerate(items) if i > first and i not in out)]
        return items, await self._size(items)

    async def _leave_out(self, items, groups, out, total, offset, *, more):
        """Adds to ``out`` the call groups of ``items`` (``groups``: the older ones, oldest first) this run left out
        of the model's view, and with ``more`` the oldest after them, down to the target; returns what the view then
        comes to. A turn that can't fold them (its summaries spent, or one failed) and finds them past the ceiling
        even cut to a stub leaves them out: the backlog a long turn leaves would otherwise fail every turn after it.
        Their tool calls, results and reasoning go first, keeping the conversation's messages; while the view still
        passes the ceiling, those go too, all but the request the turn answers. What's left out stays out for the
        rest of the run (``left_out``, in the history's own indices: an item's is its index here plus ``offset``),
        and the history keeps it all, to fold on a later turn."""
        before, noted = dict(self.left_out), bool(out)
        request = max((i for a, b in groups for i in range(a, b) if items[i].get("role") == "user"), default=None)
        for tier in ("calls", "messages"):
            needed = more and total > self.budget.hard
            for a, b in groups:
                if b + offset > self.left_out[tier] and not (needed and total > self.budget.target):
                    break
                going = [i for i in range(a, b) if i not in out and i != request
                         and (tier == "messages" or not _message(items[i]))]
                total -= await asyncio.to_thread(lambda: sum(self._count(items[i]) for i in going))
                out.update(going)
                self.left_out[tier] = max(self.left_out[tier], b + offset)
        if self.left_out != before:
            logger.error("Compaction couldn't fold %s in time (%d summaries this turn%s): %d of its oldest items "
                         "past the checkpoint are left out of the model's view; its history keeps them",
                         getattr(self.store, "conversation_id", None) or self.user_id, self.summaries,
                         ", one failed" if self.failed else "", len(out))
        if out and not noted:  # the note saying so takes its room in the view
            total += await asyncio.to_thread(self._count, [{"role": "developer", "content": PROMPTS.LEFT_OUT_NOTE}])
        return total

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

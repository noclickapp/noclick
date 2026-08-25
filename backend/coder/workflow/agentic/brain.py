"""
Brain protocol for the agentic workflow builder.

The "brain" is the upstream source of XML commands. In production it is a
streaming LiteLLM call; in harness/test mode it can be replaced with stdio
or a recorded session replay. The protocol is intentionally narrow:

    async for item in brain.step(messages, turn=...):
        if isinstance(item, str):
            ... # raw content chunk
        else:
            ... # final BrainResponse with cost/tokens/non-content

The builder layer owns XML tag filtering, retry-aware text emission,
debug callbacks, and session logging — those are not the brain's concern.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

import litellm

from ..pass_base import (
    build_provider_extra_body,
    extract_streaming_cost,
    is_transient_llm_error as _is_transient_llm_error,
)
from utils.cancellation import (
    CancelledByUser,
    aclose_quietly,
    check_cancelled,
)
from .config import AgenticBuilderConfig

logger = logging.getLogger(__name__)


def _scope_cancelled() -> bool:
    """True if the active CancelScope (bound via contextvar) is cancelled."""
    from utils.cancellation import current_scope
    s = current_scope()
    return s is not None and s.cancelled


@dataclass
class BrainResponse:
    """Final yield of a brain step — totals after all chunks are consumed."""
    text: str
    cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    # Reasoning content / tool_calls / etc. captured from delta but not in text.
    non_content_fields: Dict[str, str] = field(default_factory=dict)
    # The model OpenRouter actually served. Logged so SessionViewer can show
    # fallback hops (primary vs configured fallback).
    model: Optional[str] = None
    # Provider is rarely populated inline (litellm drops it), so we ship the
    # generation_id alongside and resolve provider on demand in the
    # SessionViewer handler when the eventual-consistency window has passed.
    provider: Optional[str] = None
    generation_id: Optional[str] = None
    # Seconds from request issued to the first content token received. None
    # for the no-yield path (raised before any chunks).
    ttft_s: Optional[float] = None


@runtime_checkable
class BrainProtocol(Protocol):
    """The brain produces XML commands one chunk at a time.

    Implementations stream raw provider content as `str` items, then yield a
    single `BrainResponse` as the final item. The builder treats the response
    as authoritative for token/cost accounting.
    """

    async def step(
        self,
        messages: List[Dict[str, str]],
        *,
        turn: int,
        generation_id: str,
        workflow_id: Optional[str] = None,
    ) -> AsyncIterator[Any]:  # yields str | BrainResponse
        ...


# ── LiteLLM-backed brain (production) ────────────────────────────────────


class LiteLLMBrain:
    """Production brain: streams `litellm.acompletion` with transient retries.

    Retry policy: up to `max_attempts` attempts on transient errors before
    any chunk has been yielded. Once a chunk is yielded, retrying would
    duplicate output on the consumer side, so subsequent failures surface
    as-is.

    Fallback model: if `fallback_model` is set and the primary's attempts
    are exhausted (still pre-yield), the loop hops once to the fallback
    model + its own provider_order for a final try. Same has_yielded
    guard applies — a mid-stream failure on the fallback raises.
    """

    def __init__(
        self,
        model: str,
        *,
        temperature: float = 0.3,
        timeout: int = 120,
        provider_order: Optional[List[str]] = None,
        provider_sort: Optional[str] = None,
        max_attempts: int = 3,
        base_backoff_s: float = 1.0,
        fallback_model: Optional[str] = None,
        fallback_provider_order: Optional[List[str]] = None,
    ):
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.provider_order = provider_order
        self.provider_sort = provider_sort
        self.max_attempts = max_attempts
        self.base_backoff_s = base_backoff_s
        self.fallback_model = fallback_model
        self.fallback_provider_order = fallback_provider_order

    async def step(
        self,
        messages: List[Dict[str, str]],
        *,
        turn: int,
        generation_id: str,
        workflow_id: Optional[str] = None,
    ) -> AsyncIterator[Any]:
        # Phase 0: primary model. Phase 1 (only if configured): fallback.
        # Each phase runs its own attempt loop with the same transient
        # retry semantics.
        active_model = self.model
        active_provider_order = self.provider_order
        on_fallback = False
        extra_body = build_provider_extra_body(active_model, active_provider_order, self.provider_sort)

        chunks: List[Any] = []
        full_response = ""
        non_content_fields: Dict[str, str] = {}
        has_yielded = False
        attempt = 0
        # TTFT: measured on the *successful* attempt only — a transient retry
        # resets the clock so the value reflects what the user actually saw.
        request_start: Optional[float] = None
        first_token_time: Optional[float] = None

        while True:
            attempt += 1
            response = None
            check_cancelled()
            try:
                request_start = time.time()
                first_token_time = None
                response = await litellm.acompletion(
                    model=active_model,
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                    temperature=self.temperature,
                    timeout=self.timeout,
                    **({"extra_body": extra_body} if extra_body else {}),
                )
                async for chunk in response:
                    if _scope_cancelled():
                        await aclose_quietly(response)
                        raise CancelledByUser()
                    chunks.append(chunk)
                    delta = chunk.choices[0].delta
                    for attr in ('reasoning_content', 'reasoning', 'tool_calls'):
                        val = getattr(delta, attr, None)
                        if val:
                            non_content_fields.setdefault(attr, '')
                            non_content_fields[attr] += str(val)
                    content = getattr(delta, 'content', None) or ''
                    if not content:
                        continue
                    if first_token_time is None:
                        first_token_time = time.time()
                    full_response += content
                    has_yielded = True
                    yield content
                break
            except CancelledByUser:
                await aclose_quietly(response)
                raise
            except Exception as e:
                await aclose_quietly(response)
                if not _is_transient_llm_error(e) or has_yielded:
                    raise
                if attempt >= self.max_attempts:
                    # Primary exhausted — hop to the fallback model if
                    # configured and not already on it. Fallback gets
                    # its own attempt budget; mid-stream failures on
                    # the fallback still raise (has_yielded guard).
                    if self.fallback_model and not on_fallback:
                        logger.warning(
                            f"[LiteLLMBrain] primary {self.model} exhausted after "
                            f"{attempt} attempts; falling back to {self.fallback_model} "
                            f"({type(e).__name__}: {e})"
                        )
                        active_model = self.fallback_model
                        active_provider_order = self.fallback_provider_order
                        on_fallback = True
                        extra_body = build_provider_extra_body(active_model, active_provider_order, self.provider_sort)
                        attempt = 0
                        chunks = []
                        full_response = ""
                        non_content_fields = {}
                        continue
                    raise
                backoff = self.base_backoff_s * (2 ** (attempt - 1))
                logger.warning(
                    f"[LiteLLMBrain] transient error on {active_model} "
                    f"(attempt {attempt}/{self.max_attempts}, retrying in {backoff:.1f}s): "
                    f"{type(e).__name__}: {e}"
                )
                # Reset accumulators — any chunk we kept came from the failed attempt.
                chunks = []
                full_response = ""
                non_content_fields = {}
                await asyncio.sleep(backoff)

        cost_result = extract_streaming_cost(chunks, messages)
        ttft_s = (
            (first_token_time - request_start)
            if first_token_time is not None and request_start is not None
            else None
        )
        yield BrainResponse(
            text=full_response,
            cost=cost_result.cost,
            input_tokens=cost_result.input_tokens,
            output_tokens=cost_result.output_tokens,
            total_tokens=cost_result.total_tokens,
            non_content_fields=non_content_fields,
            model=cost_result.model or active_model,
            provider=cost_result.provider,
            generation_id=cost_result.generation_id,
            ttft_s=ttft_s,
        )


# ── Stdio-backed brain (harness / external driver) ───────────────────────


class StdioBrain:
    """Brain that delegates each turn to an external process over stdio.

    Frame format (one JSON object per line):

      driver  → harness:  {"type":"turn_request","turn":N,"generation_id":...,
                           "workflow_id":...,"model":...,"messages":[...]}
      harness → driver :  {"type":"turn_response","content":"<add_node ...>...</add_node><done/>"}

    The driver returns the entire turn's text in one frame; the brain emits
    it as a single `str` item followed by a zero-cost `BrainResponse`. This
    keeps the consumer (`_stream_brain`) blind to whether it is talking to a
    real LLM or a stdio harness.
    """

    def __init__(
        self,
        model: str = "stdio",
        *,
        reader: Optional[asyncio.StreamReader] = None,
        writer_stream=None,
    ):
        self.model = model
        self._reader = reader
        # Plain sync stream by default — driver writes are line-oriented and small.
        self._writer = writer_stream or sys.stdout

    async def _read_line(self) -> str:
        if self._reader is not None:
            line = await self._reader.readline()
            return line.decode('utf-8') if isinstance(line, bytes) else line
        # Fallback: blocking stdin read on a worker thread so we don't stall the loop.
        return await asyncio.to_thread(sys.stdin.readline)

    def _write_frame(self, frame: Dict[str, Any]) -> None:
        line = json.dumps(frame, ensure_ascii=False)
        self._writer.write(line + "\n")
        self._writer.flush()

    async def step(
        self,
        messages: List[Dict[str, str]],
        *,
        turn: int,
        generation_id: str,
        workflow_id: Optional[str] = None,
    ) -> AsyncIterator[Any]:
        self._write_frame({
            "type": "turn_request",
            "turn": turn,
            "generation_id": generation_id,
            "workflow_id": workflow_id,
            "model": self.model,
            "messages": messages,
        })

        while True:
            line = await self._read_line()
            if not line:
                raise RuntimeError("[StdioBrain] EOF on stdin while awaiting turn_response")
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"[StdioBrain] invalid JSON frame: {e}: {line!r}")
            if frame.get("type") != "turn_response":
                # Allow forward-compatible auxiliary frames (e.g. "ping") without breaking.
                continue
            content = frame.get("content", "")
            break

        if content:
            yield content

        yield BrainResponse(text=content)


# ── Factory ──────────────────────────────────────────────────────────────


def make_default_brain(config: AgenticBuilderConfig) -> BrainProtocol:
    """Construct the production brain from an AgenticBuilderConfig."""
    return LiteLLMBrain(
        model=config.brain_model,
        temperature=config.brain_temperature,
        timeout=config.brain_timeout,
        provider_order=config.brain_provider_order,
        provider_sort=config.brain_provider_sort,
        fallback_model=config.brain_fallback_model,
        fallback_provider_order=config.brain_fallback_provider_order,
    )

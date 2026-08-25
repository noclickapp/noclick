"""LitellmModel subclass that captures provider-reported cost in-band.

OpenRouter returns the exact cost of every call on the final streaming chunk's
``usage.cost`` (when we send ``extra_body={"usage": {"include": True}}`` and
``stream_options.include_usage=True``). The SDK's stock ``LitellmModel``
transforms the LiteLLM response into its own ``ModelResponse`` before invoking
lifecycle hooks — that transformation builds a fresh SDK ``Usage`` object with
token fields only (no ``cost``) and strips ``_hidden_params``, so by the time
``BillingHooks.on_llm_end`` runs, every trace of the provider-reported cost is
gone.

An out-of-band callback and timeout races against the SDK's response
transformation: the queued callback may not run before billing reads the
result, silently losing provider-reported cost. In-band capture removes that
delivery race.

This subclass moves cost capture into the same call path as the response:
intercept the raw LiteLLM result inside ``_fetch_response``, snag
``usage.cost`` before the SDK transformation runs, stash it on a per-call slot
on the model instance. ``BillingHooks.on_llm_end`` reads the slot directly —
no callback, no contextvar, no timeout.

Streaming path: ``_fetch_response(stream=True)`` returns a
``(Response, CustomStreamWrapper)`` tuple that the SDK's
``ChatCmplStreamHandler.handle_stream`` consumes via ``async for``. We wrap
the wrapper with ``_StreamCostInterceptor``, which yields each chunk
unchanged but observes ``chunk.usage.cost`` as it flows (OpenRouter emits it
on the final usage-bearing chunk; we update the slot every time a chunk
carries usage to be robust to providers that split it).

Non-streaming path: ``_fetch_response(stream=False)`` returns an assembled
``litellm.types.utils.ModelResponse`` synchronously — we read ``usage.cost``
right off it.

Concurrency: LLM calls inside a single ``Runner.run_streamed`` are
sequential (the SDK awaits each turn), so a single per-instance slot is
safe. The slot is reset at the START of every ``_fetch_response`` so turn
N never reads turn N-1's stale value.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Optional, Tuple

from agents.extensions.models.litellm_model import LitellmModel


def extract_cost_from_response(response_obj: Any) -> Tuple[Optional[float], bool]:
    """Read provider-reported cost from a LiteLLM response or stream chunk.

    Returns ``(cost, reported)``. ``reported`` is True iff the provider
    surfaced a cost field at all — including an explicit ``0`` (so a
    ``:free`` model's reported $0 is recorded as $0 rather than mistaken
    for "no cost data" and guessed from a pricing table).

    Sources, in priority order:

      1. ``response.usage.cost`` — the OpenRouter streaming path; also
         present on assembled non-streaming responses.
      2. ``response._hidden_params["response_cost"]`` — LiteLLM's
         standardized cost field.
      3. ``response._hidden_params["additional_headers"]
         ["llm_provider-x-litellm-response-cost"]`` — OpenRouter's
         non-streaming HTTP cost header.
    """
    if response_obj is None:
        return None, False
    usage = getattr(response_obj, "usage", None)
    if usage is not None:
        cost = getattr(usage, "cost", None)
        if cost is None and isinstance(usage, dict):
            cost = usage.get("cost")
        if cost is not None:
            return float(cost), True
    hidden = getattr(response_obj, "_hidden_params", None) or {}
    cost = hidden.get("response_cost")
    if cost is not None:
        return float(cost), True
    headers = hidden.get("additional_headers") or {}
    cost = headers.get("llm_provider-x-litellm-response-cost")
    if cost is not None:
        return float(cost), True
    return None, False


class _StreamCostInterceptor:
    """Proxy iterator that yields chunks unchanged and observes cost in flight.

    OpenRouter emits ``usage`` (with ``cost``) on a single chunk near the end
    of the stream. We update the model's slot on every chunk that carries
    usage data so a provider that splits or repeats usage chunks can't drop
    the cost on the floor. The SDK's stream handler is duck-typed (does
    ``async for chunk in stream``), so this proxy needs only ``__aiter__`` /
    ``__anext__``.
    """

    __slots__ = ("_inner", "_model", "_iter")

    def __init__(self, inner: Any, model: "CostCapturingLitellmModel") -> None:
        self._inner = inner
        self._model = model
        self._iter: Optional[AsyncIterator[Any]] = None

    def __aiter__(self) -> "_StreamCostInterceptor":
        self._iter = self._inner.__aiter__()
        return self

    async def __anext__(self) -> Any:
        assert self._iter is not None, "__aiter__ must be called before __anext__"
        chunk = await self._iter.__anext__()
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            cost, reported = extract_cost_from_response(chunk)
            if reported:
                self._model._call_cost = cost
                self._model._call_cost_reported = True
        return chunk



def _is_empty_assistant_message(item: Any) -> bool:
    """An assistant turn that says nothing.

    Models routinely emit a content-free assistant message alongside a tool
    call. It carries no information, and on the Chat Completions wire it is
    actively harmful: the API requires the tool messages answering an
    assistant's ``tool_calls`` to IMMEDIATELY follow it, and this empty turn
    lands in between. The provider then reports the call id as unanswered:

        An assistant message with 'tool_calls' must be followed by tool
        messages responding to each 'tool_call_id'

    which surfaces to users as a misleading "provider outage, please retry".
    """
    if not isinstance(item, dict) or item.get("role") != "assistant":
        return False
    # Never drop a turn that carries tool calls — that is the message the tool
    # outputs are answering.
    if item.get("tool_calls") or item.get("type") == "function_call":
        return False

    content = item.get("content")
    if content is None or content == "":
        return True
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        # Responses-API shape: [{"type": "output_text", "text": ""}]
        return all(
            isinstance(part, dict) and not str(part.get("text") or "").strip()
            for part in content
        )
    return False


def strip_empty_assistant_messages(items: Any) -> Any:
    """Drop content-free assistant turns from a model input list.

    Deliberately narrow: only assistant messages, only when they carry neither
    text nor tool calls. Anything unexpected passes through untouched — this
    runs on every request, so it must never be able to eat real content.
    """
    if not isinstance(items, list):
        return items
    cleaned = [i for i in items if not _is_empty_assistant_message(i)]
    return cleaned if len(cleaned) != len(items) else items


class CostCapturingLitellmModel(LitellmModel):
    """``LitellmModel`` that exposes provider-reported cost via ``last_call_cost``.

    Read it immediately after the LLM call completes (i.e. inside
    ``on_llm_end``). The slot is reset at the start of every
    ``_fetch_response`` so a turn never sees a previous turn's value. If the
    provider didn't report cost, ``last_call_cost_reported`` is ``False`` and
    ``last_call_cost`` is ``None`` — the caller decides what to do (fall back
    to a pricing-table lookup, record $0, alert).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._call_cost: Optional[float] = None
        self._call_cost_reported: bool = False

    @property
    def last_call_cost(self) -> Optional[float]:
        return self._call_cost

    @property
    def last_call_cost_reported(self) -> bool:
        return self._call_cost_reported

    async def _fetch_response(self, *args: Any, stream: bool = False, **kwargs: Any) -> Any:
        self._call_cost = None
        self._call_cost_reported = False

        # `input` is positional arg 2 (after system_instructions) or a kwarg.
        # Cleaned here because this is the one place every model request passes
        # through, so the fix covers the in-run list as well as anything
        # reloaded from a persisted session.
        if "input" in kwargs:
            kwargs["input"] = strip_empty_assistant_messages(kwargs["input"])
        elif len(args) >= 2:
            args = (args[0], strip_empty_assistant_messages(args[1]), *args[2:])

        result = await super()._fetch_response(*args, stream=stream, **kwargs)

        if not stream:
            cost, reported = extract_cost_from_response(result)
            self._call_cost = cost
            self._call_cost_reported = reported
            return result

        response, raw_stream = result
        return response, _StreamCostInterceptor(raw_stream, self)

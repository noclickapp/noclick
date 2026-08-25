"""Unit tests for Perplexity platform-keyed (credential-less) usage billing.

Mirrors test_exa_platform_billing.py with Perplexity's two cost modes: the
chat-completions ops read in-band usage.cost.total_cost (hard error if absent),
while the Search API bills the flat published per-request price. Verifies the
pre-flight gate ordering, event shape (markup + credit-step rounding,
user_resource=False, org for organization attribution policy), BYOK no-op, fail-loud paths, the
agent-tool seam, and schema-flag ↔ metered-set parity. No I/O — billing sink
and HTTP are patched.
"""
from __future__ import annotations

import typing
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from billing.exceptions import InsufficientBalanceError
from billing.markup import (
    PLATFORM_MIN_MARKUP,
    apply_perplexity_markup,
    round_up_to_credit_step,
)
from billing.pricing import PERPLEXITY_SEARCH_REQUEST_PRICE
from billing.usage_tracker import usage_tracker
from nodes.perplexity_node import (
    PLATFORM_METERED_OPERATIONS,
    PerplexityConfig,
    PerplexityNode,
    PerplexityNodeConfig,
)

# asyncio_mode = auto (pytest.ini)

_USER = str(uuid.uuid4())
_ORG = str(uuid.uuid4())


def _node(config: dict, user_id=_USER, organization_id=_ORG) -> PerplexityNode:
    node = object.__new__(PerplexityNode)
    node.node_id = "node-1"
    node.user_id = user_id
    node.organization_id = organization_id
    node.sio = None
    node.sid = None
    node._config = PerplexityNodeConfig.model_validate(config)
    return node


def _chat_config(credentials: dict | None = None) -> dict:
    cfg: dict = {"config": {"operation": "chat_completion", "prompt": "why is the sky blue"}}
    if credentials:
        cfg["credentials"] = credentials
    return cfg


def _chat_success(total_cost: float | None = 0.008) -> dict:
    usage: dict = {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60}
    if total_cost is not None:
        usage["cost"] = {
            "input_tokens_cost": 0.001,
            "output_tokens_cost": 0.002,
            "request_cost": 0.005,
            "total_cost": total_cost,
        }
    return {
        "status": "success",
        "action": "chat_completion",
        "data": {"choices": [], "usage": usage},
        "status_code": 200,
        "timing_ms": {"api_request": 1.0},
    }


def _search_success() -> dict:
    # The Search API response has NO usage/cost object.
    return {
        "status": "success",
        "action": "search",
        "data": {"results": [], "id": "req-1"},
        "status_code": 200,
        "timing_ms": {"api_request": 1.0},
    }


def _wire(monkeypatch, response: dict, env_key: str | None = "platform-key"):
    gate = AsyncMock()
    sink = AsyncMock()
    request = AsyncMock(return_value=response)
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", gate)
    monkeypatch.setattr(usage_tracker, "track_usage_event", sink)
    monkeypatch.setattr("nodes.perplexity_node._perplexity_request", request)
    if env_key is None:
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    else:
        monkeypatch.setenv("PERPLEXITY_API_KEY", env_key)
    return gate, sink, request


# ── platform-keyed execute paths ─────────────────────────────────────────────


async def test_chat_bills_in_band_usage_cost(monkeypatch):
    gate, sink, request = _wire(monkeypatch, _chat_success(0.008))
    result = await _node(_chat_config()).execute({})

    assert result["status"] == "success"
    assert request.await_args.args[0] == "platform-key"
    gate.assert_awaited_once()
    assert gate.await_args.kwargs["surface"] == "perplexity"
    assert gate.await_args.kwargs["user_resource"] is False

    event = sink.await_args.args[0]
    assert event.total_cost == round_up_to_credit_step(
        Decimal("0.008") * PLATFORM_MIN_MARKUP
    )
    assert event.usage_subtype == "perplexity/api"
    assert event.user_resource is False
    assert event.organization_id == _ORG
    assert event.metadata["cost_source"] == "usage_cost"
    assert event.metadata["raw_cost_usd"] == 0.008


async def test_search_bills_flat_request_price(monkeypatch):
    _, sink, _ = _wire(monkeypatch, _search_success())
    config = {"config": {"operation": "search", "query": "ai agents"}}
    result = await _node(config).execute({})

    assert result["status"] == "success"
    event = sink.await_args.args[0]
    assert event.total_cost == round_up_to_credit_step(
        apply_perplexity_markup(PERPLEXITY_SEARCH_REQUEST_PRICE)
    )
    assert event.metadata["cost_source"] == "flat_search"
    assert event.metadata["raw_cost_usd"] == float(PERPLEXITY_SEARCH_REQUEST_PRICE)


async def test_gate_runs_before_api_call(monkeypatch):
    gate, sink, request = _wire(monkeypatch, _chat_success())
    gate.side_effect = InsufficientBalanceError("out of credits")

    with pytest.raises(InsufficientBalanceError):
        await _node(_chat_config()).execute({})
    request.assert_not_awaited()
    sink.assert_not_awaited()


async def test_byok_uses_user_key_no_gate_no_event(monkeypatch):
    gate, sink, request = _wire(monkeypatch, _chat_success())
    result = await _node(_chat_config({"api_key": "user-key"})).execute({})

    assert result["status"] == "success"
    assert request.await_args.args[0] == "user-key"
    gate.assert_not_awaited()
    sink.assert_not_awaited()


async def test_chat_missing_usage_cost_fails_loud(monkeypatch):
    _, sink, _ = _wire(monkeypatch, _chat_success(total_cost=None))

    with pytest.raises(ValueError, match="usage.cost"):
        await _node(_chat_config()).execute({})
    sink.assert_not_awaited()


async def test_api_error_books_nothing(monkeypatch):
    error = {"status": "error", "action": "chat_completion", "error": "boom", "status_code": 500}
    _, sink, _ = _wire(monkeypatch, error)

    result = await _node(_chat_config()).execute({})
    assert result["status"] == "error"
    sink.assert_not_awaited()


async def test_missing_platform_key_raises(monkeypatch):
    _, _, request = _wire(monkeypatch, _chat_success(), env_key=None)

    with pytest.raises(RuntimeError, match="PERPLEXITY_API_KEY"):
        await _node(_chat_config()).execute({})
    request.assert_not_awaited()


async def test_non_metered_op_still_requires_credentials(monkeypatch):
    _wire(monkeypatch, _chat_success())
    config = {"config": {"operation": "create_async_completion", "prompt": "x", "model": "sonar-deep-research"}}

    with pytest.raises(ValueError, match="Credentials are required"):
        await _node(config).execute({})


# ── node_op tool path (provider-wired into an agent, no credential) ──────────


async def test_run_node_operation_platform_bills(monkeypatch):
    from nodes.core.run_op import run_node_operation

    gate, sink, request = _wire(monkeypatch, _chat_success(0.004))
    result = await run_node_operation(
        node_type="automation-perplexity",
        operation="chat_completion",
        arguments={"prompt": "hello"},
        user_id=_USER,
        organization_id=_ORG,
    )

    assert result["status"] == "success"
    assert request.await_args.args[0] == "platform-key"
    gate.assert_awaited_once()
    event = sink.await_args.args[0]
    assert event.usage_subtype == "perplexity/api"
    assert event.total_cost == round_up_to_credit_step(
        Decimal("0.004") * PLATFORM_MIN_MARKUP
    )


# ── schema-flag parity ───────────────────────────────────────────────────────


def test_credentials_optional_flag_matches_metered_set():
    """x-credentials-optional ops must be exactly the metered set — a flagged-
    but-unmetered op advertises 'no credential needed' then fails at runtime;
    a metered-but-unflagged op is unreachable."""
    union = typing.get_args(PerplexityConfig)[0]
    flagged = set()
    for member in typing.get_args(union):
        extra = (member.model_config or {}).get("json_schema_extra") or {}
        if extra.get("x-credentials-optional") is True:
            flagged.add(member.model_fields["operation"].default)
    assert flagged == set(PLATFORM_METERED_OPERATIONS)

"""The coordinator reuses Exa execution and billing, returning bounded sources."""

from unittest.mock import AsyncMock

import pytest

from billing.exceptions import InsufficientBalanceError
from billing.usage_tracker import usage_tracker
from coder.coordinator.tools import CoordinatorTools
from tests.mocks.mock_asyncpg import MockNativePool

USER = "11111111-1111-1111-1111-111111111111"
ORG = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def search(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "test-search-key")
    gate = AsyncMock()
    bill = AsyncMock()
    http = AsyncMock(return_value={"status": "success", "action": "search", "data": {
        "results": [{"title": "Source", "url": "https://example.org/article", "publishedDate": "2026-09-20",
                     "text": "Page content " * 1000, "author": "Author"}] * 10,
        "costDollars": {"total": 0.005},
    }})
    monkeypatch.setattr(usage_tracker, "enforce_credit_gate", gate)
    monkeypatch.setattr(usage_tracker, "track_usage_event", bill)
    monkeypatch.setattr("nodes.exa_node._exa_request", http)
    monkeypatch.setattr("coder.coordinator.tools.record_tool_call", lambda **kw: None)
    tools = CoordinatorTools(pool=MockNativePool(), sio=None, user_id=USER, organization_id=ORG,
                             conversation_id=f"coordinator:{USER}")
    return tools, gate, bill, http


async def test_search_keeps_citations_caps_results_and_bills_account(search):
    tools, gate, bill, http = search
    result = await tools.execute("web_search", {"query": "Current agent harnesses", "num_results": 3,
                                                "domains": ["example.org"]})
    assert result["success"] is True and result["provider"] == "exa"
    assert len(result["results"]) == 3 and len(result["results"][0]["text"]) == 2500
    assert result["results"][0]["url"] == "https://example.org/article"
    assert result["results"][0]["published_at"] == "2026-09-20"
    assert gate.call_args.args == (USER,)
    assert gate.call_args.kwargs["organization_id"] == ORG
    assert http.call_args.args[0] == "test-search-key"
    assert http.call_args.kwargs["json_body"]["includeDomains"] == ["example.org"]
    bill.assert_awaited_once()
    assert bill.call_args.args[0].usage_subtype == "exa/search_api"
    assert bill.call_args.args[0].user_id == USER


async def test_search_credit_failure_stops_before_provider(search):
    tools, gate, bill, http = search
    gate.side_effect = InsufficientBalanceError("Insufficient credits")
    result = await tools.execute("web_search", {"query": "news"})
    assert result["success"] is False and "credits" in result["error"]
    http.assert_not_awaited()
    bill.assert_not_awaited()


async def test_search_provider_failure_is_not_reported_as_empty_success(search):
    tools, _, _, http = search
    http.return_value = {"status": "error", "error": "Search unavailable"}
    assert await tools.execute("web_search", {"query": "news"}) == {"success": False, "error": "Search unavailable"}


@pytest.mark.parametrize("args", [{"query": " "}, {"query": "x" * 2001}, {"query": "x", "num_results": 9},
                                  {"query": "x", "num_results": True}, {"query": "x", "domains": ["https://example.org"]}])
async def test_invalid_search_arguments_do_not_spend_credits(search, args):
    tools, gate, _, http = search
    assert (await tools.execute("web_search", args))["success"] is False
    gate.assert_not_awaited()
    http.assert_not_awaited()

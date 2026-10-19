"""Stripe's connection evidence through its real dropdown loader.

A key Stripe refuses must read as refused, in Stripe's own words: its customer
list answering 401 used to come back as an empty list, which evidence counts as
a working account with no customers yet ("The provider answered with your
customers" for a made-up ``sk_test_`` key).
"""

import httpx
import pytest

import nodes.stripe_node as stripe_node
from nodes.core import connection_evidence as ce

FAKE_KEY = "sk_test_" + "x" * 24
# Stripe's own answer to a key it doesn't know.
INVALID_KEY = {"error": {"message": "Invalid API Key provided: sk_test_********************xxxx",
                         "type": "invalid_request_error"}}


def _stripe_answers(monkeypatch, status: int, body: dict) -> list:
    """Every request the Stripe node makes is answered with ``status`` and ``body``; the requests it made."""
    seen: list = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    real = httpx.AsyncClient
    monkeypatch.setattr(stripe_node.httpx, "AsyncClient",
                        lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(answer)}))
    return seen


async def _evidence() -> ce.EvidenceResult:
    return await ce.collect_evidence(node_type="automation-stripe", user_id="u1",
                                     credential_data={"api_key": FAKE_KEY})


async def test_a_key_stripe_refuses_is_reported_refused_in_stripes_words(monkeypatch):
    seen = _stripe_answers(monkeypatch, 401, INVALID_KEY)
    result = await _evidence()
    assert [str(r.url) for r in seen] == [f"{stripe_node.STRIPE_API_BASE}/customers?limit=100"]
    assert result.reachable is False
    assert "Invalid API Key provided" in result.error
    assert result.hint and "rejected" in result.hint


async def test_a_restricted_key_without_the_permission_is_refused(monkeypatch):
    _stripe_answers(monkeypatch, 403, {"error": {
        "message": "The provided key 'rk_test_***abc' does not have the required permissions for this endpoint.",
        "type": "invalid_request_error"}})
    result = await _evidence()
    assert result.reachable is False
    assert "does not have the required permissions" in result.error


async def test_a_stripe_outage_cannot_judge_the_key(monkeypatch):
    _stripe_answers(monkeypatch, 500, {"error": {"message": "An unknown error occurred", "type": "api_error"}})
    assert (await _evidence()).reachable is None


async def test_a_key_stripe_takes_shows_its_customers(monkeypatch):
    _stripe_answers(monkeypatch, 200, {"object": "list", "has_more": False, "data": [
        {"id": "cus_1", "email": "ada@example.com"}, {"id": "cus_2", "name": "Grace"}]})
    result = await _evidence()
    assert result.reachable is True
    assert [(s.label, s.value) for s in result.samples] == [
        ("ada@example.com (cus_1)", "cus_1"), ("Grace (cus_2)", "cus_2")]


async def test_the_dropdown_says_what_stripe_said(monkeypatch):
    _stripe_answers(monkeypatch, 401, INVALID_KEY)
    with pytest.raises(ValueError, match=r"Invalid API Key provided.*\(HTTP 401\)"):
        await stripe_node.StripeNode.load_field_options("customer_id", {"api_key": FAKE_KEY})

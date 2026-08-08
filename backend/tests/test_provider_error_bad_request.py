"""A 400 is never an outage.

"Provider returned error" is OpenRouter's WRAPPER, not a diagnosis: it wraps a
genuine upstream 5xx and a malformed request we sent, identically. Matching it
blind told users a broken request was a transient provider outage and to retry.

That is not a cosmetic problem. Every agent that called a tool was failing on a
400, and because the message pointed at OpenRouter, the failure went unnoticed —
the classification is what hid it.
"""

from __future__ import annotations

import pytest

from nodes.agent.provider_errors import classify_provider_error

WRAPPER = '{{"error":{{"message":"Provider returned error","code":{code},"metadata":{{"raw":"{raw}"}}}}}}'


def _kind(text: str):
    result = classify_provider_error(text)
    return getattr(result, "kind", None)


def test_the_real_failure_is_reported_as_our_bug():
    """The exact error that broke every tool-calling agent."""
    text = WRAPPER.format(
        code=400,
        raw="An assistant message with 'tool_calls' must be followed by tool messages",
    )
    assert _kind(text) == "bad_request"


@pytest.mark.parametrize("code", [400, 422])
def test_request_errors_are_not_outages(code):
    assert _kind(WRAPPER.format(code=code, raw="bad")) == "bad_request"


@pytest.mark.parametrize("code", [500, 502, 503])
def test_genuine_upstream_failures_are_still_outages(code):
    """The narrowing must not cost us the case the rule was written for."""
    assert _kind(WRAPPER.format(code=code, raw="upstream died")) == "provider_outage"


def test_rate_limiting_says_slow_down_not_retry():
    """429 was landing on provider_outage, whose advice is "retry" — the exact
    wrong remedy. The rate_limited copy already existed with nothing routing
    to it."""
    assert _kind(WRAPPER.format(code=429, raw="too many requests")) == "rate_limited"


def test_credential_problems_keep_their_own_diagnosis():
    """401/403 must not be swallowed by a blanket 4xx rule — "your request was
    malformed" would send someone to the wrong fix entirely."""
    assert _kind('{"error":{"message":"No auth credentials found","code":401}}') == "invalid_key"


def test_the_bad_request_message_does_not_tell_people_to_retry():
    """Retrying a malformed request just fails again; saying so wastes the user's
    time and hides the bug."""
    from nodes.agent.provider_errors import action_for_error_text  # noqa: F401

    text = WRAPPER.format(code=400, raw="bad")
    result = classify_provider_error(text)
    message = getattr(result, "message", "") or ""
    assert "retry" not in message.lower() or "will not help" in message.lower()
    assert "outage" not in message.lower()

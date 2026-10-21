"""The monthly spending cap's refusal, as every surface that relays a stopped run reads it.

- ``billing.exceptions.spend_cap_message`` is its only mint and ``match_spend_cap`` its only recognizer; it
  names the cap and when it resets, says where it's raised, and never says "credits".
- ``provider_errors`` reads it as NoClick's own (kind ``spend_cap``, its words kept whole, a "Raise the cap"
  button that opens the settings, never a purchase), on every node type.
- The schedule breaker treats it like credit exhaustion: a billing state, never a broken workflow.
- An account no person has claimed yet holds its cap at nothing: ``unclaimed_message`` is that refusal's only mint,
  read as the cap's by every surface that reads the cap's (``match_spend_cap``), and told apart by ``match_unclaimed``.
"""

import pathlib
import re

import pytest

from billing.exceptions import (
    AccountUnclaimed, InsufficientBalanceError, SpendCapReached, match_insufficient_credits, match_spend_cap,
    match_spend_refusal, match_unclaimed, spend_cap_message, unclaimed_message,
)
from nodes.agent.provider_errors import action_for_error_text, classify_provider_error, describe_failure

REACHED = spend_cap_message(50, "November 3")
CROSSING = spend_cap_message(1250, "November 3", price_usd=12.5, left_usd=4)
UNCLAIMED = unclaimed_message()


def test_the_message_names_the_cap_when_it_resets_and_where_it_is_raised():
    assert REACHED == ("You've hit your $50 monthly cap, so work that costs money waits until it resets on "
                       "November 3, or until you raise it in Settings → Plan and billing.")
    assert CROSSING.startswith("This costs $12.50, more than the $4 left of your $1,250 monthly cap.")
    for said in (REACHED, CROSSING):
        assert "credit" not in said.lower()
        assert match_spend_refusal(said) and not match_insufficient_credits(said)
    assert match_spend_cap(REACHED).group(1) == "50" and match_spend_cap(CROSSING).group(1) == "1,250"


def test_the_recognizer_is_none_safe_and_anchored():
    assert match_spend_cap(None) is None and match_spend_cap("") is None
    assert match_spend_cap("Auto top-up reached its monthly limit") is None
    assert match_spend_cap("The key's spend cap of $5 this month is used up ($5.0000 spent).") is None
    assert match_spend_cap(f"Node agent_1 failed: {REACHED}") is not None


def test_it_is_a_spend_refusal_like_credits_running_out():
    assert isinstance(SpendCapReached(REACHED), InsufficientBalanceError)


@pytest.mark.parametrize("node_type", ["agent", "image", "serverless-function", None])
def test_it_classifies_as_noclicks_own_with_a_settings_button_on_every_node(node_type):
    assert action_for_error_text(REACHED, node_type=node_type) == {"type": "open_billing", "label": "Raise the cap"}
    found = classify_provider_error(REACHED)
    assert (found.provider, found.kind, found.message) == ("noclick", "spend_cap", REACHED)


def test_a_stopped_node_says_the_cap_in_its_own_words():
    message, action = describe_failure(SpendCapReached(REACHED), node_type="image")
    assert message == REACHED and action == {"type": "open_billing", "label": "Raise the cap"}


def test_it_never_trips_the_schedule_breaker():
    from utils.webhook_routes import FailureStreak

    assert FailureStreak(count=99, error=f"Node agent failed: {REACHED}", span_s=86_400).trips_breaker is False
    assert FailureStreak(count=99, error="boom", span_s=86_400).trips_breaker is True


def test_an_unclaimed_accounts_refusal_is_the_caps_in_its_own_words():
    """Read as the cap's wherever the cap's is (no failure email, no coordinator wake-up, no breaker, its words kept
    whole), and told apart where the API answers with the claim (``match_unclaimed``)."""
    from utils.webhook_routes import FailureStreak

    assert UNCLAIMED == ("This account was made by an agent and no person has claimed it yet, so it spends only "
                         "funds paid into it, and none are left for this.")
    assert "credit" not in UNCLAIMED.lower() and "$" not in UNCLAIMED
    assert match_spend_cap(UNCLAIMED) and match_spend_refusal(UNCLAIMED) and not match_insufficient_credits(UNCLAIMED)
    assert match_spend_cap(UNCLAIMED).group(1) is None  # no cap in dollars to name
    assert match_unclaimed(f"Node agent_1 failed: {UNCLAIMED}") and not match_unclaimed(REACHED)
    assert match_unclaimed(None) is None and match_unclaimed("") is None
    refused = AccountUnclaimed(UNCLAIMED)
    assert isinstance(refused, SpendCapReached) and isinstance(refused, InsufficientBalanceError)
    found = classify_provider_error(UNCLAIMED)
    assert (found.provider, found.kind, found.message) == ("noclick", "spend_cap", UNCLAIMED)
    assert describe_failure(refused, node_type="agent")[0] == UNCLAIMED
    assert FailureStreak(count=99, error=f"Node agent failed: {UNCLAIMED}", span_s=86_400).trips_breaker is False


def test_no_inline_mints_of_the_cap_message():
    """The cap's words come from spend_cap_message alone, so the recognizer and every router keyed to it agree."""
    backend = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith(("tests/", "cloud/tests/", ".venv/", "venv/")) or rel == "billing/exceptions.py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # What the recognizer reads: the cap and where it's raised, together; or an unclaimed account's refusal.
        if re.search(r"monthly cap\b[^\n]*(Plan and billing|WHERE_CAP_IS_RAISED)|spends only funds paid into it",
                     source):
            offenders.append(rel)
    assert not offenders, (f"inline monthly-cap refusal(s) in {offenders}: use billing.exceptions.spend_cap_message "
                           "or unclaimed_message")

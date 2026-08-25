"""The platform credit-gate message contract, end to end.

The 2026-07-29 incident: NoClick's own gate error ("Insufficient credits:
0.00 < 0.20 required") contains the words "insufficient credits" — which is
ALSO OpenRouter's literal 402 message — so the run-results popup grew an
"Add credits" button pointing at OpenRouter's top-up page. Provenance must be
decided by shape, never by which greedy rule matches first:

- ``billing.exceptions.insufficient_credits_message`` is the ONLY mint of the
  gate message; ``INSUFFICIENT_CREDITS_RE`` is the ONLY recognizer.
- ``provider_errors`` classifies the shape (and the typed
  ``InsufficientBalanceError``) as provider='noclick', without a hosted purchase action.
- ``notifications`` routes it to the credits-exhausted email — and must NOT
  route provider balance errors there (the reverse confusion).

The source scan at the bottom is the anti-recurrence guard: a new inline mint
of the gate string fails CI until it goes through the helper.
"""

import pathlib
import re

import pytest

from billing.exceptions import (
    INSUFFICIENT_CREDITS_RE,
    InsufficientBalanceError,
    insufficient_credits_message,
    match_insufficient_credits,
)
from nodes.agent.provider_errors import (
    action_for_error_text,
    classify_provider_error,
    describe_failure,
)

GATE_MSG = insufficient_credits_message(0.0, 0.20)  # the incident string


# ── Mint ↔ recognizer roundtrip ─────────────────────────────────────────────

@pytest.mark.parametrize("remaining,required", [(0.0, 0.20), (1.5, 5.0), (12.25, 1.0)])
def test_minted_message_matches_the_recognizer(remaining, required):
    m = match_insufficient_credits(insufficient_credits_message(remaining, required))
    assert m is not None
    assert float(m.group(1)) == pytest.approx(remaining, abs=0.005)
    assert float(m.group(2)) == pytest.approx(required, abs=0.005)


def test_recognizer_is_none_safe_and_anchored():
    assert match_insufficient_credits(None) is None
    assert match_insufficient_credits("") is None
    # OpenRouter's literal 402 message must NOT match the platform shape.
    assert match_insufficient_credits("402 Insufficient credits") is None
    assert match_insufficient_credits(
        "Insufficient credits. Add more using https://openrouter.ai/settings/credits"
    ) is None


# ── Classification: platform beats provider, by shape ───────────────────────

@pytest.mark.parametrize("text", [
    GATE_MSG,
    # As the run-results popup showed it (execution-runner framing).
    f"agent node agent_jli3 failed: {GATE_MSG}",
    f"Node node_abc failed: {GATE_MSG}",
    # Arbitrary harness re-framing (same anti-overfit bar as the provider corpus).
    f"turn failed: RuntimeError: [Harness v99.1] upstream said — {GATE_MSG}",
])
def test_gate_message_classifies_as_noclick_not_openrouter(text):
    match = classify_provider_error(text, channel="error")
    assert match is not None
    assert (match.provider, match.kind) == ("noclick", "no_credits")


def test_openrouter_402_still_classifies_as_openrouter():
    match = classify_provider_error("402 Insufficient credits", channel="error")
    assert (match.provider, match.kind) == ("openrouter", "no_credits")


def test_platform_rewrite_names_noclick_and_keeps_detail():
    match = classify_provider_error(GATE_MSG, channel="error")
    assert "NoClick credits" in match.message
    assert "model provider" in match.message  # draws the provenance line
    assert GATE_MSG in match.message  # verbatim detail rides along
    assert "Provider message:" not in match.message  # no provider spoke here


# ── Platform errors do not expose a hosted purchase action ─────────────────

def test_platform_errors_have_no_hosted_purchase_action():
    match = classify_provider_error(GATE_MSG, channel="error")
    assert match.action() is None
    for node_type in ("agent", "automation-image", None):
        assert action_for_error_text(
            f"Node x failed: {GATE_MSG}", node_type=node_type
        ) is None






def test_provider_actions_require_model_provider_provenance():
    """A non-agent error that merely shares a provider's phrasing must not
    grow a provider-branded button — an Apify/ElevenLabs 'insufficient
    credits' pointing at OpenRouter is the same incident in reverse."""
    text = "402 Insufficient credits"
    agent_action = action_for_error_text(text, node_type="agent")
    assert agent_action is not None and "openrouter.ai" in agent_action["url"]
    assert action_for_error_text(text, node_type="automation-elevenlabs") is None
    assert action_for_error_text(text, node_type=None) is None
    assert action_for_error_text(
        "API key not valid. Please pass a valid API key.",
        node_type="automation-youtube") is None


# ── Typed exception: provenance without regex ───────────────────────────────

def test_insufficient_balance_error_classifies_by_type_any_message():
    """The exception type IS platform provenance — a future message rewording
    must not silently demote gate failures back to unclassified."""
    message, action = describe_failure(
        InsufficientBalanceError("totally novel wording"), node_type="agent")
    assert "NoClick credits" in message
    assert action is None


def test_gate_failures_classify_for_non_agent_nodes_too():
    message, action = describe_failure(
        InsufficientBalanceError(GATE_MSG), node_type="automation-image")
    assert "NoClick credits" in message
    assert action is None


# ── Email routing: platform shape in, provider shapes out ───────────────────

def test_provider_balance_errors_do_not_look_like_the_gate():
    """send_run_failure_alert keys the credits-email delegation on the
    platform shape. Provider balance errors — including their stored
    rewrites, which carry the verbatim provider text — must not match, or
    BYOK users get told to top up NoClick credits their run never touched."""
    for provider_text in (
        "402 Insufficient credits",
        "Credit balance is too low",
        "Your newly created team doesn't have any credits yet.",
    ):
        assert match_insufficient_credits(provider_text) is None
        rewritten = classify_provider_error(provider_text, channel="error").message
        assert match_insufficient_credits(rewritten) is None, provider_text


def test_gate_message_survives_runner_framing_for_email_routing():
    m = match_insufficient_credits(f"Node agent_jli3 failed: {GATE_MSG}")
    assert m is not None and float(m.group(1)) == 0.0


# ── Anti-recurrence: the mint is a choke point ──────────────────────────────

def test_no_inline_mints_of_the_gate_message():
    """Any user-facing 'Insufficient credits: …' string must come from
    insufficient_credits_message — an inline copy can drift from the
    recognizer and silently break the button + email routing. (The classifier
    and this suite are keyed to the shape; keep mint and regex together.)"""
    backend = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith(("tests/", ".venv/", "venv/")) or rel == "billing/exceptions.py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if re.search(r"Insufficient credits:", source):
            offenders.append(rel)
    assert not offenders, (
        f"inline 'Insufficient credits:' mint(s) in {offenders} — use "
        "billing.exceptions.insufficient_credits_message instead"
    )

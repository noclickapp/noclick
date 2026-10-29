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
- A provider's 402 to NoClick's OWN key (the instance's OpenRouter key, which
  pays for what NoClick runs) is neither: it is NoClick's side, briefly
  (``provider_errors.platform_key_refusal``), worded with none of the
  provider's words about credits, with nothing to buy (2026-10-29: a
  coordinator read OpenRouter's "would exceed your available credits" on
  NoClick's key as its owner's balance and asked them to add funds).

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
    match_spend_refusal,
)
from nodes.agent.provider_errors import (
    VENDOR_UNAVAILABLE,
    action_for_error_text,
    classify_provider_error,
    describe_failure,
    normalize_turn_result,
    platform_key_refusal,
    vendor_unavailable_message,
)

GATE_MSG = insufficient_credits_message(0.0, 0.20)  # the incident string


# ── Mint ↔ recognizer roundtrip ─────────────────────────────────────────────

@pytest.mark.parametrize("remaining,required", [(0.0, 0.20), (1.5, 5.0), (12.25, 1.0), (-39.99, 0.20)])
def test_minted_message_matches_the_recognizer(remaining, required):
    m = match_insufficient_credits(insufficient_credits_message(remaining, required))
    assert m is not None
    # A balance in debt reads as none left.
    assert float(m.group(1)) == pytest.approx(max(remaining, 0.0), abs=0.005)
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


# ── The action: NoClick top-up, never a provider billing page ───────────────

@pytest.fixture
def credit_cta(monkeypatch):
    """A platform that sells credits registers CREDIT_CTA; the top-up action
    exists only then."""
    from utils import capabilities

    async def _cta(billing_user_id, pool=None):
        return "Top Up Credits", "https://example.test/dashboard?action=topup"

    monkeypatch.setattr(capabilities, "_providers", {capabilities.CREDIT_CTA: _cta})


def test_gate_error_action_opens_the_topup_popup_in_place(credit_cta):
    """`open_topup` = the client dispatches BalanceDisplay's popup event right
    where the error is shown — never a new-tab navigation (the deep-link hop
    can lose the intent, and the user is already in the app). The url rides
    along only as data for surfaces without that listener."""
    match = classify_provider_error(GATE_MSG, channel="error")
    action = match.action()
    assert action["type"] == "open_topup"
    assert action["label"] == "Add credits"
    assert "/dashboard?action=topup" in action["url"]
    assert "openrouter" not in action["url"]


def test_platform_action_applies_to_every_node_type(credit_cta):
    """The credit gate fires in dozens of node handlers — the top-up button
    must not depend on the failing node being an agent."""
    for node_type in ("agent", "automation-image", "automation-whatsapp", None):
        action = action_for_error_text(
            f"Node x failed: {GATE_MSG}", node_type=node_type)
        assert action is not None and "action=topup" in action["url"], node_type


def test_platform_errors_have_no_purchase_action_without_a_credit_cta(monkeypatch):
    """An installation that sells nothing must not show a button to buy it."""
    from utils import capabilities

    monkeypatch.setattr(capabilities, "_providers", {})
    match = classify_provider_error(GATE_MSG, channel="error")
    assert match.action() is None
    for node_type in ("agent", "automation-image", None):
        assert action_for_error_text(f"Node x failed: {GATE_MSG}", node_type=node_type) is None


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

def test_insufficient_balance_error_classifies_by_type_any_message(credit_cta):
    """The exception type IS platform provenance — a future message rewording
    must not silently demote gate failures back to unclassified."""
    message, action = describe_failure(
        InsufficientBalanceError("totally novel wording"), node_type="agent")
    assert "NoClick credits" in message
    assert action is not None and "action=topup" in action["url"]


def test_gate_failures_classify_for_non_agent_nodes_too(credit_cta):
    message, action = describe_failure(
        InsufficientBalanceError(GATE_MSG), node_type="automation-image")
    assert "NoClick credits" in message
    assert action is not None and "action=topup" in action["url"]


def test_laundered_gate_text_moves_to_error_channel():
    """A gate message surfacing as a CLI harness 'response' (e.g. relayed from
    a tool result) must fail the turn with platform guidance, not complete."""
    response, error = normalize_turn_result(GATE_MSG, None)
    assert response == ""
    assert "NoClick credits" in error


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


# ── NoClick's own key out of credit: NoClick's side, never the account's ────

# OpenRouter's 402s as it words them: the first is what answered NoClick's own key on 2026-10-29.
OPENROUTER_402S = (
    "This request would exceed your available credits given your current in-flight requests",
    'litellm.APIError: APIError: OpenrouterException - {"error":{"message":"This request would exceed your '
    'available credits given your current in-flight requests","code":402}}',
    "Insufficient credits. Add more using https://openrouter.ai/settings/credits",
)
UNAVAILABLE = vendor_unavailable_message("image service")


@pytest.mark.parametrize("text", OPENROUTER_402S + (UNAVAILABLE,))
def test_neither_openrouters_402_nor_noclicks_side_reads_as_the_credit_gate(text):
    """The out-of-funds card, the coordinator's refusal with its payment links and the turn's ``FUNDS`` wrap-up all
    key on the gate's own shape: none may fire on a provider's words, or on NoClick's own key running short."""
    from coder.openai_agent.guards import credit_refusal

    assert match_insufficient_credits(text) is None and match_spend_refusal(text) is None
    assert credit_refusal({"success": False, "error": text}) is None


def test_a_402_on_noclicks_key_is_said_as_noclicks_side_and_pages(caplog):
    said = OPENROUTER_402S[0]
    with caplog.at_level("ERROR", logger="nodes.agent.provider_errors"):
        message = platform_key_refusal(402, said, vendor="OpenRouter", call="image generation",
                                       service="image service")
    assert message == UNAVAILABLE == ("NoClick's image service is briefly unavailable; try again in a few minutes "
                                      "(nothing on your account needs to change).")
    # None of the provider's words, so nothing a model or a person could take for the account's own balance.
    assert not any(word in message.lower() for word in ("credit", "fund", "402", "openrouter", "pay"))
    # Logged at ERROR (the Slack handler pages on it) with what the vendor said, under a key of its own.
    [record] = [r for r in caplog.records if r.levelname == "ERROR"]
    assert "OpenRouter" in record.getMessage() and "image generation" in record.getMessage()
    assert said in record.getMessage() and record.alert_key == (VENDOR_UNAVAILABLE, "OpenRouter", "image generation")


@pytest.mark.parametrize("status", [None, 200, 400, 401, 403, 429, 500, 503])
def test_any_other_answer_keeps_its_own_words_and_logs_nothing(status, caplog):
    with caplog.at_level("ERROR", logger="nodes.agent.provider_errors"):
        said = platform_key_refusal(status, OPENROUTER_402S[0], vendor="OpenRouter", call="x", service="model service")
    assert said is None
    assert caplog.records == []


@pytest.mark.parametrize("framed", [
    UNAVAILABLE,
    f"Node node_abc failed: {UNAVAILABLE}",
    # A coding harness relaying the credential proxy's 503 to NoClick's own key.
    'API Error: 503 {"type":"error","error":{"type":"api_error","message":"NoClick: ' + UNAVAILABLE + '"}}',
])
def test_noclicks_side_classifies_as_noclick_with_nothing_to_buy(framed, credit_cta):
    """Even where a top-up is sold (CREDIT_CTA), NoClick's side briefly unavailable offers nothing to click: it is
    waited out. Its rewrite is the one sentence, whatever framed it."""
    match = classify_provider_error(framed, channel="error")
    assert (match.provider, match.kind) == ("noclick", VENDOR_UNAVAILABLE)
    assert match.message == UNAVAILABLE and match.action() is None
    for node_type in ("agent", "automation-image", None):
        assert action_for_error_text(framed, node_type=node_type) is None
    assert describe_failure(RuntimeError(framed), node_type="agent") == (UNAVAILABLE, None)
    assert normalize_turn_result("", framed) == ("", UNAVAILABLE)


@pytest.mark.parametrize("text", OPENROUTER_402S)
def test_a_402_on_the_accounts_own_openrouter_key_names_that_account(text):
    """On the account's own key (BYOK) the same 402 is its own OpenRouter balance, and says so."""
    match = classify_provider_error(text, channel="error")
    assert (match.provider, match.kind) == ("openrouter", "no_credits")
    assert "Your OpenRouter account has no API credits" in match.message
    assert "not your NoClick credits" in match.message
    assert "openrouter.ai/settings/credits" in action_for_error_text(text, node_type="agent")["url"]


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
        # Test code (tests/, and the hosted cloud/tests/) fakes refusals; it reaches no one.
        if "/tests/" in f"/{rel}" or rel.startswith((".venv/", "venv/")) or rel == "billing/exceptions.py":
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


def test_no_inline_mints_of_noclicks_side_unavailable():
    """NoClick's own key out of credit is said only by ``vendor_unavailable_message``: an inline copy could drift
    from ``VENDOR_UNAVAILABLE_RE``, and the classifier would hand it to a provider rule or to nothing."""
    backend = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if "/tests/" in f"/{rel}" or rel.startswith((".venv/", "venv/")) or rel == "nodes/agent/provider_errors.py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "is briefly unavailable; try again" in source:
            offenders.append(rel)
    assert not offenders, f"inline mint(s) in {offenders}: use provider_errors.vendor_unavailable_message"

"""Corpus-driven tests for the provider billing/auth error classifier.

The corpus IS the maintenance strategy: when a harness update surfaces a new
provider error shape (they show up as ``[provider_errors] unclassified`` logs /
``agent.provider_error.unclassified`` span attrs in Honeycomb), append the real
string here first, watch it fail, then extend the rule table. Rules must match
provider-origin slugs — a fixture wrapped in NEW harness framing should pass
WITHOUT a rule change; if it doesn't, the rule was overfitted to the wrapper.
"""

import pytest

from nodes.agent.provider_errors import (
    RESPONSE_CHANNEL_MAX_LEN,
    classify_provider_error,
    format_provider_message,
)

# ── Positive corpus: real strings observed from providers/harnesses ─────────
# (provider, kind, text). Keep entries VERBATIM as observed — don't tidy them.
POSITIVE_CORPUS = [
    # Representative Anthropic CLI response-channel failure.
    ("anthropic", "no_credits", "Credit balance is too low"),
    # Anthropic API JSON body, as litellm/SDKs surface it.
    ("anthropic", "no_credits",
     '{"type":"error","error":{"type":"invalid_request_error","message":"Your credit '
     'balance is too low to access the Anthropic API. Please go to Plans & Billing '
     'to upgrade or purchase credits."}}'),
    ("anthropic", "invalid_key",
     'API Error: 401 {"type":"error","error":{"type":"authentication_error",'
     '"message":"invalid x-api-key"}}'),
    ("anthropic", "account_blocked",
     '{"type":"error","error":{"type":"permission_error","message":"Your '
     'organization has been disabled."}}'),
    # Claude Code CLI subscription-cap strings (OAuth Pro/Max users).
    ("anthropic", "plan_limit", "Claude AI usage limit reached|1751968800"),
    ("anthropic", "plan_limit", "Claude usage limit reached — your limit will reset at 3am"),
    ("anthropic", "plan_limit", "5-hour limit reached ∙ resets 6pm"),
    # OpenAI — quota exhaustion rides a 429 with the insufficient_quota slug.
    ("openai", "no_credits",
     "Error code: 429 - {'error': {'message': 'You exceeded your current quota, "
     "please check your plan and billing details. For more information on this "
     "error, read the docs: https://platform.openai.com/docs/guides/error-codes/"
     "api-errors.', 'type': 'insufficient_quota', 'param': None, 'code': "
     "'insufficient_quota'}}"),
    ("openai", "no_credits",
     "You exceeded your current quota, please check your plan and billing details."),
    ("openai", "invalid_key",
     "Incorrect API key provided: sk-proj-********. You can find your API key at "
     "https://platform.openai.com/account/api-keys."),
    ("openai", "invalid_key",
     "AuthenticationError: Error code: 401 - {'error': {'message': 'Incorrect API "
     "key provided', 'type': 'invalid_request_error', 'code': 'invalid_api_key'}}"),
    # OpenRouter — 402s from BYOK keys on the SDK/openclaw/hermes paths.
    ("openrouter", "no_credits",
     'litellm.APIError: OpenRouterException - {"error":{"message":"This request '
     'requires more credits, or fewer max_tokens. You requested up to 16384 tokens, '
     'but can only afford 0.","code":402}}'),
    ("openrouter", "no_credits", "402 Insufficient credits"),
    ("openrouter", "invalid_key", "No auth credentials found"),
    # Representative LiteLLM-framed OpenRouter authentication failure.
    ("openrouter", "invalid_key",
     'litellm.AuthenticationError: AuthenticationError: OpenrouterException - '
     '{"error":{"message":"User not found.","code":401}}'),
    ("openrouter", "plan_limit", "Key limit exceeded"),
    # OpenRouter upstream-provider outage envelope — verbatim from the
    # Upstream provider outage envelope from a free model variant.
    ("openrouter", "provider_outage",
     '{"code":500,"message":"Internal Server Error","metadata":{"error_type":"server"}}'),
    ("openrouter", "provider_outage",
     'Provider returned error: upstream connect error or disconnect/reset before headers'),
    # Google / Gemini.
    ("gemini", "invalid_key", "API key not valid. Please pass a valid API key."),
    # xAI.
    ("xai", "no_credits",
     "Your newly created team doesn't have any credits yet. You can purchase "
     "credits on https://console.x.ai."),
    # Generic — wording shared by several providers; provider unknown is fine,
    # the guidance is still correct.
    ("unknown", "invalid_key", "Invalid API key"),
]

# ── Negative corpus: must NEVER classify on the response channel ────────────
NEGATIVE_RESPONSES = [
    # Long legitimate analysis that discusses quotas/credits.
    ("The AppSheet sync completed. Note that three rows were skipped because the "
     "customer's credit balance is too low according to the billing column, and "
     "two more exceeded your current quota policy defined in the sheet. " * 3),
    # Long text quoting an error slug in a code discussion.
    ("Here's why you might see insufficient_quota from OpenAI in your own app: "
     "the API returns it when prepaid credits run out. To handle it, catch the "
     "exception and surface a billing link to your user. " * 4),
    # Short benign replies.
    "All done — synced 42 rows to AppSheet.",
    "Done.",
    "",
    # "User not found" is a perfectly ordinary answer after a lookup. The
    # OpenRouter 401 rule is bound to the JSON error envelope precisely so
    # these stay replies instead of being moved to the error channel and
    # failing the run.
    "User not found.",
    "I searched Slack for that address and the user was not found.",
    "The Stripe customer lookup returned: user not found",
]


@pytest.mark.parametrize("provider,kind,text", POSITIVE_CORPUS)
def test_corpus_classifies_on_error_channel(provider, kind, text):
    match = classify_provider_error(text, channel="error")
    assert match is not None, f"corpus string failed to classify: {text[:80]!r}"
    assert (match.provider, match.kind) == (provider, kind)


@pytest.mark.parametrize("provider,kind,text", POSITIVE_CORPUS)
def test_corpus_survives_harness_rewrapping(provider, kind, text):
    """Anti-overfit guard: harnesses re-frame provider text every release, so a
    rule that only matches inside today's framing is broken by construction.
    Every corpus string must still classify inside arbitrary wrapper text."""
    wrapped = f"turn failed: RuntimeError: [Harness v99.1] upstream said — {text} (retry disabled)"
    match = classify_provider_error(wrapped, channel="error")
    assert match is not None and (match.provider, match.kind) == (provider, kind)


@pytest.mark.parametrize("provider,kind,text", POSITIVE_CORPUS)
def test_short_corpus_strings_classify_on_response_channel(provider, kind, text):
    """Laundered-into-response detection: every corpus string short enough to
    pass the length gate must classify on the response channel too."""
    if len(text) > RESPONSE_CHANNEL_MAX_LEN:
        pytest.skip("longer than the response-channel gate by design")
    match = classify_provider_error(text, channel="response")
    assert match is not None and (match.provider, match.kind) == (provider, kind)


@pytest.mark.parametrize("text", NEGATIVE_RESPONSES)
def test_legitimate_responses_never_classify(text):
    assert classify_provider_error(text, channel="response") is None


# ── Exception-type classification ──────────────────────────────────────────
# litellm normalizes every provider it supports into one static exception
# hierarchy. Matching on that covers the fifty-odd providers in
# PROVIDER_REQUIRED_CREDENTIALS, not just the handful with regex rules — and
# survives a provider rewording its message, which regex cannot.

from litellm.exceptions import (  # noqa: E402
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    ContextWindowExceededError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
)

from nodes.agent.provider_errors import (  # noqa: E402
    classify_provider_exception,
    describe_failure,
)


def _make(exc_cls, message: str, provider: str = "deepseek"):
    """Build a litellm exception. Their __init__ signatures are not uniform —
    a few require a `response` — so supply one when it is demanded."""
    kwargs = dict(message=message, llm_provider=provider, model=f"{provider}/chat")
    try:
        return exc_cls(**kwargs)
    except TypeError:
        import httpx

        return exc_cls(
            **kwargs,
            response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
        )


@pytest.mark.parametrize("exc_cls,kind", [
    (AuthenticationError, "invalid_key"),
    (PermissionDeniedError, "account_blocked"),
    (RateLimitError, "rate_limited"),
    (ServiceUnavailableError, "provider_outage"),
])
def test_exception_types_classify_without_any_matching_text(exc_cls, kind):
    """The message here is deliberately unmatched by every regex rule — the
    type alone has to carry it, which is the point of the fallback."""
    match = classify_provider_exception(_make(exc_cls, "something went sideways"))
    assert match is not None and match.kind == kind


def test_unknown_provider_still_produces_a_usable_message():
    """A provider with no entry in the metadata table must still explain
    itself; falling back to 'the model provider' beats leaking a traceback."""
    match = classify_provider_exception(
        _make(AuthenticationError, "nope", provider="sambanova")
    )
    assert match.provider == "unknown"
    assert "API key" in match.message


def test_litellm_provider_slug_is_used_when_known():
    match = classify_provider_exception(
        _make(AuthenticationError, "nope", provider="anthropic")
    )
    assert match.provider == "anthropic"


@pytest.mark.parametrize("exc_cls", [BadRequestError, ContextWindowExceededError])
def test_caller_errors_are_not_dressed_up_as_billing_problems(exc_cls):
    """A bad model id or an oversized prompt is the caller's problem. Telling
    someone to check their API key sends them somewhere that cannot help."""
    exc = _make(exc_cls, "bad input", provider="openai")
    assert classify_provider_exception(exc) is None


def test_a_specific_text_rule_beats_the_coarse_type():
    """OpenAI signals exhausted credits with a 429 — which litellm types as a
    RateLimitError. The text rule knows better, and must win, or we would tell
    someone out of credits to wait and retry forever."""
    exc = _make(
        RateLimitError,
        "You exceeded your current quota, please check your plan and billing details.",
        provider="openai",
    )
    match = classify_provider_exception(exc)
    assert match.kind == "no_credits"


def test_non_provider_exceptions_pass_straight_through():
    message, action = describe_failure(KeyError("workflow_id"), node_type="agent")
    assert "workflow_id" in message
    assert action is None


def test_non_agent_nodes_never_get_the_model_provider_rewrite():
    """The templates speak agent language and the generic rules are greedy: a
    Stripe key rejection matches "invalid api key", and Google's standard
    "API key not valid" matches the gemini rule — rewriting either would tell
    a Stripe/YouTube user to fix "this agent's credential" at aistudio."""
    for node_type, text in (
        ("automation-stripe", "Invalid API Key provided: sk_test_4eC39Hq"),
        ("automation-youtube", "API key not valid. Please pass a valid API key."),
    ):
        message, action = describe_failure(Exception(text), node_type=node_type)
        assert message == text
        assert action is None


def test_foreign_sdk_exception_names_do_not_classify_by_type():
    """stripe/openai/anthropic SDKs all mint an `AuthenticationError`; only
    litellm's own carry the model-provider meaning the name table assumes."""

    class AuthenticationError(Exception):  # deliberately shadows the name
        pass

    assert classify_provider_exception(AuthenticationError("card declined")) is None


# ── Actions ────────────────────────────────────────────────────────────────


def test_a_bad_key_offers_the_credentials_the_user_must_fix():
    exc = _make(AuthenticationError, "nope", provider="openrouter")
    _message, action = describe_failure(exc, node_type="agent")
    assert action == {"type": "open_credentials", "label": "Open credentials"}


def test_no_credits_links_to_the_place_credits_are_bought():
    match = classify_provider_error("402 Insufficient credits", channel="error")
    action = match.action()
    assert action["type"] == "open_url"
    assert action["url"].startswith("https://openrouter.ai/")


@pytest.mark.parametrize("exc_cls", [RateLimitError, ServiceUnavailableError,
                                     APIConnectionError])
def test_nothing_to_click_offers_no_button(exc_cls):
    """Waiting is the only response to a rate limit or an outage. A button
    there would be the Run button in disguise, and buttons that do nothing
    useful teach people to ignore the ones that do."""
    match = classify_provider_exception(_make(exc_cls, "upstream sad", provider="groq"))
    assert match is not None and match.action() is None


def test_a_stored_rewrite_still_yields_its_action():
    """Past runs read their error back from storage, already rewritten. The
    button has to survive that round trip, or browsing run history silently
    loses the fix the live run offered."""
    from nodes.agent.provider_errors import action_for_error_text

    raw = (
        'litellm.AuthenticationError: OpenrouterException - '
        '{"error":{"message":"User not found.","code":401}}'
    )
    stored = classify_provider_error(raw, channel="error").message

    assert action_for_error_text(stored, node_type="agent") == action_for_error_text(
        raw, node_type="agent")
    assert action_for_error_text(stored, node_type="agent")["type"] == "open_credentials"


def test_asking_for_an_action_never_rewrites():
    """Why re-deriving on read is safe rather than a second wrapping: this
    function returns a button, never a message."""
    from nodes.agent.provider_errors import action_for_error_text

    stored = classify_provider_error("402 Insufficient credits", channel="error").message
    action_for_error_text(stored, node_type="agent")  # must not mutate or re-wrap anything
    assert stored.count("Add credits at") == 1


def test_ordinary_stored_errors_have_no_action():
    from nodes.agent.provider_errors import action_for_error_text

    assert action_for_error_text(
        "Node automation-slack failed: channel_not_found", node_type="agent") is None
    assert action_for_error_text(None, node_type="agent") is None
    assert action_for_error_text("", node_type="agent") is None


def test_every_kind_has_a_message_template():
    """A kind added to the classifier without a template raises KeyError at the
    worst possible moment — while already handling someone's failure."""
    from nodes.agent.provider_errors import _KIND_BY_EXCEPTION, _RULES, _TEMPLATES

    for kind in {r.kind for r in _RULES} | set(_KIND_BY_EXCEPTION.values()):
        assert kind in _TEMPLATES, f"no user-facing template for kind {kind!r}"


def test_messages_disambiguate_noclick_credits_and_preserve_detail():
    """Billing messages must distinguish provider and instance balances while
    preserving the provider's original detail."""
    for provider, kind, text in POSITIVE_CORPUS:
        match = classify_provider_error(text, channel="error")
        if kind in ("no_credits", "plan_limit"):
            assert "not your NoClick credits" in match.message, (provider, kind)
        assert "Provider message:" in match.message
        assert text.strip()[:80] in match.message, "original detail must ride along"


def test_format_provider_message_unknown_provider_has_no_dead_links():
    msg = format_provider_message("unknown", "invalid_key", "Invalid API key")
    assert "http" not in msg.split("Provider message:")[0]


def test_classifier_tolerates_non_string():
    assert classify_provider_error({"not": "a string"}) is None

"""The rules every automated call obeys: no emergency, crisis or service number
is ever dialed, however it is written, and no voice denies being an AI."""

import pytest

from utils.call_safety import (EMERGENCY_REFUSAL, NEVER_DENY_AI, OWNER_EMERGENCY_STEP, SERVICE_CODES,
                               emergency_refusal, service_code)


@pytest.mark.parametrize("dialed,code", [
    ("911", "911"), ("9-1-1", "911"), ("+1 911", "911"), ("1-911", "911"), ("+1911", "911"), ("1 (911)", "911"),
    ("9-911", "911"), ("tel:911", "911"), ("sip:911@carrier.example", "911"), ("911,1234", "911"),
    ("911 ext 5", "911"), ("*911", "911"),
    ("112", "112"), ("+33 112", "112"), ("+91 112", "112"), ("999", "999"), ("+44 999", "999"),
    ("0044999", "999"), ("011 44 999", "999"), ("000", "000"), ("+61 000", "000"), ("111", "111"),
    ("933", "933"), ("988", "988"), ("+1 988", "988"), ("211", "211"), ("311", "311"), ("711", "711"),
])
def test_emergency_crisis_and_service_codes_are_recognised_however_written(dialed, code):
    assert service_code(dialed) == code


@pytest.mark.parametrize("dialed", [
    "+14155550123", "(415) 555-0123", "+911123456789",  # Delhi: +91 11 …, not 911
    "+14155550911", "+1 212 988 1234",  # a code inside a full number is just digits
    "+14155550123,911", "hello", "", None, "5555", "12345",
])
def test_full_numbers_and_non_numbers_are_not_service_codes(dialed):
    assert service_code(dialed) is None
    assert emergency_refusal(dialed) is None


def test_the_codes_cover_the_emergency_lines_and_every_n11():
    assert {"911", "112", "999", "000", "933", "988"} <= SERVICE_CODES
    assert {f"{n}11" for n in range(2, 10)} <= SERVICE_CODES


def test_the_refusal_says_no_call_was_placed_and_the_owner_is_told_how_to_get_help():
    refusal = emergency_refusal("+1 911")
    assert refusal == EMERGENCY_REFUSAL.format(code="911") and refusal.startswith("No call was placed: 911")
    assert OWNER_EMERGENCY_STEP not in refusal
    owner = emergency_refusal("988", for_owner=True)
    assert owner.startswith("No call was placed: 988") and owner.endswith(OWNER_EMERGENCY_STEP)
    assert "call or text 911 themselves" in owner and "text-to-911 works in most of the US" in owner
    # A location only from what the conversation already holds.
    assert "If they shared where they are in this conversation" in owner and "never guess one" in owner


def test_the_coordinator_never_sets_up_calling_for_an_emergency_and_never_denies_being_an_ai_on_a_call():
    from coder.coordinator.agent import PROMPTS, system_prompt_for

    for phone_steps in (True, False):
        assert OWNER_EMERGENCY_STEP in PROMPTS.system_prompt(in_credits=False, phone_steps=phone_steps)
    for channel in ("phone", "whatsapp", "callback", "voice"):
        assert NEVER_DENY_AI in system_prompt_for({"channel": channel}, None)
    assert NEVER_DENY_AI not in system_prompt_for({"channel": "whatsapp_text"}, None)
    assert "never claim to be human" in NEVER_DENY_AI and "Don't volunteer that you're an AI" in NEVER_DENY_AI

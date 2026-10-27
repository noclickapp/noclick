"""Gemini 3 rejects replayed functionCall parts without a thoughtSignature
(INVALID_ARGUMENT; a 2026-08 BYOK incident affected every agent tool-call turn on
gemini-3.5-flash died). Stock litellm >= 1.96 handles this natively:
a real signature carried on the tool call (provider_specific_fields, tool or
function level, or encoded into the tool_call_id) is replayed, and a dummy
validation-bypass signature is attached for gemini-3-family models when none
is present, on the first call of a parallel batch only: Gemini signs only that
one, and a dummy on every sibling made gemini-3.5 answer with empty text
(litellm 1.99). These tests pin that upstream behavior through our pinned
dependency — a litellm bump that loses it fails here before it fails in prod
(the 2026-08 incident class: dependency predates a provider requirement).
"""
from litellm.litellm_core_utils.prompt_templates.factory import (
    _get_dummy_thought_signature,
    convert_to_gemini_tool_call_invoke,
)

GEMINI_3 = "gemini-3.5-flash"


def _tool_call(call_id, args='{"to": "234", "text": "hi"}', **extra):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "whatsapp__send_text_message", "arguments": args},
        **extra,
    }


def _message(*tool_calls):
    return {"role": "assistant", "content": None, "tool_calls": list(tool_calls)}


def test_gemini3_gets_dummy_signature_on_the_first_call_when_history_has_none():
    first, sibling = convert_to_gemini_tool_call_invoke(
        _message(_tool_call("call_1"), _tool_call("call_2", '{"to": "1", "text": "yo"}')),
        model=GEMINI_3,
    )
    assert first["thoughtSignature"] == _get_dummy_thought_signature()
    assert "thoughtSignature" not in sibling
    assert [first["function_call"]["name"], sibling["function_call"]["name"]] == ["whatsapp__send_text_message"] * 2


def test_real_signature_on_tool_provider_fields_wins():
    (part,) = convert_to_gemini_tool_call_invoke(
        _message(
            _tool_call(
                "call_1", provider_specific_fields={"thought_signature": "EjQKMgER-real"}
            )
        ),
        model=GEMINI_3,
    )
    assert part["thoughtSignature"] == "EjQKMgER-real"


def test_a_siblings_real_signature_is_replayed():
    first, sibling = convert_to_gemini_tool_call_invoke(
        _message(_tool_call("call_1"), _tool_call("call_2", provider_specific_fields={"thought_signature": "EjQK-2"})),
        model=GEMINI_3,
    )
    assert first["thoughtSignature"] == _get_dummy_thought_signature()
    assert sibling["thoughtSignature"] == "EjQK-2"


def test_real_signature_on_function_provider_fields_wins():
    tc = _tool_call("call_1")
    tc["function"]["provider_specific_fields"] = {"thought_signature": "EjQKMgER-func"}
    (part,) = convert_to_gemini_tool_call_invoke(_message(tc), model=GEMINI_3)
    assert part["thoughtSignature"] == "EjQKMgER-func"


def test_dummy_signature_is_the_documented_bypass_shape():
    # Base64 payload Gemini's validator recognizes as "skip validation" — an
    # arbitrary value would be rejected as a corrupted signature.
    import base64

    assert base64.b64decode(_get_dummy_thought_signature()) == (
        b"skip_thought_signature_validator"
    )

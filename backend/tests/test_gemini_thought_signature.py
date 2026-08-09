"""Gemini 3 rejects replayed functionCall parts without a thoughtSignature
(INVALID_ARGUMENT; the 2026-08-09 BYOK incident — every agent tool-call turn on
gemini-3.5-flash died). Our litellm fork attaches one when converting
OpenAI-format assistant tool calls to Gemini contents: a real signature on the
tool call wins, else Google's documented validation-bypass placeholder
(verified live: required+accepted on gemini-3.5, tolerated on gemini-2.5,
arbitrary values rejected as corrupted). These tests pin that fork behavior
through the pinned dependency — a fork rebase that loses the patch fails here.
"""
from litellm.litellm_core_utils.prompt_templates.factory import (
    GEMINI_THOUGHT_SIGNATURE_BYPASS,
    convert_to_gemini_tool_call_invoke,
)


def _tool_call(call_id, args='{"to": "234", "text": "hi"}', **extra):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "whatsapp__send_text_message", "arguments": args},
        **extra,
    }


def test_every_function_call_part_carries_a_signature():
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [_tool_call("call_1"), _tool_call("call_2", '{"to": "1", "text": "yo"}')],
    }
    parts = convert_to_gemini_tool_call_invoke(message)
    assert len(parts) == 2
    for part in parts:
        assert part["thoughtSignature"] == GEMINI_THOUGHT_SIGNATURE_BYPASS
        assert part["function_call"]["name"] == "whatsapp__send_text_message"


def test_real_signature_on_the_tool_call_wins():
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [_tool_call("call_1", thought_signature="EjQKMgER-real")],
    }
    (part,) = convert_to_gemini_tool_call_invoke(message)
    assert part["thoughtSignature"] == "EjQKMgER-real"


def test_provider_specific_fields_signature_wins():
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            _tool_call(
                "call_1",
                provider_specific_fields={"thought_signature": "EjQKMgER-psf"},
            )
        ],
    }
    (part,) = convert_to_gemini_tool_call_invoke(message)
    assert part["thoughtSignature"] == "EjQKMgER-psf"


def test_legacy_function_call_branch_gets_the_placeholder():
    message = {
        "role": "assistant",
        "content": None,
        "function_call": {"name": "t", "arguments": '{"x": "1"}'},
    }
    (part,) = convert_to_gemini_tool_call_invoke(message)
    assert part["thoughtSignature"] == GEMINI_THOUGHT_SIGNATURE_BYPASS

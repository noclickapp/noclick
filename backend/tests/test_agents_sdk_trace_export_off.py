"""The OpenAI Agents SDK sends each run's trace (model inputs and outputs) to OpenAI when an OPENAI_API_KEY is set,
whichever model ran; NoClick's agent wrapper turns that off on import, so no run's content leaves that way."""

from agents.tracing import get_trace_provider


def test_importing_the_agent_wrapper_turns_trace_export_off():
    import coder.openai_agent  # noqa: F401

    assert get_trace_provider()._disabled is True

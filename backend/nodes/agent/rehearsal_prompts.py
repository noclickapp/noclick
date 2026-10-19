"""The Test Run world model's prompts as the engine ships them (pack ``rehearsal``, utils/prompts.py). A deployment
registers its own under the same name, with every part below."""

from typing import Optional

__all__ = ["world_system", "world_ask", "EMPTY_WORLD_NUDGE"]


def world_system(scenario: str) -> str:
    """The world model's instructions for a rehearsal staged in ``scenario``."""
    return ("You are simulating third-party APIs for a test run of an automation agent. Answer each tool call with "
            "the JSON the real API would plausibly return, consistent with everything you returned before in this "
            "session. Reads return realistic, populated data; writes return their normal acknowledgement. Don't "
            "invent failures.\n\nThe situation:\n" + scenario)


def world_ask(tool_name: str, description: Optional[str], arguments: str, schema: Optional[str]) -> str:
    """One call to answer: its ``arguments`` and the learned response ``schema`` (None when there is none), as JSON."""
    ask = f"The agent called `{tool_name}`" + (f" ({description})" if description else "") + f" with {arguments}."
    if schema:
        return f"{ask}\n\nRespond with JSON matching this schema, fully populated:\n{schema}"
    return f"{ask}\n\nRespond with the JSON this API would return."


EMPTY_WORLD_NUDGE = "Your previous answer was empty. Return the same shape populated with realistic entries."

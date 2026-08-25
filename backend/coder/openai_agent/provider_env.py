"""Provider-key environment isolation for LiteLLM-backed agent calls."""

import os
from typing import Dict, Optional


_KEY_MASK = {
    "OPENAI_API_KEY": "N/A",
    "ANTHROPIC_API_KEY": "N/A",
    "GOOGLE_API_KEY": "N/A",
    "GEMINI_API_KEY": "N/A",
    "OPENROUTER_API_KEY": "N/A",
}

_KEY_ALIASES = {"GEMINI_API_KEY": "GOOGLE_API_KEY"}


def build_litellm_env(user_env: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Return the scoped environment used for one LiteLLM request.

    User-supplied credentials mask process credentials so one provider can
    never accidentally receive an instance-level key. When no overrides are
    supplied, only missing provider aliases are added.
    """
    if user_env:
        effective = {**_KEY_MASK, **user_env}
        for source, target in _KEY_ALIASES.items():
            if source in user_env:
                effective[target] = user_env[source]
        return effective

    aliases: Dict[str, str] = {}
    for source, target in _KEY_ALIASES.items():
        if source in os.environ and target not in os.environ:
            aliases[target] = os.environ[source]
    return aliases

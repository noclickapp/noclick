"""Helpers for user-supplied execution environment variables.

An ``agent_env`` credential stores ``{NAME: value}`` pairs for an agent's
execution environment. Values are not automatically added to model
instructions; only variable names are described. Programs the agent runs can
still read and transmit environment variables, so operators should scope and
rotate them like any other credential.

Workflow dispatch validates these values here before passing them to an
execution backend.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple


# POSIX-portable environment-variable names keep keys from being reinterpreted
# as shell syntax downstream.
_VALID_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# NoClick owns this namespace for runtime configuration. Rejecting it gives the
# operator a clear error instead of silently ignoring a conflicting value.
_RESERVED_PREFIXES = ("NC_",)

# These variables control process startup and module loading. User-provided
# values could make the execution environment fail before an agent starts.
_RESERVED_RUNTIME = frozenset({
    "PATH", "HOME", "PWD", "SHELL", "USER", "LOGNAME",
    "PYTHONPATH", "PYTHONHOME",
    "LD_PRELOAD", "LD_LIBRARY_PATH",
})

# Provider authentication belongs in the model credential. Keeping it separate
# prevents an auxiliary environment bundle from changing which account or
# endpoint a configured model uses.
_RESERVED_PROVIDER = frozenset({
    "OPENAI_API_KEY", "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
    "CODEX_API_KEY", "CODEX_ACCESS_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY",
})

RESERVED_NAMES = _RESERVED_RUNTIME | _RESERVED_PROVIDER

# Environment values must be strings and remain reasonably bounded.
_MAX_VALUE_LEN = 32_768


def is_reserved(name: str) -> bool:
    return name in RESERVED_NAMES or name.startswith(_RESERVED_PREFIXES)


def validate_env_name(name: str) -> Optional[str]:
    """Return an error for an unusable variable name, otherwise ``None``."""
    if not _VALID_KEY.match(name):
        return (
            f"Invalid environment variable name {name!r}: use letters, digits and "
            f"underscores, and don't start with a digit."
        )
    if is_reserved(name):
        return (
            f"{name!r} is reserved by the execution environment and cannot be "
            f"requested. Provider API keys belong on the agent's model credential; "
            f"NC_* and shell variables are managed by NoClick."
        )
    return None


def normalize_requested_env_vars(
    value: Any,
) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    """Normalize a declared variable request to ``[{name, description}]``.

    Accept a JSON string, one name, or a list containing names and/or
    ``{"name", "description"}`` objects. This declaration contains names only;
    values are supplied separately through an ``agent_env`` credential.
    """
    if value is None or value == "" or value == []:
        return [], None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return None, (
            'agent_env_requested must be a JSON array like ["STRIPE_KEY"] or '
            '[{"name": "STRIPE_KEY", "description": "Your Stripe secret key"}].'
        )

    normalized: List[Dict[str, str]] = []
    seen: set[str] = set()
    for entry in value:
        if isinstance(entry, str):
            entry = {"name": entry}
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            return None, (
                'Each agent_env_requested entry must be "NAME" or '
                '{"name": "NAME", "description": "..."}.'
            )
        name = entry["name"].strip()
        if not name:
            continue
        error = validate_env_name(name)
        if error:
            return None, error
        if name in seen:
            continue
        seen.add(name)
        description = entry.get("description")
        item = {"name": name}
        if isinstance(description, str) and description.strip():
            item["description"] = description.strip()
        normalized.append(item)
    return normalized, None


def requested_env_var_names(config: Optional[Dict[str, Any]]) -> List[str]:
    """Return declared variable names, or an empty list for malformed input."""
    normalized, error = normalize_requested_env_vars(
        (config or {}).get("agent_env_requested")
    )
    if error or not normalized:
        return []
    return [entry["name"] for entry in normalized]


def sanitize_user_env(raw: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Validate an environment bundle and return its normalized string map."""
    if not raw:
        return {}

    clean: Dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            continue
        if not _VALID_KEY.match(name):
            raise ValueError(
                f"Invalid environment variable name {name!r}: use letters, "
                f"digits and underscores, and don't start with a digit."
            )
        if is_reserved(name):
            raise ValueError(
                f"{name!r} is reserved by the execution environment and cannot "
                f"be set. Provider API keys belong on the agent's model credential; "
                f"NC_* and shell variables are managed by NoClick."
            )
        if not isinstance(value, str):
            raise ValueError(
                f"Environment variable {name!r} must be a string, got "
                f"{type(value).__name__}."
            )
        if len(value) > _MAX_VALUE_LEN:
            raise ValueError(
                f"Environment variable {name!r} exceeds {_MAX_VALUE_LEN} characters."
            )
        clean[name] = value
    return clean


def describe_user_env(env: Optional[Dict[str, str]]) -> str:
    """Describe available variable names without exposing their values."""
    if not env:
        return ""
    names = ", ".join(f"${name}" for name in sorted(env))
    return (
        f"These environment variables are set in your shell: {names}. "
        f'Reference them by name (e.g. curl -H "Authorization: Bearer $TOKEN") '
        f"rather than printing their values."
    )

"""Which key funds an operation that runs without a user credential.

``x-credentials-optional`` on an operation's config class says the operation
can run with nothing attached. A few are optional because they are genuinely
free (Reddit's public feed); most are optional because NoClick's own provider
key pays for the call and meters it to credits. Those declare the key:

    model_config = ConfigDict(json_schema_extra=platform_keyed_operation("EXA_API_KEY", byok=True))

``byok`` says whether the node's own credential is an alternative — an Exa
credential replaces the platform key; a LinkedIn credential funds none of the
Apify-backed scraping. The hosted service holds every platform key. A
self-hosted instance holds none unless its operator adds one (environment or
Settings → Self-hosted), so there the marker applies only while the key is
configured. This module is the one place that verdict is made — the builder,
the tool-provider allowlist, the credential UI's backend mirrors and the
runtime all ask it, so "the panel said optional, the run said missing" cannot
happen.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

from utils.edition import is_local_edition

PLATFORM_KEY_MARKER = "x-platform-key"


def platform_keyed_operation(env_var: str, *, byok: bool) -> Dict[str, Any]:
    """``json_schema_extra`` for an operation the platform key pays for."""
    return {"x-credentials-optional": True, PLATFORM_KEY_MARKER: {"env": env_var, "byok": byok}}


def platform_key_of(schema: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    marker = schema.get(PLATFORM_KEY_MARKER)
    return marker if isinstance(marker, dict) and marker.get("env") else None


def platform_key_configured(env_var: str) -> bool:
    return bool((os.environ.get(env_var) or "").strip())


def platform_key_funds(schema: Mapping[str, Any]) -> bool:
    """Whether the credential-optional operation ``schema`` describes can run
    credential-less on THIS installation."""
    marker = platform_key_of(schema)
    if marker is None or not is_local_edition():
        return True
    return platform_key_configured(marker["env"])


def require_platform_key(env_var: str, service: str, *, byok: bool) -> str:
    """The platform key for ``service``; when it is missing, the error names the fix."""
    # `or ""`: tests stub os.environ.get to answer None for an absent key.
    key = (os.environ.get(env_var) or "").strip()
    if key:
        return key
    if is_local_edition():
        alternative = f", or connect your own {service} credential to this node" if byok else ""
        raise RuntimeError(
            f"This operation runs on {service}, and this instance has no {service} key. "
            f"Add it under Settings → Self-hosted ({env_var}){alternative}."
        )
    fix = f"Add your own {service} API key to run this operation." if byok else "Scraping operations are unavailable."
    raise RuntimeError(f"{env_var} is not configured on the server. {fix}")

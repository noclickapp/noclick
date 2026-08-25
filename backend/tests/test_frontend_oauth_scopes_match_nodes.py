"""The frontend connect path must request every scope its node needs.

There are two ways a user connects an OAuth credential, and they read their
scope list from different places:

- the node's ``x-oauth-scopes`` (generated from the backend scope registry), and
- ``frontend/app/utils/oauthProviders.ts``'s hand-written ``defaultScopes``,
  used by ``GenerationCredentialSelector`` — the AI builder's inline connect.

Those had silently diverged on 11 providers. PagerDuty's builder path requested
2 scopes where the node needs 49; Jira's requested 7 of 16, omitting every
Agile scope, so a credential connected that way could not run a single board,
sprint or epic operation. Jira's hand-rolled pre-flight scope check existed to
EXPLAIN those failures — nobody traced them back to the second scope list.

This pins the invariant: whatever the builder path requests must cover what the
node needs. It may request more (auth-flow scopes like ``offline_access`` that
no operation implies); it may never request less.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
PROVIDERS_TS = REPO / "frontend" / "app" / "utils" / "oauthProviders.ts"
SCHEMAS = REPO / "frontend" / "app" / "schemas" / "nodes"

# oauthProviders.ts keys that don't match their node schema's filename even
# after underscore→hyphen normalization.
_KEY_TO_NODE = {
    "atlassian": "jira",
    "github": "github-rest",
    "teams": "microsoft-teams",
    "outlook": "outlook",
}

# Zoom scopes are selected and approved on the Marketplace app itself. Zoom
# rejects a caller-supplied `scope` parameter during authorization, so its
# frontend connection path intentionally does not forward x-oauth-scopes.
_APP_CONFIGURED_SCOPE_PROVIDERS = {"zoom"}


def _find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find(value, key)
            if found is not None:
                return found
    return None


#: Provider entry key, quoted or bare — prettier strips quotes from identifier
#: keys, so both forms occur and the parser must not care.
_ENTRY_KEY = re.compile(r"^\s{4}(?:'([\w-]+)'|([\w-]+)):\s*\{", re.M)


def _frontend_default_scopes() -> dict[str, set[str]]:
    """Map each provider entry to its ``defaultScopes``.

    Brace-depth scan rather than a body regex: the entries contain nested
    objects and arrays, and a lazy ``.*?`` stops at the first closing brace it
    finds, which silently truncates entries and under-reports scopes.
    """
    source = PROVIDERS_TS.read_text()
    out: dict[str, set[str]] = {}

    for match in _ENTRY_KEY.finditer(source):
        key = match.group(1) or match.group(2)
        depth, index = 0, match.end() - 1
        while index < len(source):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        body = source[match.end() : index]

        scopes = re.search(r"defaultScopes:\s*\[(.*?)\]", body, re.S)
        if not scopes:
            continue
        out[key] = {
            part.strip().strip("'\"")
            for part in scopes.group(1).split(",")
            if part.strip().strip("'\"")
        }
    return out


def _node_scopes(key: str) -> set[str] | None:
    """Resolve a provider key to its node schema's requested scopes.

    Provider keys use underscores (``google_slides``) while schema filenames use
    hyphens (``google-slides.json``); missing that mapping silently skipped five
    providers, which is the same blindness this suite exists to prevent.
    """
    candidates = [_KEY_TO_NODE.get(key), key, key.replace("_", "-")]
    for candidate in candidates:
        if not candidate:
            continue
        path = SCHEMAS / f"{candidate}.json"
        if path.exists():
            scopes = _find(json.loads(path.read_text()), "x-oauth-scopes")
            return set(scopes) if scopes else None
    return None


_CASES = sorted(_frontend_default_scopes())


def test_frontend_provider_map_is_parseable():
    """Guard the regex above: a refactor of the TS shape must not silently
    turn this whole suite into a no-op."""
    parsed = _frontend_default_scopes()
    assert len(parsed) >= 20, (
        f"only parsed {len(parsed)} providers out of oauthProviders.ts — the "
        f"file's shape probably changed and this check has gone blind"
    )


@pytest.mark.parametrize("key", _CASES)
def test_frontend_connect_requests_every_scope_the_node_needs(key):
    if key in _APP_CONFIGURED_SCOPE_PROVIDERS:
        pytest.skip(f"{key}: scopes are configured on the provider app")

    node_scopes = _node_scopes(key)
    if node_scopes is None:
        pytest.skip(f"{key}: no node schema or no OAuth scopes")

    frontend_scopes = _frontend_default_scopes()[key]
    missing = node_scopes - frontend_scopes
    assert not missing, (
        f"oauthProviders.ts['{key}'].defaultScopes is missing {len(missing)} "
        f"scope(s) the node requires: {sorted(missing)}.\n"
        f"A credential connected through the AI builder's credential selector "
        f"would be unable to run the operations needing them."
    )

"""The OpenCode model picker must offer only Zen's live servable set.

models.dev/api.json is a historical catalog superset of the opencode/* (Zen)
provider — it keeps models Zen has rotated out (e.g. minimax-m2.5-free), which
the CLI rejects at runtime with ProviderModelNotFoundError. fetch_opencode_models()
filters opencode/* to Zen's /models endpoint so the picker never offers one.

Stubs the two fetch helpers (_fetch_models_dev, _get_zen_servable_ids) via
monkeypatch — no network, no extra deps.
"""

from __future__ import annotations

import types

import pytest

# The picker's catalogue lives with the config helpers now, so every
# edition can render the dropdown; patch it where it's defined.
import nodes.agent.config.harness_model_lists as oc


def _reset_caches():
    oc._OPENCODE_MODELS_CACHE = None
    oc._OPENCODE_MODELS_CACHE_TIME = 0


_MODELS_DEV = {
    "opencode": {
        "name": "OpenCode Zen",
        "models": {
            # In models.dev but rotated out of Zen — must be filtered out.
            "minimax-m2.5-free": {
                "name": "MiniMax M2.5 Free", "tool_call": True,
                "cost": {"input": 0, "output": 0}, "limit": {"context": 204000},
            },
            # Servable — must be offered (and badged free).
            "deepseek-v4-flash-free": {
                "name": "DeepSeek V4 Flash Free", "tool_call": True,
                "cost": {"input": 0, "output": 0}, "limit": {"context": 200000},
            },
        },
    },
    # Non-Zen provider routes via the user's own key — never filtered by Zen.
    "anthropic": {
        "name": "Anthropic",
        "models": {
            "claude-x": {
                "name": "Claude X", "tool_call": True,
                "cost": {"input": 3, "output": 15}, "limit": {"context": 200000},
            },
        },
    },
}


def _stub_fetches(monkeypatch, servable):
    async def _models_dev():
        return _MODELS_DEV

    async def _servable():
        return servable

    monkeypatch.setattr(oc, "_fetch_models_dev", _models_dev)
    monkeypatch.setattr(oc, "_get_zen_servable_ids", _servable)


@pytest.mark.asyncio
async def test_picker_filters_opencode_to_servable_set(monkeypatch):
    _reset_caches()
    _stub_fetches(monkeypatch, {"deepseek-v4-flash-free"})
    opts = await oc.fetch_opencode_models()

    by_value = {o["value"]: o["label"] for o in opts}
    assert "opencode/minimax-m2.5-free" not in by_value   # rotated out → filtered
    assert "opencode/deepseek-v4-flash-free" in by_value   # servable → offered
    assert "anthropic/claude-x" in by_value                # non-Zen unaffected
    # free badge derives from real price (cost==0), not a stale allowlist
    assert "Free" in by_value["opencode/deepseek-v4-flash-free"]


@pytest.mark.asyncio
async def test_zen_failure_drops_opencode_never_superset(monkeypatch):
    """If Zen is unreachable with no cached set, drop opencode/* rather than
    reintroduce the unservable superset — non-Zen providers still populate."""
    _reset_caches()
    _stub_fetches(monkeypatch, None)  # None = Zen unavailable, nothing cached
    opts = await oc.fetch_opencode_models()

    vals = {o["value"] for o in opts}
    assert not any(v.startswith("opencode/") for v in vals)  # no unvalidated Zen
    assert "anthropic/claude-x" in vals                      # rest still works
    _reset_caches()  # don't leak a poisoned cache into other tests






# Raw ProviderModelNotFoundError as opencode emits it on a non-zero exit — the
# picker's catalog can lag rotation / lead on new models, so a passed model can
# still 404 at the binary, which is the real authority.
_PMNF_ERROR = (
    'type=message.updated cause={"failures":[{"error":{"providerID":"opencode",'
    '"modelID":"claude-fable-5","suggestions":["claude-opus-4-8","claude-sonnet-4-6"],'
    '"_tag":"ProviderModelNotFoundError"}}]}'
)





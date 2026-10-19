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
    async def _models_dev(timeout=None):
        return _MODELS_DEV

    async def _servable(tier="opencode", timeout=None):
        return servable if tier == "opencode" else None

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


@pytest.mark.asyncio
async def test_picker_drops_models_the_cli_retired(monkeypatch):
    """opencode drops models.dev entries marked deprecated, for every provider,
    and answers one with ProviderModelNotFoundError (a bare HTTP 500 from
    `opencode serve`), even where Zen still lists the id."""
    _reset_caches()
    catalog = {
        "opencode": {"name": "OpenCode Zen", "models": {
            "old-free": {"name": "Old", "tool_call": True, "status": "deprecated", "cost": {"input": 0, "output": 0}},
            "new-free": {"name": "New", "tool_call": True, "cost": {"input": 0, "output": 0}},
        }},
        "openai": {"name": "OpenAI", "models": {
            "o4-mini": {"name": "o4-mini", "tool_call": True, "status": "deprecated", "cost": {"input": 1, "output": 4}},
            "gpt-5.5": {"name": "GPT-5.5", "tool_call": True, "cost": {"input": 1, "output": 8}},
        }},
    }

    async def _models_dev(timeout=None):
        return catalog

    async def _servable(tier="opencode", timeout=None):
        return {"old-free", "new-free"}

    monkeypatch.setattr(oc, "_fetch_models_dev", _models_dev)
    monkeypatch.setattr(oc, "_get_zen_servable_ids", _servable)
    vals = {o["value"] for o in await oc.fetch_opencode_models()}
    assert vals == {"opencode/new-free", "openai/gpt-5.5"}
    _reset_caches()


# ── run pre-flight: a model the CLI won't run fails before any sandbox ──

_PREFLIGHT_CATALOG = {
    "opencode": {"name": "OpenCode Zen", "models": {
        "deepseek-v4-flash-free": {"name": "DeepSeek V4 Flash Free", "tool_call": True, "status": "deprecated",
                                   "cost": {"input": 0, "output": 0}},
        "big-pickle": {"name": "Big Pickle", "tool_call": True, "cost": {"input": 0, "output": 0}},
        "space-bunny-free": {"name": "Space Bunny Free", "tool_call": True, "cost": {"input": 0, "output": 0}},
        "ling-3.1-flash-free": {"name": "Ling 3.1 Flash Free", "tool_call": True, "cost": {"input": 0, "output": 0}},
        "gpt-6-luna": {"name": "GPT-6 Luna", "tool_call": True, "cost": {"input": 0.1, "output": 0.5}},
    }},
    "openai": {"name": "OpenAI", "models": {
        "o4-mini": {"name": "o4-mini", "tool_call": True, "status": "deprecated", "release_date": "2025-04-16"},
        "gpt-4.1": {"name": "GPT-4.1", "tool_call": True, "release_date": "2025-04-14"},
        "gpt-5.5": {"name": "GPT-5.5", "tool_call": True, "release_date": "2026-05-01"},
        "gpt-5.6-luna": {"name": "GPT-5.6 Luna", "tool_call": True, "release_date": "2026-07-09"},
    }},
    "github-copilot": {"name": "GitHub Copilot", "models": {
        "claude-sonnet-4-5": {"name": "Claude Sonnet 4.5", "tool_call": True},
    }},
}


def _stub_preflight(monkeypatch, *, servable, catalog=_PREFLIGHT_CATALOG, default="opencode/big-pickle"):
    from nodes.agent.config import _cli_models_loader

    async def _models_dev(timeout=None):
        if catalog is None:
            raise OSError("models.dev unreachable")
        return catalog

    async def _servable(tier="opencode", timeout=None):
        return servable if tier == "opencode" else None

    monkeypatch.setattr(oc, "_fetch_models_dev", _models_dev)
    monkeypatch.setattr(oc, "_get_zen_servable_ids", _servable)
    monkeypatch.setattr(_cli_models_loader, "harness_default_model", lambda harness: default)


_ZEN_NOW = {"big-pickle", "space-bunny-free", "ling-3.1-flash-free", "gpt-6-luna"}


async def _hosted(model, env=None):
    return await oc.opencode_model_refusal(model, env, catalog_is_the_cli_list=True)


async def _open_edition(model, env=None):
    return await oc.opencode_model_refusal(model, env, catalog_is_the_cli_list=False)


@pytest.mark.asyncio
async def test_preflight_names_the_gone_zen_model_and_the_default(monkeypatch):
    _stub_preflight(monkeypatch, servable=_ZEN_NOW)
    assert await _hosted("opencode/deepseek-v4-flash-free") == (
        "OpenCode can't run 'opencode/deepseek-v4-flash-free': OpenCode Zen no longer serves it. "
        "Pick another OpenCode Model (opencode_model) on this agent, such as 'opencode/big-pickle'. "
        "Its Model (model) stays 'opencode'."
    )


@pytest.mark.asyncio
async def test_preflight_runs_offered_models(monkeypatch):
    _stub_preflight(monkeypatch, servable=_ZEN_NOW)
    assert await _hosted("opencode/big-pickle") is None
    assert await _hosted("opencode/gpt-6-luna") is None   # paid Zen model
    assert await _hosted("openai/gpt-5.5") is None
    # A provider models.dev doesn't know is a config this can't judge.
    assert await _hosted("acme/house-model") is None


@pytest.mark.asyncio
async def test_hosted_refuses_what_the_cli_retired_or_never_listed(monkeypatch):
    _stub_preflight(monkeypatch, servable=_ZEN_NOW | {"deepseek-v4-flash-free"})
    # Zen still lists it, but the CLI's catalog dropped it as deprecated.
    assert "OpenCode retired it" in await _hosted("opencode/deepseek-v4-flash-free")
    assert "OpenCode retired it" in await _hosted("openai/o4-mini")
    assert "isn't in OpenCode's model list" in await _hosted("openai/gpt-9-imaginary")


@pytest.mark.asyncio
async def test_copilot_models_are_never_judged_by_models_dev(monkeypatch):
    """With a Copilot sign-in the CLI's Copilot plugin replaces that provider's
    list with Copilot's live /models, so an id models.dev lacks still runs."""
    _stub_preflight(monkeypatch, servable=_ZEN_NOW)
    assert await _hosted("github-copilot/gpt-4.1") is None
    assert await _hosted("github-copilot/claude-sonnet-4-5") is None


@pytest.mark.asyncio
async def test_open_edition_never_refuses_on_models_dev(monkeypatch):
    """The open edition keeps the operator's own opencode config, whose models
    the CLI merges in (an LM Studio model, say): only Zen's live list judges."""
    _stub_preflight(monkeypatch, servable=_ZEN_NOW)
    assert await _open_edition("lmstudio/google/gemma-3n-e4b") is None
    assert await _open_edition("openai/my-config-model") is None
    assert await _open_edition("openai/o4-mini") is None
    assert "OpenCode Zen no longer serves it" in await _open_edition("opencode/deepseek-v4-flash-free")


@pytest.mark.asyncio
async def test_suggestions_stay_on_the_provider_the_credential_reaches(monkeypatch):
    """A Zen model is suggested only to an agent on Zen: an OpenAI agent is
    offered OpenAI's newest offered models, and a ChatGPT-plan-only one just
    those its plan runs."""
    _stub_preflight(monkeypatch, servable=_ZEN_NOW)
    refusal = await _hosted("openai/o4-mini", {"OPENAI_API_KEY": "sk-x"})
    assert refusal.endswith("such as 'openai/gpt-5.6-luna', 'openai/gpt-5.5', 'openai/gpt-4.1'. "
                            "Its Model (model) stays 'opencode'.")
    monkeypatch.setattr(oc, "_is_chatgpt_plus_supported", lambda model_id: model_id == "gpt-5.5")
    refusal = await _hosted("openai/o4-mini", {"CODEX_ACCESS_TOKEN": "t"})
    assert refusal.endswith("such as 'openai/gpt-5.5'. Its Model (model) stays 'opencode'.")


@pytest.mark.asyncio
async def test_preflight_offers_free_zen_models_when_the_default_is_gone_too(monkeypatch):
    _stub_preflight(monkeypatch, servable={"space-bunny-free", "ling-3.1-flash-free", "gpt-6-luna"})
    refusal = await _hosted("opencode/big-pickle")
    assert refusal.startswith("OpenCode can't run 'opencode/big-pickle': OpenCode Zen no longer serves it.")
    # Free and served, never the paid one or the gone default.
    assert refusal.endswith("such as 'opencode/ling-3.1-flash-free', 'opencode/space-bunny-free'. "
                            "Its Model (model) stays 'opencode'.")


@pytest.mark.asyncio
async def test_preflight_judges_nothing_it_cannot_read(monkeypatch):
    _stub_preflight(monkeypatch, servable=None, catalog=None)
    assert await _hosted("opencode/deepseek-v4-flash-free") is None
    assert await _hosted("openai/o4-mini") is None
    # Zen readable, models.dev not: the gateway's word alone still refuses.
    _stub_preflight(monkeypatch, servable=_ZEN_NOW, catalog=None)
    refusal = await _hosted("opencode/deepseek-v4-flash-free")
    assert "OpenCode Zen no longer serves it" in refusal
    assert "'opencode/big-pickle'" in refusal


@pytest.mark.asyncio
async def test_local_runner_judges_only_zen_and_refuses_before_starting_the_cli(monkeypatch, tmp_path):
    """The open edition's runner asks with its own scope and fails the turn
    with the pre-flight's words before it spawns anything."""
    from nodes.agent import local_harness

    _stub_preflight(monkeypatch, servable=_ZEN_NOW)
    asked = []
    real = oc.opencode_model_refusal

    async def spy(model, env=None, **scope):
        asked.append(scope)
        return await real(model, env, **scope)

    monkeypatch.setattr(oc, "opencode_model_refusal", spy)
    monkeypatch.setattr(local_harness, "_workspace_dir", lambda *a: tmp_path)
    node = types.SimpleNamespace(workflow_id="wf", node_id="agent", conversation_id="c")
    config = types.SimpleNamespace(conversation_key="k", opencode_model="opencode/deepseek-v4-flash-free")
    with pytest.raises(ValueError, match="OpenCode Zen no longer serves it"):
        await local_harness.run_local_harness_turn(node, config, {}, "u", {}, [], model_type="opencode")
    assert asked == [{"catalog_is_the_cli_list": False}]

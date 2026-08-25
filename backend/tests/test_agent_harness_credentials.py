"""Builder credential pipeline for AI agent nodes (harness credentials).

The rule under test: CLI harnesses (codex / claude-code / opencode / openclaw /
hermes) ALWAYS require a user credential — harness runs have no per-call cost
capture, so platform keys can't fund them. The only credential-free agent
configs are the SDK LLM path on an openrouter/* model (platform key + cost
capture) and the media model types (flat per-unit pricing). Pins the fix for
the "builder declares done, user hits disconnected-credential on the agent
node" failure (extension run 068428db, wf 4b71f9bf).
"""

import re
from pathlib import Path

import pytest

from nodes.agent.config.providers import (
    AGENT_OAUTH_CREDENTIAL_TYPES,
    HARNESS_SUBMODEL_FIELDS,
    WRAPPER_ID_BY_MODEL_TYPE,
    agent_credential_requirement,
    agent_credential_types,
    resolve_agent_cred_model,
)
from coder.workflow.operation_catalog import (
    credential_status_line,
    get_credential_info,
    known_credential_types,
    node_accepted_credential_types,
    node_requires_credentials,
)
from coder.workflow.graph_state import GraphState, NodeState


# ---------------------------------------------------------------------------
# Predicate truth table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("config", [
    {},  # default model is the LLM openrouter default
    {"model": "openrouter/~openai/gpt-mini-latest"},
    {"model": "openrouter/anthropic/claude-sonnet-4-5"},
    {"model": "gemini-image-generator"},   # image → platform key, flat pricing
    {"model": "veo-3.0-generate-001"},     # video
    {"model": "kling-v3"},                 # kling
])
def test_no_user_credential_needed(config):
    assert agent_credential_requirement(config).required is False


@pytest.mark.parametrize("config,expected_type,expected_oauth", [
    # CLI harnesses always require — including openrouter sub-models
    # (the case that motivated this: no harness cost tracking → no platform key).
    ({"model": "codex"}, "agent_codex", "agent_codex_oauth"),
    ({"model": "claude-code"}, "agent_claude_code", "agent_claude_code_oauth"),
    ({"model": "opencode"}, "agent_opencode", None),  # Zen default sub-model
    ({"model": "opencode", "opencode_model": "anthropic/claude-sonnet-4-5"},
     "agent_anthropic", "agent_claude_code_oauth"),
    ({"model": "openclaw"}, "agent_openrouter", None),  # default sub is openrouter/*
    ({"model": "hermes"}, "agent_openrouter", None),    # default sub is openrouter/*
    ({"model": "hermes", "hermes_agent_model": "xai/grok-4"},
     "agent_xai", None),
    ({"model": "openclaw", "openclaw_model": "openai/gpt-5"},
     "agent_openai", "agent_codex_oauth"),
    # SDK LLM path on a non-openrouter model needs the user's provider key
    # (platform keys are ENV_MASKed) — but never subscription OAuth.
    ({"model": "anthropic/claude-sonnet-4-5"}, "agent_anthropic", None),
])
def test_user_credential_required(config, expected_type, expected_oauth):
    req = agent_credential_requirement(config)
    assert req.required is True
    assert req.credential_type == expected_type
    assert expected_type in req.accepted_types
    assert "agent_api_key" in req.accepted_types  # legacy generic bundles
    if expected_oauth:
        assert expected_oauth in req.accepted_types
    else:
        assert not any(t.endswith("_oauth") for t in req.accepted_types)


def test_model_type_only_config_resolves_wrapper():
    # Discriminated configs may carry model_type without a model string.
    req = agent_credential_requirement({"model_type": "codex"})
    assert req.required is True
    assert req.credential_type == "agent_codex"


def test_resolve_agent_cred_model_accepts_dict_and_object():
    # The execute path passes the validated Pydantic config; builder paths
    # pass raw dicts — one rule for both.
    from nodes.agent.config import HermesAgentConfig

    cfg_obj = HermesAgentConfig(model="hermes", message="hi")
    assert resolve_agent_cred_model(cfg_obj) == cfg_obj.hermes_agent_model
    assert resolve_agent_cred_model(
        {"model": "hermes", "hermes_agent_model": "xai/grok-4"}
    ) == "xai/grok-4"
    # Dict missing the sub-model falls back to the schema default.
    assert resolve_agent_cred_model({"model": "hermes"}) == cfg_obj.hermes_agent_model
    # codex/claude-code keep the wrapper id; non-wrappers pass through.
    assert resolve_agent_cred_model({"model": "codex", "codex_model": "gpt-5"}) == "codex"
    assert resolve_agent_cred_model({"model": "anthropic/claude-sonnet-4-5"}) == "anthropic/claude-sonnet-4-5"


# ---------------------------------------------------------------------------
# Registry mirrors — providers.py is the ONE backend registry; the FE mirrors
# (TS can't import it) and the OAuth handlers (minting sites) must stay in sync
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_repo_file(rel: str) -> str:
    path = _REPO_ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not present in this checkout")
    return path.read_text()


def _parse_ts_map(source: str, name: str) -> dict:
    block = re.search(rf"{name}[^=]*=\s*\{{(.*?)\}}", source, re.S)
    assert block, f"{name} not found"
    return dict(re.findall(r"['\"]?([\w-]+)['\"]?\s*:\s*['\"]([\w-]+)['\"]", block.group(1)))


class TestRegistryMirrors:
    def test_fe_wrapper_submodel_fields_match(self):
        src = _read_repo_file("frontend/app/lib/agentCredentialModel.ts")
        fe = _parse_ts_map(src, "WRAPPER_SUBMODEL_FIELD_BY_MODEL")
        assert fe == HARNESS_SUBMODEL_FIELDS

    def test_fe_cli_model_provider_matches(self):
        src = _read_repo_file("frontend/app/lib/agentChat.ts")
        fe = _parse_ts_map(src, "CLI_MODEL_PROVIDER")
        assert fe == {wrapper: mt for mt, wrapper in WRAPPER_ID_BY_MODEL_TYPE.items()}

    def test_fe_knows_every_oauth_credential_type(self):
        src = _read_repo_file("frontend/app/lib/agentCredentialModel.ts")
        for cred_type in set(AGENT_OAUTH_CREDENTIAL_TYPES.values()):
            assert cred_type in src, f"{cred_type} missing from agentCredentialModel.ts"



# ---------------------------------------------------------------------------
# operation_catalog wiring
# ---------------------------------------------------------------------------

def test_node_requires_credentials_agent_is_config_sensitive():
    assert node_requires_credentials("agent", None, {"model": "openrouter/x"}) is False
    assert node_requires_credentials("agent", None, {"model": "openclaw"}) is True


def test_accepted_types_for_agent():
    # agent_env is an accepted ATTACH target (a NON-PRIMARY secondary — sandbox
    # env vars), so set_credentials can file it onto an agent. It must NOT be in
    # agent_credential_requirement().accepted_types, or it would satisfy the MODEL
    # credential — that separation is asserted below.
    accepted = node_accepted_credential_types("agent", None, {"model": "codex"})
    assert accepted == {"agent_codex", "agent_api_key", "agent_codex_oauth", "agent_env"}
    # Even a platform-billed agent (no model credential needed) still accepts an
    # env bundle as an attach target.
    assert node_accepted_credential_types("agent", None, {"model": "openrouter/x"}) == {"agent_env"}


def test_agent_env_is_attachable_but_not_model_satisfying():
    from nodes.agent.config.providers import agent_credential_requirement

    cfg = {"model": "codex"}
    assert "agent_env" in node_accepted_credential_types("agent", None, cfg)
    assert "agent_env" not in agent_credential_requirement(cfg).accepted_types


def test_known_credential_types_include_agent_types():
    kt = known_credential_types()
    assert {
        "agent_api_key", "agent_codex", "agent_claude_code", "agent_opencode",
        "agent_openrouter", "agent_anthropic", "agent_codex_oauth",
        "agent_claude_code_oauth",
    } <= set(kt)
    assert set(agent_credential_types()) <= set(kt)


def test_get_credential_info_agent():
    info = get_credential_info("agent", None, {"model": "claude-code"})
    assert info is not None
    # provider_key doubles as the FE credentialIds map key — must be the DB type.
    assert info.provider_key == "agent_claude_code"
    assert info.credential_type == "agent_claude_code"
    assert info.is_oauth is False
    assert get_credential_info("agent", None, {"model": "openrouter/x"}) is None


class TestCredentialStatusLine:
    def test_needed_line_names_search_type(self):
        line = credential_status_line("agent", None, {"model": "codex"}, "agent-1")
        assert line.startswith("[credentials needed:")
        assert 'type="agent_codex"' in line
        assert "OPENAI_API_KEY" in line

    def test_attached_via_primary_type(self):
        line = credential_status_line(
            "agent", None,
            {"model": "codex", "credentialIds": {"agent_codex": "c1"}}, "agent-1",
        )
        assert line == "[credentials: codex ✓]"

    def test_attached_via_oauth_alias(self):
        line = credential_status_line(
            "agent", None,
            {"model": "codex", "credentialIds": {"agent_codex_oauth": "c1"}}, "agent-1",
        )
        assert line == "[credentials: codex ✓]"

    def test_platform_billed_gets_positive_line(self):
        # The positive signal stops the brain pattern-matching
        # "agent node → connect account" for platform-billed models.
        line = credential_status_line(
            "agent", None, {"model": "openrouter/~openai/gpt-mini-latest"}, "agent-1",
        )
        assert line == (
            "[credentials: not required — this model runs on NoClick's "
            "platform key and is billed per use]"
        )


# ---------------------------------------------------------------------------
# <ask field="credential"> on agent nodes
# ---------------------------------------------------------------------------

def _agent_state(config):
    state = GraphState()
    state.nodes["agent-1"] = NodeState(
        id="agent-1", type="agent", label="Agent", goal="research",
        operation=None, config=config,
    )
    return state


class TestAgentCredentialAsk:
    def test_ask_allowed_for_harness_and_carries_form_context(self):
        from coder.workflow.agentic.commands import extract_ask_requests
        from coder.workflow.workflow_xml import XmlOp
        config = {"model": "codex", "message": "do research"}
        ops = [XmlOp(tag="ask",
                     attrs={"node": "agent-1", "field": "credential", "label": "Connect?"},
                     body=None)]
        requests, rejections = extract_ask_requests(ops, _agent_state(config))
        assert rejections == []
        assert len(requests) == 1
        req = requests[0]
        assert req["type"] == "credential"
        assert req["nodeType"] == "agent"
        assert req["credentialType"] == "agent_codex"
        # The FE agent credential form is harness/sub-model sensitive — the
        # ask must carry the node's config so it renders the right fields.
        assert req["nodeConfig"]["model"] == "codex"
        assert req["credentialIds"] == {}

    def test_ask_rejected_for_platform_billed_llm(self):
        from coder.workflow.agentic.commands import extract_ask_requests
        from coder.workflow.workflow_xml import XmlOp
        ops = [XmlOp(tag="ask",
                     attrs={"node": "agent-1", "field": "credential", "label": "Connect?"},
                     body=None)]
        requests, rejections = extract_ask_requests(
            ops, _agent_state({"model": "openrouter/~openai/gpt-mini-latest"}),
        )
        assert requests == []
        assert any("does not require credentials" in r for r in rejections)

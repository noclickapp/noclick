"""Every node parses its credentials under every row type it can be attached with.

The credentials ROW type is authoritative: `utils.credentials.get_credential`
stamps it onto the decrypted blob before the node's config model sees it. A
credential model whose `credential_type` is narrower than the row types the
attach paths can file under it fails at parse in production while every static
check stays green — the agent's single literal did exactly that (2026-09-07).
This walks the whole registry so the next such gap fails here first.
"""
from typing import Literal

from coder.workflow.operation_catalog import node_accepted_credential_types
from nodes.agent.config.providers import agent_credential_types
from nodes.core.registry import NODE_REGISTRY

from nodes.core.base import credential_type_literals


def _row_types_for(node_type: str) -> set:
    accepted = set(node_accepted_credential_types(node_type))
    if node_type == "agent":
        accepted |= set(agent_credential_types())
    return accepted


def _gaps(registry) -> list[str]:
    gaps = []
    for node_type, node_class in sorted(registry.items()):
        config_model = node_class.get_config_model()
        if config_model is None or "credentials" not in getattr(config_model, "model_fields", {}):
            continue
        covered = credential_type_literals(config_model)
        if covered is None:
            continue
        missing = _row_types_for(node_type) - covered
        if missing:
            gaps.append(f"{node_type}: model accepts {sorted(covered)} but rows can be {sorted(missing)}")
    return gaps


def test_every_node_credential_model_accepts_the_row_types_it_can_hold():
    assert _gaps(NODE_REGISTRY) == []


def test_the_guard_bites_on_a_single_literal_agent_model():
    from pydantic import Field
    from nodes.agent.config import AgentCredentials, AgentNodeConfig
    from nodes.core.base import NodeConfig

    class NarrowCredentials(AgentCredentials):
        credential_type: Literal["agent_api_key"] = Field("agent_api_key")

    class NarrowConfig(NodeConfig[AgentNodeConfig.model_fields["config"].annotation, NarrowCredentials]):
        pass

    class NarrowAgent(NODE_REGISTRY["agent"]):
        @classmethod
        def get_config_model(cls):
            return NarrowConfig

    (gap,) = _gaps({"agent": NarrowAgent})
    assert "agent_codex_oauth" in gap and "agent_openrouter" in gap

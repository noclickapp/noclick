"""Every node parses its credentials under every row type it can be attached with.

The credentials ROW type is authoritative: `utils.credentials.get_credential`
stamps it onto the decrypted blob before the node's config model sees it. A
credential model whose `credential_type` is narrower than the row types the
attach paths can file under it fails at parse in production while every static
check stays green — the agent's single literal did exactly that (2026-09-07).
This walks the whole registry so the next such gap fails here first.
"""
from typing import Annotated, Literal, Union, get_args, get_origin

from coder.workflow.operation_catalog import node_accepted_credential_types
from nodes.agent.config.providers import agent_credential_types
from nodes.core.registry import NODE_REGISTRY

ANY = object()


def _member_models(annotation):
    origin = get_origin(annotation)
    if origin is Annotated:
        return _member_models(get_args(annotation)[0])
    if origin is Union or str(origin) == "<class 'types.UnionType'>":
        return [m for arg in get_args(annotation) for m in _member_models(arg)]
    return [annotation] if hasattr(annotation, "model_fields") else []


def _accepted_by(member) -> set | object:
    field = member.model_fields.get("credential_type")
    if field is None:
        return ANY
    annotation = field.annotation
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    if get_origin(annotation) is Union:
        values: set = set()
        for arg in get_args(annotation):
            if get_origin(arg) is Literal:
                values.update(get_args(arg))
            elif arg is str:
                return ANY
        return values
    if get_origin(annotation) is Literal:
        return set(get_args(annotation))
    return ANY if annotation is str else set()


def _row_types_for(node_type: str) -> set:
    accepted = set(node_accepted_credential_types(node_type))
    if node_type == "agent":
        accepted |= set(agent_credential_types())
    return accepted


def _gaps(registry) -> list[str]:
    gaps = []
    for node_type, node_class in sorted(registry.items()):
        config_model = node_class.get_config_model()
        field = getattr(config_model, "model_fields", {}).get("credentials") if config_model else None
        if field is None:
            continue
        members = _member_models(field.annotation)
        if not members:
            continue
        accepted = [_accepted_by(m) for m in members]
        if any(a is ANY for a in accepted):
            continue
        covered = set().union(*accepted)
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

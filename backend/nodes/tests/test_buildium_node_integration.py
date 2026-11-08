"""Buildium integration with staging discovery and credential validation."""
from copy import deepcopy
import pytest
from nodes import buildium_node as B
from nodes.tests.test_buildium_node_mock import AUTH, world


def test_discovered_node_and_credential_family():
    from nodes.core.registry import NODE_REGISTRY
    assert NODE_REGISTRY[B.NODE_TYPE] is B.BuildiumNode
    config = B.BuildiumNode.parse_config({"credentials": deepcopy(AUTH), "config": {"operation": "check_connection"}})
    assert config.credentials.credential_type == B.FAMILY


@pytest.mark.asyncio
async def test_connection_validation_checks_provider_reachability(world):
    result = await B.BuildiumNode.validate_credential_access(deepcopy(AUTH))
    assert result == {"valid": True, "proves": "reachability", "identity_verified": False}
    assert len(world.calls) == 1


@pytest.mark.asyncio
async def test_connection_validation_rejects_failed_provider(world):
    import httpx
    world.override = lambda _: httpx.Response(403, json={"error": "PRIVATE-PROVIDER"})
    result = await B.BuildiumNode.validate_credential_access(deepcopy(AUTH))
    assert result["valid"] is False
    assert "PRIVATE-" not in str(result)

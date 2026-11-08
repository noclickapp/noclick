"""Axonaut access validation using staging's native node hook."""
import pytest
from nodes.tests.test_axonaut_node_mock import native, ensure_native_db_pool, KEY

async def test_access_identity(native):
    from nodes.axonaut_node import AxonautNode
    assert await AxonautNode.validate_credential_access({"api_key": KEY}) == {"valid": True, "name": "Fixture operator"}

@pytest.mark.parametrize("status,valid", [(401, False), (403, False), (429, None), (503, None)])
async def test_access_provider_failure(native, status, valid):
    from nodes.axonaut_node import AxonautNode
    native.replies[("GET", "me")] = (status, {"message": KEY})
    result = await AxonautNode.validate_credential_access({"api_key": KEY})
    assert result["valid"] is valid and KEY not in str(result)

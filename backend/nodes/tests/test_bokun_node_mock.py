"""Bókun uses staging's standard credential lifecycle for static keys and tokens.
These checks replace tests for the original PR's unshipped shared authority adapter.
"""
import pytest
from nodes.bokun_node import BokunNode, credential_shape
from nodes.core.base import WorkflowNode

KEY = {"credential_type": "bokun_rest_keys", "access_key": "synthetic-access-key-001", "secret_key": "synthetic-secret-key-001", "environment": "sandbox"}

@pytest.mark.asyncio
async def test_static_credentials_use_staging_noop_refresh():
    assert BokunNode.freshen_credential.__func__ is WorkflowNode.freshen_credential.__func__
    value = dict(KEY)
    assert await BokunNode.freshen_credential(value) is value

@pytest.mark.parametrize("changes", [{"credential_type": "other"}, {"access_key": ""}, {"secret_key": "private\nvalue"}, {"environment": "unknown"}])
def test_invalid_credential_shape_is_rejected_without_secret_disclosure(changes):
    with pytest.raises(ValueError) as caught:
        credential_shape({**KEY, **changes})
    assert KEY["secret_key"] not in str(caught.value)
    assert "private" not in str(caught.value)

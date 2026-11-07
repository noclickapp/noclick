"""Exercise Creem through staging's operation dispatcher and connection probe.

Provider HTTP is mocked by the same fixture as the node transport tests.
"""
from nodes.tests.test_creem_node_mock import native, BLOB, FAMILY, USER


async def test_creem_dispatcher_uses_loaded_api_key(native):
    from nodes.core.run_op import run_node_operation
    result = await run_node_operation(node_type="automation-creem", operation="list_products", arguments={}, user_id=USER, credential_data=BLOB)
    assert result["status"] == "success"
    assert native.requests[-1].headers["x-api-key"] == BLOB["api_key"]


async def test_creem_connection_probe(native):
    from nodes.core.credential_connect import validate_for_connect
    result = await validate_for_connect(credential_type=FAMILY, credential_data=BLOB, user_id=USER)
    assert result.ok
    assert native.requests[-1].url.path == "/v1/products/search"

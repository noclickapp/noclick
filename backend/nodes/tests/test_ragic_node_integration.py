"""Credential access hook integration with the same request/parser as execution."""
import pytest
from nodes.tests.test_ragic_node_mock import native, ensure_native_db_pool, BLOB, RECORD


async def test_validation_without_witness_makes_no_request(native):
    from nodes.ragic_node import RagicNode
    result = await RagicNode.validate_credential_access(BLOB)
    assert result['valid'] is None
    assert native.requests == []


async def test_validation_uses_exact_paired_witness_and_discards_fields(native):
    from nodes.ragic_node import RagicNode
    result = await RagicNode.validate_credential_access({**BLOB, 'witness_record_id': RECORD, 'witness_field_id': 1000001})
    assert result['valid'] is True
    assert 'data' not in result and 'name' not in result
    assert len(native.requests) == 1
    assert native.requests[0].url.params.get_list('fetchDomainIds') == ['1000001']


@pytest.mark.parametrize('change', [{'server': 'evil.test'}, {'credential_type': 'slack_oauth'}, {'witness_record_id': RECORD}])
async def test_validation_refuses_invalid_credentials_without_http(native, change):
    from nodes.ragic_node import RagicNode
    result = await RagicNode.validate_credential_access({**BLOB, **change})
    assert result['valid'] is False and native.requests == []


async def test_validation_does_not_accept_provider_rejection(native):
    from nodes.ragic_node import RagicNode
    native.reply = (403, {'status': 'ERROR'})
    result = await RagicNode.validate_credential_access({**BLOB, 'witness_record_id': RECORD, 'witness_field_id': 1000001})
    assert result['valid'] is False

"""Exercise staging's real connect seam with the free PDL Cleaner probe."""
import json
import pytest
from nodes.tests.test_people_data_labs_node_mock import native, ensure_native_db_pool, USER, FAMILY, BLOB, KEY


async def test_connect_proves_reachability_without_account_identity_or_paid_query(native):
    from nodes.core.credential_connect import shape_credential, validate_for_connect
    shaped, errors, resolved = shape_credential(FAMILY, BLOB)
    assert not errors and shaped == BLOB
    assert resolved[0] == 'automation-people-data-labs'
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data=BLOB, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert verdict.evidence.samples == [] and verdict.evidence.account_label is None
    assert 'verified_as' not in verdict.verified_metadata()
    assert [r.url.path for r in native.requests] == ['/v5/company/clean']


async def test_connect_provider_authentication_rejection_is_not_a_false_green(native):
    from nodes.core.credential_connect import validate_for_connect
    native.replies['company/clean'] = (401, {'status': 401, 'error': {'message': KEY}})
    result = await validate_for_connect(credential_type=FAMILY, credential_data=BLOB, user_id=USER)
    assert not result.ok and result.evidence.reachable is False
    assert KEY not in json.dumps(result.verified_metadata()) and KEY not in (result.rejection or '')


@pytest.mark.parametrize('status', [429, 503])
async def test_connect_outage_or_rate_limit_remains_unverified(native, status):
    from nodes.core.credential_connect import validate_for_connect
    native.replies['company/clean'] = (status, {'status': status})
    result = await validate_for_connect(credential_type=FAMILY, credential_data=BLOB, user_id=USER)
    assert result.ok and result.evidence.reachable is None
    assert result.verified_metadata() == {}


@pytest.mark.parametrize('payload', [{'status': 200}, {'status': 200, 'id': ''}, {'status': 200, 'id': KEY}])
async def test_connection_refuses_malformed_cleaner_response(native, payload):
    native.replies['company/clean'] = (200, payload)
    result = await native.run('check_connection')
    assert result['status'] == 'error' and KEY not in json.dumps(result)


async def test_saved_validation_uses_free_probe_and_explains_entitlement_limit(native):
    from nodes.people_data_labs_node import PeopleDataLabsNode
    result = await PeopleDataLabsNode.validate_credential_access(BLOB)
    assert result['valid'] is True and 'remain unverified' in result['hint']
    assert [r.url.path for r in native.requests] == ['/v5/company/clean']


async def test_provider_documented_cleaner_response(native):
    from pathlib import Path
    # Complete JSON example, copied verbatim in value from PDL's quickstart:
    # https://docs.peopledatalabs.com/docs/quickstart-cleaner-apis
    response = json.loads((Path(__file__).parent / 'fixtures/people-data-labs/company-clean.json').read_text())
    native.replies['company/clean'] = (200, response)
    result = await native.run('check_connection')
    assert result['status'] == 'success' and set(result['data']) == {'proof'}
    assert response['ticker'] is None

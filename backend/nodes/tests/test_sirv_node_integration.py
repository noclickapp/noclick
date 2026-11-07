"""Sirv registration, discovery and staging credential-loading seams."""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from nodes import sirv_node as R
from nodes.tests.test_sirv_node_mock import AUTH, USER, args, world


def test_public_discovery_supplied_expiry_scope_and_native_not_oauth():
    from utils.credential_request_routes import _get_credential_fields, _get_oauth_provider
    schema = R.SirvNode.get_config_schema()['$defs']['SirvAccessTokenCredential']
    assert _get_oauth_provider(R.FAMILY) is None
    assert schema['title'] == 'Sirv Access Token'
    assert schema['properties']['credential_type']['const'] == R.FAMILY
    assert {'access_token', 'root_folder', 'expires_at', 'scope'} <= set(schema['required'])
    assert schema['properties']['access_token']['ui:sensitive'] is True
    assert not schema.get('x-oauth-provider') and 'refresh_token' not in schema['properties']
    fields = _get_credential_fields(R.FAMILY)
    assert {'access_token', 'root_folder', 'expires_at', 'scope'} <= {f['name'] for f in fields}


@pytest.mark.asyncio
async def test_registered_operation_uses_staging_runner(world):
    from nodes.core.run_op import run_node_operation
    result = await run_node_operation(node_type=R.NODE_TYPE, operation='list_folder',
        arguments=args('list_folder'), credential_data=deepcopy(AUTH), user_id=USER)
    assert result['read_completed'] is True and result['identity_verified'] is False
    assert all(req.url.path in {'/v2/files/stat', '/v2/files/readdir'} for req in world.calls)


@pytest.mark.asyncio
async def test_unsaved_connection_evidence_uses_root_picker(world):
    from nodes.core.connection_evidence import collect_evidence
    result = await collect_evidence(node_type=R.NODE_TYPE, credential_data=deepcopy(AUTH), user_id=USER)
    assert result.reachable is True
    assert R.SirvNode.connection_evidence.proves == 'reachability'
    assert result.account_label is None and result.answers_field == 'root_folder'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['pending_approval', 'rejected'])
async def test_saved_evidence_admission_precedes_transport(world, monkeypatch, status):
    from nodes.core.connection_evidence import collect_evidence
    from utils import credentials, credential_approval
    resolve = AsyncMock(return_value=deepcopy(AUTH))
    admit = AsyncMock(return_value={'status': status})
    monkeypatch.setattr(credentials, 'resolve_credential_with_owner_fallback', resolve)
    monkeypatch.setattr(credential_approval, 'admit_lookup', admit)
    result = await collect_evidence(node_type=R.NODE_TYPE, credential_id='saved-sirv', user_id=USER)
    assert result.reachable is None and result.samples == []
    resolve.assert_awaited_once()
    admit.assert_awaited_once()
    assert world.calls == []

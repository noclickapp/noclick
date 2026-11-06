"""Actual native factory/connect/admission/current-row seams, prepared UNRUN."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from nodes.core.registry import NodeFactory
from nodes.jwplayer_node import FAMILY, OPERATIONS, JWPlayerError, JWPlayerNode
from nodes.tests.test_jwplayer_node_mock import MEDIA, PLAYLIST, SITE, TOKEN

ACTOR = '11111111-1111-4111-8111-111111111111'
CID = '22222222-2222-4222-8222-222222222222'


def stored_data():
    return {'credentialIds': {FAMILY: CID}, 'credentials': {'credential_type': FAMILY, 'api_secret': TOKEN, 'site_id': SITE}, 'config': {'operation': 'list_media'}}


def test_real_factory_all_five_operations_original_raw_guards_and_validation_parity():
    for operation in OPERATIONS:
        data = stored_data(); data['config']['operation'] = operation
        if operation == 'get_media': data['config']['media_id'] = MEDIA
        if operation == 'get_playlist': data['config']['playlist_id'] = PLAYLIST
        node = NodeFactory.create_node('native', 'automation-jwplayer', data, user_id=ACTOR)
        assert isinstance(node, JWPlayerNode) and node.config.config.operation == operation
    for key, value in [('page', True), ('page_length', '7'), ('include_names', 'false')]:
        data = stored_data(); data['config'][key] = value
        assert JWPlayerNode.validate_config(data)['valid'] is False
        with pytest.raises(ValueError): JWPlayerNode.parse_config(data)
    for value in (7, True, 'https://api.jwplayer.com/v2/media/Ny05CEfj', 'short'):
        data = stored_data(); data['config'] = {'operation': 'get_media', 'media_id': value}
        assert JWPlayerNode.validate_config(data)['valid'] is False
        with pytest.raises(ValueError): NodeFactory.create_node('n', 'automation-jwplayer', data)
    for key, value in [('credential_type', 'foreign_family'), ('api_secret', 7), ('site_id', 12345678)]:
        data = stored_data(); data['credentials'][key] = value
        with pytest.raises(ValueError): NodeFactory.create_node('n', 'automation-jwplayer', data)
    data = stored_data(); data['credentials'].pop('credential_type')
    with pytest.raises(ValueError, match='family tag'): NodeFactory.create_node('n', 'automation-jwplayer', data)
    data = stored_data(); data['config'] = {'operation': 'get_media', 'media_id': '{{vars.media_id}}'}
    assert NodeFactory.create_node('n', 'automation-jwplayer', data).config.config.media_id == '{{vars.media_id}}'


@pytest.mark.asyncio
async def test_manual_connect_actual_property_catalog_probe_does_not_claim_identity(monkeypatch):
    from nodes.core.credential_connect import validate_for_connect
    request = AsyncMock(return_value={'media': []})
    monkeypatch.setattr(JWPlayerNode, '_request', request)
    verdict = await validate_for_connect(credential_type=FAMILY, credential_data={'api_secret': TOKEN, 'site_id': SITE}, user_id=ACTOR, pool=object())
    assert verdict.ok and verdict.evidence.reachable is True and JWPlayerNode.connection_evidence.proves == 'reachability'
    assert not verdict.evidence.account_label and request.await_count == 1
    assert request.await_args.args[0] == '/media/'


@pytest.mark.asyncio
async def test_native_saved_map_reaches_real_admission_before_http(monkeypatch):
    import utils.credential_approval as admission
    admit = AsyncMock(return_value={'id': CID, 'status': 'rejected', 'new_request': False})
    monkeypatch.setattr(admission.CredentialApprovalRepo, 'admit', admit)
    monkeypatch.setattr(admission, 'get_native_pool', lambda: object())
    node = NodeFactory.create_node('n', 'automation-jwplayer', stored_data(), user_id=ACTOR)
    node._request = AsyncMock(side_effect=AssertionError('No HTTP'))
    result = await node.run({})
    assert result['executed'] is False and result['status'] == 'rejected'
    assert admit.await_args.kwargs['credential_id'] == CID
    node._request.assert_not_called()


@pytest.mark.asyncio
async def test_current_canonical_share_row_native_type_property_version_and_no_graph_free_fallback(monkeypatch):
    import utils.database_pool as db
    import utils.encryption as encryption
    import utils.credentials as credential_utils
    state = {'version': 1, 'family': FAMILY, 'revoked': None, 'raw_family': FAMILY, 'exists': True, 'site': SITE, 'owner': ACTOR, 'id': CID}
    sql = []
    class Connection:
        async def fetchrow(self, query, *args):
            sql.append(query)
            if 'FROM credentials c' not in query: return None
            assert 'resource_shares' in query and str(args[0]) == CID and str(args[1]) == ACTOR and args[2] is None
            if not state['exists']: return None
            return {'id': state['id'], 'owner_id': state['owner'], 'organization_id': None, 'credential_type': state['family'], 'credential': 'fixture-encrypted', 'revoked_at': state['revoked'], 'token_version': state['version'], 'updated_at': 'fixed'}
    class Pool:
        @asynccontextmanager
        async def acquire(self): yield Connection()
    class Encryption:
        def decrypt_credential(self, blob): return {'credential_type': state['raw_family'], 'api_secret': 'current-jwx-secret-42', 'site_id': state['site']}
    monkeypatch.setattr(db, 'get_native_pool', lambda: Pool())
    monkeypatch.setattr(encryption, 'get_encryption', lambda: Encryption())
    owner = AsyncMock(side_effect=AssertionError('Graph-free reads must not fall back to an owner'))
    monkeypatch.setattr(credential_utils, 'get_workflow_owner_id', owner)
    node = NodeFactory.create_node('n', 'automation-jwplayer', stored_data(), user_id=ACTOR)
    node._frame = node._snapshot(); node._binding = None
    assert (await node._fresh()).api_secret == 'current-jwx-secret-42'
    state['version'] = 2
    with pytest.raises(JWPlayerError, match='version changed'): await node._fresh()
    for key, value in [('family', 'foreign'), ('raw_family', 'foreign'), ('revoked', 'now'), ('exists', False), ('site', 'other123'), ('id', '33333333-3333-4333-8333-333333333333')]:
        state.update(version=1, family=FAMILY, raw_family=FAMILY, revoked=None, exists=True, site=SITE, id=CID); state[key] = value
        node._binding = None
        with pytest.raises(JWPlayerError): await node._fresh()
    owner.assert_not_called()
    assert sql

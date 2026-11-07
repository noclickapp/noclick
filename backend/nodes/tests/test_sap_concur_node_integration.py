"""Provider refresh exercised through staging's shared lock/CAS manager.

Only the external credential store, audit sink and HTTP transport are faked.
The original PR's shared authority/handler changes are outside this re-cut.
"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nodes.tests.test_sap_concur_node_mock import native, ensure_native_db_pool, USER, CID, BLOB, EXPIRED, REFRESH


@pytest.fixture
async def saved(native, monkeypatch):
    from nodes.core import oauth_refresh
    state = SimpleNamespace(blob={**deepcopy(EXPIRED), 'credential_type': 'sap_concur_oauth', 'token_version': 7}, writes=[])
    class Store:
        def __init__(self, pool, user_id, credential_id):
            assert user_id == USER and credential_id == CID
        lock_key = CID
        async def load(self):
            return deepcopy(state.blob)
        async def persist(self, new_data, metadata_updates=None):
            assert new_data['token_version'] == state.blob['token_version']
            state.writes.append(deepcopy(new_data))
            state.blob = {**deepcopy(new_data), 'token_version': state.blob['token_version'] + 1}
            return 1, None
    monkeypatch.setattr(oauth_refresh, 'CredentialsTableStore', Store)
    monkeypatch.setattr(oauth_refresh, 'record_refresh_event', AsyncMock())
    return state


async def test_shared_manager_rotates_and_persists_region_and_pair(native, saved):
    from nodes.sap_concur_node import freshen, lists
    data = await freshen(saved.blob, user_id=USER, credential_id=CID)
    assert saved.blob['refresh_token'] == data['refresh_token'] == 'synthetic_new_refresh'
    assert saved.blob['geolocation'] == data['geolocation'] == 'https://eu2.api.concursolutions.com'
    assert len(saved.writes) == 1 and 'id_token' not in saved.blob
    assert (await lists(data))['items']
    assert native.requests[-1].url.host == 'eu2.api.concursolutions.com'
    assert native.requests[-1].headers['Authorization'] == 'Bearer synthetic_new_access'
    from urllib.parse import parse_qs
    grant = parse_qs(native.requests[0].content.decode())
    assert grant['grant_type'] == ['refresh_token'] and grant['client_secret'] == [EXPIRED['client_secret']]
    assert 'Authorization' not in native.requests[0].headers


@pytest.mark.parametrize('bad', [
    {'geolocation': 'https://us2.api.concursolutions.com.attacker.invalid'},
    {'geolocation': 'https://us2.api.concursolutions.com/private'},
    {'refresh_token': None}, {'token_type': 'Other'}, {'expires_in': True},
])
async def test_bad_refresh_response_never_persists_or_requests_resource(native, saved, bad):
    from nodes.sap_concur_node import freshen
    native.replies[('POST', '/oauth2/v0/token')] = (200, {
        'access_token': 'synthetic_new_access', 'refresh_token': 'synthetic_new_refresh',
        'expires_in': 3600, 'token_type': 'Bearer', 'scope': 'spend.list.read',
        'geolocation': 'https://eu2.api.concursolutions.com', **bad})
    with pytest.raises(ValueError):
        await freshen(saved.blob, user_id=USER, credential_id=CID)
    assert saved.writes == [] and saved.blob['refresh_token'] == REFRESH
    assert len(native.requests) == 1


async def test_fresh_token_needs_no_store_or_network(native):
    from nodes.sap_concur_node import freshen
    assert (await freshen(BLOB))['access_token'] == BLOB['access_token']
    assert native.requests == []


async def test_expired_unsaved_pair_is_not_consumed(native):
    from nodes.sap_concur_node import freshen
    with pytest.raises(RuntimeError, match='Save the native SAP Concur connection'):
        await freshen(EXPIRED)
    assert native.requests == []

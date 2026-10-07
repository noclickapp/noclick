"""Current JWX OAS contract fixtures, authored but UNRUN."""
import json

import httpx
import pytest

import nodes.jwplayer_node as native

TOKEN = "fixture-jwx-secret-42"
SITE = "abc123XY"
MEDIA = "Ny05CEfj"
PLAYLIST = "Xj02BPzr"


def make_node(operation, **fields):
    data = {"config": {"operation": operation, **fields}, "credentials": {
        "credential_type": native.FAMILY, "api_secret": TOKEN, "site_id": SITE}}
    return native.JWPlayerNode("native", "automation-jwplayer", data, native.JWPlayerNode.parse_config(data), user_id="actor")


def media(id=MEDIA):
    return {"id": id, "created": "2026-10-01T12:00:00Z", "last_modified": "2026-10-02T12:00:00.001+00:00",
        "status": "processing", "media_type": "video", "hosting_type": "hosted", "duration": 12.5,
        "source_url": "https://private.example.test/source", "error_message": "Private provider detail", "schema": "https://schema.example.test",
        "relationships": {"protection_rule": {"id": "private"}}, "metadata": {"title": "Private title", "description": "Private content", "custom_params": {"key": "Private"}, "drm": {"license": "private"}}}


def playlist(id=PLAYLIST):
    return {"id": id, "playlist_type": "manual", "default": True, "metadata": {"title": "Private playlist", "description": "Private content", "link": "https://private.example.test/", "custom_params": {"secret": "Private"}}}


def transport(monkeypatch, handler):
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_media_exact_header_property_page_envelope_private_projection_and_unknown_completion(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.jwplayer.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert request.url.path == "/v2/sites/" + SITE + "/media/"
        assert dict(request.url.params) == {"page": "2", "page_length": "3"}
        return httpx.Response(200, json={"media": [media()], "page": 2, "page_length": 3, "total": 17, "links": {"next": "https://foreign.example.test/"}})
    transport(monkeypatch, respond)
    data = (await make_node("list_media", page=2, page_length=3).execute({}))['data']
    assert data['media'][0] == {"id": MEDIA, "created": "2026-10-01T12:00:00Z", "last_modified": "2026-10-02T12:00:00.001+00:00", "status": "processing", "media_type": "video", "hosting_type": "hosted", "duration": 12.5}
    assert data['site_id'] == SITE and data['provider_total'] == 17 and data['completion'] == 'unknown'
    assert 'Private' not in str(data) and 'https://' not in str(data) and len(calls) == 1
    assert 'principal_id' not in data and 'account_id' not in data and 'next_cursor' not in data


@pytest.mark.parametrize('operation,kind,row,resource_id', [('get_media', 'media', media(), MEDIA), ('get_playlist', 'playlist', playlist(), PLAYLIST)])
@pytest.mark.asyncio
async def test_details_are_direct_resource_envelopes_and_exact_ids(monkeypatch, operation, kind, row, resource_id):
    calls = []
    def respond(request):
        calls.append(request)
        assert not request.url.params
        assert request.url.path == f'/v2/sites/{SITE}/{"media" if kind == "media" else "playlists"}/{resource_id}/'
        return httpx.Response(200, json=row)
    transport(monkeypatch, respond)
    config = {'media_id' if kind == 'media' else 'playlist_id': resource_id}
    data = (await make_node(operation, include_names=True, **config).execute({}))['data']
    assert data[kind]['id'] == resource_id and 'title' in data[kind]
    assert 'custom_params' not in str(data) and 'source_url' not in str(data) and len(calls) == 1
    transport(monkeypatch, lambda request: httpx.Response(200, json={**row, 'id': 'wrong123'}))
    with pytest.raises(native.JWPlayerError, match='another'): await make_node(operation, **config).execute({})
    transport(monkeypatch, lambda request: httpx.Response(200, json={'data': row}))
    with pytest.raises(native.JWPlayerError): await make_node(operation, **config).execute({})


@pytest.mark.asyncio
async def test_playlist_and_content_type_distinct_collections_and_content_types_no_paging(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        if request.url.path.endswith('/playlists/'):
            assert dict(request.url.params) == {'page': '1', 'page_length': '20'}
            return httpx.Response(200, json={'playlists': [playlist()]})
        assert request.url.path.endswith('/content_type_schemas/') and not request.url.params
        return httpx.Response(200, json={'content_type_schemas': [
            {'id': 'Type0001', 'metadata': {'hosting_type': 'ott_data', 'display_name': 'Private schema', 'sections': [{'secret': 'Private'}], 'is_active': True}},
            {'id': 'Type0002', 'metadata': {'hosting_type': 'live_bcl'}}]})
    transport(monkeypatch, respond)
    p = (await make_node('list_playlists').execute({}))['data']
    assert p['playlists'] == [{'id': PLAYLIST, 'playlist_type': 'manual'}]
    assert 'provider_total' not in p and 'provider_page' not in p and p['completion'] == 'unknown'
    c = (await make_node('list_content_types', limit=1).execute({}))['data']
    assert c['content_type_schemas'] == [{'id': 'Type0001', 'hosting_type': 'ott_data'}]
    assert c['locally_truncated'] is True and c['completion'] == 'unknown'
    assert 'requested_page' not in c and 'Private' not in str(c) and len(requests) == 2


@pytest.mark.parametrize('payload', [
    {'data': [media()]}, {'media': [media(), media()]}, {'media': [media(id=' short ')]},
    {'media': [media()], 'page': 2}, {'media': [media()], 'total': True},
    {'media': [dict(media(), status='deployed')]}, {'media': [dict(media(), duration=True)]},
    {'media': [dict(media(), created='2026-13-01T12:00:00Z')]},
])
@pytest.mark.asyncio
async def test_wrong_envelopes_duplicate_ids_counter_mismatch_and_invalid_metadata_withheld(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(native.JWPlayerError): await make_node('list_media').execute({})


@pytest.mark.asyncio
async def test_enum_description_disagreement_and_page_overflow_not_invented(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={'playlists': [dict(playlist(), playlist_type='recommendations')]}))
    with pytest.raises(native.JWPlayerError, match='published OAS enum'): await make_node('list_playlists').execute({})
    transport(monkeypatch, lambda request: httpx.Response(200, json={'media': [media(), media(id='Media002')]}))
    with pytest.raises(native.JWPlayerError, match='bound'): await make_node('list_media', page_length=1).execute({})


@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 503])
@pytest.mark.asyncio
async def test_error_bodies_private_redirects_not_followed_and_no_retry(monkeypatch, status):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, text=TOKEN + ' private error', headers={'location': 'https://foreign.example.test/'})
    transport(monkeypatch, respond)
    with pytest.raises(native.JWPlayerError) as error: await make_node('list_media').execute({})
    assert error.value.status_code == status and TOKEN not in str(error.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_escaped_secret_reflection_pending_refs_closed_routes_and_changed_raw_context(monkeypatch):
    escaped = json.dumps({'media': [media()], 'debug': TOKEN}).replace('fixture', '\\u0066ixture')
    transport(monkeypatch, lambda request: httpx.Response(200, content=escaped, headers={'content-type': 'application/json'}))
    with pytest.raises(native.JWPlayerError, match='reflected'): await make_node('list_media').execute({})
    calls = []
    transport(monkeypatch, lambda request: calls.append(request) or httpx.Response(200, json={'media': []}))
    node = make_node('get_media', media_id='{{vars.media_id}}')
    with pytest.raises(native.JWPlayerError, match='Resolve'): await node.execute({})
    for route in ('/me', '/sites', '/media/Ny05CEfj/playback/', '/content-types/'):
        with pytest.raises(native.JWPlayerError, match='Unsupported'): await node._request(route)
    node = make_node('list_content_types'); node._frame = node._snapshot(); node._binding = None
    with pytest.raises(native.JWPlayerError, match='Unsupported'): await node._request('/content_type_schemas/', {'page': 1})
    assert calls == []
    node = make_node('list_media')
    async def changed(route, params=None):
        node.node_data['credentials']['site_id'] = 'other123'
        return {'media': []}
    node._request = changed
    with pytest.raises(native.JWPlayerError, match='selection changed'): await node.execute({})

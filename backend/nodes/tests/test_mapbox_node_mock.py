"""Mapbox requests exercised through the native factory with synthetic credentials."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import mapbox_node as native
from nodes.core.registry import NodeFactory

CREDENTIAL = {"credential_type": "mapbox_access_token", "access_token": "synthetic-mapbox-token", "username": "mapbox"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="mapbox-test", node_type="automation-mapbox",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200, headers=None):
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(status, json=body, headers=headers)
    original = httpx.AsyncClient
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,method,suffix,status", [
    ("check_connection", "GET", "/tokens/v2", 200),
    ("list_styles", "GET", "/styles/v1/mapbox", 200),
    ("get_style", "GET", "/styles/v1/mapbox/style1", 200),
    ("create_style", "POST", "/styles/v1/mapbox", 201),
    ("update_style", "PATCH", "/styles/v1/mapbox/style1", 200),
    ("delete_style", "DELETE", "/styles/v1/mapbox/style1", 204),
    ("get_style_draft", "GET", "/styles/v1/mapbox/style1/draft", 200),
    ("update_style_draft", "PATCH", "/styles/v1/mapbox/style1/draft", 200),
    ("delete_style_draft", "DELETE", "/styles/v1/mapbox/style1/draft", 204),
    ("get_sprite", "GET", "/styles/v1/mapbox/style1/sprite", 200),
    ("delete_sprite_image", "DELETE", "/styles/v1/mapbox/style1/sprite/star", 200),
    ("forward_geocode", "GET", "/search/geocode/v6/forward", 200),
    ("reverse_geocode", "GET", "/search/geocode/v6/reverse", 200),
])
async def test_requests(monkeypatch, operation, method, suffix, status):
    config = {"operation": operation}
    if 'style1' in suffix: config['style_id'] = 'style1'
    if operation in {'create_style', 'update_style', 'update_style_draft'}:
        config.update(name='My map', sources={}, layers=[])
    if operation == 'delete_sprite_image': config['icon_name'] = 'star'
    if operation == 'forward_geocode': config['q'] = 'New York'
    if operation == 'reverse_geocode': config.update(longitude=-73.9, latitude=40.7)
    body = [] if operation == 'list_styles' else json.loads((Path(__file__).parent / 'fixtures/mapbox/token-validation.json').read_text()) if operation == 'check_connection' else {'id': 'style1'}
    seen = transport(monkeypatch, body, status)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    request = seen[0]
    assert request.method == method and request.url.path == suffix
    assert request.url.host == 'api.mapbox.com'
    assert request.url.params['access_token'] == CREDENTIAL['access_token']
    if method in {'POST', 'PATCH'}:
        assert json.loads(request.content) == {'name': 'My map', 'version': 8, 'sources': {}, 'layers': []}


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'code':'TokenInvalid'}, {'code':'TokenExpired'}, {'code':'TokenValid','token':{'user':'other'}}])
async def test_connection_rejects_invalid_token_and_account_mismatch(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({'operation':'check_connection'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_pagination_exposes_cursor_without_following(monkeypatch):
    seen = transport(monkeypatch, [{'id':'style1'}], headers={'Link':'<https://api.mapbox.com/styles/v1/mapbox?start=style1>; rel="next"'})
    result = await node({'operation':'list_styles'}).execute({})
    assert result['next_start'] == 'style1' and result['has_more']
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[301,401,403,404,429,500])
async def test_errors_never_expose_token(monkeypatch, status):
    transport(monkeypatch, {'message':CREDENTIAL['access_token']},status)
    result = await node({'operation':'check_connection'}).execute({})
    assert result['status'] == 'error' and CREDENTIAL['access_token'] not in str(result)


def test_resource_path_segments_reject_traversal():
    from pydantic import ValidationError
    for value in ['..', '.', '../other', 'other/resource']:
        with pytest.raises(ValidationError):
            native.GetStyle(style_id=value)

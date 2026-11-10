"""Request boundaries, hand-connect, Google OAuth refresh and annotation polling."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.google_books_node import (
    BASE, CONFIG_MODELS, GoogleBooksNode, GoogleBooksNodeConfig,
    GoogleBooksAccessTokenCredential, GoogleBooksOAuthCredential, GoogleBooksOnAnnotationUpdatedConfig,
)
from nodes.scopes.google_books import BOOKS, GOOGLE_BOOKS_SCOPES


def node(operation, **values):
    model = GoogleBooksOnAnnotationUpdatedConfig if operation == 'on_annotation_updated' else CONFIG_MODELS[operation]
    return GoogleBooksNode(node_id='google-books-test', node_type='automation-google-books', node_data={},
        config=GoogleBooksNodeConfig(config=model(**values), credentials=GoogleBooksOAuthCredential(access_token='book-token')))


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,params,body', [
    ('search_volumes', {'q': 'intitle:flowers', 'order_by': 'newest'}, 'GET', '/volumes',
     {'q': 'intitle:flowers', 'orderBy': 'newest', 'maxResults': '40', 'startIndex': '0'}, None),
    ('get_volume', {'volume_id': 'zyTCAlFPjgYC'}, 'GET', '/volumes/zyTCAlFPjgYC', {}, None),
    ('list_my_bookshelves', {}, 'GET', '/mylibrary/bookshelves', {}, None),
    ('get_my_bookshelf', {'shelf': '7'}, 'GET', '/mylibrary/bookshelves/7', {}, None),
    ('list_my_bookshelf_volumes', {'shelf': '7', 'start_index': 40}, 'GET', '/mylibrary/bookshelves/7/volumes', {'startIndex': '40', 'maxResults': '40'}, None),
    ('add_volume', {'shelf': '7', 'volume_id': 'zyTCAlFPjgYC'}, 'POST', '/mylibrary/bookshelves/7/addVolume', {'volumeId': 'zyTCAlFPjgYC'}, None),
    ('remove_volume', {'shelf': '7', 'volume_id': 'zyTCAlFPjgYC'}, 'POST', '/mylibrary/bookshelves/7/removeVolume', {'volumeId': 'zyTCAlFPjgYC'}, None),
    ('move_volume', {'shelf': '7', 'volume_id': 'zyTCAlFPjgYC', 'volume_position': 0}, 'POST', '/mylibrary/bookshelves/7/moveVolume', {'volumeId': 'zyTCAlFPjgYC', 'volumePosition': '0'}, None),
    ('clear_bookshelf', {'shelf': '7'}, 'POST', '/mylibrary/bookshelves/7/clearVolumes', {}, None),
    ('list_public_bookshelves', {'user_id': '112'}, 'GET', '/users/112/bookshelves', {}, None),
    ('get_public_bookshelf', {'user_id': '112', 'shelf': '7'}, 'GET', '/users/112/bookshelves/7', {}, None),
    ('list_public_bookshelf_volumes', {'user_id': '112', 'shelf': '7'}, 'GET', '/users/112/bookshelves/7/volumes', {'startIndex': '0', 'maxResults': '40'}, None),
    ('list_annotations', {'page_token': 'opaque+/=', 'updated_min': '2026-01-01T00:00:00Z'}, 'GET', '/mylibrary/annotations', {'pageToken': 'opaque+/=', 'updatedMin': '2026-01-01T00:00:00Z', 'maxResults': '40'}, None),
    ('create_annotation', {'annotation': {'volumeId': 'v', 'data': 'note'}}, 'POST', '/mylibrary/annotations', {}, {'volumeId': 'v', 'data': 'note'}),
    ('update_annotation', {'annotation_id': 'a', 'annotation': {'volumeId': 'v', 'data': ''}}, 'PUT', '/mylibrary/annotations/a', {}, {'volumeId': 'v', 'data': ''}),
    ('delete_annotation', {'annotation_id': 'a'}, 'DELETE', '/mylibrary/annotations/a', {}, None),
    ('get_reading_position', {'volume_id': 'v'}, 'GET', '/mylibrary/readingpositions/v', {}, None),
    ('set_reading_position', {'volume_id': 'v', 'position': 'GB.1', 'timestamp': '2026-01-01T00:00:00Z'}, 'POST', '/mylibrary/readingpositions/v/setPosition', {'position': 'GB.1', 'timestamp': '2026-01-01T00:00:00Z'}, None),
    ('list_my_books', {}, 'GET', '/volumes/mybooks', {'startIndex': '0', 'maxResults': '40'}, None),
    ('list_recommended_volumes', {}, 'GET', '/volumes/recommended', {}, None),
    ('rate_recommended_volume', {'volume_id': 'v', 'rating': 'HAVE_IT'}, 'POST', '/volumes/recommended/rate', {'volumeId': 'v', 'rating': 'HAVE_IT'}, None),
], ids=lambda value: 'google-books-' + value if isinstance(value, str) and value in CONFIG_MODELS else None)
async def test_google_books_request_contract(operation, config, method, path, params, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, BASE + path).respond(200, json={'kind': 'books#test'})
        result = await node(operation, **config).execute({})
    request = route.calls[0].request
    assert dict(request.url.params) == params
    assert request.headers['authorization'] == 'Bearer book-token'
    assert (json.loads(request.content) if request.content else None) == body
    assert result['data'] == {'kind': 'books#test'}


def test_google_books_manual_connect_and_scope():
    credential = GoogleBooksOAuthCredential(access_token='book-token')
    assert credential.credential_type == 'google_oauth'
    assert GoogleBooksAccessTokenCredential(access_token='book-token').credential_type == 'google_books_access_token'
    assert credential.refresh_token is None
    assert GOOGLE_BOOKS_SCOPES.declared_scopes() == [BOOKS]
    with pytest.raises(ValidationError):
        GoogleBooksOAuthCredential(access_token='Bearer book-token')
    with pytest.raises(ValidationError):
        CONFIG_MODELS['search_volumes'](q='book', max_results=41)


@pytest.mark.asyncio
async def test_google_books_refresh_uses_shared_choke_point(monkeypatch):
    instance = node('list_my_bookshelves')
    instance.config.credentials.refresh_token = 'refresh'
    hook = AsyncMock(return_value='new-access')
    monkeypatch.setattr('nodes.core.oauth_refresh.ensure_fresh_oauth_token', hook)
    assert await instance._token(instance.config.credentials) == 'new-access'
    assert hook.call_args.kwargs['provider'] == 'google'
    freshen = AsyncMock(return_value={'access_token': 'renewed'})
    monkeypatch.setattr('nodes.core.oauth_refresh.freshen_oauth_credential', freshen)
    assert await GoogleBooksNode.freshen_credential({'refresh_token': 'refresh'}) == {'access_token': 'renewed'}
    assert freshen.call_args.kwargs['provider'] == 'google'


@pytest.mark.asyncio
async def test_google_books_provider_rejection_and_empty_success():
    with respx.mock as router:
        route = router.get(BASE + '/mylibrary/bookshelves').respond(401, json={'error': {'message': 'Invalid Credentials'}})
        with pytest.raises(ValueError, match='Invalid Credentials'):
            await node('list_my_bookshelves').execute({})
        route.respond(200, json={'error': {'message': 'failed'}})
        with pytest.raises(ValueError, match='unexpected response'):
            await node('list_my_bookshelves').execute({})
        router.post(BASE + '/mylibrary/bookshelves/7/clearVolumes').respond(204)
        assert (await node('clear_bookshelf', shelf='7').execute({}))['data'] == {}


@pytest.mark.asyncio
async def test_google_books_poll_baseline_updates_and_agent_event():
    annotation = json.loads((Path(__file__).parent / 'fixtures/google-books/annotation.json').read_text())
    instance = node('on_annotation_updated', volume_id='A String')
    state = {}
    async def update(mutator, **kwargs):
        replacement, result = mutator(copy.deepcopy(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    instance._update_node_state = update
    with respx.mock as router:
        route = router.get(BASE + '/mylibrary/annotations').respond(200, json={'items': [annotation]})
        first = await instance.execute({})
        assert first['annotations'] == []
        assert instance.trigger_produced_no_event(first)
        # Synthetic update to the same documented resource tests revision dedup.
        revised = {**annotation, 'updated': 'changed', 'data': 'Revised note'}
        route.respond(200, json={'items': [revised]})
        second = await instance.execute({})
        assert second['annotations'] == [revised]
        assert instance.trigger_emitted_event(second)
        event = GoogleBooksNode.resolve_agent_event(second)
        assert 'Revised note' in event['text']
        assert 'A String' in event['text']
        assert (await instance.execute({}))['annotations'] == []
        assert dict(route.calls[0].request.url.params) == {'maxResults': '40', 'volumeId': 'A String'}


@pytest.mark.asyncio
async def test_google_books_poll_pages_and_repeated_cursor():
    instance = node('on_annotation_updated')
    instance._filter_unseen = AsyncMock(side_effect=lambda items, key: items)
    row = {'id': 'a', 'updated': 'now', 'volumeId': 'v'}
    with respx.mock as router:
        route = router.get(BASE + '/mylibrary/annotations').mock(side_effect=[
            httpx.Response(200, json={'items': [row], 'nextPageToken': 'next'}),
            httpx.Response(200, json={'items': [{**row, 'id': 'b'}]})])
        assert (await instance.execute({}))['new_annotation_count'] == 2
        assert route.calls[1].request.url.params['pageToken'] == 'next'
        route.respond(200, json={'items': [row], 'nextPageToken': 'loop'})
        with pytest.raises(ValueError, match='repeated'):
            await instance.execute({})
        route.respond(200, json={'items': [{'id': 'a'}]})
        with pytest.raises(ValueError, match='id and updated'):
            await instance.execute({})

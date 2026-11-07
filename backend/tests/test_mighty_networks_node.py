"""Native Mighty GraphQL behavior against synthetic DNS and HTTP boundaries."""
import asyncio
import html
import json
import re
import socket
from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock
import httpx
import pytest
import pytest_asyncio
from nodes import mighty_networks_node as native
from nodes.core.registry import NODE_REGISTRY
from nodes.core.run_op import run_node_operation
from utils import ssrf

DATE = '2026-01-01T00:00:00Z'
TOKEN = 'synthetic-mighty-bearer-key'
NODE = 'automation-mighty-networks'
BASE = {'credential_type': 'mighty_networks_api_key', 'api_key': TOKEN, 'network_id': '123'}
GRANT = 'host:write:network_spaces host:write:network_members host:write:network_posts'


def space(rid='Space44', resource='44', title='Synthetic Space'):
    return {'__typename': 'Space', 'id': rid, 'resourceId': resource, 'title': title, 'discoverable': False, 'explorable': False, 'spacesCollection': None}


def post(rid='Post81', resource='81'):
    return {'__typename': 'Post', 'id': rid, 'resourceId': resource, 'title': 'Synthetic draft', 'status': 'draft', 'postType': 'post', 'createdAt': DATE, 'updatedAt': DATE, 'lastEditedAt': DATE, 'space': {'id': 'Space44', 'resourceId': '44'}, 'creator': {'id': 'User7', 'resourceId': '7'}, 'bodyText': 'Private original draft'}


class Boundary:
    def __init__(self):
        self.blob = deepcopy(BASE)
        self.requests = []; self.responses = {}; self.after_http = None
        self.network = {'__typename': 'Network', 'id': 'Network123', 'resourceId': '123', 'title': 'Synthetic Network', 'private_url': 'https://private.invalid/proof'}
        self.me = {'__typename': 'User', 'id': 'User7', 'resourceId': '7', 'name': 'Synthetic Host', 'email': 'private@example.invalid'}
        self.spaces = {'Space44': space()}
        self.tags = {'Tag61': {'__typename': 'Tag', 'id': 'Tag61', 'resourceId': '61', 'title': 'Synthetic tag', 'description': None, 'color': None, 'createdAt': DATE, 'updatedAt': DATE}}
        self.collections = {'9': {'__typename': 'SpacesCollection', 'id': '9', 'name': 'Empty synthetic collection', 'visibleToMembers': False}}
        self.posts = {'Post81': post()}
        self.templates = [{'__typename': 'SpaceTemplate', 'canonicalName': 'feed_v3', 'title': 'Synthetic feed', 'templateType': 'PRESET'}]
    def wire(self, request):
        self.requests.append(request)
        assert request.method == 'POST' and request.url.scheme == 'https' and request.url.host == 'api.mn.co'
        assert request.url.path == '/networks/' + self.blob['network_id'] + '/graphql' and not request.url.query
        assert request.headers['authorization'] == 'Bearer ' + self.blob.get('api_key', self.blob.get('access_token'))
        assert request.headers['user-agent'] == 'NoClick/1.0 (+https://www.noclick.com)'
        envelope = json.loads(request.content); assert set(envelope) == {'query', 'variables'}
        document, variables = envelope['query'], envelope['variables']
        name = re.match(r'(?:query|mutation) (\w+)', document)[1]
        key = re.search(r'result:(\w+)\(input:', document)[1] if name == 'NCMightyMutation' else name
        result = None; payload = {'data': {'network': deepcopy(self.network)}}
        if name == 'NCMightyIdentity': payload['data']['me'] = deepcopy(self.me)
        elif name in ('NCSpaces', 'NCTags', 'NCPosts'):
            rows = list({'NCSpaces': self.spaces, 'NCTags': self.tags, 'NCPosts': self.posts}[name].values())
            if name == 'NCPosts':
                assert variables['spaceId'] == 'Space44' and 'postTypes:[POST,ARTICLE]' in document
                rows = [row for row in rows if row['space']['id'] == variables['spaceId'] and (not variables['statuses'] or row['status'].upper() in variables['statuses'])]
            assert 1 <= variables['first'] <= 50
            offset = int(variables['after'].split(':')[1]) if variables.get('after') else 0
            page = rows[offset:offset + variables['first']]
            result = {'nodes': deepcopy(page), 'pageInfo': {'hasNextPage': offset + len(page) < len(rows), 'endCursor': 'offset:' + str(offset + len(page)) if page else None}}
        elif name in ('NCSpace', 'NCTag', 'NCPost', 'NCPostText'):
            if name in ('NCPost', 'NCPostText'):
                # post() returns PostInterface; resourceId is only on concrete Post.
                assert 'result:post(idOrSlug:$id){__typename ... on Post{' in document
            table = self.spaces if name == 'NCSpace' else self.tags if name == 'NCTag' else self.posts
            result = deepcopy(next((row for row in table.values() if variables['id'] in (row['id'], row['resourceId'])), None))
            if result is None: payload['errors'] = [{'message': TOKEN, 'extensions': {'code': 'NOT_FOUND'}}]
        elif name == 'NCCollections': result = deepcopy(list(self.collections.values()))
        elif name == 'NCTemplates': result = deepcopy(self.templates)
        elif name == 'NCMightyMutation':
            attrs = variables['input']; result = {'errors': []}
            if key in ('createPost', 'updatePost'):
                assert attrs['status'] == 'DRAFT' and attrs['notify'] is False
                assert not set(attrs).intersection({'assetIds', 'publishedAt'})
                rid = attrs.get('id', 'Post99')
                if key == 'updatePost': assert attrs['expectedLastEditedAt'] == DATE
                else: assert attrs['spaceId'] == 'Space44' and attrs['postType'] in ('post', 'article')
                self.posts[rid] = {**self.posts.get(rid, post(rid, '99')), 'title': attrs['title'], 'bodyText': html.unescape(attrs['body'])}
                result['post'] = deepcopy(self.posts[rid])
            elif key == 'deletePost':
                del self.posts[attrs['id']]; result['deletedId'] = attrs['id']
            elif key in ('createTag', 'updateTag', 'deleteTag'):
                rid = attrs.get('tagId', 'Tag99')
                if key == 'deleteTag': result['tag'] = self.tags.pop(rid)
                else:
                    self.tags[rid] = {**self.tags.get(rid, {'__typename': 'Tag', 'id': rid, 'resourceId': '99', 'description': None, 'color': None, 'createdAt': DATE, 'updatedAt': DATE}), **{k: v for k, v in attrs.items() if k != 'tagId'}}
                    result['tag'] = deepcopy(self.tags[rid])
            elif key in ('createSpace', 'updateSpace'):
                rid = attrs.get('spaceId', 'Space99'); assert not set(attrs).intersection({'featureToggles', 'enabledFeatureKeys', 'collectionName'})
                self.spaces[rid] = {**self.spaces.get(rid, space(rid, '99')), 'title': attrs['title']}; result['space'] = deepcopy(self.spaces[rid])
            elif key in ('createSpacesCollection', 'updateSpacesCollection'):
                rid = attrs.get('collectionId', '99'); assert not set(attrs).intersection({'spaceTitles', 'visibleToMembers'})
                self.collections[rid] = {'__typename': 'SpacesCollection', 'id': rid, 'name': attrs['name'], 'visibleToMembers': False}; result['spacesCollection'] = deepcopy(self.collections[rid])
            elif key == 'deleteSpacesCollection':
                del self.collections[attrs['collectionId']]; result['deletedSpacesCollectionId'] = 'gid://synthetic/SpacesCollection/' + attrs['collectionId']
            else: raise AssertionError('Unexpected mutation field')
            payload = {'data': {'result': result}}
        else: raise AssertionError('Unexpected closed native document')
        if name not in ('NCMightyIdentity', 'NCMightyMutation'): payload['data']['network']['result'] = result
        override = self.responses.get(key)
        if isinstance(override, Exception): raise override
        if isinstance(override, int): return httpx.Response(override, json={'message': TOKEN}, request=request)
        if callable(override): payload = override(payload)
        elif isinstance(override, bytes): return httpx.Response(200, content=override, headers={'content-type': 'application/json'}, request=request)
        elif override is not None: payload = deepcopy(override)
        if self.after_http: self.after_http(name, key)
        return httpx.Response(200, json=payload, request=request)


@pytest_asyncio.fixture
async def boundary(monkeypatch):
    value = Boundary()
    original = ssrf.guarded_async_client
    @asynccontextmanager
    async def transport(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async with original(transport=httpx.MockTransport(value.wire), **kwargs) as client: yield client
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]))
    monkeypatch.setattr(native, 'guarded_async_client', transport)
    return value


async def run(boundary, operation='test_connection', args=None):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=args or {}, credential_data=deepcopy(boundary.blob), user_id='mighty-test-user')


OPERATIONS = {
    'test_connection': {}, 'get_me': {}, 'get_network': {}, 'list_spaces': {}, 'get_space': {'space_id': 'Space44'}, 'list_space_templates': {},
    'create_private_space': {'template_canonical_name': 'feed_v3', 'title': 'New private Space'}, 'rename_space': {'space_id': 'Space44', 'title': 'New title'},
    'list_collections': {}, 'get_collection': {'collection_id': '9'}, 'create_collection': {'name': 'New collection'}, 'rename_collection': {'collection_id': '9', 'name': 'New name'}, 'delete_empty_collection': {'collection_id': '9'},
    'list_tags': {}, 'get_tag': {'tag_id': 'Tag61'}, 'create_tag': {'title': 'New tag', 'color': '#AABBCC'}, 'update_tag': {'tag_id': 'Tag61', 'title': 'New name'}, 'delete_tag': {'tag_id': 'Tag61'},
    'list_posts': {'space_id': 'Space44'}, 'get_post': {'space_id': 'Space44', 'post_id': 'Post81'}, 'create_draft_post': {'space_id': 'Space44', 'title': 'New draft', 'body_text': 'Private new draft'}, 'update_draft_post': {'space_id': 'Space44', 'post_id': 'Post81', 'title': 'New draft', 'body_text': 'Private new draft'}, 'delete_draft_post': {'space_id': 'Space44', 'post_id': 'Post81'},
}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(OPERATIONS))
async def test_23_actual_factory_actions_and_mutation_readbacks(boundary, operation):
    boundary.blob.update(allow_management_writes=operation in native.MUTATION_SCOPES, scope=GRANT)
    output = await run(boundary, operation, OPERATIONS[operation])
    assert NODE_REGISTRY[NODE] is native.MightyNetworksNode and output['action'] == operation
    assert all(value not in json.dumps(output) for value in (TOKEN, 'private.invalid', 'private@example.invalid', 'Private original draft', 'Private new draft'))
    if operation in native.MUTATION_SCOPES:
        assert output['data'].get('readback_verified') is True or output['data'].get('absent_from_selected_view') is True
        assert output['data']['notification_delivery_verified'] is None
    if operation == 'create_collection': assert output['data']['created_new_verified'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('expiry', ['2099-01-01T00:00:00Z', '2000-01-01T00:00:00Z'])
async def test_actual_supplied_oauth_expiry_scope_and_application_context(boundary, expiry):
    boundary.blob = {'credential_type': 'mighty_networks_supplied_oauth', 'access_token': TOKEN, 'network_id': '123', 'client_id': 'synthetic-client', 'scope': 'read:userinfo read:network', 'expires_at': expiry}
    if expiry.startswith('2000'):
        with pytest.raises(native.MightyNetworksDenied): await run(boundary)
        assert boundary.requests == []
    else:
        assert (await run(boundary))['data']['account_identity_verified'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('problem', ['network', 'null_me', 'foreign_space', 'published', 'foreign_creator', 'no_edit_anchor', 'write_policy', 'scope'])
async def test_real_identity_parent_owned_draft_and_write_policy_refusals(boundary, problem):
    boundary.blob.update(allow_management_writes=True, scope=GRANT)
    if problem == 'network': boundary.network['resourceId'] = '124'
    if problem == 'null_me': boundary.me = None
    if problem == 'foreign_space': boundary.posts['Post81']['space']['id'] = 'Space45'; boundary.posts['Post81']['space']['resourceId'] = '45'
    if problem == 'published': boundary.posts['Post81']['status'] = 'posted'
    if problem == 'foreign_creator': boundary.posts['Post81']['creator']['id'] = 'User8'
    if problem == 'no_edit_anchor': boundary.posts['Post81']['lastEditedAt'] = None
    if problem == 'write_policy': boundary.blob['allow_management_writes'] = False
    if problem == 'scope': boundary.blob['scope'] = 'host:read:network_posts'
    with pytest.raises((native.MightyNetworksDenied, native.MightyNetworksUnavailable)):
        await run(boundary, 'update_draft_post', OPERATIONS['update_draft_post'])
    assert not any(json.loads(r.content)['query'].startswith('mutation') for r in boundary.requests)


@pytest.mark.asyncio
async def test_real_relay_paging_and_grant_network_bound_continuation(boundary):
    boundary.spaces['Space45'] = space('Space45', '45', 'Second Space')
    first = await run(boundary, 'list_spaces', {'limit': 1}); token = first['data']['next_page_token']
    second = await run(boundary, 'list_spaces', {'limit': 1, 'page_token': token})
    assert second['data']['items'][0]['id'] == 'Space45' and second['data']['has_more'] is False
    boundary.blob['api_key'] = 'different-synthetic-key'; before = len(boundary.requests)
    with pytest.raises(ValueError): await run(boundary, 'list_spaces', {'limit': 1, 'page_token': token})
    assert len(boundary.requests) == before + 1  # Current authenticated identity precedes cursor admission.


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [b'{bad', b'null', {'data': {'result': {'errors': ['Private provider failure']}}}, {'data': {'result': {'errors': [], 'post': None}}}, 500, httpx.ReadTimeout('Private synthetic timeout')])
async def test_possible_mutation_failure_remains_unknown_without_retry(boundary, failure):
    boundary.blob['allow_management_writes'] = True; boundary.responses['createPost'] = failure
    output = await run(boundary, 'create_draft_post', OPERATIONS['create_draft_post'])
    assert output['data']['outcome'] == 'unknown' and output['data']['receipt_id'] is None
    assert len([r for r in boundary.requests if json.loads(r.content)['query'].startswith('mutation')]) == 1


@pytest.mark.asyncio
async def test_actual_receipt_preserved_when_readback_fails_but_never_claims_global_absence(boundary):
    boundary.blob['allow_management_writes'] = True; boundary.responses['NCPostText'] = 500
    output = await run(boundary, 'create_draft_post', OPERATIONS['create_draft_post'])
    assert output['data']['outcome'] == 'unknown' and output['data']['receipt_id'] == 'Post99'
    boundary.responses.clear()
    removed = await run(boundary, 'delete_draft_post', OPERATIONS['delete_draft_post'])
    assert removed['data']['receipt_id'] == 'Post81' and removed['data']['absent_from_selected_view'] is True and removed['data']['global_deletion_verified'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('code', ['UNAUTHENTICATED', 'FORBIDDEN', 'NOT_FOUND', 'BAD_USER_INPUT', 'INTERNAL_SERVER_ERROR', None])
async def test_http200_graphql_errors_reject_partial_data_and_withhold_raw_details(boundary, code, caplog):
    boundary.responses['NCMightyIdentity'] = {'data': {'me': boundary.me, 'network': boundary.network}, 'errors': [{'message': TOKEN + ' private.invalid', 'extensions': {'code': code}}]}
    with pytest.raises((native.MightyNetworksDenied, native.MightyNetworksUnavailable)) as error: await run(boundary)
    assert TOKEN not in str(error.value) + caplog.text and 'private.invalid' not in str(error.value)
    assert len(boundary.requests) == 1


@pytest.mark.asyncio
async def test_actual_public_dns_guard_refuses_private_address_before_http(boundary, monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]))
    with pytest.raises(native.MightyNetworksUnavailable): await run(boundary)
    assert boundary.requests == []


def test_actual_typed_parse_rejects_foreign_rest_keys_free_graphql_host_and_refresh_material():
    for blob in ({**BASE, 'credential_type': 'mighty_admin_rest'}, {**BASE, 'network_id': '../escape'}, {**BASE, 'refresh_token': 'synthetic-refresh'}, {**BASE, 'scope': 'read:network'}):
        with pytest.raises(ValueError): native.MightyNetworksNode.parse_config({'credentials': blob, 'config': {'operation': 'test_connection'}})
    with pytest.raises(ValueError): native.MightyNetworksNode.parse_config({'credentials': BASE, 'config': {'operation': 'graphql', 'query': 'query { me { id } }'}})


@pytest.mark.asyncio
async def test_staging_credential_validation_and_picker_hooks(boundary):
    node = native.MightyNetworksNode
    assert (await node.validate_credential_access(BASE))["valid"] is True
    options = await node.load_field_options("post_id", credential_data=BASE, context={"space_id": "Space44"})
    assert options["options"] == [{"value": "Post81", "label": "Synthetic draft"}]
    with pytest.raises(ValueError):
        await node.load_field_options("post_id", credential_data=BASE)
    boundary.responses["NCMightyIdentity"] = {"errors": [{"extensions": {"code": "UNAUTHENTICATED"}}]}
    assert (await node.validate_credential_access(BASE))["valid"] is False
    boundary.responses["NCMightyIdentity"] = {"errors": [{"message": "Private failure"}]}
    assert (await node.validate_credential_access(BASE))["valid"] is None


@pytest.mark.asyncio
async def test_post_interface_non_post_response_is_refused(boundary):
    boundary.responses['NCPost'] = {'data': {'network': {**boundary.network, 'result': {'__typename': 'Event', 'id': 'Event1'}}}}
    with pytest.raises(native.MightyNetworksUnavailable):
        await run(boundary, 'get_post', {'space_id': 'Space44', 'post_id': 'Event1'})

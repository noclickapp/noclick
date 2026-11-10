"""Google Books v1 search, libraries, reading positions and annotation polling.

Contract: https://books.googleapis.com/$discovery/rest?version=v1
Auth: https://developers.google.com/books/docs/v1/using#auth
Annotations: https://developers.google.com/resources/api-libraries/documentation/books/v1/python/latest/books_v1.mylibrary.annotations.html
"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.google_books_operations import OPERATIONS, WIRE_NAMES
from nodes.scopes.google_books import GOOGLE_BOOKS_SCOPES

BASE = 'https://books.googleapis.com/books/v1'

class GoogleBooksAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title='Google Books Access Token', json_schema_extra={
        'x-credential-url': 'https://developers.google.com/oauthplayground/',
        'x-credential-instructions': 'Paste an OAuth access token authorized for https://www.googleapis.com/auth/books. API keys cannot access your private library or make changes. A pasted token works until it expires; replace it to renew access.',
    })
    credential_type: Literal['google_books_access_token'] = Field('google_books_access_token', json_schema_extra={'ui:hidden': True})
    access_token: str = Field(..., title='Access Token', min_length=1, repr=False, json_schema_extra={'ui:widget': 'password'})

    @field_validator('access_token', mode='before')
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name='Token')
        if any(c.isspace() for c in value):
            raise ValueError('Paste the token without the Bearer prefix')
        return value

class GoogleBooksOAuthCredential(GoogleBooksAccessTokenCredential):
    # Google's existing family handler saves new Books grants as google_oauth.
    # Classroom owns this shared type; declaring it borrowed keeps one owner.
    model_config = ConfigDict(title='Google Books OAuth', json_schema_extra={
        'x-credential-type': 'oauth', 'x-oauth-provider': 'google',
        'x-oauth-scopes': GOOGLE_BOOKS_SCOPES.declared_scopes(),
        'x-credential-url': 'https://console.cloud.google.com/apis/library/books.googleapis.com',
    })
    credential_type: Literal['google_oauth'] = Field('google_oauth', json_schema_extra={'ui:hidden': True})
    refresh_token: str | None = Field(None, title='Refresh Token', repr=False, json_schema_extra={'ui:widget': 'password'})
    expires_at: str | None = Field(None, title='Token Expiry', description='ISO 8601 expiry, if known.')
    email: str | None = Field(None, title='Google Account')
    scope: str | None = Field(None, title='Granted Scopes', json_schema_extra={'ui:hidden': True})

class _Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

class AnnotationRange(_Input):
    startPosition: str | None = None
    endPosition: str | None = None
    startOffset: str | None = None
    endOffset: str | None = None

class AnnotationRanges(_Input):
    contentVersion: str | None = None
    gbTextRange: AnnotationRange | None = None
    gbImageRange: AnnotationRange | None = None
    cfiRange: AnnotationRange | None = None
    imageCfiRange: AnnotationRange | None = None

class AnnotationInput(_Input):
    volumeId: str = Field(..., min_length=1, title='Book ID')
    layerId: str | None = None
    data: str | None = Field(None, description='Your note or other annotation data.')
    selectedText: str | None = None
    beforeSelectedText: str | None = None
    afterSelectedText: str | None = None
    highlightStyle: str | None = None
    pageIds: list[str] | None = None
    clientVersionRanges: AnnotationRanges | None = None

def _field(name, required):
    default = ... if required else None
    title = name.replace('_', ' ').title()
    if name == 'max_results':
        return int, Field(40, ge=1, le=40, title='Page Size')
    if name == 'start_index':
        return int, Field(0, ge=0, title=title)
    if name == 'volume_position':
        return int, Field(default, ge=0, title=title)
    if name == 'annotation':
        return AnnotationInput, Field(default, title='Annotation')
    choices = {
        'order_by': ('newest', 'relevance'), 'filter': ('ebooks', 'free-ebooks', 'full', 'paid-ebooks', 'partial'),
        'print_type': ('ALL', 'BOOKS', 'MAGAZINES'), 'projection': ('FULL', 'LITE'),
        'rating': ('HAVE_IT', 'NOT_INTERESTED'), 'action': ('bookmark', 'chapter', 'next-page', 'prev-page', 'scroll', 'search'),
    }
    typ = Literal[choices[name]] if name in choices else str
    if not required:
        typ = typ | None
    return typ, Field(default, title=title, **({'min_length': 1} if name not in choices else {}))

def _model(name, op):
    paths = tuple(part.split('}')[0] for part in op.path.split('{')[1:])
    fields = {key: _field(key, key in op.required or key in paths) for key in dict.fromkeys((*paths, *op.fields))}
    label = name.replace('_', ' ').title()
    return create_model('GoogleBooks' + ''.join(p.title() for p in name.split('_')) + 'Config',
        __base__=_Input, __module__=__name__, operation=(Literal[name], Field(name, title=label, json_schema_extra={
            'ui:hidden': True, 'x-display-name': label, 'x-category': 'Google Books', 'x-is-trigger': False})), **fields)

CONFIG_MODELS = {name: _model(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})

class GoogleBooksOnAnnotationUpdatedConfig(PollTriggerConfigBase):
    operation: Literal['on_annotation_updated'] = Field('on_annotation_updated', title='On New or Updated Annotation', json_schema_extra={
        'ui:hidden': True, 'x-display-name': 'On New or Updated Annotation', 'x-category': 'Triggers', 'x-is-trigger': True})
    volume_id: str | None = Field(None, title='Book ID', min_length=1, description='Optional book to watch; otherwise watch your whole library.')
    updated_min: str | None = Field(None, title='Updated Since', description='Optional inclusive RFC 3339 lower bound for annotation updates.')

    @field_validator('updated_min')
    @classmethod
    def timestamp(cls, value):
        if value is not None and datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('Use a timestamp with a timezone')
        return value

GoogleBooksConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (GoogleBooksOnAnnotationUpdatedConfig,)], Field(discriminator='operation')]

class GoogleBooksNodeConfig(NodeConfig[GoogleBooksConfig, Union[GoogleBooksAccessTokenCredential, GoogleBooksOAuthCredential]]):
    pass

class GoogleBooksNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = 'automation-google-books'
    borrowed_credential_types = frozenset({'google_oauth'})
    credential_provider_labels = {'google_books': 'Google Books'}
    scope_registry = GOOGLE_BOOKS_SCOPES
    connection_evidence = ConnectionEvidence(operation='list_my_bookshelves', noun='bookshelves')

    @classmethod
    def get_config_model(cls):
        return GoogleBooksNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get('refresh_token'):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider='google')

    async def _token(self, credential):
        if not isinstance(credential, GoogleBooksOAuthCredential) or not credential.refresh_token:
            return credential.access_token
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.google_oauth import refresh_access_token
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get('credential_id'),
            user_id=self.user_id, credential=data, refresh=refresh_access_token, provider='google', caller_path='execute')
        for key in ('access_token', 'refresh_token', 'expires_at'):
            setattr(credential, key, data.get(key))
        return token

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
        if response.is_error:
            try:
                detail = response.json().get('error', {}).get('message')
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f'Google Books API error {response.status_code}: {detail or "request failed"}')
        data = response.json() if response.content else {}
        if not isinstance(data, dict) or 'error' in data:
            raise ValueError('Google Books returned an unexpected response')
        return data

    async def _poll_annotations(self, token, config):
        params = {'maxResults': 40}
        if config.volume_id is not None:
            params['volumeId'] = config.volume_id
        if config.updated_min is not None:
            params['updatedMin'] = config.updated_min
        items, seen_pages = [], set()
        for _ in range(100):
            data = await self._request(token, 'GET', '/mylibrary/annotations', params=params)
            page = data.get('items', [])
            if not isinstance(page, list) or any(not isinstance(row, dict) or not row.get('id') or not row.get('updated') for row in page):
                raise ValueError('Google Books annotations need id and updated fields for polling')
            items.extend(page)
            cursor = data.get('nextPageToken')
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen_pages:
                raise ValueError('Google Books repeated an annotation page token')
            seen_pages.add(cursor)
            params['pageToken'] = cursor
        else:
            raise ValueError('More than 4,000 annotations; narrow the book or Updated Since filter')
        fresh = await self._filter_unseen(items, lambda row: row['id'] + ':' + row['updated'])
        return {'annotations': fresh, 'new_annotation_count': len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get('annotations') if isinstance(output, dict) else None
        if not isinstance(rows, list):
            return super().resolve_agent_event(output)
        if not rows:
            return None
        lines = [f"- Annotation {row.get('id')} on book {row.get('volumeId')}: {row.get('data') or row.get('selectedText') or '(no text)'} (updated {row.get('updated')})" for row in rows[:20]]
        return {'text': 'Google Books: new or updated annotations in your library:\n' + '\n'.join(lines), 'conversation_key': None}

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError('Connect Google Books')
        config = self.config.config
        self.scope_registry.require(config.operation)
        token = await self._token(credential)
        if isinstance(config, GoogleBooksOnAnnotationUpdatedConfig):
            return await self._poll_annotations(token, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={'operation'})
        path = spec.path
        for key in tuple(values):
            if '{' + key + '}' in path:
                path = path.replace('{' + key + '}', quote(str(values.pop(key)), safe=''))
        body = values.pop('annotation', None) if spec.body else None
        params = {WIRE_NAMES.get(key, key): value for key, value in values.items()}
        data = await self._request(token, spec.method, path, params=params, body=body)
        return {'operation': config.operation, 'data': data}

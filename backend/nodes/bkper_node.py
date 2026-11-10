"""Bkper v5: https://bkper.com/docs/api/rest/openapi.json.

OAuth: https://bkper.com/docs/platform/scripts/rest-api
Webhook identity: https://bkper.com/docs/platform/apps/self-hosted
"""
from __future__ import annotations
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.bkper_operations import OPERATIONS
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.bkper import BKPER_SCOPES

BASE = "https://api.bkper.app"
SERVICE_ACCOUNT = "bkper-hrd@appspot.gserviceaccount.com"
EVENT_TYPES = tuple(next(p['enum'] for p in OPERATIONS['list_events']['parameters'] if p['name'] == 'type'))
_GOOGLE_KEYS = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", timeout=10)


def _id(value):
    if type(value) is int:
        value = str(value)
    if not value or value in {".", ".."} or len(value) > 512 or any(c in value for c in "/?#\\") or any(ord(c) < 33 for c in value):
        raise ValueError("Copy a single Bkper resource ID")
    return value


class BkperOAuthCredential(BaseModel):
    credential_type: Literal['google_oauth'] = Field('google_oauth', json_schema_extra={'ui:hidden': True})
    access_token: str = Field(..., min_length=1, title='Access Token', json_schema_extra={'ui:widget': 'password'})
    refresh_token: str | None = Field(None, title='Refresh Token', json_schema_extra={'ui:widget': 'password'})
    expires_at: str | None = Field(None, title='Token Expiry')
    email: str | None = Field(None, title='Google Account')
    scope: str | None = Field(None, json_schema_extra={'ui:hidden': True})
    client_id: str | None = Field(None, json_schema_extra={'ui:hidden': True})
    client_secret: str | None = Field(None, json_schema_extra={'ui:hidden': True})
    model_config = ConfigDict(title='Bkper Google Account', hide_input_in_errors=True, json_schema_extra={
        'x-credential-type': 'oauth', 'x-oauth-provider': 'google',
        'x-oauth-scopes': BKPER_SCOPES.declared_scopes(),
        'x-credential-url': 'https://bkper.com/docs/platform/scripts/rest-api',
        'x-credential-instructions': 'Sign in with the Google account you use for Bkper. An existing OAuth access token can also be supplied; refresh token and expiry enable renewal.',
    })
    @field_validator('access_token', 'refresh_token', mode='before')
    @classmethod
    def token(cls, value):
        return clean_secret(value, field_name='Token', key=True) if value is not None else value


class _Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AccountRef(_Input):
    id: str | None = None
    name: str | None = None
    @model_validator(mode='after')
    def identifiable(self):
        if not self.id and not self.name:
            raise ValueError('An account ID or name is required')
        return self


class GroupRef(_Input):
    id: str


class BookBody(_Input):
    id: str | None = None
    name: str | None = None
    timeZone: str | None = None
    fractionDigits: int | None = Field(None, ge=0)
    decimalSeparator: Literal['DOT', 'COMMA'] | None = None
    properties: dict[str, str] | None = None


class AccountBody(_Input):
    id: str | None = None
    name: str | None = None
    type: Literal['ASSET', 'LIABILITY', 'INCOMING', 'OUTGOING'] | None = None
    archived: bool | None = None
    groups: list[GroupRef] | None = None
    properties: dict[str, str] | None = None


class GroupBody(_Input):
    id: str | None = None
    name: str | None = None
    parent: GroupRef | None = None
    hidden: bool | None = None
    properties: dict[str, str] | None = None


class TransactionBody(_Input):
    id: str | None = None
    date: str | None = Field(None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    amount: str | None = Field(None, pattern=r'^-?\d+(?:\.\d+)?$')
    description: str | None = None
    creditAccount: AccountRef | None = None
    debitAccount: AccountRef | None = None
    properties: dict[str, str] | None = None
    remoteIds: list[str] | None = None
    urls: list[str] | None = None


BODY_MODELS = {'Book': BookBody, 'Account': AccountBody, 'Group': GroupBody, 'Transaction': TransactionBody}
PARAM_NAMES = {'bookId': 'book_id', 'id': 'resource_id', 'resoureId': 'resource_id_filter'}


class _OperationInput(_Input):
    # Canvas labels and credential attachments are metadata, never API fields.
    model_config = ConfigDict(extra='ignore')

    @model_validator(mode='after')
    def required_body_values(self):
        body = getattr(self, 'body', None)
        if body is None:
            return self
        name = self.operation
        if name.startswith('update_') or name in {'post_transaction', 'check_transaction', 'trash_transaction'}:
            if not body.id:
                raise ValueError('The body must include the resource ID')
        if name.startswith('create_') and name != 'create_transaction' and not body.name:
            raise ValueError('Give the new resource a name')
        if name == 'create_transaction' and any(getattr(body, key) is None for key in ('date', 'amount', 'creditAccount', 'debitAccount')):
            raise ValueError('A transaction needs date, amount, credit account and debit account')
        return self


def _config(name, op):
    label = name.replace('_', ' ').title()
    fields = {'operation': (Literal[name], Field(name, title=label, description=op['description'], json_schema_extra={
        'ui:hidden': True, 'x-display-name': label, 'x-category': 'Bkper', 'x-is-trigger': False}))}
    for param in op['parameters']:
        key = PARAM_NAMES.get(param['name'], param['name'])
        if param['in'] == 'body':
            fields['body'] = (BODY_MODELS[param['name']], Field(..., title=param['name'], description='Only supplied fields are sent. Updates must include the ID.'))
            continue
        kind = {'integer': int, 'boolean': bool}.get(param.get('type'), str)
        if param.get('enum'):
            kind = Literal[tuple(param['enum'])]
        extra = {'x-dynamic-options': {'field_name': 'book_id', 'allow_custom': True}} if key == 'book_id' else {}
        fields[key] = (kind if param.get('required') else kind | None, Field(... if param.get('required') else None,
            title=key.replace('_', ' ').title(), description=param.get('description', ''), json_schema_extra=extra))
    return create_model('Bkper' + label.replace(' ', '') + 'Config', __base__=_OperationInput, **fields)


CONFIG_MODELS = {name: _config(name, op) for name, op in OPERATIONS.items()}


class BkperOnBookEventConfig(WebhookTriggerConfigBase):
    operation: Literal['on_book_event'] = Field('on_book_event', title='On Book Event', json_schema_extra={
        'ui:hidden': True, 'x-is-trigger': True, 'x-display-name': 'On Book Event', 'x-category': 'Triggers'})
    book_id: str = Field(..., title='Book', json_schema_extra={'x-dynamic-options': {'field_name': 'book_id', 'allow_custom': True}})
    webhook_url: str | None = Field(None, title='Webhook URL', json_schema_extra={'ui:readonly': True, 'ui:loadValue': True})


BkperOperationConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (BkperOnBookEventConfig,)], Field(discriminator='operation')]


class BkperNodeConfig(NodeConfig[BkperOperationConfig, BkperOAuthCredential]):
    pass


class BkperNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = 'automation-bkper'
    connection_evidence = ConnectionEvidence(noun='books', operation='list_books', identity_operation='get_user')
    scope_registry = BKPER_SCOPES
    webhook_signing_secret_not_issued = True

    @classmethod
    def get_config_model(cls):
        return BkperNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get('refresh_token'):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.google_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider='google')

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
        if response.is_error:
            try:
                problem = response.json()
                nested = problem.get('error')
                detail = (nested.get('message') if isinstance(nested, dict) else nested) or problem.get('detail') or problem.get('message')
            except (ValueError, AttributeError):
                detail = None
            if detail:
                raise httpx.HTTPStatusError(f'Bkper API {response.status_code}: {detail}', request=response.request, response=response)
        response.raise_for_status()
        data = response.json() if response.content else {}
        if not isinstance(data, dict):
            raise ValueError('Bkper returned an unexpected response')
        if 'error' in data:
            raise ValueError(str(data['error']))
        return data

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        if field_name != 'book_id':
            return {'options': []}
        cred = await cls.freshen_credential(dict(credential_data or {}))
        data = await cls._request(cred['access_token'], 'GET', '/v5/books')
        return {'options': [{'value': x['id'], 'label': x.get('name') or x['id']} for x in data.get('items', [])
            if x.get('id') and (not search or search.lower() in (x.get('name') or '').lower())]}

    async def execute(self, inputs):
        cred = self.config.credentials
        if cred is None:
            raise ValueError('Connect the Google account you use with Bkper')
        config = self.config.config
        self.scope_registry.require(config.operation)
        data = cred.model_dump()
        token = cred.access_token
        if cred.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.google_oauth import refresh_access_token
            token = await ensure_fresh_oauth_token(credential_id=self.node_data.get('credential_id'),
                user_id=self.user_id, credential=data, refresh=refresh_access_token, provider='google', caller_path='execute')
            for field in ('access_token', 'refresh_token', 'expires_at'):
                setattr(cred, field, data.get(field))
        if config.operation == 'on_book_event':
            return self.resolve_trigger_payload(inputs, config.model_dump())
        spec = OPERATIONS[config.operation]
        path, params, body = spec['path'], {}, None
        for param in spec['parameters']:
            name = param['name']
            if param['in'] == 'body':
                body = config.body.model_dump(exclude_none=True)
            else:
                value = getattr(config, PARAM_NAMES.get(name, name))
                if value is None:
                    continue
                if param['in'] == 'path':
                    path = path.replace('{' + name + '}', quote(_id(value), safe=''))
                else:
                    params[name] = value
        return await self._request(token, spec['method'], path, params=params or None, body=body)

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        book = quote(_id(config['book_id']), safe='')
        cred = await cls.freshen_credential(dict(credential))
        # One app per node prevents overwriting another workflow's callback.
        app_id = 'noclick-' + re.sub(r'[^a-zA-Z0-9_-]', '-', node_id)
        method = 'PUT'
        try:
            await cls._request(cred['access_token'], 'GET', '/v5/apps/' + quote(app_id, safe=''))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            method = 'POST'
        await cls._request(cred['access_token'], method, '/v5/apps', body={
            'id': app_id, 'name': 'NoClick Book Events', 'apiVersion': 'v5',
            'webhookUrl': webhook_url, 'webhookUrlDev': webhook_url,
            'events': list(EVENT_TYPES), 'installable': True,
        })
        installed = await cls._request(cred['access_token'], 'GET', f'/v5/books/{book}/integrations')
        result = next((row for row in installed.get('items', []) if row.get('agentId') == app_id), None)
        if result is None:
            result = await cls._request(cred['access_token'], 'POST', f'/v5/books/{book}/integrations', body={'agentId': app_id})
        if not result.get('id'):
            raise ValueError('Bkper did not return an integration ID')
        return {'external_webhook_id': result['id']}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        if not credential or not config.get('external_webhook_id'):
            return
        cred = await cls.freshen_credential(dict(credential))
        book = quote(_id(config['book_id']), safe='')
        identifier = quote(_id(str(config['external_webhook_id'])), safe='')
        await cls._request(cred['access_token'], 'DELETE', f'/v5/books/{book}/integrations/{identifier}')

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {'book_id': config.get('book_id')}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Service-to-function JWT authenticates the invoker, not a body HMAC.
        audience = config.get('webhook_url')
        value = next((v for k, v in headers.items() if k.lower() == 'authorization'), '')
        if not audience or not value.startswith('Bearer '):
            return False
        token = value[7:]
        try:
            key = _GOOGLE_KEYS.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=['RS256'], audience=audience,
                issuer=['https://accounts.google.com', 'accounts.google.com'],
                options={'require': ['exp', 'iat', 'aud', 'iss', 'sub', 'email', 'email_verified']})
            return claims['email'] == SERVICE_ACCOUNT and claims['email_verified'] is True
        except (jwt.PyJWTError, ValueError, OSError):
            return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get('bookId') == config.get('book_id') and payload.get('type') in EVENT_TYPES

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        # Event auth headers can contain a user's OAuth token; never emit them.
        return {key: value for key, value in payload.items() if key in {
            'agent', 'book', 'bookId', 'botResponses', 'createdAt', 'createdOn',
            'data', 'id', 'resource', 'type', 'user',
        }}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get('type') not in EVENT_TYPES:
            return None
        user, book = output.get('user') or {}, output.get('book') or {}
        event_type = output['type'].replace('_', ' ').lower()
        who = user.get('name') or user.get('username') or 'Someone'
        book_id = output.get('bookId') or book.get('id') or ''
        content = (output.get('data') or {}).get('object') or {}
        return {'text': f"Bkper: {who} — {event_type} in {book.get('name') or book_id}. "
            f"Event ID: {output.get('id')}; book ID: {book_id}; resource: {output.get('resource')}. Content: {content}",
            'conversation_key': f'bkper:{book_id}'}

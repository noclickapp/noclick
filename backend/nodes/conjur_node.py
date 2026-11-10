"""CyberArk Conjur Open Source REST API (published OpenAPI 5.3.2)."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_https_origin


Kind = Literal['variable', 'policy', 'user', 'role', 'host', 'host_factory', 'group', 'layer']


def _identifier(value):
    if not isinstance(value, str) or not value or re.search(r'[\s:\x00-\x1f\x7f]', value):
        raise ValueError('Use a Conjur identifier without whitespace or colons')
    if value in {'.', '..'}:
        raise ValueError('Use a resource identifier, not a path segment')
    return value


class ConjurAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title='Conjur API Key', hide_input_in_errors=True, json_schema_extra={
        'x-credential-url': 'https://github.com/cyberark/conjur-openapi-spec/blob/main/spec/authentication.yml',
        'x-credential-instructions': 'Enter your Conjur HTTPS server origin, account, login and existing API key. For a host, use host/<host-id> as the login. NoClick exchanges the key for a short-lived access token for each execution and verifies the connection with WhoAmI. Permissions remain controlled by your Conjur policy. Secret reads and loaded policies can return sensitive values.'})
    credential_type: Literal['conjur_api_key'] = Field('conjur_api_key', json_schema_extra={'ui:hidden': True})
    server_url: str = Field(..., title='Server URL', description='Exact HTTPS origin of your Conjur server, e.g. https://conjur.example.com.')
    account: str = Field(..., min_length=1, title='Account')
    login: str = Field(..., min_length=1, title='Login', description='User ID, or host/<host-id>. Enter the original value, without URL encoding.')
    api_key: str = Field(..., min_length=50, max_length=56, title='API key', json_schema_extra={'ui:widget': 'password'})

    @field_validator('server_url')
    @classmethod
    def origin(cls, value):
        return normalize_https_origin(value, field_name='Conjur server URL')

    @field_validator('account', 'login')
    @classmethod
    def identifier(cls, value):
        return _identifier(value)

    @field_validator('api_key')
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name='API key', key=True)
        if not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Paste the API key without whitespace')
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra='ignore', hide_input_in_errors=True)


class GetIdentity(_Input):
    """Show the authenticated account and username."""
    operation: Literal['get_identity'] = Field('get_identity', json_schema_extra={'ui:hidden': True})


class _Page(_Input):
    limit: int = Field(100, ge=1, le=1000, description='Maximum results in this page. Use offset to request subsequent pages.')
    offset: int = Field(0, ge=0)
    search: Optional[str] = Field(None, min_length=1)


class ListResources(_Page):
    """List accessible resources for the authenticated account."""
    operation: Literal['list_resources'] = Field('list_resources', json_schema_extra={'ui:hidden': True})
    kind: Optional[Kind] = None


class ListAccountResources(_Page):
    """List resources through the account resource endpoint."""
    operation: Literal['list_account_resources'] = Field('list_account_resources', json_schema_extra={'ui:hidden': True})
    kind: Optional[Kind] = None


class ListKindResources(_Page):
    """List resources of a selected kind in the connected account."""
    operation: Literal['list_kind_resources'] = Field('list_kind_resources', json_schema_extra={'ui:hidden': True})
    kind: Kind = Field(...)


class _Resource(_Input):
    kind: Kind = Field(...)
    identifier: str = Field(..., min_length=1, description='Original resource ID, e.g. prod/aws/db-password; NoClick URL-encodes it.')

    @field_validator('identifier')
    @classmethod
    def identifier_value(cls, value):
        return _identifier(value)


class GetResource(_Resource):
    """Read resource metadata, permissions and versions."""
    operation: Literal['get_resource'] = Field('get_resource', json_schema_extra={'ui:hidden': True})


class GetSecret(_Input):
    """Read the latest or a retained version of a secret value."""
    operation: Literal['get_secret'] = Field('get_secret', json_schema_extra={'ui:hidden': True})
    identifier: str = Field(..., min_length=1, description='Original variable ID; NoClick URL-encodes it.')
    version: Optional[int] = Field(None, ge=1)

    @field_validator('identifier')
    @classmethod
    def identifier_value(cls, value):
        return _identifier(value)


class SetSecret(_Input):
    """Add a new secret value to an existing variable."""
    operation: Literal['set_secret'] = Field('set_secret', json_schema_extra={'ui:hidden': True})
    identifier: str = Field(..., min_length=1)
    value: str = Field(..., description='UTF-8 secret value; sent verbatim as the request body.', json_schema_extra={'ui:widget': 'password'})

    @field_validator('identifier')
    @classmethod
    def identifier_value(cls, value):
        return _identifier(value)


class GetSecrets(_Input):
    """Fetch several secrets in one API call."""
    operation: Literal['get_secrets'] = Field('get_secrets', json_schema_extra={'ui:hidden': True})
    variable_ids: str = Field(..., min_length=1, description='Comma-separated fully qualified IDs, e.g. myorg:variable:secret1,myorg:variable:secret2. NoClick URL-encodes the query.')


class GetRole(_Resource):
    """Get role details, direct members or memberships."""
    operation: Literal['get_role'] = Field('get_role', json_schema_extra={'ui:hidden': True})
    view: Literal['details', 'members', 'memberships', 'all'] = 'details'
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class _Membership(_Resource):
    member: str = Field(..., min_length=1, pattern=r'^[^ ]+$', description='Fully qualified role ID to grant or revoke, e.g. myorg:user:alice.')


class AddRoleMember(_Membership):
    """Grant the selected role to a member."""
    operation: Literal['add_role_member'] = Field('add_role_member', json_schema_extra={'ui:hidden': True})


class RemoveRoleMember(_Membership):
    """Revoke a direct role membership."""
    operation: Literal['remove_role_member'] = Field('remove_role_member', json_schema_extra={'ui:hidden': True})


class _Policy(_Input):
    identifier: str = Field(..., min_length=1, description='Policy ID; use root for the root policy.')
    policy: str = Field(..., min_length=1, description='Conjur policy YAML, sent verbatim.', json_schema_extra={'ui:widget': 'code_editor'})

    @field_validator('identifier')
    @classmethod
    def identifier_value(cls, value):
        return _identifier(value)


class LoadPolicy(_Policy):
    """Add policy data; omitted objects are retained and deletions are refused."""
    operation: Literal['load_policy'] = Field('load_policy', json_schema_extra={'ui:hidden': True})


class UpdatePolicy(_Policy):
    """Modify policy data, including explicit delete, revoke and deny statements."""
    operation: Literal['update_policy'] = Field('update_policy', json_schema_extra={'ui:hidden': True})


class ReplacePolicy(_Policy):
    """Replace a policy: existing objects omitted from this YAML will be deleted."""
    operation: Literal['replace_policy'] = Field('replace_policy', json_schema_extra={'ui:hidden': True})


class GetPublicKeys(_Resource):
    """Read SSH public keys for a user or host."""
    operation: Literal['get_public_keys'] = Field('get_public_keys', json_schema_extra={'ui:hidden': True})


ConjurOperation = Annotated[Union[GetIdentity, GetSecret, SetSecret, GetSecrets,
    ListResources, ListAccountResources, ListKindResources, GetResource,
    GetRole, AddRoleMember, RemoveRoleMember, LoadPolicy, UpdatePolicy,
    ReplacePolicy, GetPublicKeys], Field(discriminator='operation')]


class ConjurConfig(NodeConfig[ConjurOperation, ConjurAPIKeyCredential]):
    pass


class ConjurNode(WorkflowNode):
    integration_type = 'automation-conjur'
    connection_evidence = ConnectionEvidence(noun='Conjur account', identity_operation='get_identity', identity_keys=('username', 'account'))

    @classmethod
    def get_config_model(cls):
        return ConjurConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError('Connect a Conjur API key')
        credential = self.config.credentials
        op = self.config.config
        enc = lambda value: quote(value, safe='')
        account = enc(credential.account)
        token = None

        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            client.headers.pop('Accept-Encoding', None)
            async def request(method, path, *, params=None, content=None, content_type=None, authenticate=False):
                headers = {'Accept': 'application/json'}
                if authenticate:
                    headers['Accept-Encoding'] = 'base64'
                else:
                    headers['Authorization'] = 'Token token=' + token
                if content_type:
                    headers['Content-Type'] = content_type
                response = await client.request(method, credential.server_url + path, params=params, content=content, headers=headers)
                if not 200 <= response.status_code < 300:
                    message = response.text[:2000]
                    for secret in (credential.api_key, token, getattr(op, 'value', None)):
                        if secret:
                            message = message.replace(secret, '[redacted]')
                    raise ValueError(f'Conjur HTTP {response.status_code}: {message}')
                return response

            auth = await request('POST', f'/authn/{account}/{enc(credential.login)}/authenticate',
                content=credential.api_key.encode(), content_type='text/plain', authenticate=True)
            token = auth.text.strip()
            if not token or not token.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in token):
                raise ValueError('Conjur returned an invalid base64 access token')

            action = op.operation
            method, params, content, content_type = 'GET', {}, None, None
            if action == 'get_identity':
                path = '/whoami'
            elif isinstance(op, (GetSecret, SetSecret)):
                path = f'/secrets/{account}/variable/{enc(op.identifier)}'
                if isinstance(op, SetSecret):
                    method, content, content_type = 'POST', op.value.encode(), 'application/octet-stream'
                elif op.version is not None:
                    params['version'] = op.version
            elif isinstance(op, GetSecrets):
                path, params = '/secrets', {'variable_ids': op.variable_ids}
            elif isinstance(op, (ListResources, ListAccountResources, ListKindResources)):
                path = '/resources'
                if not isinstance(op, ListResources):
                    path += '/' + account
                if isinstance(op, ListKindResources):
                    path += '/' + enc(op.kind)
                elif op.kind is not None:
                    params['kind'] = op.kind
                params.update(limit=op.limit, offset=op.offset)
                if op.search is not None:
                    params['search'] = op.search
            elif isinstance(op, GetResource):
                path = f'/resources/{account}/{enc(op.kind)}/{enc(op.identifier)}'
            elif isinstance(op, (GetRole, AddRoleMember, RemoveRoleMember)):
                path = f'/roles/{account}/{enc(op.kind)}/{enc(op.identifier)}'
                if isinstance(op, GetRole):
                    if op.view != 'details':
                        params[op.view] = 'true'
                    if op.view == 'members':
                        params.update(limit=op.limit, offset=op.offset)
                else:
                    method = 'POST' if isinstance(op, AddRoleMember) else 'DELETE'
                    params = {'members': 'true', 'member': op.member}
            elif isinstance(op, _Policy):
                path = f'/policies/{account}/policy/{enc(op.identifier)}'
                method = {'load_policy': 'POST', 'update_policy': 'PATCH', 'replace_policy': 'PUT'}[action]
                content, content_type = op.policy.encode(), 'text/plain'
            elif isinstance(op, GetPublicKeys):
                path = f'/public_keys/{account}/{enc(op.kind)}/{enc(op.identifier)}'
            else:
                raise ValueError('Unsupported Conjur operation')
            response = await request(method, path, params=params, content=content, content_type=content_type)
            if response.status_code == 204 or not response.content:
                data = None
            elif isinstance(op, (GetSecret, GetPublicKeys)):
                data = response.text
            else:
                data = response.json()
            result = {'status': 'success', 'operation': action, 'data': data, 'http_status': response.status_code}
            if isinstance(op, (ListResources, ListAccountResources, ListKindResources)):
                if not isinstance(data, list):
                    raise ValueError('Conjur did not return a resource list')
                # Offset pagination offers no stable snapshot; the caller requests each page explicitly.
                result.update(next_offset=op.offset + len(data) if len(data) == op.limit else None)
            await self.emit(result)
            return result

"""SendX audience metadata and finite contact/list/tag workflows; no delivery actions."""
from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from typing import Annotated, Literal, Union

from opentelemetry.instrumentation.utils import suppress_instrumentation
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator, model_serializer, model_validator

from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = 'automation-sendx'
ROOT = 'https://api.sendx.io/api/v1/rest'
MAX_BYTES = 2 * 1024 * 1024
ContactID = Annotated[str, StringConstraints(strict=True, pattern=r'^contact_[a-zA-Z0-9]{22}$')]
ListID = Annotated[str, StringConstraints(strict=True, pattern=r'^(list_)?[a-zA-Z0-9]{22}$')]
TagID = Annotated[str, StringConstraints(strict=True, pattern=r'^(tag_)?[a-zA-Z0-9]{22}$')]
CustomFieldID = Annotated[str, StringConstraints(strict=True, pattern=r'^(custom_field_)?[a-zA-Z0-9]{22}$')]
CampaignID = Annotated[str, StringConstraints(strict=True, pattern=r'^campaign_[a-zA-Z0-9]{22}$')]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=255)]
Operation = Literal['list_contacts', 'get_contact', 'list_lists', 'get_list', 'list_tags', 'get_tag', 'list_custom_fields', 'get_custom_field', 'list_campaigns', 'get_campaign', 'get_campaign_report', 'create_contact', 'update_contact', 'delete_contact', 'create_list', 'update_list', 'delete_list', 'create_tag', 'update_tag', 'delete_tag']
OPERATIONS = ('list_contacts', 'get_contact', 'list_lists', 'get_list', 'list_tags', 'get_tag', 'list_custom_fields', 'get_custom_field', 'list_campaigns', 'get_campaign', 'get_campaign_report', 'create_contact', 'update_contact', 'delete_contact', 'create_list', 'update_list', 'delete_list', 'create_tag', 'update_tag', 'delete_tag')
READS = set(OPERATIONS[:11])
KINDS = {'contacts': ('contact', ContactID), 'lists': ('list', ListID), 'tags': ('tag', TagID), 'custom_fields': ('customfield', CustomFieldID), 'campaigns': ('campaign', CampaignID)}
PREFIXES = {'contacts': 'contact_', 'lists': 'list_', 'tags': 'tag_', 'custom_fields': 'custom_field_', 'campaigns': 'campaign_'}
EFFECTS = 'Contact/list/tag writes can trigger existing SendX automations. No notification-free, draft-isolation or account-ownership guarantee is established.'
_private_http = ContextVar('sendx_private_http', default=False)


class _PrivateHTTPFilter(logging.Filter):
    def filter(self, record):
        return not _private_http.get()


for _logger in ('httpx', 'httpcore', 'httpcore.connection', 'httpcore.http11', 'httpcore.http2'):
    logging.getLogger(_logger).addFilter(_PrivateHTTPFilter())


def _id(kind, value):
    try:
        result = TypeAdapter(KINDS[kind][1]).validate_python(value)
        return result if result.startswith(PREFIXES[kind]) else PREFIXES[kind] + result
    except ValueError:
        raise ValueError('Malformed documented SendX resource identifier.') from None


class SendXTeamAPIKeyCredential(BaseModel):
    credential_type: Literal['sendx_team_api_key'] = Field('sendx_team_api_key', json_schema_extra={'ui:hidden': True})
    api_key: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)] = Field(title='Existing Team API Key', repr=False, json_schema_extra={'ui:widget': 'password'})
    witness_list_id: ListID = Field(title='Existing Protected Witness List ID', description='Read on connect and before operations. Keep this list separate from cleanup targets. Access proves resource reachability, not a named team or account identity.')
    contact_ids: list[ContactID] = Field(default_factory=list, max_length=20, title='Allowed Contact IDs')
    list_ids: list[ListID] = Field(min_length=1, max_length=20, title='Allowed List IDs', description='Include the witness. Optional list_ prefix is accepted by the documented path contract.')
    tag_ids: list[TagID] = Field(default_factory=list, max_length=20, title='Allowed Tag IDs')
    custom_field_ids: list[CustomFieldID] = Field(default_factory=list, max_length=20, title='Allowed Custom Field IDs')
    campaign_ids: list[CampaignID] = Field(default_factory=list, max_length=20, title='Allowed Campaign Metadata IDs')
    write_contact_ids: list[ContactID] = Field(default_factory=list, max_length=20, title='Allowed Owned Contact Write IDs')
    write_list_ids: list[ListID] = Field(default_factory=list, max_length=20, title='Allowed Owned List Write IDs')
    write_tag_ids: list[TagID] = Field(default_factory=list, max_length=20, title='Allowed Owned Tag Write IDs')
    disposable_contact_ids: list[ContactID] = Field(default_factory=list, max_length=20, title='Owned Disposable Contact IDs', description='Explicit local cleanup declaration, not provider ownership evidence. Delete is soft and cancels pending campaigns.')
    disposable_list_ids: list[ListID] = Field(default_factory=list, max_length=20, title='Owned Disposable List IDs')
    disposable_tag_ids: list[TagID] = Field(default_factory=list, max_length=20, title='Owned Disposable Tag IDs')
    allowed_operations: list[Operation] = Field(min_length=1, max_length=20, title='Allowed Operations', description='Local restrictions do not grant SendX permissions. Get List is required for protected connection evidence. New IDs never automatically extend these restrictions.')
    model_config = ConfigDict(extra='ignore', validate_assignment=True, title='SendX Existing Team API Key', json_schema_extra={'x-credential-url': 'https://docs.sendx.io/api-reference/introduction', 'x-credential-description': 'Supply an existing key from SendX Settings → Team → API. This fixed-host REST integration uses X-Team-ApiKey. It does not issue keys or invent a self endpoint; protected list access is reachability evidence only.'})

    @model_validator(mode='before')
    @classmethod
    def native_fields(cls, data):
        if not isinstance(data, dict) or set(data) - set(cls.model_fields) - {'token_version', 'updated_at'}:
            raise ValueError('Supply only native SendX credentials and explicit resource restrictions.')
        return data

    @field_validator('api_key')
    @classmethod
    def token_only(cls, value):
        value = clean_secret(value, field_name='Existing SendX Team API Key')
        if not value or any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError('Supply only the issued header-safe key, without a prefix or whitespace.')
        return value

    @model_validator(mode='after')
    def restrictions(self):
        for kind in KINDS:
            field = kind[:-1] + '_ids' if kind in ('contacts', 'lists', 'tags', 'campaigns') else 'custom_field_ids'
            allowed = [_id(kind, value) for value in getattr(self, field)]
            if len(set(allowed)) != len(allowed):
                raise ValueError('Use distinct resource restrictions; bare/prefixed aliases are the same resource.')
            if kind in ('contacts', 'lists', 'tags'):
                write = [_id(kind, value) for value in getattr(self, 'write_' + field)]
                disposable = [_id(kind, value) for value in getattr(self, 'disposable_' + field)]
                if len(set(write)) != len(write) or len(set(disposable)) != len(disposable) or not set(write) <= set(allowed) or not set(disposable) <= set(write):
                    raise ValueError('Write and disposable restrictions must be distinct subsets of allowed IDs.')
        if (_id('lists', self.witness_list_id) not in {_id('lists', value) for value in self.list_ids}
                or _id('lists', self.witness_list_id) in {_id('lists', value) for value in self.disposable_list_ids}
                or 'get_list' not in self.allowed_operations or len(set(self.allowed_operations)) != len(self.allowed_operations)):
            raise ValueError('Preserve the protected witness and explicitly allow Get List.')
        return self

    @model_serializer(mode='wrap')
    def preserve_tag(self, handler):
        result = handler(self)
        result['credential_type'] = self.credential_type
        return result


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


def _op(value, title):
    return Field(value, title=title, json_schema_extra={'const': value, 'ui:hidden': True, 'x-display-name': title, 'x-category': 'Audience Metadata', 'x-is-trigger': False})


def _selector(field, description='Explicitly allowed current resource ID.'):
    return Field(description=description, json_schema_extra={'x-dynamic-options': {'field_name': field, 'searchable': True, 'allow_custom': True}})


class _Page(_Model):
    offset: Annotated[int, Field(strict=True, ge=0, le=1000000)] = Field(0, description='One provider page, with no automatic traversal.')
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = Field(10, description='Native cap follows the formal schema. Array length does not prove a last page.')


class _SearchPage(_Page):
    search: Annotated[str, StringConstraints(strict=True, min_length=2, max_length=100)] | None = Field(None, description='Documented partial search; omit to leave the filter unset.')


class SendXListContactsConfig(_Page):
    operation: Literal['list_contacts'] = _op('list_contacts', 'List Allowed Contacts')
    limit: Annotated[int, Field(strict=True, ge=1, le=30)] = Field(10, description='Formal contact schema caps limit at 30; prose says 100. This node uses 30.')
    search: Annotated[str, StringConstraints(strict=True, min_length=2, max_length=255)] | None = None


class SendXGetContactConfig(_Model):
    operation: Literal['get_contact'] = _op('get_contact', 'Get Allowed Contact Metadata')
    contact_id: ContactID = _selector('contact_id')


class SendXListListsConfig(_SearchPage):
    operation: Literal['list_lists'] = _op('list_lists', 'List Allowed Lists')


class SendXGetListConfig(_Model):
    operation: Literal['get_list'] = _op('get_list', 'Get Allowed List Metadata')
    list_id: ListID | None = Field(None, description='Omit to read the protected witness list.', json_schema_extra={'x-dynamic-options': {'field_name': 'list_id', 'searchable': True, 'allow_custom': True}})


class SendXListTagsConfig(_Page):
    operation: Literal['list_tags'] = _op('list_tags', 'List Allowed Tags')


class SendXGetTagConfig(_Model):
    operation: Literal['get_tag'] = _op('get_tag', 'Get Allowed Tag Metadata')
    tag_id: TagID = _selector('tag_id')


class SendXListCustomFieldsConfig(_SearchPage):
    operation: Literal['list_custom_fields'] = _op('list_custom_fields', 'List Allowed Custom Field Definitions')


class SendXGetCustomFieldConfig(_Model):
    operation: Literal['get_custom_field'] = _op('get_custom_field', 'Get Allowed Custom Field Definition')
    custom_field_id: CustomFieldID = _selector('custom_field_id')


class SendXListCampaignsConfig(_Page):
    operation: Literal['list_campaigns'] = _op('list_campaigns', 'List Allowed Campaign Metadata')
    campaign_type: Literal['all', 'draft', 'scheduled', 'sent'] = Field('all', description='Read filter only; this node cannot create, schedule or send campaigns.')


class SendXGetCampaignConfig(_Model):
    operation: Literal['get_campaign'] = _op('get_campaign', 'Get Allowed Campaign Metadata')
    campaign_id: CampaignID = _selector('campaign_id')


class SendXGetCampaignReportConfig(_Model):
    operation: Literal['get_campaign_report'] = _op('get_campaign_report', 'Get Allowed Campaign Aggregate Report')
    campaign_id: CampaignID = _selector('campaign_id', 'Protected campaign metadata is read first. Report link URLs and recipient records are not returned.')


class _Mutation(_Model):
    automation_effects_acknowledged: Literal[True] = Field(title='Allow Possible Existing Automation Effects', description=EFFECTS)

    @field_validator('automation_effects_acknowledged', mode='before')
    @classmethod
    def explicit_effects(cls, value):
        if value is not True:
            raise ValueError('Explicitly acknowledge possible existing SendX automation effects.')
        return value


class _ContactFields(_Mutation):
    email: Text = Field(description='Required by the current RestEContact schema for both create and update. No identity/identify quickstart fields are accepted.')
    first_name: Text | None = None
    last_name: Text | None = None
    company: Text | None = None

    @field_validator('email')
    @classmethod
    def email_shape(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Supply an email address, not a URL or control text.')
        return value

    @model_validator(mode='after')
    def concrete_fields(self):
        if any(getattr(self, field) is None for field in self.model_fields_set & {'first_name', 'last_name', 'company'}):
            raise ValueError('Null is not a documented contact metadata clearing value.')
        return self


class SendXCreateContactConfig(_ContactFields):
    operation: Literal['create_contact'] = _op('create_contact', 'Create Contact')
    lists: list[ListID] | None = Field(None, max_length=20, description='Optional explicit currently allowed lists, checked by protected reads before create. Membership can trigger automations.')
    tags: list[TagID] | None = Field(None, max_length=20, description='Optional explicit currently allowed tags, checked before create.')


class SendXUpdateContactConfig(_ContactFields):
    operation: Literal['update_contact'] = _op('update_contact', 'Update Owned Contact Metadata')
    contact_id: ContactID = _selector('contact_id')


class SendXDeleteContactConfig(_Mutation):
    operation: Literal['delete_contact'] = _op('delete_contact', 'Soft Delete Owned Disposable Contact')
    contact_id: ContactID = _selector('contact_id', 'Explicit disposable target only. Soft deletion removes list memberships and cancels pending campaigns; history is retained.')


class SendXCreateListConfig(_Mutation):
    operation: Literal['create_list'] = _op('create_list', 'Create List')
    name: Text = Field(description='Only name is documented in RestEList; no opt-in type or suppression flag is sent.')


class SendXUpdateListConfig(_Mutation):
    operation: Literal['update_list'] = _op('update_list', 'Rename Owned List')
    list_id: ListID = _selector('list_id')
    name: Text


class SendXDeleteListConfig(_Mutation):
    operation: Literal['delete_list'] = _op('delete_list', 'Delete Owned Disposable List')
    list_id: ListID = _selector('list_id')


class SendXCreateTagConfig(_Mutation):
    operation: Literal['create_tag'] = _op('create_tag', 'Create Tag')
    name: Text = Field(description='Name must be unique within the SendX team.')


class SendXUpdateTagConfig(_Mutation):
    operation: Literal['update_tag'] = _op('update_tag', 'Rename Owned Tag')
    tag_id: TagID = _selector('tag_id')
    name: Text


class SendXDeleteTagConfig(_Mutation):
    operation: Literal['delete_tag'] = _op('delete_tag', 'Delete Owned Disposable Tag')
    tag_id: TagID = _selector('tag_id')


SendXConfig = Annotated[Union[SendXListContactsConfig, SendXGetContactConfig, SendXListListsConfig, SendXGetListConfig, SendXListTagsConfig, SendXGetTagConfig, SendXListCustomFieldsConfig, SendXGetCustomFieldConfig, SendXListCampaignsConfig, SendXGetCampaignConfig, SendXGetCampaignReportConfig, SendXCreateContactConfig, SendXUpdateContactConfig, SendXDeleteContactConfig, SendXCreateListConfig, SendXUpdateListConfig, SendXDeleteListConfig, SendXCreateTagConfig, SendXUpdateTagConfig, SendXDeleteTagConfig], Field(discriminator='operation')]


class SendXFullConfig(NodeConfig[SendXConfig, SendXTeamAPIKeyCredential]):
    pass


def _credential(raw):
    if not isinstance(raw, dict) or raw.get('credential_type') != 'sendx_team_api_key':
        raise ValueError('Choose the native SendX team API key method.')
    try:
        return SendXTeamAPIKeyCredential.model_validate(raw)
    except ValueError:
        raise ValueError('Invalid native SendX credential or resource restrictions.') from None


def _text(value, limit=255, empty=False):
    if not isinstance(value, str) or len(value) > limit or not empty and not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Malformed bounded SendX metadata text.')
    return value


def _private(credential, value):
    if json.dumps(credential.api_key)[1:-1] in json.dumps(value, allow_nan=False, default=str):
        raise ValueError('Credential material cannot appear in native parameters or outputs.')


def _allowed(credential, kind, level=''):
    field = kind[:-1] + '_ids' if kind != 'custom_fields' else 'custom_field_ids'
    return {_id(kind, value) for value in getattr(credential, level + field)}


def _resource(kind, raw, credential, expected_id=None):
    if not isinstance(raw, dict):
        raise ValueError('Expected a documented SendX resource object.')
    resource_id = _id(kind, raw.get('id'))
    if raw.get('id') != resource_id or expected_id is not None and resource_id != _id(kind, expected_id):
        raise ValueError('Response identity differs from its documented prefix or requested resource.')
    result = {'id': resource_id}
    if kind == 'contacts':
        _text(raw.get('email'))
        for flag in ('unsubscribed', 'bounced', 'spam', 'blocked', 'dropped'):
            if flag in raw:
                if type(raw[flag]) is not bool:
                    raise ValueError('Malformed contact state flag.')
                result[flag] = raw[flag]
        for field, related in (('lists', 'lists'), ('tags', 'tags')):
            if field in raw:
                values = raw[field]
                if not isinstance(values, list) or len(values) > 1000:
                    raise ValueError('Contact relationship projection exceeds native bounds.')
                # Related records outside the explicit current scope are never returned.
                result[field] = sorted({_id(related, value) for value in values} & _allowed(credential, related))
        result['profile_fields_returned'] = False
    else:
        result['name'] = _text(raw.get('name'))
        if kind in ('lists', 'custom_fields'):
            value = raw.get('type')
            if type(value) is not int or value not in (range(5) if kind == 'custom_fields' else (0, 1)):
                raise ValueError('Malformed documented list or custom-field type.')
            result['type'] = value
        if kind == 'custom_fields' and 'description' in raw:
            result['description'] = _text(raw['description'], 1000, empty=True)
        if kind == 'campaigns' and 'status' in raw:
            if type(raw['status']) is not int:
                raise ValueError('Malformed campaign status.')
            result['status'] = raw['status']
    for field in ('created', 'updated'):
        if field in raw:
            result[field] = _text(raw[field], 64)
    _private(credential, result)
    return result


class _ProviderFailure(ValueError):
    def __init__(self, status, resource_missing=False):
        self.status, self.resource_missing = status, resource_missing
        super().__init__({401: 'SendX authentication was rejected.', 403: 'SendX denied the operation.', 404: 'SendX resource was not found.', 409: 'SendX reported a resource conflict.', 422: 'SendX rejected the request shape.', 429: 'SendX rate limit reached; no retry performed.'}.get(status, 'SendX did not return the documented completion status.'))


class _ReadbackFailure(ValueError):
    def __init__(self, resource_id):
        self.resource_id = resource_id
        super().__init__('SendX acknowledged the mutation, but independent protected readback remains unverified. Inspect the returned ID before any retry.')


class SendXNode(WorkflowNode):
    integration_type = 'automation-sendx'
    credential_type = 'sendx_team_api_key'
    connection_evidence = ConnectionEvidence(operation='get_list', noun='configured list API', label_keys=('id',), proves='reachability')

    @classmethod
    def get_config_model(cls):
        return SendXFullConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data.get('credentials'), dict):
            credential = _credential(config_data['credentials'])
            _private(credential, {key: value for key, value in config_data.items() if key != 'credentials'})
        return super().parse_config(config_data)

    @classmethod
    def _extract_actionable_validation_error(cls, error, config_data):
        return 'Choose a documented SendX operation and bounded native resource/body fields.'

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data.get('credentials'), dict):
                credential = _credential(config_data['credentials'])
                _private(credential, {key: value for key, value in config_data.items() if key != 'credentials'})
        except ValueError:
            return ValidationResult(valid=False, errors=['Choose native SendX credentials and current explicit resource restrictions.'])
        return super().validate_config(config_data)

    @classmethod
    async def _request(cls, credential, kind, verb, resource_id=None, *, params=None, body=None):
        if kind not in KINDS or verb not in ('list', 'get', 'create', 'update', 'delete', 'report') or verb == 'report' and kind != 'campaigns' or verb in ('create', 'update', 'delete') and kind not in ('contacts', 'lists', 'tags'):
            raise ValueError('Unsupported closed SendX route.')
        path = '/' + KINDS[kind][0]
        if verb in ('get', 'update', 'delete', 'report'):
            _id(kind, resource_id)
            path += '/' + resource_id
        if verb == 'report':
            path = '/report/campaign/' + resource_id
        method = {'list': 'GET', 'get': 'GET', 'report': 'GET', 'create': 'POST', 'update': 'PUT', 'delete': 'DELETE'}[verb]
        expected = 201 if verb == 'create' else 200
        _private(credential, {'params': params, 'body': body})
        marker = _private_http.set(True)
        try:
            with suppress_instrumentation():
                async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                    async with client.stream(method, ROOT + path, headers={'X-Team-ApiKey': credential.api_key, 'Accept': 'application/json'}, params=params, json=body) as response:
                        status = response.status_code
                        if status not in (expected, 404):
                            raise _ProviderFailure(status)
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise ValueError('SendX response exceeds the native byte bound.')
                            chunks.append(chunk)
                        if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                            raise ValueError('Expected documented JSON, not text, media or redirects.')
                        try:
                            payload = json.loads(b''.join(chunks), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                        except (ValueError, UnicodeError):
                            raise ValueError('Malformed SendX JSON.') from None
            if status == 404:
                raise _ProviderFailure(404, resource_missing=isinstance(payload, dict) and payload.get('status') == 'error' and isinstance(payload.get('message'), str))
            return payload
        finally:
            _private_http.reset(marker)

    @classmethod
    async def _get(cls, credential, kind, resource_id):
        raw = await cls._request(credential, kind, 'get', resource_id)
        return raw, _resource(kind, raw, credential, resource_id)

    @classmethod
    async def _dispatch(cls, credential, config):
        op = config.operation
        if op not in credential.allowed_operations:
            raise ValueError('Operation is outside current explicit restrictions.')
        _private(credential, config.model_dump())
        verb = op.split('_', 1)[0]
        kind = {'contact': 'contacts', 'list': 'lists', 'tag': 'tags', 'custom_field': 'custom_fields', 'campaign': 'campaigns'}.get(op.split('_', 1)[1], op.split('_', 1)[1])
        if op == 'get_campaign_report':
            kind, verb = 'campaigns', 'report'
        field = kind[:-1] + '_id' if kind != 'custom_fields' else 'custom_field_id'
        target_id = getattr(config, field, None)
        if op == 'get_list' and target_id is None:
            target_id = credential.witness_list_id
        if target_id is not None:
            canonical = _id(kind, target_id)
            if canonical not in _allowed(credential, kind):
                raise ValueError('Resource is outside the current explicit restriction.')
            if verb in ('update', 'delete') and canonical not in _allowed(credential, kind, 'write_'):
                raise ValueError('Mutation target must be explicitly allowed for owned writes.')
            if verb == 'delete' and canonical not in _allowed(credential, kind, 'disposable_'):
                raise ValueError('Delete requires an explicitly owned disposable target.')
        witness_raw, witness = await cls._get(credential, 'lists', credential.witness_list_id)
        result = {'status': 'success', 'action': op, 'proves': 'reachability', 'account_identity_verified': False, 'provider_team_identity_verified': False, 'protected_witness_access_verified': True, 'witness_list_id': witness['id'], 'mutation_performed': op not in READS}
        if verb == 'list':
            params = {'offset': config.offset, 'limit': config.limit}
            if getattr(config, 'search', None) is not None:
                params['search'] = config.search
            if kind == 'campaigns':
                params['campaignType'] = config.campaign_type
            raw = await cls._request(credential, kind, 'list', params=params)
            if not isinstance(raw, list) or len(raw) > config.limit:
                raise ValueError('Expected a bounded documented bare-array page.')
            rows, seen = [], set()
            for value in raw:
                if not isinstance(value, dict):
                    raise ValueError('Malformed resource page.')
                resource_id = _id(kind, value.get('id'))
                if resource_id in seen:
                    raise ValueError('Duplicate resource in the provider page.')
                seen.add(resource_id)
                if resource_id in _allowed(credential, kind):
                    rows.append(_resource(kind, value, credential))
            result.update(resources=rows, provider_rows_received=len(raw), offset=config.offset, limit=config.limit, next_page_token=None, has_more=None, pagination='One requested offset page. The API documents no next cursor or total; array length does not establish exhaustion.', local_scope_auto_extended=False)
        elif verb in ('get', 'report'):
            raw, resource = (witness_raw, witness) if kind == 'lists' and _id(kind, target_id) == witness['id'] else await cls._get(credential, kind, target_id)
            result['resource'] = resource
            if verb == 'report':
                report = await cls._request(credential, kind, 'report', target_id)
                fields = ('clickedUniqueContactCount', 'openedUniqueContactCount', 'sentContactCount', 'unsubscribeContactCount', 'bounceContactCount', 'spamContactCount', 'clickedContactCount', 'openedContactCount')
                if not isinstance(report, dict) or _id(kind, report.get('campaignId')) != resource['id'] or any(type(report.get(name)) is not int or report[name] < 0 for name in fields):
                    raise ValueError('Malformed campaign-bound aggregate report.')
                result['report'] = {'campaignId': resource['id'], **{name: report[name] for name in fields}, 'link_urls_returned': False}
        else:
            if verb != 'create':
                await cls._get(credential, kind, target_id)
            body = None
            if verb != 'delete':
                if kind == 'contacts':
                    names = {'email': 'email', 'first_name': 'firstName', 'last_name': 'lastName', 'company': 'company'}
                    body = {output: getattr(config, source) for source, output in names.items() if source in config.model_fields_set}
                    if isinstance(config, SendXCreateContactConfig):
                        for related in ('lists', 'tags'):
                            values = getattr(config, related)
                            if values is not None:
                                canonical_values = [_id(related, value) for value in values]
                                if len(set(canonical_values)) != len(values) or not set(canonical_values) <= _allowed(credential, related):
                                    raise ValueError('Contact association must use distinct explicitly allowed records.')
                                for value in values:
                                    await cls._get(credential, related, value)
                                body[related] = values
                else:
                    body = {'name': config.name}
            acknowledgement = await cls._request(credential, kind, verb, target_id, body=body)
            acknowledged_id = target_id
            if verb != 'delete':
                resource = _resource(kind, acknowledgement, credential, None if verb == 'create' else target_id)
                acknowledged_id = resource['id']
            try:
                if verb == 'delete':
                    if not isinstance(acknowledgement, dict) or acknowledgement.get('status') != 'success' or not isinstance(acknowledgement.get('message'), str):
                        raise ValueError('Expected the documented JSON DeleteResponse.')
                    try:
                        await cls._get(credential, kind, target_id)
                    except _ProviderFailure as exc:
                        if exc.status != 404 or not exc.resource_missing:
                            raise
                    else:
                        raise ValueError('Deleted resource still returned by its protected GET.')
                    result.update(resource_id=_id(kind, target_id), deletion='soft' if kind == 'contacts' else 'documented resource deletion', erasure_or_history_retention_verified=False)
                else:
                    if verb == 'create' and resource['id'] in _allowed(credential, kind):
                        raise ValueError('Create returned an existing allowed resource ID.')
                    readback_raw, readback = await cls._get(credential, kind, acknowledged_id)
                    if readback['id'] != resource['id']:
                        raise ValueError('Readback identity changed.')
                    for name, value in body.items():
                        if name in ('lists', 'tags'):
                            if not isinstance(readback_raw.get(name), list) or not {_id(name, item) for item in value} <= {_id(name, item) for item in readback_raw[name]}:
                                raise ValueError('Requested association was not observed in the protected readback.')
                        elif readback_raw.get(name) != value:
                            raise ValueError('Requested metadata was not observed in the protected readback.')
                    result['resource'] = readback
            except Exception:
                raise _ReadbackFailure(_id(kind, acknowledged_id)) from None
            result.update(mutation_acknowledged=True, readback_verified=True, local_scope_auto_extended=False, effects=EFFECTS)
        _private(credential, result)
        return result

    async def execute(self, inputs):
        try:
            if not isinstance(self.config, SendXFullConfig) or self.config.credentials is None:
                raise ValueError('Native SendX credential and config required.')
            credential = self.config.credentials
            return await self._dispatch(credential, self.config.config)
        except _ReadbackFailure as exc:
            return {'status': 'error', 'error': str(exc), 'mutation_acknowledged': True, 'resource_id': exc.resource_id, 'readback_verified': False, 'automatic_retry_performed': False, 'effects': EFFECTS}
        except _ProviderFailure as exc:
            return {'status': 'error', 'error': str(exc), 'http_status': exc.status, 'automatic_retry_performed': False}
        except Exception as exc:
            return {'status': 'error', 'error': 'SendX access or resource workflow remains unverified; check current credentials, restrictions and the documented response.', 'error_type': type(exc).__name__, 'automatic_retry_performed': False}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None, limit=None):
        credential = _credential(credential_data)
        fields = {'contact_id': 'contacts', 'list_id': 'lists', 'tag_id': 'tags', 'custom_field_id': 'custom_fields', 'campaign_id': 'campaigns'}
        if field_name not in fields or page_token is not None or limit is not None and (type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError('Unsupported selector or pagination; selectors read explicit current IDs only.')
        context = context or {}
        allowed_context = {'operation', *fields, *(name + '__label' for name in fields), '_user_id', 'offset', 'limit', 'search', 'campaign_type', 'email', 'first_name', 'last_name', 'company', 'lists', 'tags', 'name', 'automation_effects_acknowledged'}
        if not isinstance(context, dict) or set(context) - allowed_context or context.get('operation') not in (None, *OPERATIONS):
            raise ValueError('Selector context cannot override credential or host authority.')
        for field, kind in fields.items():
            if context.get(field) not in (None, '') and _id(kind, context[field]) not in _allowed(credential, kind):
                raise ValueError('Selector context is outside the current explicit resource restriction.')
        _private(credential, {key: value for key, value in context.items() if key != '_user_id'})
        if search:
            _text(search, 100)
            _private(credential, search)
        kind = fields[field_name]
        read_op = 'get_' + ('custom_field' if kind == 'custom_fields' else kind[:-1])
        if read_op not in credential.allowed_operations:
            raise ValueError('Selector read is outside current allowed operations.')
        _, witness = await cls._get(credential, 'lists', credential.witness_list_id)
        rows = []
        for resource_id in sorted(_allowed(credential, kind)):
            resource = witness if kind == 'lists' and resource_id == witness['id'] else (await cls._get(credential, kind, resource_id))[1]
            label = resource.get('name', resource['id'])
            if not search or search.casefold() in label.casefold() or search in resource_id:
                rows.append({'value': resource_id, 'label': label, 'metadata': {'protected_resource_access_verified': True, 'provider_team_identity_verified': False}})
        _private(credential, rows)
        return {'options': rows[:limit or 100], 'next_page_token': None}

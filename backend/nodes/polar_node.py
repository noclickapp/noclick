"""Native organization-token Polar metadata workflows, pinned to API 2026-10."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from urllib.parse import quote
from contextvars import ContextVar
from typing import Annotated, Literal, Optional, Union

from opentelemetry.instrumentation.utils import suppress_instrumentation
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StringConstraints, field_validator, model_serializer, model_validator

from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

VERSION = '2026-10'
TAG = 'polar_organization_access_token'
NODE_TYPE = 'automation-polar'
MAX_BYTES = 2 * 1024 * 1024
UUID = Annotated[str, StringConstraints(strict=True, pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')]
Text = Annotated[str, StringConstraints(strict=True, max_length=2000)]
ProductName = Annotated[str, StringConstraints(strict=True, min_length=3, max_length=64)]
BenefitDescription = Annotated[str, StringConstraints(strict=True, min_length=3, max_length=42)]
Metadata = Annotated[dict[Annotated[str, StringConstraints(strict=True, min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_.-]+$')], Union[Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)], StrictBool, StrictInt, Annotated[StrictFloat, Field(allow_inf_nan=False)]]], Field(max_length=50)]
Kind = Literal['products', 'customers', 'benefits', 'subscriptions', 'orders']
Scope = Literal['organizations:read', 'products:read', 'products:write', 'customers:read', 'customers:write', 'benefits:read', 'benefits:write', 'subscriptions:read', 'orders:read', 'webhooks:write']
Operation = Literal['on_order_event', 'on_subscription_event', 'on_customer_event', 'check_connection', 'get_organization', 'list_products', 'get_product', 'create_draft_product', 'update_product_metadata', 'archive_product', 'delete_product', 'list_customers', 'get_customer', 'create_customer', 'update_customer_metadata', 'delete_customer', 'list_benefits', 'get_benefit', 'create_draft_custom_benefit', 'update_custom_benefit_metadata', 'delete_custom_benefit', 'list_subscriptions', 'get_subscription', 'list_orders', 'get_order']
OPERATIONS = ('check_connection', 'get_organization', 'list_products', 'get_product', 'create_draft_product', 'update_product_metadata', 'archive_product', 'delete_product', 'list_customers', 'get_customer', 'create_customer', 'update_customer_metadata', 'delete_customer', 'list_benefits', 'get_benefit', 'create_draft_custom_benefit', 'update_custom_benefit_metadata', 'delete_custom_benefit', 'list_subscriptions', 'get_subscription', 'list_orders', 'get_order')
_private_http = ContextVar('polar_private_http', default=False)


class _PrivateHTTPFilter(logging.Filter):
    def filter(self, record):
        return not _private_http.get()


for _logger in ('httpx', 'httpcore', 'httpcore.connection', 'httpcore.http11', 'httpcore.http2'):
    logging.getLogger(_logger).addFilter(_PrivateHTTPFilter())


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


class PolarResourceBinding(_Model):
    kind: Kind
    resource_id: UUID
    customer_id: Optional[UUID] = None
    owned_disposable: StrictBool = False

    @model_validator(mode='after')
    def explicit_parent(self):
        if (self.kind in ('subscriptions', 'orders')) != (self.customer_id is not None):
            raise ValueError('Subscription/order bindings require their customer parent; other resources do not.')
        return self


class PolarOrganizationAccessTokenCredential(BaseModel):
    credential_type: Literal['polar_organization_access_token'] = Field(TAG, json_schema_extra={'ui:hidden': True})
    organization_access_token: Annotated[str, StringConstraints(strict=True, min_length=24, max_length=4096, pattern=r'^polar_oat_[A-Za-z0-9_-]+$')] = Field(title='Organization Access Token', repr=False, json_schema_extra={'ui:widget': 'password'}, description='Existing OAT from this environment. No PAT, customer session, OAuth client secret, or partner token interchange.')
    environment: Literal['sandbox', 'production'] = Field(title='Polar Environment', description='Select explicitly; tokens and organizations are separate in each environment.')
    organization_id: UUID = Field(title='Organization ID')
    declared_scopes: list[Scope] = Field(min_length=1, max_length=10, title='Configured Token Scopes', description='Existing OAT permissions plus local restrictions. These supplied values are not token introspection or proof of a provider grant.')
    allowed_operations: list[Operation] = Field(min_length=1, max_length=25, title='Allowed Operations')
    resource_bindings: list[PolarResourceBinding] = Field(default_factory=list, max_length=250, title='Current Resource Restrictions', description='If a kind has bindings, reads are limited to those IDs. Existing-resource writes require a binding; deletion also requires owned_disposable. Newly created IDs are never added automatically.')
    model_config = ConfigDict(extra='ignore', validate_assignment=True, title='Polar Organization Access Token', json_schema_extra={'x-credential-url': 'https://polar.sh/docs/integrate/authentication', 'x-credential-description': 'Existing organization access token. OAuth partner integration setup and customer portal tokens are separate; no automatic OAuth connection is claimed.'})

    @field_validator('organization_access_token')
    @classmethod
    def clean_token(cls, value):
        return clean_secret(value, field_name='Organization Access Token')

    @model_validator(mode='after')
    def current_restrictions(self):
        if len(self.declared_scopes) != len(set(self.declared_scopes)) or len(self.allowed_operations) != len(set(self.allowed_operations)):
            raise ValueError('Supply distinct scope and operation restrictions.')
        if 'organizations:read' not in self.declared_scopes or 'check_connection' not in self.allowed_operations:
            raise ValueError('The protected organization connection check must be permitted.')
        if len({(row.kind, row.resource_id) for row in self.resource_bindings}) != len(self.resource_bindings):
            raise ValueError('Each resource requires one current binding.')
        return self

    @model_serializer(mode='wrap')
    def preserve_tag(self, handler):
        data = handler(self)
        data['credential_type'] = TAG
        return data


def _op(value, title, category='Metadata'):
    return Field(value, title=title, json_schema_extra={'const': value, 'ui:hidden': True, 'x-display-name': title, 'x-category': category, 'x-is-trigger': False})


def _dynamic(field, parent=None):
    return {'x-dynamic-options': {'field_name': field, 'searchable': True, 'allow_custom': True, **({'depends_on': parent} if parent else {})}}


class PolarCheckConfig(_Model):
    operation: Literal['check_connection'] = _op('check_connection', 'Check Protected Organization Access')


class PolarOrganizationTarget(_Model):
    organization_id: UUID = Field(json_schema_extra=_dynamic('organization_id'), description='Must equal the current OAT organization and selected environment.')


class PolarGetOrganizationConfig(PolarOrganizationTarget):
    operation: Literal['get_organization'] = _op('get_organization', 'Get Organization Metadata')


class PolarPage(_Model):
    page: int = Field(1, ge=1, le=10000)
    limit: int = Field(25, ge=1, le=100, description='One bounded page; documented total_count/max_page drive continuation, never item count.')


class PolarListProductsConfig(PolarOrganizationTarget, PolarPage):
    operation: Literal['list_products'] = _op('list_products', 'List Product Metadata')


class PolarProductTarget(PolarOrganizationTarget):
    product_id: UUID = Field(json_schema_extra=_dynamic('product_id', 'organization_id'))


class PolarGetProductConfig(PolarProductTarget):
    operation: Literal['get_product'] = _op('get_product', 'Get Product Metadata')


class PolarEffectsConfirmation(_Model):
    confirm_effects: Literal[True] = Field(description='Explicitly permit this documented provider write. Metadata may drive storefronts, customer members, webhooks or existing workflows; actual effects remain subject to isolated verification.', json_schema_extra={'ui:widget': 'checkbox'})

    @field_validator('confirm_effects', mode='before')
    @classmethod
    def require_true(cls, value):
        if value is not True:
            raise ValueError('Explicit true confirmation is required.')
        return value


class PolarCreateProductConfig(PolarOrganizationTarget, PolarEffectsConfirmation):
    operation: Literal['create_draft_product'] = _op('create_draft_product', 'Create Draft Zero-Price Product', 'Metadata Writes')
    name: ProductName
    description: Optional[Text] = None
    metadata: Optional[Metadata] = None


class PolarMetadataPatch(_Model):
    @model_validator(mode='after')
    def supplied_metadata(self):
        names = self.model_fields_set & {'name', 'description', 'metadata'}
        if not names or any(getattr(self, field) is None for field in names if field != 'description'):
            raise ValueError('Supply metadata fields; only a documented nullable description can be explicitly cleared.')
        return self


class PolarUpdateProductConfig(PolarProductTarget, PolarEffectsConfirmation, PolarMetadataPatch):
    operation: Literal['update_product_metadata'] = _op('update_product_metadata', 'Update Product Name / Description / Metadata', 'Metadata Writes')
    name: Optional[ProductName] = None
    description: Optional[Text] = None
    metadata: Optional[Metadata] = None


class PolarArchiveProductConfig(PolarProductTarget, PolarEffectsConfirmation):
    operation: Literal['archive_product'] = _op('archive_product', 'Archive Bound Product', 'Metadata Writes')


class PolarDeleteProductConfig(PolarProductTarget, PolarEffectsConfirmation):
    operation: Literal['delete_product'] = _op('delete_product', 'Delete Owned Disposable Draft Product', 'Disposable Cleanup')


class PolarListCustomersConfig(PolarOrganizationTarget, PolarPage):
    operation: Literal['list_customers'] = _op('list_customers', 'List Customer Metadata')


class PolarCustomerTarget(PolarOrganizationTarget):
    customer_id: UUID = Field(json_schema_extra=_dynamic('customer_id', 'organization_id'))


class PolarGetCustomerConfig(PolarCustomerTarget):
    operation: Literal['get_customer'] = _op('get_customer', 'Get Customer Metadata')


class PolarCreateCustomerConfig(PolarOrganizationTarget, PolarEffectsConfirmation):
    operation: Literal['create_customer'] = _op('create_customer', 'Create Individual Customer Record', 'Metadata Writes')
    email: Annotated[str, StringConstraints(strict=True, min_length=3, max_length=254, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')] = Field(description='Required documented individual customer email. The provider automatically creates an owner member; invitation/notification behavior is not claimed quiet.')
    external_id: Optional[Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]] = Field(None, description='Unique within this organization and immutable after setting; no update field is exposed.')
    metadata: Optional[Metadata] = None


class PolarUpdateCustomerConfig(PolarCustomerTarget, PolarEffectsConfirmation, PolarMetadataPatch):
    operation: Literal['update_customer_metadata'] = _op('update_customer_metadata', 'Update Customer Metadata Only', 'Metadata Writes')
    metadata: Metadata


class PolarDeleteCustomerConfig(PolarCustomerTarget, PolarEffectsConfirmation):
    operation: Literal['delete_customer'] = _op('delete_customer', 'Delete Owned Disposable Customer — Cancels / Revokes', 'Disposable Cleanup')
    confirm_cascade: Literal[True] = Field(description='Deletion immediately cancels active subscriptions and revokes benefits, clears external_id, and retains historical transaction information. No anonymization or erase guarantee.', json_schema_extra={'ui:widget': 'checkbox'})
    _strict_cascade = field_validator('confirm_cascade', mode='before')(PolarEffectsConfirmation.require_true.__func__)


class PolarListBenefitsConfig(PolarOrganizationTarget, PolarPage):
    operation: Literal['list_benefits'] = _op('list_benefits', 'List Benefit Metadata')


class PolarBenefitTarget(PolarOrganizationTarget):
    benefit_id: UUID = Field(json_schema_extra=_dynamic('benefit_id', 'organization_id'))


class PolarGetBenefitConfig(PolarBenefitTarget):
    operation: Literal['get_benefit'] = _op('get_benefit', 'Get Benefit Metadata')


class PolarCreateBenefitConfig(PolarOrganizationTarget, PolarEffectsConfirmation):
    operation: Literal['create_draft_custom_benefit'] = _op('create_draft_custom_benefit', 'Create Draft Unassigned Custom Benefit', 'Metadata Writes')
    description: BenefitDescription
    metadata: Optional[Metadata] = None


class PolarUpdateBenefitConfig(PolarBenefitTarget, PolarEffectsConfirmation, PolarMetadataPatch):
    operation: Literal['update_custom_benefit_metadata'] = _op('update_custom_benefit_metadata', 'Update Custom Benefit Description / Metadata', 'Metadata Writes')
    description: Optional[BenefitDescription] = None
    metadata: Optional[Metadata] = None

    @field_validator('description', mode='before')
    @classmethod
    def no_null_description(cls, value):
        if value is None:
            raise ValueError('Custom benefit description cannot be cleared.')
        return value


class PolarDeleteBenefitConfig(PolarBenefitTarget, PolarEffectsConfirmation):
    operation: Literal['delete_custom_benefit'] = _op('delete_custom_benefit', 'Delete Owned Disposable Draft Custom Benefit', 'Disposable Cleanup')
    confirm_revoke: Literal[True] = Field(description='The documented DELETE revokes every associated grant. A draft/disposable binding is a local restriction, not proof that no grants exist.', json_schema_extra={'ui:widget': 'checkbox'})
    _strict_revoke = field_validator('confirm_revoke', mode='before')(PolarEffectsConfirmation.require_true.__func__)


class PolarListSubscriptionsConfig(PolarCustomerTarget, PolarPage):
    operation: Literal['list_subscriptions'] = _op('list_subscriptions', 'List Bound Customer Subscription Metadata')


class PolarGetSubscriptionConfig(PolarCustomerTarget):
    operation: Literal['get_subscription'] = _op('get_subscription', 'Get Bound Subscription Metadata')
    subscription_id: UUID = Field(json_schema_extra=_dynamic('subscription_id', 'customer_id'))


class PolarListOrdersConfig(PolarCustomerTarget, PolarPage):
    operation: Literal['list_orders'] = _op('list_orders', 'List Bound Customer Order Metadata')


class PolarGetOrderConfig(PolarCustomerTarget):
    operation: Literal['get_order'] = _op('get_order', 'Get Bound Order Metadata')
    order_id: UUID = Field(json_schema_extra=_dynamic('order_id', 'customer_id'))


# Event names and payloads: https://polar.sh/docs/openapi/2026-10.openapi.json
TRIGGER_EVENTS = {
    'on_order_event': ('order.created', 'order.paid', 'order.updated', 'order.refunded'),
    'on_subscription_event': ('subscription.created', 'subscription.active', 'subscription.updated', 'subscription.canceled', 'subscription.uncanceled', 'subscription.revoked', 'subscription.past_due'),
    'on_customer_event': ('customer.created', 'customer.updated', 'customer.deleted'),
}


def _trigger(value, title):
    return Field(value, title=title, json_schema_extra={'const': value, 'ui:hidden': True,
        'x-display-name': title, 'x-category': 'Triggers', 'x-is-trigger': True})


class PolarWebhookConfig(PolarOrganizationTarget, WebhookTriggerConfigBase):
    webhook_url: Optional[str] = Field(None, title='Webhook URL',
        description='Registered with Polar automatically; the token needs webhooks:write.',
        json_schema_extra={'ui:widget': 'webhook', 'ui:copyable': True, 'ui:loadValue': True})


class PolarOnOrderConfig(PolarWebhookConfig):
    operation: Literal['on_order_event'] = _trigger('on_order_event', 'On Order Event')
    event_type: Literal[*TRIGGER_EVENTS['on_order_event']] = Field('order.paid', title='Order Event')


class PolarOnSubscriptionConfig(PolarWebhookConfig):
    operation: Literal['on_subscription_event'] = _trigger('on_subscription_event', 'On Subscription Event')
    event_type: Literal[*TRIGGER_EVENTS['on_subscription_event']] = Field('subscription.active', title='Subscription Event')


class PolarOnCustomerConfig(PolarWebhookConfig):
    operation: Literal['on_customer_event'] = _trigger('on_customer_event', 'On Customer Event')
    event_type: Literal[*TRIGGER_EVENTS['on_customer_event']] = Field('customer.created', title='Customer Event')


PolarConfig = Annotated[Union[PolarOnOrderConfig, PolarOnSubscriptionConfig, PolarOnCustomerConfig, PolarCheckConfig, PolarGetOrganizationConfig, PolarListProductsConfig, PolarGetProductConfig, PolarCreateProductConfig, PolarUpdateProductConfig, PolarArchiveProductConfig, PolarDeleteProductConfig, PolarListCustomersConfig, PolarGetCustomerConfig, PolarCreateCustomerConfig, PolarUpdateCustomerConfig, PolarDeleteCustomerConfig, PolarListBenefitsConfig, PolarGetBenefitConfig, PolarCreateBenefitConfig, PolarUpdateBenefitConfig, PolarDeleteBenefitConfig, PolarListSubscriptionsConfig, PolarGetSubscriptionConfig, PolarListOrdersConfig, PolarGetOrderConfig], Field(discriminator='operation')]


class PolarFullConfig(NodeConfig[PolarConfig, PolarOrganizationAccessTokenCredential]):
    pass


def _credential(raw):
    if not isinstance(raw, dict) or raw.get('credential_type') not in (None, TAG) or set(raw) - set(PolarOrganizationAccessTokenCredential.model_fields) - {'token_version', 'updated_at'}:
        raise ValueError('Use the native organization-token credential with its explicit environment and restrictions.')
    try:
        return PolarOrganizationAccessTokenCredential.model_validate(raw)
    except ValueError:
        raise ValueError('Invalid native Polar token, organization, environment or restrictions.') from None


def _uuid(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', value):
        raise ValueError('Malformed Polar resource UUID.')
    return value


def _text(value, limit=256):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(char) < 32 for char in value):
        raise ValueError('Malformed bounded Polar metadata text.')
    return value


def _private(credential, value):
    if credential.organization_access_token in json.dumps(value, allow_nan=False):
        raise ValueError('Credential material cannot appear in parameters or native outputs.')


class _ProviderFailure(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__({401: 'Polar rejected authentication.', 403: 'Polar denied the organization, scope or resource.', 404: 'Polar resource or pinned API version was not found.', 409: 'Polar rejected a conflicting resource operation.', 422: 'Polar rejected the documented request.', 429: 'Polar rate limit reached; no automatic retry.'}.get(status, 'Polar returned an unsupported response status.'))


class PolarNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = 'automation-polar'
    connection_evidence = ConnectionEvidence(operation='check_connection', noun='protected organization API', proves='reachability')

    @staticmethod
    def _configured_event(config):
        return config.get('event_type') or {
            'on_order_event': 'order.paid', 'on_subscription_event': 'subscription.active',
            'on_customer_event': 'customer.created',
        }.get(config.get('operation'))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {'organization_id': config.get('organization_id'), 'event_type': cls._configured_event(config)}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        account = _credential(credential)
        parsed = PolarFullConfig.model_validate({'config': config, 'credentials': credential}).config
        if parsed.operation not in TRIGGER_EVENTS:
            raise ValueError('Choose a Polar trigger.')
        if parsed.operation not in account.allowed_operations or parsed.organization_id != account.organization_id or 'webhooks:write' not in account.declared_scopes:
            raise ValueError('Permit the trigger and webhooks:write for this organization.')
        endpoint = await cls._request(account, None, 'webhooks/endpoints', 'POST', body={
            'url': webhook_url, 'format': 'raw', 'api_version': VERSION,
            'events': [parsed.event_type], 'organization_id': parsed.organization_id})
        return {'external_webhook_id': _text(endpoint['id']), 'signing_secret': _text(endpoint['secret'], 4096)}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = config.get('external_webhook_id')
        if not endpoint_id:
            return
        if not credential:
            raise ValueError('Connect Polar to remove its webhook endpoint.')
        account = _credential(credential)
        if 'webhooks:write' not in account.declared_scopes:
            raise ValueError('Removing the endpoint needs webhooks:write.')
        try:
            await cls._request(account, None, 'webhooks/endpoints', 'DELETE', _text(str(endpoint_id)))
        except _ProviderFailure as exc:
            if exc.status != 404:
                raise

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://polar.sh/docs/integrate/webhooks/delivery#custom-validation
        # Polar's SDK accepts both the current Standard Webhooks key and the legacy key.
        secret = config.get('signing_secret')
        lowered = {key.lower(): value for key, value in headers.items()}
        timestamp = lowered.get('webhook-timestamp', '')
        delivery_id = lowered.get('webhook-id', '')
        signature = lowered.get('webhook-signature', '')
        if not isinstance(secret, str) or not secret or not timestamp.isdigit() or not delivery_id or abs(time.time() - int(timestamp)) > 300:
            return False
        message = delivery_id.encode() + b'.' + timestamp.encode() + b'.' + body
        keys = [secret.encode()]
        if secret.startswith('whsec_'):
            try:
                keys.append(base64.b64decode(secret[6:] + '=' * (-len(secret[6:]) % 4), validate=True))
            except ValueError:
                pass
        expected = [base64.b64encode(hmac.new(key, message, hashlib.sha256).digest()).decode() for key in keys]
        return any(hmac.compare_digest(part[3:], digest) for part in signature.split() if part.startswith('v1,') for digest in expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = payload.get('type')
        if event not in TRIGGER_EVENTS.get(config.get('operation'), ()) or event != cls._configured_event(config):
            return False
        return isinstance(payload.get('data'), dict)

    @classmethod
    def resolve_agent_event(cls, output):
        event = output.get('type')
        if event not in {name for group in TRIGGER_EVENTS.values() for name in group}:
            return super().resolve_agent_event(output)
        record = output.get('data')
        if not isinstance(record, dict) or not record.get('id'):
            return None
        customer = record if event.startswith('customer.') else record.get('customer') or {}
        who = customer.get('name') or customer.get('email') or customer.get('id') or 'Customer'
        lines = [f"Polar {event}: {who}", f"At: {output.get('timestamp')}",
            f"Organization: {customer.get('organization_id')}", f"Resource ID: {record['id']}"]
        if not event.startswith('customer.'):
            lines.extend([f"Customer ID: {record.get('customer_id')}", f"Product ID: {record.get('product_id')}", f"Status: {record.get('status')}"])
            if event.startswith('order.'):
                lines.append(f"Total: {record.get('total_amount')} {record.get('currency')} (minor currency units)")
            else:
                lines.append(f"Amount: {record.get('amount')} {record.get('currency')} (minor currency units)")
        return {'text': '\n'.join(lines), 'conversation_key': str(record['id']), 'title': f'Polar {event}: {who}'}

    @classmethod
    def get_config_model(cls):
        return PolarFullConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data.get('credentials'), dict):
            _credential(config_data['credentials'])
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data.get('credentials'), dict):
                _credential(config_data['credentials'])
        except ValueError:
            return ValidationResult(valid=False, errors=['Use the native Polar organization token and explicit current environment.'])
        return super().validate_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        credential = _credential(credential_data)
        try:
            await cls._dispatch(credential, PolarCheckConfig())
        except _ProviderFailure as exc:
            return {'valid': False if exc.status in (401, 403) else None, 'error': str(exc)}
        except Exception:
            return {'valid': None, 'error': 'Protected organization access remains unverified.'}
        return {'valid': True, 'proves': 'reachability', 'account_identity_verified': False}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Organization access tokens do not rotate automatically."""
        return _credential(credential_data).model_dump()

    @classmethod
    async def _recheck(cls, authority, credential):
        if authority is not None:
            from utils.credentials import resolve_credential_with_owner_fallback
            current = await resolve_credential_with_owner_fallback(**authority)
            if not current or _credential(current).model_dump() != credential.model_dump():
                raise ValueError('Current saved Polar credential is unavailable or changed.')

    @classmethod
    async def _request(cls, credential, authority, kind, method='GET', resource_id=None, *, params=None, body=None):
        if kind not in ('organizations', 'products', 'customers', 'benefits', 'subscriptions', 'orders', 'webhooks/endpoints') or method not in ('GET', 'POST', 'PATCH', 'DELETE'):
            raise ValueError('Unsupported closed Polar route.')
        if kind in ('organizations', 'subscriptions', 'orders') and method != 'GET' or method != 'GET' and kind not in ('products', 'customers', 'benefits', 'webhooks/endpoints') or method == 'POST' and resource_id is not None or method in ('PATCH', 'DELETE') and resource_id is None:
            raise ValueError('Unsupported native Polar method/resource combination.')
        if resource_id:
            identifier = quote(_text(str(resource_id)), safe='') if kind == 'webhooks/endpoints' else _uuid(resource_id)
            suffix = '/' + identifier
        else:
            suffix = '' if kind == 'webhooks/endpoints' else '/'
        host = 'sandbox-api.polar.sh' if credential.environment == 'sandbox' else 'api.polar.sh'
        await cls._recheck(authority, credential)
        _private(credential, {'params': params, 'body': body})
        marker = _private_http.set(True)
        try:
            with suppress_instrumentation():
                async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                    async with client.stream(method, f'https://{host}/v1/{kind}{suffix}', headers={'Authorization': 'Bearer ' + credential.organization_access_token, 'Polar-Version': VERSION, 'Accept': 'application/json'}, params=params, json=body) as response:
                        status = response.status_code
                        if status != (201 if method == 'POST' else 204 if method == 'DELETE' else 200):
                            raise _ProviderFailure(status)
                        if response.headers.get('Polar-Version', VERSION if kind == 'webhooks/endpoints' else None) != VERSION:
                            raise ValueError('Polar response did not confirm the pinned API version.')
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise ValueError('Polar response exceeds the native bound.')
                            chunks.append(chunk)
                        data = b''.join(chunks)
                        if status == 204:
                            if data:
                                raise ValueError('Expected documented empty deletion acknowledgement.')
                            payload = None
                        else:
                            if not data or response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                                raise ValueError('Expected documented JSON, not empty, text, media or async data.')
                            try:
                                payload = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                            except (ValueError, UnicodeError):
                                raise ValueError('Malformed Polar JSON.') from None
                            if not isinstance(payload, dict) or any(field in payload for field in ('error', 'errors', 'detail')):
                                raise ValueError('Polar error or malformed envelope cannot report success.')
            await cls._recheck(authority, credential)
            return payload
        finally:
            _private_http.reset(marker)

    @staticmethod
    def _binding(credential, kind, resource_id, customer_id=None, *, write=False, disposable=False):
        rows = [row for row in credential.resource_bindings if row.kind == kind]
        found = next((row for row in rows if row.resource_id == resource_id), None)
        if (rows or write) and found is None or found and found.customer_id != customer_id or disposable and (found is None or not found.owned_disposable):
            raise ValueError('Resource is outside its current explicit parent/disposable restriction.')
        return found

    @classmethod
    def _grant(cls, credential, config):
        op = config.operation
        if op not in credential.allowed_operations or getattr(config, 'organization_id', credential.organization_id) != credential.organization_id:
            raise ValueError('Operation or organization is outside the current restriction.')
        kind = 'products' if 'product' in op else 'customers' if 'customer' in op else 'benefits' if 'benefit' in op else 'subscriptions' if 'subscription' in op else 'orders' if 'order' in op else 'organizations'
        write = op.startswith(('create_', 'update_', 'delete_', 'archive_'))
        required = kind + (':write' if write else ':read')
        if required not in credential.declared_scopes and (write or kind + ':write' not in credential.declared_scopes):
            raise ValueError('Configured token scope restriction lacks this operation.')
        for family, field in (('products', 'product_id'), ('customers', 'customer_id'), ('benefits', 'benefit_id'), ('subscriptions', 'subscription_id'), ('orders', 'order_id')):
            if hasattr(config, field):
                cls._binding(credential, family, getattr(config, field), getattr(config, 'customer_id', None) if family in ('subscriptions', 'orders') else None, write=write and family == kind, disposable=op.startswith('delete_') and family == kind)
        if kind in ('orders', 'subscriptions') and not {'customers:read', 'customers:write'}.intersection(credential.declared_scopes):
            raise ValueError('Billing metadata requires protected customer parent access.')
        _private(credential, config.model_dump())

    @staticmethod
    def _record(raw, kind, organization_id, customer_id=None):
        if not isinstance(raw, dict):
            raise ValueError('Expected documented Polar object.')
        record = {'id': _uuid(raw.get('id')), 'organization_id': organization_id}
        if kind == 'organizations':
            if record['id'] != organization_id:
                raise ValueError('Organization identity changed.')
            record.update(name=_text(raw.get('name')), slug=_text(raw.get('slug'), 100))
        elif kind in ('products', 'customers', 'benefits'):
            if _uuid(raw.get('organization_id')) != organization_id:
                raise ValueError('Response organization differs from the current binding.')
        else:
            nested = raw.get('customer')
            if not isinstance(nested, dict) or _uuid(nested.get('organization_id')) != organization_id or _uuid(nested.get('id')) != customer_id or _uuid(raw.get('customer_id')) != customer_id:
                raise ValueError('Billing metadata does not match its current customer/organization parent.')
            record['customer_id'] = customer_id
            if raw.get('product') is not None:
                product = raw['product']
                if not isinstance(product, dict) or _uuid(product.get('organization_id')) != organization_id or _uuid(product.get('id')) != _uuid(raw.get('product_id')):
                    raise ValueError('Billing metadata product parent changed.')
                record['product_id'] = product['id']
            record['status'] = _text(raw.get('status'), 40)
        if kind == 'products':
            record['name'] = _text(raw.get('name'), 64)
            if raw.get('visibility') not in ('draft', 'private', 'public') or type(raw.get('is_archived')) is not bool:
                raise ValueError('Malformed product visibility or archive flag.')
            record.update(visibility=raw['visibility'], is_archived=raw['is_archived'])
        elif kind == 'customers':
            if raw.get('type') not in ('individual', 'team'):
                raise ValueError('Malformed customer type.')
            record['type'] = raw['type']
        elif kind == 'benefits':
            if raw.get('type') not in ('custom', 'discord', 'github_repository', 'downloadables', 'license_keys', 'meter_credit', 'feature_flag', 'slack_shared_channel'):
                raise ValueError('Malformed benefit type.')
            record.update(type=raw['type'], description=_text(raw.get('description'), 42))
        for field in ('created_at', 'modified_at'):
            if field in raw and raw[field] is not None:
                record[field] = _text(raw[field], 64)
        return record

    @classmethod
    def _page(cls, payload, config):
        if not isinstance(payload, dict) or not isinstance(payload.get('items'), list) or len(payload['items']) > config.limit or not isinstance(payload.get('pagination'), dict):
            raise ValueError('Expected bounded items/pagination envelope.')
        ids = [_uuid(row.get('id')) for row in payload['items'] if isinstance(row, dict)]
        pagination = payload['pagination']
        total, max_page = pagination.get('total_count'), pagination.get('max_page')
        if len(ids) != len(payload['items']) or len(ids) != len(set(ids)) or type(total) is not int or type(max_page) is not int or not len(ids) <= total <= 2147483647 or not 0 <= max_page <= 10000 or total > 0 and max_page == 0:
            raise ValueError('Malformed documented page counts or duplicate identities.')
        return payload['items'], {'page': config.page, 'page_limit': config.limit, 'total_count': total, 'max_page': max_page, 'count_scope': 'provider query before local binding projection', 'next_page': config.page + 1 if config.page < max_page else None, 'continuation_verified': True}

    @staticmethod
    def _echo(raw, body):
        for field in ('name', 'description', 'metadata', 'email', 'external_id', 'visibility', 'is_archived', 'type'):
            if field not in body:
                continue
            actual, expected = raw.get(field), body[field]
            matches = isinstance(actual, dict) and all(key in actual and type(actual[key]) is type(value) and actual[key] == value for key, value in expected.items()) if isinstance(expected, dict) else type(actual) is type(expected) and actual == expected
            if not matches:
                raise ValueError('Mutation response does not confirm the supplied metadata.')

    @classmethod
    async def _dispatch(cls, credential, config, authority=None):
        cls._grant(credential, config)
        op = config.operation
        organization_raw = await cls._request(credential, authority, 'organizations', resource_id=credential.organization_id)
        organization = cls._record(organization_raw, 'organizations', credential.organization_id)
        result = {'status': 'success', 'action': op, 'environment': credential.environment, 'api_version': VERSION, 'account_identity_verified': False}
        if op in ('check_connection', 'get_organization'):
            if op == 'check_connection':
                result.update(proves='reachability', organization_access_verified=True, write_access_verified=False)
            else:
                result['record'] = organization
        else:
            kind = 'products' if 'product' in op else 'customers' if 'customer' in op else 'benefits' if 'benefit' in op else 'subscriptions' if 'subscription' in op else 'orders'
            parent = getattr(config, 'customer_id', None) if kind in ('subscriptions', 'orders') else None
            if parent:
                raw = await cls._request(credential, authority, 'customers', resource_id=parent)
                if cls._record(raw, 'customers', credential.organization_id)['id'] != parent:
                    raise ValueError('Customer witness identity changed.')
            if op.startswith('list_'):
                payload = await cls._request(credential, authority, kind, params={'organization_id': credential.organization_id, 'page': config.page, 'limit': config.limit, **({'customer_id': parent} if parent else {})})
                rows, pagination = cls._page(payload, config)
                records = [cls._record(row, kind, credential.organization_id, parent) for row in rows]
                allowed = {row.resource_id for row in credential.resource_bindings if row.kind == kind and row.customer_id == parent}
                has_restrictions = any(row.kind == kind for row in credential.resource_bindings)
                result.update(records=[row for row in records if not has_restrictions or row['id'] in allowed], **pagination)
            elif op.startswith('create_'):
                body = config.model_dump(exclude_unset=True, exclude={'operation', 'organization_id', 'confirm_effects'}, exclude_none=True)
                body['organization_id'] = credential.organization_id
                if kind == 'products':
                    body.update(visibility='draft', recurring_interval=None, prices=[{'amount_type': 'fixed', 'price_amount': 0, 'price_currency': 'usd'}])
                elif kind == 'benefits':
                    body.update(type='custom', visibility='draft', properties={})
                else:
                    body['type'] = 'individual'
                raw = await cls._request(credential, authority, kind, 'POST', body=body)
                record = cls._record(raw, kind, credential.organization_id)
                cls._echo(raw, body)
                if kind == 'products' and (raw.get('is_recurring') is not False or not isinstance(raw.get('prices'), list) or len(raw['prices']) != 1 or not isinstance(raw['prices'][0], dict) or raw['prices'][0].get('amount_type') != 'fixed' or type(raw['prices'][0].get('price_amount')) is not int or raw['prices'][0]['price_amount'] != 0 or raw['prices'][0].get('price_currency') != 'usd'):
                    raise ValueError('Creation did not return the documented draft zero-price product.')
                result.update(record=record, http_status=201, owned_disposable_binding_added=False)
            else:
                field = {'products': 'product_id', 'customers': 'customer_id', 'benefits': 'benefit_id', 'subscriptions': 'subscription_id', 'orders': 'order_id'}[kind]
                resource_id = getattr(config, field)
                raw = await cls._request(credential, authority, kind, resource_id=resource_id)
                record = cls._record(raw, kind, credential.organization_id, parent)
                if record['id'] != resource_id:
                    raise ValueError('Resource witness identity changed.')
                if op.startswith(('update_', 'delete_')) and kind == 'benefits' and raw.get('type') != 'custom':
                    raise ValueError('Only the explicitly bound custom benefit metadata lifecycle is supported.')
                if op.startswith('update_') or op == 'archive_product':
                    body = {'is_archived': True} if op == 'archive_product' else {field: getattr(config, field) for field in config.model_fields_set & {'name', 'description', 'metadata'}}
                    if kind == 'benefits':
                        body['type'] = 'custom'
                    raw = await cls._request(credential, authority, kind, 'PATCH', resource_id, body=body)
                    record = cls._record(raw, kind, credential.organization_id)
                    if record['id'] != resource_id:
                        raise ValueError('Updated resource identity changed.')
                    cls._echo(raw, body)
                elif op.startswith('delete_'):
                    if kind == 'products' and (raw.get('is_deletable') is not True or raw.get('visibility') != 'draft') or kind == 'benefits' and (raw.get('deletable') is not True or raw.get('visibility') != 'draft') or kind == 'customers' and raw.get('type') != 'individual':
                        raise ValueError('Deletion requires the current documented disposable draft/type witness.')
                    await cls._request(credential, authority, kind, 'DELETE', resource_id)
                    result.update(acknowledged=True, http_status=204, cleanup_verified=False, deletion_effects={'products': 'Provider allows deletion only without orders, subscriptions, trials or discounts.', 'benefits': 'Every associated grant is revoked; absence of grants is not proved.', 'customers': 'Active subscriptions are canceled and benefits revoked; historical transaction information remains.'}[kind])
                if not op.startswith('delete_'):
                    result['record'] = record
        if op.startswith(('create_', 'update_', 'delete_', 'archive_')):
            result.update(provider_effects_verified=False, disposition='Documented provider metadata lifecycle; real storefront/member/webhook/access/billing effects and readback remain subject to isolated verification.')
        _private(credential, result)
        return result

    async def execute(self, inputs):
        try:
            if not isinstance(self.config, PolarFullConfig) or self.config.credentials is None:
                raise ValueError('Native credentials and config are required.')
            if self.config.config.operation in TRIGGER_EVENTS:
                return self.no_event_output(self.config.config.operation)
            credential = _credential(self.config.credentials.model_dump())
            if 'credentials' in self.node_data and _credential(self.node_data['credentials']).model_dump() != credential.model_dump():
                raise ValueError('Raw credential differs from its parsed current shape.')
            authority = None
            if self.node_data.get('credential_id'):
                from utils.database_pool import get_native_pool
                authority = dict(credential_id=self.node_data['credential_id'], user_id=self.user_id,
                    pool=getattr(self, '_approval_pool', None) or get_native_pool(),
                    org_id=getattr(self, 'organization_id', None), workflow_id=getattr(self, 'workflow_id', None))
            return await self._dispatch(credential, self.config.config, authority)
        except _ProviderFailure as exc:
            return {'status': 'error', 'error': str(exc), 'http_status': exc.status}
        except Exception as exc:
            return {'status': 'error', 'error': 'Polar request remains unverified; check current token, environment, organization, scope, resource parents and documented response.', 'error_type': type(exc).__name__}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None, limit=None):
        credential = _credential(credential_data)
        authority = None
        await cls._recheck(authority, credential)
        context = context or {}
        if page_token is not None and not re.fullmatch(r'[1-9][0-9]{0,3}|10000', str(page_token)):
            raise ValueError('Use a bounded native page number, not a continuation URL.')
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError('Use a bounded native selector limit.')
        if field_name == 'organization_id':
            result = await cls._dispatch(credential, PolarCheckConfig(), authority)
            rows = [{'value': credential.organization_id, 'label': credential.organization_id, 'metadata': {'environment': credential.environment, 'provider_access_verified': result['organization_access_verified']}}]
        else:
            models = {'product_id': PolarListProductsConfig, 'customer_id': PolarListCustomersConfig, 'benefit_id': PolarListBenefitsConfig, 'subscription_id': PolarListSubscriptionsConfig, 'order_id': PolarListOrdersConfig}
            model = models.get(field_name)
            if model is None:
                raise ValueError('Unsupported native Polar selector.')
            arguments = {'organization_id': context.get('organization_id'), 'page': int(page_token or 1), 'limit': limit or 25}
            if field_name in ('subscription_id', 'order_id'):
                arguments['customer_id'] = context.get('customer_id')
            config = model.model_validate(arguments)
            result = await cls._dispatch(credential, config, authority)
            rows = [{'value': row['id'], 'label': row['id'], 'metadata': {'organization_id': credential.organization_id, 'environment': credential.environment, **({'customer_id': context['customer_id']} if field_name in ('subscription_id', 'order_id') else {})}} for row in result['records']]
        if search:
            needle = _text(search, 100).casefold()
            rows = [row for row in rows if needle in row['label'].casefold()]
        _private(credential, rows)
        return {'options': rows, 'next_page_token': str(result['next_page']) if result.get('next_page') else None}

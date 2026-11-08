"""TidyHQ API v2 operations, mapped one-to-one to the published OpenAPI contract.

Authentication: https://docs.tidyhq.com/guides/getting-started
Contract: https://api.tidyhq.com/v2/openapi.json (version 2.0).
Collections return one offset page and the provider's pagination headers.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.tidy import TIDY_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.tidyhq.com/v2"


class TidyOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Tidy Account", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "tidy",
            "x-oauth-scopes": TIDY_SCOPES.declared_scopes(),
            "x-credential-url": "https://dev.tidyhq.com/oauth_applications",
            "x-credential-instructions": "Connect TidyHQ and choose your organisation. Access follows your Tidy roles. Tidy documents non-expiring tokens without refresh tokens; reconnect if access is revoked.",
        })
    credential_type: Literal["tidy_oauth"] = Field("tidy_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh Token", repr=False)
    expires_at: str | None = Field(None, title="Token Expiry")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("Use a Tidy access token")
        value = clean_secret(value, field_name="Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Use the token without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def resource_ids(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) or value in {".", ".."}:
                raise ValueError("Use a single Tidy resource ID")
        return value


class _Page(_Input):
    limit: int = Field(25, ge=1, le=100, description="Items in this page. Use the pagination headers to continue.")
    offset: int = Field(0, ge=0, description="Number of items to skip; no automatic pagination.")
    updated_since: datetime | None = Field(None, description="Only resources updated since this ISO8601 timestamp.")
    updated_before: datetime | None = Field(None, description="Only resources updated before this ISO8601 timestamp.")


class _ContactList(_Page):
    search_terms: str | None = Field(None, max_length=1000)
    registered: bool | None = None
    all: bool | None = Field(None, description="Include inactive contacts.")
    ids: str | None = Field(None, max_length=4000, description="Comma-separated contact IDs.")
    scope: Literal["sports_australia_connect", "contact_id_number"] | None = None


class _GroupList(_Page):
    search_terms: str | None = Field(None, max_length=1000)
    all: bool | None = None


class _MembershipList(_Page):
    active: bool | None = None
    all: bool | None = None


class _SubscriptionList(_Page):
    active: bool | None = None


class _EventList(_Page):
    after: datetime | None = None
    before: datetime | None = None


class _InvoiceList(_Page):
    status: Literal["activated", "cancelled"] | None = None


class _ContactID(_Input):
    contact_id: str = Field(..., min_length=1, title="Contact ID")


class _GroupID(_Input):
    group_id: str = Field(..., min_length=1, title="Group ID")


class _MembershipID(_Input):
    membership_id: str = Field(..., min_length=1, title="Membership ID")


class _SubscriptionID(_Input):
    subscription_id: str = Field(..., min_length=1, title="Subscription ID")


class _MembershipLevelID(_Input):
    membership_level_id: str = Field(..., min_length=1, title="Membership Level ID")


class _EventID(_Input):
    event_id: str = Field(..., min_length=1, title="Event ID")


class _InvoiceID(_Input):
    invoice_id: str = Field(..., min_length=1, title="Invoice ID")


class _ContactFields(_Input):
    first_name: str | None = Field(None, max_length=1000)
    last_name: str | None = Field(None, max_length=1000)
    nick_name: str | None = Field(None, max_length=1000)
    company: str | None = Field(None, max_length=1000)
    email_address: str | None = Field(None, max_length=1000)
    phone_number: str | None = Field(None, max_length=1000)
    address1: str | None = Field(None, max_length=1000)
    city: str | None = Field(None, max_length=1000)
    state: str | None = Field(None, max_length=1000)
    postcode: str | None = Field(None, max_length=1000)
    country: str | None = Field(None, max_length=1000)
    details: str | None = Field(None, max_length=10000)
    subscribed: bool | None = Field(None, description="Set marketing subscription explicitly; omitted by default.")

    @model_validator(mode="after")
    def has_changes(self):
        if not any(getattr(self, key) is not None for key in _ContactFields.model_fields):
            raise ValueError("Supply at least one contact field")
        return self


class _NewContact(_ContactFields):
    first_name: str = Field(..., min_length=1, max_length=1000)
    last_name: str = Field(..., min_length=1, max_length=1000)


class _ContactUpdate(_ContactFields, _ContactID):
    pass


class _MembershipSubscriptionList(_SubscriptionList, _MembershipID):
    pass


class _NewSubscription(_MembershipID):
    payment_type: Literal["paid", "invoice", "pay_now"]
    payment_method: Literal["cash", "card", "cheque", "bank", "other"] | None = None
    partial_payment_amount: str | None = None
    ref_no: str | None = None
    due_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    auto_renew: bool | None = None
    send_welcome_mail: bool = Field(False, description="Explicitly send a welcome email.")
    send_invoice_mail: bool = Field(False, description="Explicitly send an invoice email.")
    auto_assign_users: bool = Field(False, description="Create or assign user accounts; creation sends signup emails.")

    @model_validator(mode="after")
    def payment(self):
        if self.payment_type == "paid" and self.payment_method is None:
            raise ValueError("A paid subscription requires a payment method")
        return self


class _SubscriptionUpdate(_MembershipID, _SubscriptionID):
    start_date: date | None = None
    end_date: date | None = None
    state: Literal["active", "partial", "expired", "cancelled"] | None = None

    @model_validator(mode="after")
    def changes(self):
        if self.start_date is None and self.end_date is None and self.state is None:
            raise ValueError("Supply a date or state to update")
        return self


class GetCurrentContact(_Input):
    operation: Literal["get_current_contact"] = "get_current_contact"


class GetOrganization(_Input):
    operation: Literal["get_organization"] = "get_organization"


class ListContacts(_ContactList):
    operation: Literal["list_contacts"] = "list_contacts"


class GetContact(_ContactID):
    operation: Literal["get_contact"] = "get_contact"


class CreateContact(_NewContact):
    operation: Literal["create_contact"] = "create_contact"


class UpdateContact(_ContactUpdate):
    operation: Literal["update_contact"] = "update_contact"


class DeleteContact(_ContactID):
    operation: Literal["delete_contact"] = "delete_contact"


class ListGroups(_GroupList):
    operation: Literal["list_groups"] = "list_groups"


class GetGroup(_GroupID):
    operation: Literal["get_group"] = "get_group"


class ListMemberships(_MembershipList):
    operation: Literal["list_memberships"] = "list_memberships"


class GetMembership(_MembershipID):
    operation: Literal["get_membership"] = "get_membership"


class ListSubscriptions(_SubscriptionList):
    operation: Literal["list_subscriptions"] = "list_subscriptions"


class GetSubscription(_SubscriptionID):
    operation: Literal["get_subscription"] = "get_subscription"


class ListMembershipSubscriptions(_MembershipSubscriptionList):
    operation: Literal["list_membership_subscriptions"] = "list_membership_subscriptions"


class CreateMembershipSubscription(_NewSubscription):
    operation: Literal["create_membership_subscription"] = "create_membership_subscription"


class UpdateMembershipSubscription(_SubscriptionUpdate):
    operation: Literal["update_membership_subscription"] = "update_membership_subscription"


class ListMembershipLevels(_Page):
    operation: Literal["list_membership_levels"] = "list_membership_levels"


class GetMembershipLevel(_MembershipLevelID):
    operation: Literal["get_membership_level"] = "get_membership_level"


class ListEvents(_EventList):
    operation: Literal["list_events"] = "list_events"


class GetEvent(_EventID):
    operation: Literal["get_event"] = "get_event"


class ListInvoices(_InvoiceList):
    operation: Literal["list_invoices"] = "list_invoices"


class GetInvoice(_InvoiceID):
    operation: Literal["get_invoice"] = "get_invoice"


TidyConfig = Annotated[Union[
    GetCurrentContact,
    GetOrganization,
    ListContacts,
    GetContact,
    CreateContact,
    UpdateContact,
    DeleteContact,
    ListGroups,
    GetGroup,
    ListMemberships,
    GetMembership,
    ListSubscriptions,
    GetSubscription,
    ListMembershipSubscriptions,
    CreateMembershipSubscription,
    UpdateMembershipSubscription,
    ListMembershipLevels,
    GetMembershipLevel,
    ListEvents,
    GetEvent,
    ListInvoices,
    GetInvoice
], Field(discriminator="operation")]


class TidyFullConfig(NodeConfig[TidyConfig, TidyOAuthCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# One request per operation, matching the pinned v2 method and path.
ROUTES = {
    "get_current_contact": ("GET", "/contacts/me"),
    "get_organization": ("GET", "/organization"),
    "list_contacts": ("GET", "/contacts"),
    "get_contact": ("GET", "/contacts/{contact_id}"),
    "create_contact": ("POST", "/contacts"),
    "update_contact": ("PATCH", "/contacts/{contact_id}"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}"),
    "list_groups": ("GET", "/groups"),
    "get_group": ("GET", "/groups/{group_id}"),
    "list_memberships": ("GET", "/memberships"),
    "get_membership": ("GET", "/memberships/{membership_id}"),
    "list_subscriptions": ("GET", "/subscriptions"),
    "get_subscription": ("GET", "/subscriptions/{subscription_id}"),
    "list_membership_subscriptions": ("GET", "/memberships/{membership_id}/subscriptions"),
    "create_membership_subscription": ("POST", "/memberships/{membership_id}/subscriptions"),
    "update_membership_subscription": ("PATCH", "/memberships/{membership_id}/subscriptions/{subscription_id}"),
    "list_membership_levels": ("GET", "/membership_levels"),
    "get_membership_level": ("GET", "/membership_levels/{membership_level_id}"),
    "list_events": ("GET", "/events"),
    "get_event": ("GET", "/events/{event_id}"),
    "list_invoices": ("GET", "/invoices"),
    "get_invoice": ("GET", "/invoices/{invoice_id}"),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


class TidyNode(WorkflowNode):
    integration_type = "automation-tidy"
    scope_registry = TIDY_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_contacts", noun="contacts", identity_operation="get_current_contact")

    @classmethod
    def get_config_model(cls):
        return TidyFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.tidy_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool,
            user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="tidy")

    async def execute(self, inputs):
        if not isinstance(self.config, TidyFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Tidy account")
        config = self.config.config
        credential = self.config.credentials
        self.scope_registry.require(config.operation)
        token = credential.access_token
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.tidy_oauth import refresh_access_token
            credential_data = credential.model_dump()
            token = await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                credential=credential_data, refresh=refresh_access_token, provider="tidy", caller_path="execute")
            credential.access_token = credential_data["access_token"]
            credential.refresh_token = credential_data.get("refresh_token")
            credential.expires_at = credential_data.get("expires_at")
        method, template = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{field: quote(values.pop(field), safe="") for field in path_fields})
        kwargs = {}
        if method == "GET" and values:
            kwargs["params"] = {key: str(value).lower() if isinstance(value, bool) else value for key, value in values.items()}
        elif method in {"POST", "PATCH"}:
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        secrets = (token, credential.refresh_token)
        if len(response.content) > 10_000_000:
            raise ValueError("Tidy response exceeds the size limit")
        if response.status_code == 204 and method == "DELETE":
            return {"status": "success", "operation": config.operation, "http_status": 204, "deleted": True}
        if 300 <= response.status_code < 400:
            raise ValueError("Tidy redirected the request; reconnect your account")
        if not response.content and config.operation == "update_membership_subscription" and response.status_code == 200:
            return {"status": "success", "operation": config.operation, "http_status": 200, "data": None}
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from Tidy")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Tidy returned invalid JSON") from None
        if response.status_code >= 400 or isinstance(body, dict) and (body.get("error") or body.get("errors")):
            message = "Tidy rejected the request"
            if isinstance(body, dict):
                message = body.get("error_description") or body.get("message") or body.get("error") or body.get("errors") or message
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, secrets)}
        expected_status = 204 if method == "DELETE" else 201 if config.operation == "create_contact" else 200
        if response.status_code != expected_status:
            raise ValueError("Tidy did not confirm this operation")
        if config.operation.startswith("list_"):
            if not isinstance(body, list) or any(not isinstance(item, dict) for item in body):
                raise ValueError("Expected a Tidy resource collection")
        elif not isinstance(body, dict):
            raise ValueError("Expected a Tidy resource object")
        pagination = {key: response.headers[key] for key in (
            "X-Pagination-Per-Page", "X-Pagination-Current-Page",
            "X-Pagination-Total-Pages", "X-Pagination-Total-Entries") if key in response.headers}
        return _redact({"status": "success", "operation": config.operation,
            "http_status": response.status_code, "data": body,
            **({"pagination": pagination} if config.operation.startswith("list_") else {})}, secrets)

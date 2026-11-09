"""Quiltt REST operations pinned to the provider's 2026-04-01 contract.

Uses a manually supplied environment API key and exposes one request per operation.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.quiltt.io"

class QuilttApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Quiltt API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.quiltt.dev/api-keys",
        "x-credential-instructions": "Paste your Quiltt environment API Key secret from Dashboard → API Keys. The key is sent as a Bearer token to api.quiltt.io. Connection verification reads profiles in that environment.",
    })
    credential_type: Literal["quiltt_api_key"] = Field("quiltt_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key Secret", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API Key Secret")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key secret without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    limit: int = Field(25, ge=1, title="Items Per Page")

class _Ids(_Input):
    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def identifier(cls, value, info):
        if info.field_name.endswith("_id") and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value)):
            raise ValueError("Use a Quiltt resource ID without a path or query")
        return value

class _ProfileId(_Ids):
    profile_id: str = Field(..., title="Profile ID")

class _SubscriptionId(_Ids):
    subscription_id: str = Field(..., title="Subscription ID")

class _AccountId(_Ids):
    account_id: str = Field(..., title="Account ID")

class _ConnectionId(_Ids):
    connection_id: str = Field(..., title="Connection ID")

class _ProfileFields(_Input):
    name: str | None = Field(None, min_length=1, title="Name")
    email: str | None = Field(None, title="Email", json_schema_extra={"format": "email"})
    phone: str | None = Field(None, title="Phone", description="E.164 phone number in the US or Canada.")
    date_of_birth: date | None = Field(None, alias="dateOfBirth", title="Date of Birth")
    metadata: dict | None = Field(None, min_length=1, max_length=50, title="Custom Metadata")

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value):
        if value is not None and not re.fullmatch(r"\+1[0-9]{10}", value):
            raise ValueError("Enter an E.164 US or Canadian phone number")
        return value

class _ProfileCreate(_ProfileFields):
    uuid: UUID | None = Field(None, title="Profile UUID")

class _ProfileUpdate(_ProfileFields, _ProfileId):
    pass

EVENT_TYPE = Literal['profile', 'profile.created', 'profile.ready', 'profile.deleted', 'connection', 'connection.created', 'connection.synced', 'connection.synced.successful', 'connection.synced.successful.initial', 'connection.synced.successful.historical', 'connection.synced.errored', 'connection.synced.errored.repairable', 'connection.synced.errored.institution', 'connection.synced.errored.provider', 'connection.synced.errored.service', 'connection.disconnected', 'account', 'account.created', 'account.owners_verified', 'account.reconnected', 'account.verified', 'balance', 'balance.created', 'statement', 'statement.ready']

class _SubscriptionFields(_Input):
    name: str | None = Field(None, title="Subscription Name")
    target_url: str | None = Field(None, alias="targetUrl", title="Webhook Target URL", json_schema_extra={"format": "uri"})
    event_types: list[EVENT_TYPE] | None = Field(None, alias="eventTypes", min_length=1, title="Event Types")
    disabled: bool | None = Field(None, title="Disabled")

    @field_validator("target_url")
    @classmethod
    def https_url(cls, value):
        if value is not None and not re.fullmatch(r"https://[^\s/?#]+(?:/[^\s]*)?", value):
            raise ValueError("Enter the HTTPS URL that should receive Quiltt webhooks")
        return value

class _SubscriptionCreate(_SubscriptionFields):
    name: str = Field(..., title="Subscription Name")
    target_url: str = Field(..., alias="targetUrl", title="Webhook Target URL", json_schema_extra={"format": "uri"})
    event_types: list[EVENT_TYPE] = Field(..., alias="eventTypes", min_length=1, title="Event Types")

class _SubscriptionUpdate(_SubscriptionFields, _SubscriptionId):
    pass

class _Mx(_ProfileId):
    member_guid: str = Field(..., alias="memberGuid", title="MX Member GUID")
    user_guid: str | None = Field(None, alias="userGuid", title="MX User GUID", description="Required for the first MX import for a profile; omit on subsequent imports.")
    externally_managed: bool = Field(False, alias="externallyManaged", title="Externally Managed")

class _Plaid(_ProfileId):
    access_token: str = Field(..., alias="accessToken", title="Plaid Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    mode: Literal["REALTIME", "BACKGROUND"] = Field("REALTIME", title="Import Mode")
    externally_managed: bool = Field(False, alias="externallyManaged", title="Externally Managed")
    migrate_webhook: bool = Field(True, alias="migrateWebhook", title="Migrate Plaid Webhook", description="Allow Quiltt to replace the webhook registered with Plaid. Set false to preserve it; syncing will be less frequent.")

class _Export(_ProfileId, _ConnectionId):
    pass

class _Institution(_Input):
    routing_number: str = Field(..., alias="routingNumber", pattern=r"^[0-9]{9}$", title="US Routing Number")

class ListProfilesConfig(_Page):
    operation: Literal["list_profiles"] = Field("list_profiles", title="List Profiles", json_schema_extra={"ui:hidden": True})

class GetProfileConfig(_ProfileId):
    operation: Literal["get_profile"] = Field("get_profile", title="Get Profile", json_schema_extra={"ui:hidden": True})

class CreateProfileConfig(_ProfileCreate):
    operation: Literal["create_profile"] = Field("create_profile", title="Create Profile", json_schema_extra={"ui:hidden": True})

class UpdateProfileConfig(_ProfileUpdate):
    operation: Literal["update_profile"] = Field("update_profile", title="Update Profile", json_schema_extra={"ui:hidden": True})

class DeleteProfileConfig(_ProfileId):
    operation: Literal["delete_profile"] = Field("delete_profile", title="Delete Profile", description="Permanently deletes the profile and all associated financial data. Completion can take up to 15 minutes.", json_schema_extra={"ui:hidden": True})

class ListSubscriptionsConfig(_Page):
    operation: Literal["list_subscriptions"] = Field("list_subscriptions", title="List Subscriptions", json_schema_extra={"ui:hidden": True})

class GetSubscriptionConfig(_SubscriptionId):
    operation: Literal["get_subscription"] = Field("get_subscription", title="Get Subscription", json_schema_extra={"ui:hidden": True})

class CreateSubscriptionConfig(_SubscriptionCreate):
    operation: Literal["create_subscription"] = Field("create_subscription", title="Create Subscription", json_schema_extra={"ui:hidden": True})

class UpdateSubscriptionConfig(_SubscriptionUpdate):
    operation: Literal["update_subscription"] = Field("update_subscription", title="Update Subscription", json_schema_extra={"ui:hidden": True})

class DeleteSubscriptionConfig(_SubscriptionId):
    operation: Literal["delete_subscription"] = Field("delete_subscription", title="Delete Subscription", json_schema_extra={"ui:hidden": True})

class ImportMxConnectionConfig(_Mx):
    operation: Literal["import_mx_connection"] = Field("import_mx_connection", title="Import Mx Connection", json_schema_extra={"ui:hidden": True})

class ImportPlaidConnectionConfig(_Plaid):
    operation: Literal["import_plaid_connection"] = Field("import_plaid_connection", title="Import Plaid Connection", json_schema_extra={"ui:hidden": True})

class ExportConnectionConfig(_Export):
    operation: Literal["export_connection"] = Field("export_connection", title="Export Connection", description="Export provider credentials for direct API access. Quiltt Support must enable this feature for your environment.", json_schema_extra={"ui:hidden": True})

class RefreshBalanceConfig(_AccountId):
    operation: Literal["refresh_balance"] = Field("refresh_balance", title="Refresh Balance", description="Requests an asynchronous refresh, usually billable in production. Accepted does not mean completed; listen for balance.created.", json_schema_extra={"ui:hidden": True})

class RefreshTransactionsConfig(_ConnectionId):
    operation: Literal["refresh_transactions"] = Field("refresh_transactions", title="Refresh Transactions", description="Requests an asynchronous refresh; accepted does not mean completed.", json_schema_extra={"ui:hidden": True})

class SearchInstitutionsConfig(_Institution):
    operation: Literal["search_institutions"] = Field("search_institutions", title="Search Institutions", json_schema_extra={"ui:hidden": True})

Operation = Annotated[Union[ListProfilesConfig, GetProfileConfig, CreateProfileConfig, UpdateProfileConfig, DeleteProfileConfig, ListSubscriptionsConfig, GetSubscriptionConfig, CreateSubscriptionConfig, UpdateSubscriptionConfig, DeleteSubscriptionConfig, ImportMxConnectionConfig, ImportPlaidConnectionConfig, ExportConnectionConfig, RefreshBalanceConfig, RefreshTransactionsConfig, SearchInstitutionsConfig], Field(discriminator="operation")]

class QuilttNodeConfig(NodeConfig[Operation, QuilttApiKeyCredential]):
    pass

ROUTES = {'list_profiles': ('GET', '/v1/profiles'),
 'get_profile': ('GET', '/v1/profiles/{profile_id}'),
 'create_profile': ('POST', '/v1/profiles'),
 'update_profile': ('PATCH', '/v1/profiles/{profile_id}'),
 'delete_profile': ('DELETE', '/v1/profiles/{profile_id}'),
 'list_subscriptions': ('GET', '/v1/webhooks/subscriptions'),
 'get_subscription': ('GET', '/v1/webhooks/subscriptions/{subscription_id}'),
 'create_subscription': ('POST', '/v1/webhooks/subscriptions'),
 'update_subscription': ('PATCH', '/v1/webhooks/subscriptions/{subscription_id}'),
 'delete_subscription': ('DELETE', '/v1/webhooks/subscriptions/{subscription_id}'),
 'import_mx_connection': ('POST', '/v1/profiles/{profile_id}/connections/import/mx'),
 'import_plaid_connection': ('POST', '/v1/profiles/{profile_id}/connections/import/plaid'),
 'export_connection': ('GET', '/v1/profiles/{profile_id}/connections/{connection_id}/export'),
 'refresh_balance': ('POST', '/v1/accounts/{account_id}/balances/refresh'),
 'refresh_transactions': ('POST', '/v1/connections/{connection_id}/transactions/refresh'),
 'search_institutions': ('GET', '/v1/institutions')}

class QuilttNode(WorkflowNode):
    integration_type = "automation-quiltt"
    connection_evidence = ConnectionEvidence(noun="profiles", operation="list_profiles")

    @classmethod
    def get_config_model(cls):
        return QuilttNodeConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Quiltt API key")
        method, route = ROUTES[config.operation]
        values = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        for field in ("profile_id", "subscription_id", "account_id", "connection_id"):
            if field in values:
                route = route.replace("{" + field + "}", quote(values.pop(field), safe=""))
        kwargs = {"params": values} if method == "GET" else {"json": values} if method in {"POST", "PATCH"} and values else {}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + route, headers={
                "Authorization": "Bearer " + credential.api_key, "Accept": "application/json",
            }, **kwargs)
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                message = " ".join(str(error.get(k, "")) for k in ("message", "instruction")).strip() if isinstance(error, dict) else ""
            except ValueError:
                message = ""
            message = message or f"Quiltt returned HTTP {response.status_code}"
            for secret in (credential.api_key, getattr(config, "access_token", None)):
                if secret:
                    message = message.replace(secret, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        if response.status_code in {202, 204} and not response.content:
            return {"status": "success", "http_status": response.status_code, "accepted": True}
        body = response.json()
        result = {"status": "success", "data": body}
        if config.operation in {"list_profiles", "list_subscriptions"}:
            if not isinstance(body, list):
                raise ValueError("Quiltt returned an unexpected list response")
            result["pagination"] = {key: response.headers[key] for key in ("current-page", "page-items", "total-count", "total-pages") if key in response.headers}
        return result

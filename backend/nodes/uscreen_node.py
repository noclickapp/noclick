"""Uscreen Publisher API v1.0.2: customer, access, content and reporting automation.

Contract: https://uscreen.io/api/publisher.yml
Authentication: https://help.uscreen.tv/en/articles/4576093-uscreen-api
Each operation makes one documented request; writes are never retried automatically.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.uscreen_operations import OPERATIONS
from utils.ssrf import guarded_async_client

BASE = "https://uscreen.io/publisher_api/v1"


class UscreenAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Uscreen API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://help.uscreen.tv/en/articles/4576093-uscreen-api",
            "x-credential-instructions": "Paste your Publisher API authorization key from your Uscreen Customer Success Manager or Support team. API access requires UscreenPlus. NoClick sends the key directly in the Authorization header."})
    credential_type: Literal["uscreen_api_key"] = Field("uscreen_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without an Authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def constraints(self):
        route = OPERATIONS[self.operation]
        for name in route["path_fields"].values():
            value = str(getattr(self, name))
            if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
                raise ValueError("Use a resource ID or customer email, without a URL or path")
        for name in ("from_time", "to_time", "event_launch_datetime"):
            value = getattr(self, name, None)
            if value is not None:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None: raise ValueError()
                except ValueError:
                    raise ValueError("Use an RFC 3339 timestamp with timezone") from None
        if getattr(self, "with_manual_billing", None) and getattr(self, "perform_action_at", None) is not None:
            raise ValueError("Omit perform_action_at when billing is manual")
        if self.operation == "grant_access" and self.product_type != "recurring" and self.with_manual_billing is not None:
            raise ValueError("Manual billing is only supported for recurring products")
        if self.operation == "update_customer" and not any(getattr(self, key) is not None for key in route["body_fields"]):
            raise ValueError("Provide at least one customer field to update")
        return self


class UscreenListCustomersConfig(_Input):
    'Get paginated list of customers'
    operation: Literal['list_customers'] = Field('list_customers', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1, description='Page number')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    date_field: str | None = Field(None, min_length=1, max_length=10000, description='Date field to filter by. Available fields: created_at, updated_at. Default: created_at. If not set, created_at is used')

class UscreenCreateCustomerConfig(_Input):
    'Invite a new customer'
    operation: Literal['create_customer'] = Field('create_customer', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, max_length=10000, description='Customer email. Should be unique')
    name: str = Field(..., min_length=1, max_length=10000, description='Customer name')
    skip_invite: bool | None = Field(None, strict=True, description="If you don't want to send a platform invite email, please send skip_invite = true.")
    field_1: str | None = Field(None, min_length=1, max_length=10000, description="Value for store's custom user field 1")
    field_2: str | None = Field(None, min_length=1, max_length=10000, description="Value for store's custom user field 2")
    field_3: str | None = Field(None, min_length=1, max_length=10000, description="Value for store's custom user field 3")
    opted_in_for_news_and_updates: bool | None = Field(None, strict=True, description='If you want to have the customer opted out of news and update emails, send opted_in_for_news_and_updates = false. The default applies to new customers only — when this call updates a customer who already exists as a lead, their current consent is left untouched unless you send this field explicitly.')
    opted_in_for_community_updates: bool | None = Field(None, strict=True, description="If you want to have the customer opted out of community update emails, send opted_in_for_community_updates = false. As with opted_in_for_news_and_updates, the default applies to new customers only and never overwrites an existing lead's choice.")
    legacy_id: str | None = Field(None, min_length=1, max_length=10000, description='External identifier used to reference this customer in third-party systems')
    tags: list[str] | None = Field(None, max_length=25, description='List of tag names to assign to this customer at creation. Names must contain only lowercase letters, numbers, and dashes (e.g. "annual-member", "vip"). Maximum 25 tags.')
    unsubscribed_topic_ids: list[int] | None = Field(None, description='Email topic ids to unsubscribe this customer from at creation (see GET /email_topics). Only ever unsubscribes — topics left out of the list are untouched. Ids that do not belong to an active topic of this store, and values that are not whole numbers, are rejected with a 422.')

class UscreenGetCustomerConfig(_Input):
    'Get a customer information'
    operation: Literal['get_customer'] = Field('get_customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')

class UscreenUpdateCustomerConfig(_Input):
    'Update a customer information'
    operation: Literal['update_customer'] = Field('update_customer', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')
    email: str | None = Field(None, min_length=1, max_length=10000, description="New customer's email")
    name: str | None = Field(None, min_length=1, max_length=10000, description="New customer's name")
    field_1: str | None = Field(None, min_length=1, max_length=10000, description="Value for store's custom user field 1")
    field_2: str | None = Field(None, min_length=1, max_length=10000, description="Value for store's custom user field 2")
    field_3: str | None = Field(None, min_length=1, max_length=10000, description="Value for store's custom user field 3")
    opted_in_for_news_and_updates: bool | None = Field(None, strict=True, description='When enabled, the customer will receive marketing emails')
    opted_in_for_community_updates: bool | None = Field(None, strict=True, description='When enabled, the customer will receive community update emails')
    tags: list[str] | None = Field(None, max_length=25, description='List of tag names to assign to this customer. Names must contain only lowercase letters, numbers, and dashes (e.g. "annual-member", "vip"). Maximum 25 tags. This is a replace operation — the provided list becomes the full set of tags. Omitting this field leaves existing tags unchanged. This field cannot be combined with `add_tags` or `remove_tags`. To change tags and keep the customer\'s other tags, use `add_tags` instead.')
    add_tags: list[str] | None = Field(None, max_length=25, description='Tag names to add to this customer. Tags already on the customer stay. A name that the store does not have yet creates the tag, with the same name rules as `tags`. A name the customer already has does nothing. Maximum 25 names.\n\nEach added tag starts the published automations with a Tag added trigger that matches it. An automation that matches any tag starts too, so a misspelled name creates a new tag and starts those automations.\n\nIntegrations that run next to automations should use `add_tags`, not `tags`. For example, an automation adds a tag to the customer, and a moment later an update with `tags` removes it, because the list that the integration sends does not contain that tag. `add_tags` changes only the listed tags.\n\nA request returns 422 when the same name is in `add_tags` and `remove_tags`, or when the value is not an array of strings. Every tag error comes under the `tags` key of the error object.')
    remove_tags: list[str] | None = Field(None, max_length=25, description="Tag names to remove from this customer. The customer's other tags stay. A name the customer does not have does nothing. Maximum 25 names.\n\nA request returns 422 when the same name is in `add_tags` and `remove_tags`, or when the value is not an array of strings. Every tag error comes under the `tags` key of the error object.")
    unsubscribed_topic_ids: list[int] | None = Field(None, description="Email topic ids to unsubscribe this customer from (see GET /email_topics). Unlike `tags`, this is NOT a replace operation — it only ever unsubscribes. Topics left out of the list keep their current state, and re-sending an id the customer is already unsubscribed from does nothing. An empty list and an omitted field are both no-ops.\n\nThis field cannot re-subscribe a customer: resubscribing is the customer's own act, performed from their email preferences page. Values that are not whole numbers, and ids that do not belong to an active topic of this store, are rejected with a 422.\n\nTo opt a customer out of all marketing email instead, send `opted_in_for_news_and_updates: false`.")

class UscreenListAccessesConfig(_Input):
    'Get paginated list of accesses'
    operation: Literal['list_accesses'] = Field('list_accesses', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')
    page: int | None = Field(None, strict=True, ge=1, description='Page number')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')

class UscreenGrantAccessConfig(_Input):
    'Grant access to a customer'
    operation: Literal['grant_access'] = Field('grant_access', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')
    perform_action_at: str | None = Field(None, min_length=1, max_length=10000, description='Seconds since the Epoch. Next perform action needed in case of rent or recurring product types. System will add next due automatically in case of a blank field.')
    product_id: int = Field(..., strict=True, ge=1, description='Product ID')
    product_type: Literal['program', 'recurring', 'rent', 'freebie', 'fixed_price'] = Field(..., min_length=1, max_length=10000, description='Uscreen system product type. Can be a program|recurring|rent|freebie|fixed_price')
    with_manual_billing: bool | None = Field(None, strict=True, description='Allows you to process billing outside the Uscreen platform. Default false.')
    skip_automations: bool | None = Field(None, strict=True, description='When true, automation enrollment (e.g. bundle_assigned) is skipped for this action. Defaults to false.')

class UscreenGetAccessConfig(_Input):
    'Get access by ID'
    operation: Literal['get_access'] = Field('get_access', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')
    access_id: str = Field(..., min_length=1, max_length=10000, description='Access ID')

class UscreenRevokeAccessConfig(_Input):
    'Revoke access by ID'
    operation: Literal['revoke_access'] = Field('revoke_access', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')
    access_id: str = Field(..., min_length=1, max_length=10000, description='Access ID')

class UscreenGetSubscriptionConfig(_Input):
    "Get a customer's active subscription"
    operation: Literal['get_subscription'] = Field('get_subscription', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')

class UscreenCreateSubscriptionConfig(_Input):
    'Create a subscription for a customer'
    operation: Literal['create_subscription'] = Field('create_subscription', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')
    product_id: int = Field(..., strict=True, ge=1, description='Subscription plan ID')
    with_manual_billing: bool | None = Field(None, strict=True, description='Process billing outside the Uscreen platform. Defaults to false. When true, omit perform_action_at.')
    perform_action_at: int | None = Field(None, strict=True, ge=0, description='Unix timestamp for the next billing/renewal date. Omit when with_manual_billing is true.')
    currency: str | None = Field(None, min_length=1, max_length=10000, description="Three-letter currency code (ISO 4217) for localized pricing. Must be one of the store's configured currencies. When omitted, the store's default currency is used.")
    cover_fees: bool | None = Field(None, strict=True, description='When true, transaction fees are added to the subscription price and covered by the customer. Only applicable when the store has cover-my-fees enabled.')
    skip_automations: bool | None = Field(None, strict=True, description='When true, automation enrollment (e.g. subscription_assigned) is skipped for this action. Defaults to false.')

class UscreenCancelSubscriptionConfig(_Input):
    "Cancel a customer's active subscription"
    operation: Literal['cancel_subscription'] = Field('cancel_subscription', json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=10000, description='Customer ID or Email')

class UscreenListInvoicesConfig(_Input):
    'Get paginated list of Invoices'
    operation: Literal['list_invoices'] = Field('list_invoices', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1, description='Page number')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    date_field: str | None = Field(None, min_length=1, max_length=10000, description='Date field to filter by. Available fields: created_at, updated_at. Default: created_at. If not set, created_at is used')

class UscreenGetInvoiceConfig(_Input):
    'Get invoice by ID'
    operation: Literal['get_invoice'] = Field('get_invoice', json_schema_extra={"ui:hidden": True})
    invoice_id: str = Field(..., min_length=1, max_length=10000, description='Invoice ID')

class UscreenListOffersConfig(_Input):
    'Get paginated list of offers'
    operation: Literal['list_offers'] = Field('list_offers', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1, description='Page number')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')

class UscreenGetOfferConfig(_Input):
    'Get an offer information'
    operation: Literal['get_offer'] = Field('get_offer', json_schema_extra={"ui:hidden": True})
    offer_id: str = Field(..., min_length=1, max_length=10000, description='Offer ID')

class UscreenListContentsConfig(_Input):
    'Get paginated list of contents (videos, collections and live events) (alias for /programs)'
    operation: Literal['list_contents'] = Field('list_contents', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1, description='Page number')
    include: str | None = Field(None, min_length=1, max_length=10000, description='Comma-separated list of relationship paths to include in the response. Available relationships: author.')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    content_type: Literal['collection', 'live_event', 'video'] | None = Field(None, min_length=1, max_length=10000, description='Filter results by content type (enum)')

class UscreenGetContentConfig(_Input):
    'Get content information (video, collection or live event) (alias for /programs/{id})'
    operation: Literal['get_content'] = Field('get_content', json_schema_extra={"ui:hidden": True})
    content_id: str = Field(..., min_length=1, max_length=10000, description='Content ID (same as program ID)')
    include: str | None = Field(None, min_length=1, max_length=10000, description='Comma-separated list of relationship paths to include in the response. Available relationships: author.')

class UscreenListPlaylistItemsConfig(_Input):
    'Get list of playlist items (formerly known as chapters) and file resources (alias for /programs/{program_id}/chapters)'
    operation: Literal['list_playlist_items'] = Field('list_playlist_items', json_schema_extra={"ui:hidden": True})
    content_id: str = Field(..., min_length=1, max_length=10000, description='Content ID (same as program ID)')

class UscreenPublishContentConfig(_Input):
    'Publish a video, collection or live event'
    operation: Literal['publish_content'] = Field('publish_content', json_schema_extra={"ui:hidden": True})
    content_id: str = Field(..., min_length=1, max_length=10000, description='Content ID')
    event_launch_datetime: str | None = Field(None, min_length=1, max_length=10000, description='**Live events only.** The date and time when the live event is scheduled to launch, formatted in RFC 3339. Must be in the future. Example: 2025-06-01T12:00:00Z. Similar to what `scheduled` offers for videos and collections.')

class UscreenUnpublishContentConfig(_Input):
    'Unpublish a video, collection or live event'
    operation: Literal['unpublish_content'] = Field('unpublish_content', json_schema_extra={"ui:hidden": True})
    content_id: str = Field(..., min_length=1, max_length=10000, description='Content ID')

class UscreenListGroupsConfig(_Input):
    'Get paginated list of groups'
    operation: Literal['list_groups'] = Field('list_groups', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1, description='Page number')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    date_field: str | None = Field(None, min_length=1, max_length=10000, description='Date field to filter by. Available fields: created_at, updated_at. Default: created_at. If not set, created_at is used')

class UscreenListGroupMembersConfig(_Input):
    'Get paginated list of group members'
    operation: Literal['list_group_members'] = Field('list_group_members', json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., strict=True, ge=1, description='Group ID')
    page: int | None = Field(None, strict=True, ge=1, description='Page number')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z')
    date_field: str | None = Field(None, min_length=1, max_length=10000, description='Date field to filter by. Available fields: created_at, updated_at. Default: created_at. If not set, created_at is used')

class UscreenAddGroupMemberConfig(_Input):
    'Add a member to a group'
    operation: Literal['add_group_member'] = Field('add_group_member', json_schema_extra={"ui:hidden": True})
    group_id: int = Field(..., strict=True, ge=1, description='Group ID')
    email: str = Field(..., min_length=1, max_length=10000, description="Member's email address")
    name: str = Field(..., min_length=1, max_length=10000, description="Member's full name")
    role: Literal['member', 'manager'] = Field(..., min_length=1, max_length=10000, description="Member's role in the group. Can be 'member' or 'manager'. Defaults to 'member' if not provided.")
    skip_automations: bool | None = Field(None, strict=True, description='When true, automation enrollment (e.g. lead_created) is skipped for this action. Defaults to false.')

class UscreenListVideoViewsConfig(_Input):
    'Get details on video views for a specific user, video, video collection or live event. Optionally filter by date range (default: last 12 months). The effective range is echoed back in the `X-Range-From` and `X-Range-To` response headers'
    operation: Literal['list_video_views'] = Field('list_video_views', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, strict=True, ge=1, description='Page number')
    per_page: int | None = Field(None, strict=True, ge=1, le=100, description='Number of results per page (default 10, max 100)')
    user_id: str | None = Field(None, min_length=1, max_length=10000, description='User ID or Email')
    content_id: str | None = Field(None, min_length=1, max_length=10000, description='Video, Collection or Live Event ID')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z. Must be within last 12 months. Default: 12 months ago')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z. Default: current time')

class UscreenGetTotalWatchTimeConfig(_Input):
    'Get the total video watch time for a specific user, video, video collection or live event. Optionally filter by date range (default: last 12 months)'
    operation: Literal['get_total_watch_time'] = Field('get_total_watch_time', json_schema_extra={"ui:hidden": True})
    user_id: str | None = Field(None, min_length=1, max_length=10000, description='User ID or Email')
    content_id: str | None = Field(None, min_length=1, max_length=10000, description='Video, Collection or Live Event ID')
    from_time: str | None = Field(None, min_length=1, max_length=10000, description='Starting date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z. Must be within last 12 months. Default: 12 months ago')
    to_time: str | None = Field(None, min_length=1, max_length=10000, description='Ending date and time for the filter range, formatted in RFC 3339. Example: 2023-01-01T00:00:00Z. Default: current time')


UscreenConfig = Annotated[Union[UscreenListCustomersConfig, UscreenCreateCustomerConfig, UscreenGetCustomerConfig, UscreenUpdateCustomerConfig, UscreenListAccessesConfig, UscreenGrantAccessConfig, UscreenGetAccessConfig, UscreenRevokeAccessConfig, UscreenGetSubscriptionConfig, UscreenCreateSubscriptionConfig, UscreenCancelSubscriptionConfig, UscreenListInvoicesConfig, UscreenGetInvoiceConfig, UscreenListOffersConfig, UscreenGetOfferConfig, UscreenListContentsConfig, UscreenGetContentConfig, UscreenListPlaylistItemsConfig, UscreenPublishContentConfig, UscreenUnpublishContentConfig, UscreenListGroupsConfig, UscreenListGroupMembersConfig, UscreenAddGroupMemberConfig, UscreenListVideoViewsConfig, UscreenGetTotalWatchTimeConfig], Field(discriminator="operation")]


class UscreenFullConfig(NodeConfig[UscreenConfig, UscreenAPIKeyCredential]):
    pass


class UscreenNode(WorkflowNode):
    integration_type = "automation-uscreen"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers")

    @classmethod
    def get_config_model(cls):
        return UscreenFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Uscreen API key")
        route = OPERATIONS[config.operation]
        path = route["path"]
        for parameter, field in route["path_fields"].items():
            path = path.replace("{" + parameter + "}", quote(str(getattr(config, field)), safe=""))
        params = {name: getattr(config, field) for name, field in route["query_fields"].items() if getattr(config, field) is not None}
        body = {field: getattr(config, field) for field in route["body_fields"] if getattr(config, field) is not None}
        # Customer consent stays unchanged unless a person explicitly supplies it.
        kwargs = {"params": params, "headers": {"Authorization": credential.api_key, "Accept": "application/json"}}
        if route["body_fields"]:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(route["method"], BASE + path, **kwargs)
        if response.status_code not in route["statuses"]:
            # Preserve the provider's rejection for the shared credential-connect seam.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message or "Uscreen rejected the request"}
        result = {"status": "success", "http_status": response.status_code, "operation": config.operation}
        if response.status_code == 204 or not response.content:
            return {**result, "data": None}
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Expected a bounded JSON response from Uscreen")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Unexpected Uscreen response shape")
        if isinstance(data, dict) and ("error" in data or "errors" in data):
            return {"status": "error", "error": json.dumps(data).replace(credential.api_key, "[redacted]")}
        # Do not follow provider links: expose page numbers for explicit continuation.
        next_page = None
        if 'rel="next"' in response.headers.get("link", ""):
            for link in response.headers["link"].split(","):
                if 'rel="next"' not in link: continue
                match = re.match(r'\s*<([^>]+)>', link)
                if not match: raise ValueError("Invalid Uscreen pagination link")
                target = urlsplit(match[1])
                if target.scheme != "https" or target.netloc != "uscreen.io" or target.path != urlsplit(BASE + path).path:
                    raise ValueError("Unexpected Uscreen pagination destination")
                pages = parse_qs(target.query).get("page", [])
                if len(pages) != 1 or not pages[0].isdigit() or int(pages[0]) <= (getattr(config, "page", None) or 1):
                    raise ValueError("Invalid Uscreen continuation page")
                next_page = int(pages[0])
        # Defensive redaction if a provider response unexpectedly echoes our key.
        data = json.loads(json.dumps(data).replace(credential.api_key, "[redacted]"))
        return {**result, "data": data, "next_page": next_page,
                "total_count": response.headers.get("total-count")}

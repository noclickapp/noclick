"""Stibee v2: one published API operation per action, using a pasted API key.

Lists return one page; callers advance offset explicitly. A send acknowledgement
means Stibee accepted the request, never that every recipient received it.
Contract: https://developers.stibee.com/openapi.yml (2.0.0).
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.stibee.com/v2"


def email_address(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[^\s@<>/]+@[^\s@<>/]+\.[^\s@<>/]+", value
    ):
        raise ValueError("Enter a subscriber or sender email address")
    return value


EmailAddress = Annotated[str, BeforeValidator(email_address)]
ResourceID = Annotated[int, Field(gt=0)]


class StibeeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Stibee API Key",
        extra="ignore",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://help.stibee.com/api-webhook/api#id-1-api-2",
            "x-credential-instructions": "Paste an API key created after January 21, 2025 from Stibee Workspace settings > API keys. Subscriber operations require Standard or above; email and group operations require Pro or Enterprise, and address-book reads require Enterprise. Connection verification lists your emails and needs Pro or Enterprise. NoClick sends the key only to api.stibee.com in the AccessToken header.",
        },
    )
    credential_type: Literal["stibee_api_key"] = Field(
        "stibee_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=8192,
        repr=False,
        title="API Key",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or re.search(r"[\s\x00-\x1f\x7f:]", value):
            raise ValueError("Paste only the API key without a header prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, populate_by_name=True
    )

    @field_validator("*", mode="after")
    @classmethod
    def bounded_json(cls, value):
        if isinstance(value, (dict, list)):
            try:
                if len(json.dumps(value, allow_nan=False)) > 1_000_000:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValueError("Use finite JSON values within one megabyte") from None
        return value


class Page(Input):
    offset: int = Field(
        0, ge=0, description="Start offset; this operation returns one page only."
    )
    limit: int = Field(20, ge=1, le=100)


class ListID(Input):
    list_id: ResourceID = Field(..., title="Address book ID")


class GroupID(ListID):
    group_id: ResourceID


class SubscriberID(ListID):
    subscriber: EmailAddress


class EmailID(Input):
    email_id: ResourceID


class Subscriber(Input):
    email: EmailAddress
    status: Literal["subscribed", "unsubscribed"] = Field(
        ..., description="Use subscribed only when you have the subscriber's consent."
    )
    marketing_allowed: bool | None = Field(None, alias="marketingAllowed")
    fields: dict[str, Any] | None = Field(
        None,
        description="Values for existing Stibee custom fields, such as name and age.",
    )


class EmailFields(Input):
    subject: str | None = Field(None, min_length=1, max_length=1000)
    sender_email: EmailAddress | None = Field(None, alias="senderEmail")
    sender_name: str | None = Field(
        None, alias="senderName", min_length=1, max_length=1000
    )
    list_id: ResourceID | None = Field(None, alias="listId")
    segment_ids: list[ResourceID] | None = Field(
        None, alias="segmentIds", max_length=100
    )
    group_ids: list[ResourceID] | None = Field(None, alias="groupIds", max_length=100)


class StibeeListListsConfig(Page):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "enterprise",
            "x-tier-label": "Enterprise",
        }
    )
    operation: Literal["list_lists"] = Field(
        "list_lists", description="List lists", json_schema_extra={"ui:hidden": True}
    )
    sort_order: Literal["desc", "asc"] = "desc"


class StibeeGetListConfig(ListID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "enterprise",
            "x-tier-label": "Enterprise",
        }
    )
    operation: Literal["get_list"] = Field(
        "get_list", description="Get list", json_schema_extra={"ui:hidden": True}
    )


class StibeeListSubscribersConfig(ListID, Page):
    operation: Literal["list_subscribers"] = Field(
        "list_subscribers",
        description="List subscribers",
        json_schema_extra={"ui:hidden": True},
    )
    limit: int = Field(100, ge=1, le=1000)
    statuses: str | None = Field(
        None, description="Comma-separated subscribed, unsubscribed, archived or ready."
    )


class StibeeAddSubscriberConfig(ListID):
    operation: Literal["add_subscriber"] = Field(
        "add_subscriber",
        description="Add subscriber",
        json_schema_extra={"ui:hidden": True},
    )
    subscriber: Subscriber
    update_enabled: bool | None = Field(None, alias="updateEnabled")


class StibeeUpdateSubscriberConfig(SubscriberID):
    operation: Literal["update_subscriber"] = Field(
        "update_subscriber",
        description="Update subscriber",
        json_schema_extra={"ui:hidden": True},
    )
    fields: dict[str, Any] = Field(..., min_length=1)


class StibeeUnsubscribeSubscriberConfig(SubscriberID):
    operation: Literal["unsubscribe_subscriber"] = Field(
        "unsubscribe_subscriber",
        description="Unsubscribe subscriber",
        json_schema_extra={"ui:hidden": True},
    )


class StibeeGetSubscriberCountConfig(ListID):
    operation: Literal["get_subscriber_count"] = Field(
        "get_subscriber_count",
        description="Get subscriber count",
        json_schema_extra={"ui:hidden": True},
    )
    statuses: str | None = Field(
        None, description="Comma-separated subscribed, unsubscribed, archived or ready."
    )


class StibeeDeleteSubscribersConfig(ListID):
    operation: Literal["delete_subscribers"] = Field(
        "delete_subscribers",
        description="Delete subscribers",
        json_schema_extra={"ui:hidden": True},
    )
    subscribers: list[EmailAddress] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Permanently delete these subscribers from this address book.",
    )


class StibeeListGroupsConfig(ListID, Page):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["list_groups"] = Field(
        "list_groups", description="List groups", json_schema_extra={"ui:hidden": True}
    )
    sort_by: Literal["id", "name"] = "id"
    sort_order: Literal["desc", "asc"] = "desc"


class StibeeCreateGroupConfig(ListID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["create_group"] = Field(
        "create_group",
        description="Create group",
        json_schema_extra={"ui:hidden": True},
    )
    name: str = Field(..., min_length=1, max_length=1000)


class StibeeUpdateGroupConfig(GroupID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["update_group"] = Field(
        "update_group",
        description="Update group",
        json_schema_extra={"ui:hidden": True},
    )
    name: str = Field(..., min_length=1, max_length=1000)


class StibeeDeleteGroupConfig(GroupID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["delete_group"] = Field(
        "delete_group",
        description="Delete group",
        json_schema_extra={"ui:hidden": True},
    )


class StibeeAssignGroupConfig(GroupID):
    operation: Literal["assign_group"] = Field(
        "assign_group",
        description="Assign group",
        json_schema_extra={"ui:hidden": True},
    )
    subscriber: EmailAddress


class StibeeReleaseGroupConfig(GroupID):
    operation: Literal["release_group"] = Field(
        "release_group",
        description="Release group",
        json_schema_extra={"ui:hidden": True},
    )
    subscriber: EmailAddress


class StibeeListEmailsConfig(Page):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["list_emails"] = Field(
        "list_emails", description="List emails", json_schema_extra={"ui:hidden": True}
    )
    list_id: ResourceID | None = None
    ids: str | None = Field(None, pattern=r"^[1-9][0-9]*(,[1-9][0-9]*)*$")
    statuses: str | None = None
    types: str | None = None
    sort_by: Literal["createdTime", "modifiedTime", "sentTime"] | None = None
    sort_order: Literal["asc", "desc"] | None = None


class StibeeGetEmailConfig(EmailID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["get_email"] = Field(
        "get_email", description="Get email", json_schema_extra={"ui:hidden": True}
    )


class StibeeCreateEmailConfig(EmailFields):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["create_email"] = Field(
        "create_email",
        description="Create email",
        json_schema_extra={"ui:hidden": True},
    )
    subject: str = Field(..., min_length=1, max_length=1000)
    sender_email: EmailAddress = Field(..., alias="senderEmail")
    sender_name: str = Field(..., alias="senderName", min_length=1, max_length=1000)
    list_id: ResourceID = Field(..., alias="listId")


class StibeeUpdateEmailConfig(EmailID, EmailFields):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["update_email"] = Field(
        "update_email",
        description="Update email",
        json_schema_extra={"ui:hidden": True},
    )

    @model_validator(mode="after")
    def has_changes(self):
        if not any(
            getattr(self, field) is not None
            for field in (
                "subject",
                "sender_email",
                "sender_name",
                "list_id",
                "segment_ids",
                "group_ids",
            )
        ):
            raise ValueError("Provide at least one email field to update")
        return self


class StibeeDeleteEmailConfig(EmailID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["delete_email"] = Field(
        "delete_email",
        description="Delete email",
        json_schema_extra={"ui:hidden": True},
    )


class StibeeCopyEmailConfig(EmailID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["copy_email"] = Field(
        "copy_email", description="Copy email", json_schema_extra={"ui:hidden": True}
    )


class StibeeGetEmailStatsConfig(Input):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["get_email_stats"] = Field(
        "get_email_stats",
        description="Get email stats",
        json_schema_extra={"ui:hidden": True},
    )
    ids: str = Field(
        ...,
        pattern=r"^[1-9][0-9]*(,[1-9][0-9]*){0,9}$",
        description="One to ten comma-separated email IDs.",
    )


class StibeeGetEmailLogsConfig(EmailID, Page):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["get_email_logs"] = Field(
        "get_email_logs",
        description="Get email logs",
        json_schema_extra={"ui:hidden": True},
    )
    limit: int = Field(20, ge=1, le=1000)
    actions: str | None = Field(
        None, description="Comma-separated activity codes, such as O,C."
    )
    subscribers: str | None = Field(
        None, description="Up to 30 comma-separated exact subscriber email addresses."
    )


class StibeeGetEmailContentConfig(EmailID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["get_email_content"] = Field(
        "get_email_content",
        description="Get email content",
        json_schema_extra={"ui:hidden": True},
    )
    ab_test: Literal["A", "B"] | None = None


class StibeeUpdateEmailContentConfig(EmailID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["update_email_content"] = Field(
        "update_email_content",
        description="Update email content",
        json_schema_extra={"ui:hidden": True},
    )
    html: str = Field(
        ...,
        min_length=1,
        max_length=1_000_000,
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "html"},
    )


class StibeeSendEmailConfig(EmailID):
    model_config = ConfigDict(
        json_schema_extra={
            "x-requires-tier": "pro_or_enterprise",
            "x-tier-label": "Pro or Enterprise",
        }
    )
    operation: Literal["send_email"] = Field(
        "send_email",
        description="Send this normal email to its configured audience; acceptance does not prove delivery.",
        json_schema_extra={"ui:hidden": True},
    )


StibeeConfig = Annotated[
    Union[
        StibeeListListsConfig,
        StibeeGetListConfig,
        StibeeListSubscribersConfig,
        StibeeAddSubscriberConfig,
        StibeeUpdateSubscriberConfig,
        StibeeUnsubscribeSubscriberConfig,
        StibeeGetSubscriberCountConfig,
        StibeeDeleteSubscribersConfig,
        StibeeListGroupsConfig,
        StibeeCreateGroupConfig,
        StibeeUpdateGroupConfig,
        StibeeDeleteGroupConfig,
        StibeeAssignGroupConfig,
        StibeeReleaseGroupConfig,
        StibeeListEmailsConfig,
        StibeeGetEmailConfig,
        StibeeCreateEmailConfig,
        StibeeUpdateEmailConfig,
        StibeeDeleteEmailConfig,
        StibeeCopyEmailConfig,
        StibeeGetEmailStatsConfig,
        StibeeGetEmailLogsConfig,
        StibeeGetEmailContentConfig,
        StibeeUpdateEmailContentConfig,
        StibeeSendEmailConfig,
    ],
    Field(discriminator="operation"),
]


class StibeeFullConfig(NodeConfig[StibeeConfig, StibeeAPIKeyCredential]):
    pass


# Each tuple maps to exactly one pinned provider operation; no arbitrary routes.
ROUTES = {
    "list_lists": (
        "GET",
        "/lists",
        {"offset": "offset", "limit": "limit", "sort_order": "sortOrder"},
        {},
        "nullable_array",
    ),
    "get_list": ("GET", "/lists/{list_id}", {}, {}, "object"),
    "list_subscribers": (
        "GET",
        "/lists/{list_id}/subscribers",
        {"offset": "offset", "limit": "limit", "statuses": "statuses"},
        {},
        "array",
    ),
    "add_subscriber": (
        "POST",
        "/lists/{list_id}/subscribers",
        {},
        {"subscriber": "subscriber", "update_enabled": "updateEnabled"},
        "ok",
    ),
    "update_subscriber": (
        "PUT",
        "/lists/{list_id}/subscribers/{subscriber}",
        {},
        {"fields": "fields"},
        "ok",
    ),
    "unsubscribe_subscriber": (
        "POST",
        "/lists/{list_id}/subscribers/{subscriber}/unsubscribe",
        {},
        {},
        "ok",
    ),
    "get_subscriber_count": (
        "GET",
        "/lists/{list_id}/subscribers/count",
        {"statuses": "statuses"},
        {},
        "count",
    ),
    "delete_subscribers": (
        "DELETE",
        "/lists/{list_id}/subscribers",
        {},
        {"subscribers": "subscribers"},
        "ok",
    ),
    "list_groups": (
        "GET",
        "/lists/{list_id}/groups",
        {
            "offset": "offset",
            "limit": "limit",
            "sort_by": "sortBy",
            "sort_order": "sortOrder",
        },
        {},
        "array",
    ),
    "create_group": ("POST", "/lists/{list_id}/groups", {}, {"name": "name"}, "id"),
    "update_group": (
        "PUT",
        "/lists/{list_id}/groups/{group_id}",
        {},
        {"name": "name"},
        "ok",
    ),
    "delete_group": ("DELETE", "/lists/{list_id}/groups/{group_id}", {}, {}, "ok"),
    "assign_group": (
        "POST",
        "/lists/{list_id}/groups/{group_id}/assign",
        {},
        {"subscriber": "subscriber"},
        "ok",
    ),
    "release_group": (
        "POST",
        "/lists/{list_id}/groups/{group_id}/release",
        {},
        {"subscriber": "subscriber"},
        "ok",
    ),
    "list_emails": (
        "GET",
        "/emails",
        {
            "offset": "offset",
            "limit": "limit",
            "list_id": "listId",
            "ids": "ids",
            "statuses": "statuses",
            "types": "types",
            "sort_by": "sortBy",
            "sort_order": "sortOrder",
        },
        {},
        "page",
    ),
    "get_email": ("GET", "/emails/{email_id}", {}, {}, "object"),
    "create_email": (
        "POST",
        "/emails",
        {},
        {
            "subject": "subject",
            "sender_email": "senderEmail",
            "sender_name": "senderName",
            "list_id": "listId",
            "segment_ids": "segmentIds",
            "group_ids": "groupIds",
        },
        "id",
    ),
    "update_email": (
        "PUT",
        "/emails/{email_id}",
        {},
        {
            "subject": "subject",
            "sender_email": "senderEmail",
            "sender_name": "senderName",
            "list_id": "listId",
            "segment_ids": "segmentIds",
            "group_ids": "groupIds",
        },
        "ok",
    ),
    "delete_email": ("DELETE", "/emails/{email_id}", {}, {}, "ok"),
    "copy_email": ("POST", "/emails/{email_id}/copy", {}, {}, "id"),
    "get_email_stats": ("GET", "/emails/stats", {"ids": "ids"}, {}, "items"),
    "get_email_logs": (
        "GET",
        "/emails/{email_id}/logs",
        {
            "offset": "offset",
            "limit": "limit",
            "actions": "actions",
            "subscribers": "subscribers",
        },
        {},
        "page",
    ),
    "get_email_content": (
        "GET",
        "/emails/{email_id}/content",
        {"ab_test": "abTest"},
        {},
        "html",
    ),
    "update_email_content": (
        "POST",
        "/emails/{email_id}/content",
        {},
        {"html": "html"},
        "ok",
    ),
    "send_email": ("POST", "/emails/{email_id}/send", {}, {}, "ok"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {
            _redact(key, secret): _redact(item, secret) for key, item in value.items()
        }
    return value


class StibeeNode(WorkflowNode):
    integration_type = "automation-stibee"
    connection_evidence = ConnectionEvidence(
        operation="list_emails", noun="emails", label_keys=("subject", "id")
    )

    @classmethod
    def get_config_model(cls):
        return StibeeFullConfig

    @staticmethod
    def _check_family(config_data):
        raw = config_data.get("credentials")
        if (
            isinstance(raw, dict)
            and "credential_type" in raw
            and raw["credential_type"] != "stibee_api_key"
        ):
            raise ValueError("Attach a Stibee API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect a Stibee API key")
        method, path, query_fields, body_fields, kind = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + field + "}", quote(str(values[field]), safe=""))
        query = {
            wire: values[field]
            for field, wire in query_fields.items()
            if field in values
        }
        body = {
            wire: getattr(config, field)
            for field, wire in body_fields.items()
            if field in values
        }
        # Nested subscriber keys also use Stibee's camel-case spelling.
        if isinstance(body.get("subscriber"), Subscriber):
            body["subscriber"] = body["subscriber"].model_dump(
                by_alias=True, exclude_none=True
            )
        headers = {
            "AccessToken": credential.api_key,
            "Accept": "text/html" if kind == "html" else "application/json, text/plain",
        }
        kwargs = {"params": query} if query else {}
        if config.operation == "update_email_content":
            headers["Content-Type"] = "text/html; charset=utf-8"
            kwargs["content"] = config.html.encode("utf-8")
        elif body:
            kwargs["json"] = body
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method, BASE + path, headers=headers, **kwargs
                )
        except httpx.RequestError:
            raise ValueError(
                "Stibee could not be reached; request outcome is unknown. Inspect writes before retrying."
            ) from None
        if len(response.content) > 5_000_000:
            raise ValueError("Stibee response exceeds the supported size")
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        payload = None
        if mime == "application/json":
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Stibee returned invalid JSON") from None
        if response.status_code != 200 or (
            isinstance(payload, dict)
            and (
                str(payload.get("code", "")).startswith("Errors.") or "error" in payload
            )
        ):
            message = payload.get("message") if isinstance(payload, dict) else None
            detail = (
                _redact(message, credential.api_key)[:1000]
                if isinstance(message, str)
                else "Stibee did not confirm the request"
            )
            raise ValueError(f"Stibee HTTP {response.status_code}: {detail}")
        result = {
            "status": "accepted" if config.operation == "send_email" else "success",
            "operation": config.operation,
            "http_status": response.status_code,
        }
        if kind == "ok":
            if mime != "text/plain" or response.text.strip() != "ok":
                raise ValueError(
                    "Stibee did not return its documented ok acknowledgement; inspect writes before retrying"
                )
            result["acknowledged"] = True
            if config.operation == "send_email":
                result["delivery_verified"] = False
            return result
        if kind == "html":
            if mime != "text/html":
                raise ValueError(
                    "Stibee returned an unexpected content type for email HTML"
                )
            return {**result, "html": _redact(response.text, credential.api_key)}
        if mime != "application/json":
            raise ValueError("Stibee returned an unexpected content type")
        if kind == "nullable_array" and payload is None:
            payload = []
        if kind in {"array", "nullable_array"}:
            if not isinstance(payload, list) or any(
                not isinstance(row, dict) for row in payload
            ):
                raise ValueError("Stibee returned an invalid list")
            result["data"] = payload
            result["offset"], result["limit"] = config.offset, config.limit
            # Array endpoints have no total: a full page only suggests another.
            result["next_offset"] = (
                config.offset + len(payload) if len(payload) == config.limit else None
            )
        elif kind in {"page", "items"}:
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("items"), list)
                or any(not isinstance(row, dict) for row in payload["items"])
            ):
                raise ValueError("Stibee returned an invalid items envelope")
            result["data"] = payload["items"]
            if kind == "page":
                if (
                    any(
                        type(payload.get(key)) is not int or payload[key] < 0
                        for key in ("total", "offset", "limit")
                    )
                    or payload["limit"] < 1
                ):
                    raise ValueError("Stibee returned invalid pagination")
                result.update(
                    {key: payload[key] for key in ("total", "offset", "limit")}
                )
                result["next_offset"] = (
                    payload["offset"] + len(payload["items"])
                    if payload["items"]
                    and payload["offset"] + len(payload["items"]) < payload["total"]
                    else None
                )
        else:
            if not isinstance(payload, dict):
                raise ValueError("Stibee returned an invalid object")
            key = "total" if kind == "count" else "id"
            if type(payload.get(key)) is not int or payload[key] < (
                0 if kind == "count" else 1
            ):
                raise ValueError("Stibee response is missing its documented " + key)
            result["data"] = payload
        return _redact(result, credential.api_key)

"""MailerLite Classic v2: subscriber, group and custom-field automation.

Contract: https://developers-classic.mailerlite.com/reference
Classic accounts only. Each operation performs exactly one API request.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.mailerlite.com/api/v2"
CREDENTIAL_TYPE = "mailerlite_classic_api_key"


class MailerLiteClassicAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="MailerLite Classic API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers-classic.mailerlite.com/docs/authentication",
            "x-credential-instructions": "In your MailerLite Classic account, open Integrations and copy the API key. Paste it here. This connection uses the Classic v2 API; keys from the new MailerLite are not compatible.",
        })
    credential_type: Literal["mailerlite_classic_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_values(cls, value, info):
        if info.field_name in {"identifier", "subscriber_identifier"}:
            if not re.fullmatch(r"[0-9]+|[^\s/@?#%]+@[^\s/@?#%]+\.[^\s/@?#%]+", value):
                raise ValueError("Use a subscriber ID or email address")
        return value


class _Page(_Input):
    limit: int = Field(100, ge=1, le=100, description="One page only; use next_offset to request the next page.")
    offset: int = Field(0, ge=0, le=2147483647)


class _SubscriberBody(_Input):
    email: str = Field(..., min_length=3, max_length=320)
    name: str | None = Field(None, max_length=1000)
    fields: dict[str, str] | None = Field(None, description="Custom field keys mapped to values, for example company or city.")
    resubscribe: bool = Field(False, description="Explicitly reactivate an unsubscribed subscriber.")
    type: Literal["active", "unsubscribed", "unconfirmed"] | None = None

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Use an email address")
        return value


class MailerLiteClassicGetAccountConfig(_Input):
    """Get account."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class MailerLiteClassicListSubscribersConfig(_Page):
    """List subscribers."""
    operation: Literal["list_subscribers"] = Field("list_subscribers", json_schema_extra={"ui:hidden": True})
    type: Literal["active", "unsubscribed", "unconfirmed", "bounced", "junk"] | None = None


class MailerLiteClassicSearchSubscribersConfig(_Page):
    """Search subscribers."""
    operation: Literal["search_subscribers"] = Field("search_subscribers", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, max_length=1000)
    minimized: bool = False


class MailerLiteClassicGetSubscriberConfig(_Input):
    """Get subscriber."""
    operation: Literal["get_subscriber"] = Field("get_subscriber", json_schema_extra={"ui:hidden": True})
    identifier: str = Field(..., min_length=1, max_length=320)


class MailerLiteClassicCreateSubscriberConfig(_SubscriberBody):
    """Create subscriber."""
    operation: Literal["create_subscriber"] = Field("create_subscriber", json_schema_extra={"ui:hidden": True})


class MailerLiteClassicUpdateSubscriberConfig(_Input):
    """Update subscriber."""
    operation: Literal["update_subscriber"] = Field("update_subscriber", json_schema_extra={"ui:hidden": True})
    identifier: str = Field(..., min_length=1, max_length=320)
    name: str | None = Field(None, max_length=1000)
    type: Literal["active", "unsubscribed"] | None = None
    fields: dict[str, str] | None = None
    resend_autoresponders: bool | None = None

    @model_validator(mode="after")
    def nonempty_update(self):
        if all(getattr(self, k) is None for k in ("name", "type", "fields", "resend_autoresponders")):
            raise ValueError("Set at least one subscriber field to update")
        return self


class MailerLiteClassicGetSubscriberActivityConfig(_Input):
    """Get subscriber activity."""
    operation: Literal["get_subscriber_activity"] = Field("get_subscriber_activity", json_schema_extra={"ui:hidden": True})
    identifier: str = Field(..., min_length=1, max_length=320)


class MailerLiteClassicListSubscriberGroupsConfig(_Input):
    """List subscriber groups."""
    operation: Literal["list_subscriber_groups"] = Field("list_subscriber_groups", json_schema_extra={"ui:hidden": True})
    identifier: str = Field(..., min_length=1, max_length=320)


class MailerLiteClassicAssignSubscriberGroupsConfig(_Input):
    """Assign subscriber groups."""
    operation: Literal["assign_subscriber_groups"] = Field("assign_subscriber_groups", json_schema_extra={"ui:hidden": True})
    identifier: str = Field(..., min_length=1, max_length=320)
    groups: list[Annotated[int, Field(gt=0, le=2147483647)]] = Field(..., min_length=1, max_length=100)


class MailerLiteClassicListGroupsConfig(_Page):
    """List groups."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})


class MailerLiteClassicGetGroupConfig(_Input):
    """Get group."""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, title="Group ID")


class MailerLiteClassicCreateGroupConfig(_Input):
    """Create group."""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)


class MailerLiteClassicRenameGroupConfig(_Input):
    """Rename group."""
    operation: Literal["rename_group"] = Field("rename_group", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, title="Group ID")
    name: str = Field(..., min_length=1, max_length=1000)


class MailerLiteClassicDeleteGroupConfig(_Input):
    """Delete group."""
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, title="Group ID")


class MailerLiteClassicListGroupSubscribersConfig(_Page):
    """List group subscribers."""
    operation: Literal["list_group_subscribers"] = Field("list_group_subscribers", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, title="Group ID")
    type: Literal["active", "unsubscribed", "unconfirmed", "bounced", "junk"] | None = None


class MailerLiteClassicAddGroupSubscriberConfig(_SubscriberBody):
    """Add group subscriber."""
    operation: Literal["add_group_subscriber"] = Field("add_group_subscriber", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, title="Group ID")
    autoresponders: bool = Field(True, description="Allow MailerLite to send group autoresponders.")


class MailerLiteClassicRemoveGroupSubscriberConfig(_Input):
    """Remove group subscriber."""
    operation: Literal["remove_group_subscriber"] = Field("remove_group_subscriber", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, title="Group ID")
    subscriber_identifier: str = Field(..., min_length=1, max_length=320)


class MailerLiteClassicListFieldsConfig(_Input):
    """List fields."""
    operation: Literal["list_fields"] = Field("list_fields", json_schema_extra={"ui:hidden": True})


class MailerLiteClassicCreateFieldConfig(_Input):
    """Create field."""
    operation: Literal["create_field"] = Field("create_field", json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=1000)
    type: Literal["TEXT", "NUMBER", "DATE"] = "TEXT"


class MailerLiteClassicUpdateFieldConfig(_Input):
    """Update field."""
    operation: Literal["update_field"] = Field("update_field", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, title="Field ID")
    title: str = Field(..., min_length=1, max_length=1000)


class MailerLiteClassicDeleteFieldConfig(_Input):
    """Delete field."""
    operation: Literal["delete_field"] = Field("delete_field", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., gt=0, le=2147483647, title="Field ID")


class MailerLiteClassicListCampaignsConfig(_Page):
    """List campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})
    status: Literal["sent", "draft", "outbox"] = "sent"
    order: Literal["asc", "desc"] = "desc"


class MailerLiteClassicGetStatsConfig(_Input):
    """Get stats."""
    operation: Literal["get_stats"] = Field("get_stats", json_schema_extra={"ui:hidden": True})
    timestamp: int | None = Field(None, ge=0, le=2147483647)


MailerLiteClassicConfig = Annotated[Union[
    MailerLiteClassicGetAccountConfig,
    MailerLiteClassicListSubscribersConfig,
    MailerLiteClassicSearchSubscribersConfig,
    MailerLiteClassicGetSubscriberConfig,
    MailerLiteClassicCreateSubscriberConfig,
    MailerLiteClassicUpdateSubscriberConfig,
    MailerLiteClassicGetSubscriberActivityConfig,
    MailerLiteClassicListSubscriberGroupsConfig,
    MailerLiteClassicAssignSubscriberGroupsConfig,
    MailerLiteClassicListGroupsConfig,
    MailerLiteClassicGetGroupConfig,
    MailerLiteClassicCreateGroupConfig,
    MailerLiteClassicRenameGroupConfig,
    MailerLiteClassicDeleteGroupConfig,
    MailerLiteClassicListGroupSubscribersConfig,
    MailerLiteClassicAddGroupSubscriberConfig,
    MailerLiteClassicRemoveGroupSubscriberConfig,
    MailerLiteClassicListFieldsConfig,
    MailerLiteClassicCreateFieldConfig,
    MailerLiteClassicUpdateFieldConfig,
    MailerLiteClassicDeleteFieldConfig,
    MailerLiteClassicListCampaignsConfig,
    MailerLiteClassicGetStatsConfig
], Field(discriminator="operation")]


class MailerLiteClassicFullConfig(NodeConfig[MailerLiteClassicConfig, MailerLiteClassicAPIKeyCredential]):
    pass


ROUTES = {'get_account': {'method': 'GET',
                 'path': '/me',
                 'query': [],
                 'body': [],
                 'kind': 'account',
                 'docs': 'https://developers-classic.mailerlite.com/reference/account'},
 'list_subscribers': {'method': 'GET',
                      'path': '/subscribers',
                      'query': ['limit', 'offset', 'type'],
                      'body': [],
                      'kind': 'list',
                      'docs': 'https://developers-classic.mailerlite.com/reference/subscribers'},
 'search_subscribers': {'method': 'GET',
                        'path': '/subscribers/search',
                        'query': ['query', 'limit', 'offset', 'minimized'],
                        'body': [],
                        'kind': 'list',
                        'docs': 'https://developers-classic.mailerlite.com/reference/search-for-subscribers'},
 'get_subscriber': {'method': 'GET',
                    'path': '/subscribers/{identifier}',
                    'query': [],
                    'body': [],
                    'kind': 'object',
                    'docs': 'https://developers-classic.mailerlite.com/reference/single-subscriber'},
 'create_subscriber': {'method': 'POST',
                       'path': '/subscribers',
                       'query': [],
                       'body': ['email', 'name', 'fields', 'resubscribe', 'type'],
                       'kind': 'object',
                       'docs': 'https://developers-classic.mailerlite.com/reference/create-a-subscriber'},
 'update_subscriber': {'method': 'PUT',
                       'path': '/subscribers/{identifier}',
                       'query': [],
                       'body': ['name', 'type', 'fields', 'resend_autoresponders'],
                       'kind': 'object',
                       'docs': 'https://developers-classic.mailerlite.com/reference/update-subscriber'},
 'get_subscriber_activity': {'method': 'GET',
                             'path': '/subscribers/{identifier}/activity',
                             'query': [],
                             'body': [],
                             'kind': 'list',
                             'docs': 'https://developers-classic.mailerlite.com/reference/activity-of-single-subscriber'},
 'list_subscriber_groups': {'method': 'GET',
                            'path': '/subscribers/{identifier}/groups',
                            'query': [],
                            'body': [],
                            'kind': 'list',
                            'docs': 'https://developers-classic.mailerlite.com/reference/groups-subscriber-belongs-to'},
 'assign_subscriber_groups': {'method': 'POST',
                              'path': '/subscribers/{identifier}/groups',
                              'query': [],
                              'body': ['groups'],
                              'kind': 'confirmation',
                              'docs': 'https://developers-classic.mailerlite.com/reference/subscribersid-or-emailgroups'},
 'list_groups': {'method': 'GET',
                 'path': '/groups',
                 'query': ['limit', 'offset'],
                 'body': [],
                 'kind': 'list',
                 'docs': 'https://developers-classic.mailerlite.com/reference/groups'},
 'get_group': {'method': 'GET',
               'path': '/groups/{id}',
               'query': [],
               'body': [],
               'kind': 'object',
               'docs': 'https://developers-classic.mailerlite.com/reference/single-group'},
 'create_group': {'method': 'POST',
                  'path': '/groups',
                  'query': [],
                  'body': ['name'],
                  'kind': 'object',
                  'docs': 'https://developers-classic.mailerlite.com/reference/create-group'},
 'rename_group': {'method': 'PUT',
                  'path': '/groups/{id}',
                  'query': [],
                  'body': ['name'],
                  'kind': 'object',
                  'docs': 'https://developers-classic.mailerlite.com/reference/rename-group'},
 'delete_group': {'method': 'DELETE',
                  'path': '/groups/{id}',
                  'query': [],
                  'body': [],
                  'kind': 'confirmation',
                  'docs': 'https://developers-classic.mailerlite.com/reference/delete-group'},
 'list_group_subscribers': {'method': 'GET',
                            'path': '/groups/{id}/subscribers',
                            'query': ['limit', 'offset', 'type'],
                            'body': [],
                            'kind': 'list',
                            'docs': 'https://developers-classic.mailerlite.com/reference/subscribers-in-a-group'},
 'add_group_subscriber': {'method': 'POST',
                          'path': '/groups/{id}/subscribers',
                          'query': [],
                          'body': ['email',
                                   'name',
                                   'fields',
                                   'resubscribe',
                                   'autoresponders',
                                   'type'],
                          'kind': 'object',
                          'docs': 'https://developers-classic.mailerlite.com/reference/add-single-subscriber'},
 'remove_group_subscriber': {'method': 'DELETE',
                             'path': '/groups/{id}/subscribers/{subscriber_identifier}',
                             'query': [],
                             'body': [],
                             'kind': 'empty',
                             'docs': 'https://developers-classic.mailerlite.com/reference/remove-subscriber'},
 'list_fields': {'method': 'GET',
                 'path': '/fields',
                 'query': [],
                 'body': [],
                 'kind': 'list',
                 'docs': 'https://developers-classic.mailerlite.com/reference/all-fields'},
 'create_field': {'method': 'POST',
                  'path': '/fields',
                  'query': [],
                  'body': ['title', 'type'],
                  'kind': 'object',
                  'docs': 'https://developers-classic.mailerlite.com/reference/create-field'},
 'update_field': {'method': 'PUT',
                  'path': '/fields/{id}',
                  'query': [],
                  'body': ['title'],
                  'kind': 'object',
                  'docs': 'https://developers-classic.mailerlite.com/reference/update-field'},
 'delete_field': {'method': 'DELETE',
                  'path': '/fields/{id}',
                  'query': [],
                  'body': [],
                  'kind': 'empty',
                  'docs': 'https://developers-classic.mailerlite.com/reference/remove-field'},
 'list_campaigns': {'method': 'GET',
                    'path': '/campaigns/{status}',
                    'query': ['limit', 'offset', 'order'],
                    'body': [],
                    'kind': 'list',
                    'docs': 'https://developers-classic.mailerlite.com/reference/campaigns-by-type'},
 'get_stats': {'method': 'GET',
               'path': '/stats',
               'query': ['timestamp'],
               'body': [],
               'kind': 'object',
               'docs': 'https://developers-classic.mailerlite.com/reference/stats'}}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class MailerLiteClassicNode(WorkflowNode):
    integration_type = "automation-mailerlite-classic"
    connection_evidence = ConnectionEvidence(noun="groups", operation="list_groups", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return MailerLiteClassicFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            return {"status": "error", "error": "Connect a MailerLite Classic API key"}
        op = self.config.config
        route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path = route["path"].format(**{k: quote(str(v), safe="") for k, v in values.items()})
        params = {k: str(values[k]).lower() if isinstance(values[k], bool) else values[k]
                  for k in route["query"] if k in values}
        body = {k: values[k] for k in route["body"] if k in values}
        kwargs = {"params": params} if params else {}
        if route["body"]:
            kwargs["json"] = body
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], BASE_URL + path,
                    headers={"X-MailerLite-ApiKey": credential.api_key, "Accept": "application/json"}, **kwargs)
            if response.status_code == 204 and route["kind"] == "empty":
                return {"status": "success", "deleted": True}
            expected_status = 201 if op.operation == "create_group" else 200
            if response.status_code != expected_status:
                message = "MailerLite Classic request failed"
                try:
                    error = response.json().get("error")
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"]
                except (ValueError, AttributeError):
                    pass
                return {"status": "error", "error": _redact(f"HTTP {response.status_code}: {message}", credential.api_key)[:1000],
                        "http_status": response.status_code}
            if len(response.content) > 10_000_000:
                raise ValueError("Response exceeds the MailerLite Classic JSON size limit")
            data = response.json()
            if isinstance(data, dict) and ("error" in data or "errors" in data):
                return {"status": "error", "error": _redact(str(data.get("error", data.get("errors"))), credential.api_key)[:1000]}
            kind = route["kind"]
            if kind == "empty":
                raise ValueError("Expected deletion confirmation from MailerLite Classic")
            if kind == "list":
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError("Expected a list from MailerLite Classic")
            elif not isinstance(data, dict):
                raise ValueError("Expected an object from MailerLite Classic")
            if kind == "confirmation" and data.get("success") is not True:
                raise ValueError("MailerLite Classic did not confirm the change")
            if kind == "account":
                data = data.get("account")
                if not isinstance(data, dict) or not data.get("id") or not (data.get("email") or data.get("name")):
                    raise ValueError("Expected account identity from MailerLite Classic")
            result = {"status": "success", "data": _redact(data, credential.api_key)}
            if kind == "list" and "limit" in values:
                # A full page only suggests another page; never claim the complete collection.
                result.update(offset=op.offset, limit=op.limit,
                    has_more=len(data) >= op.limit,
                    next_offset=op.offset + op.limit if len(data) >= op.limit else None)
            return result
        except (httpx.HTTPError, ValueError) as exc:
            # Transport errors can include the request headers; do not expose them.
            message = str(exc) if isinstance(exc, ValueError) else "MailerLite Classic request could not be completed"
            return {"status": "error", "error": _redact(message, credential.api_key)[:1000]}

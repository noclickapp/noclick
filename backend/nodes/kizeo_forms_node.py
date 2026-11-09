"""Kizeo Forms REST v3: fixed, single-request operations from its published Swagger.

A supplied API token is sent verbatim in Authorization to the fixed Kizeo host.
List responses are returned as supplied; no undocumented pagination is invented.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://forms.kizeo.com/rest/v3"



class KizeoFormsAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Kizeo Forms API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://kizeo.github.io/kizeo-forms-documentations/docs/restv3/",
            "x-credential-instructions": "Paste your existing Kizeo Forms API token. An administrator can request a token from support@kizeo.com with the company code and administrator or group leader user ID. NoClick sends it directly in the Authorization header. Your token's user permissions determine which forms, data, lists and groups you can access.",
        },
    )
    credential_type: Literal["kizeo_forms_api_token"] = Field("kizeo_forms_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value



class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)



class _Form(_Input):
    form_id: int = Field(..., ge=1, description="Kizeo form ID; use List Forms to find it.")



class _Data(_Form):
    data_id: int = Field(..., ge=1, description="Kizeo submission ID.")



class _List(_Input):
    list_id: int = Field(..., ge=1, description="External list ID; use List Lists to find it.")



class _Group(_Input):
    group_id: int = Field(..., ge=1, description="Group ID; use List Groups to find it.")



class _Action(_Form):
    action: str = Field(..., min_length=1, max_length=200, description="The read/unread action name used by your workflow.")

    @field_validator("action")
    @classmethod
    def action_segment(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use an action name without dot segments or control characters")
        return value



class _Mark(_Action):
    data_ids: list[int] = Field(..., min_length=1, description="Submission IDs to mark for this action.")

    @field_validator("data_ids")
    @classmethod
    def positive_ids(cls, value):
        if any(i < 1 for i in value):
            raise ValueError("Submission IDs must be positive")
        return value



class DataFilter(_Input):
    field: str
    operator: str
    type: str
    val: str



class DataOrder(_Input):
    col: str
    type: str



class PushValue(_Input):
    value: str



class ListFormsConfig(_Input):
    """List all forms accessible to the token user."""
    operation: Literal["list_forms"] = Field("list_forms", json_schema_extra={"ui:hidden": True})


class GetFormConfig(_Form):
    """Get a form definition including its field identifiers."""
    operation: Literal["get_form"] = Field("get_form", json_schema_extra={"ui:hidden": True})


class SearchDataConfig(_Form):
    """Search submissions with the documented advanced filter body."""
    operation: Literal["search_data"] = Field("search_data", json_schema_extra={"ui:hidden": True})
    global_filters: str | None = None
    filters: list[DataFilter] = Field(default_factory=list)
    order: list[DataOrder] = Field(default_factory=list)


class GetDataConfig(_Data):
    """Get one form submission and its field values."""
    operation: Literal["get_data"] = Field("get_data", json_schema_extra={"ui:hidden": True})


class ListUnreadDataConfig(_Action):
    """Read submissions not yet marked for the named action."""
    operation: Literal["list_unread_data"] = Field("list_unread_data", json_schema_extra={"ui:hidden": True})
    limit: int = Field(100, ge=1, le=1000, description="Maximum unread submissions to return.")


class MarkDataReadConfig(_Mark):
    """Mark selected submissions as read for an action."""
    operation: Literal["mark_data_read"] = Field("mark_data_read", json_schema_extra={"ui:hidden": True})


class MarkDataUnreadConfig(_Mark):
    """Mark selected submissions as unread for an action."""
    operation: Literal["mark_data_unread"] = Field("mark_data_unread", json_schema_extra={"ui:hidden": True})


class PushDataConfig(_Form):
    """Send prefilled form data to a user. This sends a push notification."""
    operation: Literal["push_data"] = Field("push_data", json_schema_extra={"ui:hidden": True})
    recipient_user_id: int = Field(..., ge=1, description="Recipient user ID for this push.")
    fields: dict[str, PushValue] = Field(..., description='Form field IDs mapped to objects such as {"value": "text"}.')


class ListPushInboxConfig(_Input):
    """Receive new pushed form data from the inbox."""
    operation: Literal["list_push_inbox"] = Field("list_push_inbox", json_schema_extra={"ui:hidden": True})


class ListExportsConfig(_Form):
    """List the Word and Excel export templates for a form."""
    operation: Literal["list_exports"] = Field("list_exports", json_schema_extra={"ui:hidden": True})


class ListListsConfig(_Input):
    """List accessible external lists."""
    operation: Literal["list_lists"] = Field("list_lists", json_schema_extra={"ui:hidden": True})


class GetListConfig(_List):
    """Get an external list definition with the user filters applied."""
    operation: Literal["get_list"] = Field("get_list", json_schema_extra={"ui:hidden": True})


class GetCompleteListConfig(_List):
    """Get the complete external list without applying user filters."""
    operation: Literal["get_complete_list"] = Field("get_complete_list", json_schema_extra={"ui:hidden": True})


class UpdateListConfig(_List):
    """Replace an external list with the supplied items."""
    operation: Literal["update_list"] = Field("update_list", json_schema_extra={"ui:hidden": True})
    items: list[str] = Field(..., description="Replacement external list items. An empty array clears the list.")


class ListUsersConfig(_Input):
    """List users in the account, subject to the token user permissions."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})


class ListGroupsConfig(_Input):
    """List groups in the account."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})


class GetGroupConfig(_Group):
    """Get one group including its users and leaders."""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})


class CreateGroupConfig(_Input):
    """Create a group with an optional parent group."""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    parent_group_id: int | None = Field(None, ge=1)


class UpdateGroupConfig(_Group):
    """Update the group name and optionally its parent."""
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    parent_group_id: int | None = Field(None, ge=1)


class DeleteGroupConfig(_Group):
    """Delete the selected group."""
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"ui:hidden": True})


class ListGroupUsersConfig(_Group):
    """List users of the selected group."""
    operation: Literal["list_group_users"] = Field("list_group_users", json_schema_extra={"ui:hidden": True})


KizeoFormsConfig = Annotated[Union[
    ListFormsConfig,
    GetFormConfig,
    SearchDataConfig,
    GetDataConfig,
    ListUnreadDataConfig,
    MarkDataReadConfig,
    MarkDataUnreadConfig,
    PushDataConfig,
    ListPushInboxConfig,
    ListExportsConfig,
    ListListsConfig,
    GetListConfig,
    GetCompleteListConfig,
    UpdateListConfig,
    ListUsersConfig,
    ListGroupsConfig,
    GetGroupConfig,
    CreateGroupConfig,
    UpdateGroupConfig,
    DeleteGroupConfig,
    ListGroupUsersConfig
], Field(discriminator="operation")]



class KizeoFormsFullConfig(NodeConfig[KizeoFormsConfig, KizeoFormsAPITokenCredential]):
    pass


ROUTES = {'list_forms': ('GET', '/forms', ()),
 'get_form': ('GET', '/forms/{form_id}', ()),
 'search_data': ('POST', '/forms/{form_id}/data/advanced', ('global_filters', 'filters', 'order')),
 'get_data': ('GET', '/forms/{form_id}/data/{data_id}', ()),
 'list_unread_data': ('GET', '/forms/{form_id}/data/unread/{action}/{limit}', ()),
 'mark_data_read': ('POST', '/forms/{form_id}/markasreadbyaction/{action}', ('data_ids',)),
 'mark_data_unread': ('POST', '/forms/{form_id}/markasunreadbyaction/{action}', ('data_ids',)),
 'push_data': ('POST', '/forms/{form_id}/push', ('recipient_user_id', 'fields')),
 'list_push_inbox': ('GET', '/forms/push/inbox', ()),
 'list_exports': ('GET', '/forms/{form_id}/exports', ()),
 'list_lists': ('GET', '/lists', ()),
 'get_list': ('GET', '/lists/{list_id}', ()),
 'get_complete_list': ('GET', '/lists/{list_id}/complete', ()),
 'update_list': ('PUT', '/lists/{list_id}', ('items',)),
 'list_users': ('GET', '/users', ()),
 'list_groups': ('GET', '/groups', ()),
 'get_group': ('GET', '/group/{group_id}', ()),
 'create_group': ('POST', '/group', ('name', 'parent_group_id')),
 'update_group': ('PUT', '/group/{group_id}', ('name', 'parent_group_id')),
 'delete_group': ('DELETE', '/group/{group_id}', ()),
 'list_group_users': ('GET', '/group/{group_id}/users', ())}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"password", "token", "api_token", "authorization"}}
    return value



class KizeoFormsNode(WorkflowNode):
    integration_type = "automation-kizeo-forms"
    connection_evidence = ConnectionEvidence(noun="forms", operation="list_forms")

    @classmethod
    def get_config_model(cls):
        return KizeoFormsFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, KizeoFormsFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Kizeo Forms API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, template, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        body = {key: values[key] for key in body_fields if key in values} if body_fields else None
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": token, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        # Never retry mutations: a lost response can still mean the write happened.
        if len(response.content) > 10_000_000:
            raise ValueError("Kizeo Forms response exceeds 10 MB")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"Kizeo Forms returned non-JSON (HTTP {response.status_code})") from None
        payload = _redact(payload, token)
        if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and payload.get("status") == "error"):
            message = payload.get("message") if isinstance(payload, dict) else None
            return {"status": "error", "status_code": response.status_code,
                "error": str(message or f"Kizeo Forms request failed (HTTP {response.status_code})")}
        if not isinstance(payload, (dict, list)):
            raise ValueError("Kizeo Forms returned an unexpected JSON value")
        # Keep the provider response intact, including its documented envelopes.
        result = {"status": "success", "operation": config.operation, "data": payload}
        if config.operation == "list_forms":
            rows = payload.get("forms", payload.get("data", payload)) if isinstance(payload, dict) else payload
            if isinstance(rows, dict) and "forms" in rows:
                rows = rows["forms"]
            if isinstance(rows, list):
                result["items"] = rows
            elif isinstance(rows, dict) and "id" in rows:
                result["items"] = [rows]
            else:
                raise ValueError("Kizeo Forms response did not contain forms")
        return result

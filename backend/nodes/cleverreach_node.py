"""CleverReach REST v3: explicit, single-request list and receiver operations.

Contract: https://rest.cleverreach.com/v3/explorer/swagger.json (version 3).
Receiver write bodies follow the provider's unwrapped examples, rather than
its contradictory Swagger `postdata` property. Tokens are supplied by users;
this node does not acquire, refresh, or revoke them.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://rest.cleverreach.com/v3"
TOKEN_TYPE = "cleverreach_access_token"
Identifier = Annotated[str, Field(min_length=1, max_length=320, pattern=r"^[A-Za-z0-9_@.+-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^\s@/]+@[^\s@/]+\.[^\s@/]+$")]
Timestamp = Annotated[int, Field(ge=0, le=253402300799)]


class CleverreachAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="CleverReach Access Token", hide_input_in_errors=True, extra="ignore",
        json_schema_extra={
            "x-credential-url": "https://github.com/CleverReach/php-sdk#quick-start",
            "x-credential-instructions": "In CleverReach, open My Account → Interfaces → REST API and use Test process now to get an API token, then paste it here. NoClick sends it as a Bearer token to rest.cleverreach.com. Use a token with access to the lists and actions you need. If it expires, replace it with a new token; NoClick does not refresh pasted tokens.",
        })
    credential_type: Literal["cleverreach_access_token"] = Field(TOKEN_TYPE, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the access token")
        value = clean_secret(value, field_name="Access token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(0, ge=0, le=10000, description="Zero-based page. Each run retrieves one page.")
    pagesize: int = Field(50, ge=1, le=100)


class ListGroups(_Page):
    """List the account's receiver lists; also used to prove the connection."""
    operation: Literal["list_groups"] = "list_groups"
    search: Text | None = None
    order: Literal["created ASC", "created DESC", "changed ASC", "changed DESC"] | None = None


class _Group(_Input):
    group_id: Identifier


class GetGroup(_Group):
    operation: Literal["get_group"] = "get_group"


class GetGroupStats(_Group):
    operation: Literal["get_group_stats"] = "get_group_stats"


class DeleteGroup(_Group):
    """Permanently delete the selected receiver list."""
    operation: Literal["delete_group"] = "delete_group"


class _GroupFields(_Input):
    name: Text
    receiver_info: str | None = Field(None, max_length=4000)
    locked: bool | None = None
    backup: bool | None = None


class CreateGroup(_GroupFields):
    operation: Literal["create_group"] = "create_group"


class UpdateGroup(_GroupFields):
    operation: Literal["update_group"] = "update_group"
    group_id: Identifier


class ListReceivers(_Page, _Group):
    operation: Literal["list_receivers"] = "list_receivers"
    type: Literal["all", "active", "inactive", "bounce", "softbounce", "hardbounce"] = "all"
    email_list: str | None = Field(None, max_length=4000, description="Comma-separated receiver email addresses to find.")
    detail: int = Field(0, ge=0, le=7, description="Bit mask: events=1, orders=2, tags=4.")


class _Receiver(_Input):
    receiver_id: Identifier = Field(..., description="Receiver ID or email address.")


class GetReceiver(_Receiver):
    operation: Literal["get_receiver"] = "get_receiver"


class GetGroupReceiver(_Receiver, _Group):
    operation: Literal["get_group_receiver"] = "get_group_receiver"


class DeleteReceiver(_Receiver, _Group):
    """Remove the receiver from the selected list only."""
    operation: Literal["delete_receiver"] = "delete_receiver"


class DeactivateReceiver(_Receiver, _Group):
    operation: Literal["deactivate_receiver"] = "deactivate_receiver"


class _ReceiverFields(_Group):
    source: Text | None = None
    attributes: dict[str, str] | None = Field(None, description="List-specific attribute names and values.")
    global_attributes: dict[str, str] | None = Field(None, description="Global attribute names and values.")


class CreateReceiver(_ReceiverFields):
    """Add a receiver. Supply only recipients whose consent you have recorded.

    Omitting registered/activated activates the receiver immediately, as the
    provider documents. This action does not send a double opt-in email.
    """
    operation: Literal["create_receiver"] = "create_receiver"
    email: Email
    registered: Timestamp | None = None
    activated: Timestamp | None = None
    deactivated: Timestamp | None = None
    check_blacklist: bool = True


class UpdateReceiver(_ReceiverFields, _Receiver):
    """Update receiver profile attributes without changing email or subscription state."""
    operation: Literal["update_receiver"] = "update_receiver"

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, key) is None for key in ("source", "attributes", "global_attributes")):
            raise ValueError("Supply source or receiver attributes to update")
        return self


class GetReceiverTags(_Receiver):
    operation: Literal["get_receiver_tags"] = "get_receiver_tags"


class AddReceiverTags(_Receiver):
    """Add tags; a group ID is required by CleverReach to trigger THEA automations."""
    operation: Literal["add_receiver_tags"] = "add_receiver_tags"
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(..., min_length=1, max_length=100)
    group_id: Identifier | None = None


class GetReceiverGroups(_Receiver):
    operation: Literal["get_receiver_groups"] = "get_receiver_groups"
    state: Literal["all", "active", "inactive"] = "all"


class ListTags(_Input):
    operation: Literal["list_tags"] = "list_tags"
    group_id: Identifier | None = None
    origin: str | None = Field(None, max_length=50)
    order_by: Literal["tag", "origin", "count"] = "tag"
    limit: int = Field(20, ge=1, le=100)
    page: int = Field(0, ge=0, le=10000)


class ListMailings(_Input):
    operation: Literal["list_mailings"] = "list_mailings"
    state: Literal["finished", "draft", "waiting", "running", "automation"] = "draft"
    limit: int = Field(25, ge=1, le=100)
    page: int = Field(0, ge=0, le=10000)
    omit_body: bool = True


class GetMailing(_Input):
    operation: Literal["get_mailing"] = "get_mailing"
    mailing_id: Identifier


class ListReports(_Page):
    operation: Literal["list_reports"] = "list_reports"
    group_id: Identifier | None = None
    mode: Literal["full", "basic"] = "full"


class GetReport(_Input):
    operation: Literal["get_report"] = "get_report"
    report_id: Identifier


CleverreachConfig = Annotated[Union[
    ListGroups, GetGroup, CreateGroup, UpdateGroup, DeleteGroup, GetGroupStats,
    ListReceivers, GetGroupReceiver, CreateReceiver, UpdateReceiver, DeleteReceiver,
    DeactivateReceiver, GetReceiver, GetReceiverTags, AddReceiverTags, GetReceiverGroups,
    ListTags, ListMailings, GetMailing, ListReports, GetReport,
], Field(discriminator="operation")]


class CleverreachNodeConfig(NodeConfig[CleverreachConfig, CleverreachAccessTokenCredential]):
    pass


# Each user operation maps to exactly one published HTTP operation.
ROUTES = {
    "list_groups": ("GET", "/groups"),
    "get_group": ("GET", "/groups/{group_id}"),
    "create_group": ("POST", "/groups"),
    "update_group": ("PUT", "/groups/{group_id}"),
    "delete_group": ("DELETE", "/groups/{group_id}"),
    "get_group_stats": ("GET", "/groups/{group_id}/stats"),
    "list_receivers": ("GET", "/groups/{group_id}/receivers"),
    "get_group_receiver": ("GET", "/groups/{group_id}/receivers/{receiver_id}"),
    "create_receiver": ("POST", "/groups/{group_id}/receivers"),
    "update_receiver": ("PUT", "/groups/{group_id}/receivers/{receiver_id}"),
    "delete_receiver": ("DELETE", "/groups/{group_id}/receivers/{receiver_id}"),
    "deactivate_receiver": ("PUT", "/groups/{group_id}/receivers/{receiver_id}/deactivate"),
    "get_receiver": ("GET", "/receivers/{receiver_id}"),
    "get_receiver_tags": ("GET", "/receivers/{receiver_id}/tags"),
    "add_receiver_tags": ("POST", "/receivers/{receiver_id}/tags"),
    "get_receiver_groups": ("GET", "/receivers/{receiver_id}/groups"),
    "list_tags": ("GET", "/tags"),
    "list_mailings": ("GET", "/mailings"),
    "get_mailing": ("GET", "/mailings/{mailing_id}"),
    "list_reports": ("GET", "/reports"),
    "get_report": ("GET", "/reports/{report_id}"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class CleverreachNode(WorkflowNode):
    integration_type = "automation-cleverreach"
    connection_evidence = ConnectionEvidence(noun="receiver lists", operation="list_groups", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return CleverreachNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CleverReach access token")
        op = self.config.config
        token = self.config.credentials.access_token
        method, path = ROUTES[op.operation]
        fields = op.model_dump(exclude={"operation"}, exclude_none=True)
        for key in ("group_id", "receiver_id", "mailing_id", "report_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(fields.pop(key)), safe=""))
        params, body = {}, None
        if method == "GET":
            params = fields
        elif fields:
            if isinstance(op, CreateReceiver):
                params["check_blacklist"] = fields.pop("check_blacklist")
            body = fields
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("CleverReach request could not be confirmed. Inspect write results before retrying.") from None
        if len(response.content) > 8_000_000:
            raise ValueError("CleverReach response exceeds the supported size")
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        try:
            payload = response.json() if response.content and (mime == "application/json" or mime.endswith("+json")) else None
        except ValueError:
            raise ValueError("CleverReach returned invalid JSON") from None
        if response.status_code not in {200, 201, 202, 204}:
            # Preserve the provider's rejection text for the shared connect seam.
            detail = payload.get("message") or payload.get("error") if isinstance(payload, dict) else payload
            result = {"status": "error", "http_status": response.status_code,
                "message": detail if isinstance(detail, str) else "CleverReach request rejected"}
        else:
            if response.status_code != 204 and payload is None:
                raise ValueError("Expected a JSON response from CleverReach")
            if payload is False or (isinstance(payload, dict) and (payload.get("error") or payload.get("success") is False)):
                result = {"status": "error", "http_status": response.status_code,
                    "message": (payload.get("message") or payload.get("error") if isinstance(payload, dict) else None) or "CleverReach reported an error"}
            else:
                result = {"status": "success", "http_status": response.status_code, "data": payload}
                if isinstance(op, (_Page, ListTags, ListMailings)):
                    size = getattr(op, "pagesize", getattr(op, "limit", 50))
                    # A full page is only a hint. Do not claim an exact total.
                    result["pagination"] = {"page": op.page, "page_size": size,
                        "next_page": op.page + 1 if isinstance(payload, list) and len(payload) >= size and op.page < 10000 else None,
                        "complete": False}
                if method != "GET":
                    result["write_acknowledged"] = True
                    result["readback_verified"] = False
        result = _redact(result, token)
        await self.emit(result)
        return result

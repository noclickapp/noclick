"""KlickTipp Management API operations using a temporary API-user session.

Each public operation maps to one published endpoint. Login and logout are
transport concerns; session cookies never enter workflow output or storage.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import re
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.klicktipp.com"


class KlickTippCredential(BaseModel):
    model_config = ConfigDict(title="KlickTipp API User", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-instructions": "Requires KlickTipp Premium or higher. Create a dedicated API User under My Account → Settings → User Account → Sub-Accounts, then enter its username and password. NoClick logs in for each operation and logs out afterward; sessions are never saved.",
            "x-credential-url": "https://developers.klicktipp.com/guides/management-api-authentication",
        })
    credential_type: Literal["klicktipp_api_user"] = Field("klicktipp_api_user", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, title="API user username", description="The dedicated API User, such as mainaccount-subaccountname.")
    password: str = Field(..., min_length=1, title="API user password", json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_values(self):
        for name in ("subscriberid", "fieldid"):
            value = getattr(self, name, None)
            if value is not None and not re.fullmatch(r"[A-Za-z0-9]+", value):
                raise ValueError(f"{name} must be a single KlickTipp identifier")
        for name in ("email", "newemail"):
            value = getattr(self, name, None)
            if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                raise ValueError(f"{name} must be an email address")
        return self


class KlickTippListContactsConfig(_Input):
    """GET /subscriber."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    status: str | None = Field(None, pattern=r"^(subscribed|pending|unsubscribed)(,(subscribed|pending|unsubscribed))*$")
    bounceStatus: str | None = Field(None, pattern=r"^(hardbounce|softbounce|spambounce|nobounce)(,(hardbounce|softbounce|spambounce|nobounce))*$")
    limit: int = Field(100, ge=1, le=500, description="Page size. Pass nextCursor from the response as cursor for the next page.")
    cursor: str | None = None

class KlickTippGetContactsConfig(_Input):
    """GET /subscriber/bulk/{subscriberids}."""
    operation: Literal["get_contacts"] = Field("get_contacts", json_schema_extra={"ui:hidden": True})
    subscriberids: str = Field(..., pattern=r"^[1-9][0-9]*(,[1-9][0-9]*){0,199}$", description="Up to 200 comma-separated numeric contact IDs.")

class KlickTippListChangedContactsConfig(_Input):
    """GET /subscriber/changed."""
    operation: Literal["list_changed_contacts"] = Field("list_changed_contacts", json_schema_extra={"ui:hidden": True})
    from_timestamp: int = Field(0, ge=0, description="Inclusive Unix timestamp in seconds.")
    cursor: str | None = None
    limit: int = Field(100, ge=1, le=200)

class KlickTippGetContactConfig(_Input):
    """GET /subscriber/{subscriberid}."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    subscriberid: str = Field(..., min_length=1)

class KlickTippCreateOrUpdateContactConfig(_Input):
    """POST /subscriber."""
    operation: Literal["create_or_update_contact"] = Field("create_or_update_contact", json_schema_extra={"ui:hidden": True})
    email: str | None = None
    smsnumber: str | None = None
    listid: int | None = Field(None, ge=1, description="Opt-in process ID. Omitting this triggers the default double opt-in and may email the contact.")
    tagid: int | None = Field(None, ge=1)
    fields: dict[str, str] | None = Field(None, description="KlickTipp field names and string values; date/time fields use Unix seconds.")

    @model_validator(mode="after")
    def require_contact(self):
        if not self.email and not self.smsnumber:
            raise ValueError("Enter an email address or SMS number")
        return self

class KlickTippUpdateContactConfig(_Input):
    """PUT /subscriber/{subscriberid}."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    subscriberid: str = Field(..., min_length=1)
    newemail: str | None = None
    newsmsnumber: str | None = None
    fields: dict[str, str] | None = None

class KlickTippDeleteContactConfig(_Input):
    """DELETE /subscriber/{subscriberid}."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    subscriberid: str = Field(..., min_length=1, description="Permanently delete this contact.")

class KlickTippUnsubscribeContactConfig(_Input):
    """POST /subscriber/unsubscribe."""
    operation: Literal["unsubscribe_contact"] = Field("unsubscribe_contact", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)

class KlickTippTagContactConfig(_Input):
    """POST /subscriber/tag."""
    operation: Literal["tag_contact"] = Field("tag_contact", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    tagids: list[int] = Field(..., min_length=1)

class KlickTippUntagContactConfig(_Input):
    """POST /subscriber/untag."""
    operation: Literal["untag_contact"] = Field("untag_contact", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    tagid: int = Field(..., ge=1)

class KlickTippSearchContactConfig(_Input):
    """POST /subscriber/search."""
    operation: Literal["search_contact"] = Field("search_contact", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)

class KlickTippSearchTaggedContactsConfig(_Input):
    """POST /subscriber/tagged."""
    operation: Literal["search_tagged_contacts"] = Field("search_tagged_contacts", json_schema_extra={"ui:hidden": True})
    tagid: int = Field(..., ge=1)
    status: list[Literal["subscribed", "pending", "unsubscribed"]] = Field(default_factory=lambda: ["subscribed"])
    bounceStatus: list[Literal["hardbounce", "softbounce", "spambounce", "nobounce"]] = Field(default_factory=lambda: ["softbounce", "spambounce", "nobounce"])

class KlickTippListTagsConfig(_Input):
    """GET /tag."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})

class KlickTippGetTagConfig(_Input):
    """GET /tag/{tagid}."""
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra={"ui:hidden": True})
    tagid: int = Field(..., ge=1)

class KlickTippCreateTagConfig(_Input):
    """POST /tag."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    text: str | None = None

class KlickTippUpdateTagConfig(_Input):
    """PUT /tag/{tagid}."""
    operation: Literal["update_tag"] = Field("update_tag", json_schema_extra={"ui:hidden": True})
    tagid: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1)
    text: str | None = None

class KlickTippDeleteTagConfig(_Input):
    """DELETE /tag/{tagid}."""
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"ui:hidden": True})
    tagid: int = Field(..., ge=1)

class KlickTippListFieldsConfig(_Input):
    """GET /field."""
    operation: Literal["list_fields"] = Field("list_fields", json_schema_extra={"ui:hidden": True})
    detail: bool = False

class KlickTippGetFieldConfig(_Input):
    """GET /field/{fieldid}."""
    operation: Literal["get_field"] = Field("get_field", json_schema_extra={"ui:hidden": True})
    fieldid: str = Field(..., min_length=1, description="Unprefixed field ID, for example 12345.")
    detail: bool = False

class KlickTippCreateFieldConfig(_Input):
    """POST /field/create."""
    operation: Literal["create_field"] = Field("create_field", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=250)
    type: Literal["field-single", "field-paragraph", "field-email", "field-number", "field-url", "field-date", "field-time", "field-datetime", "field-html", "field-decimal"] = Field(...)
    multidimensional: bool = True
    ai_description: str | None = Field(None, max_length=2000)

class KlickTippListOptinProcessesConfig(_Input):
    """GET /list."""
    operation: Literal["list_optin_processes"] = Field("list_optin_processes", json_schema_extra={"ui:hidden": True})
    detail: bool = False

class KlickTippGetOptinProcessConfig(_Input):
    """GET /list/{listid}."""
    operation: Literal["get_optin_process"] = Field("get_optin_process", json_schema_extra={"ui:hidden": True})
    listid: int = Field(..., ge=1)

class KlickTippSearchRedirectUrlConfig(_Input):
    """POST /list/redirect."""
    operation: Literal["search_redirect_url"] = Field("search_redirect_url", json_schema_extra={"ui:hidden": True})
    listid: str = Field(..., pattern=r"^[0-9]+$")
    email: str = Field(..., min_length=1)

KlickTippConfig = Annotated[Union[
    KlickTippListContactsConfig,
    KlickTippGetContactsConfig,
    KlickTippListChangedContactsConfig,
    KlickTippGetContactConfig,
    KlickTippCreateOrUpdateContactConfig,
    KlickTippUpdateContactConfig,
    KlickTippDeleteContactConfig,
    KlickTippUnsubscribeContactConfig,
    KlickTippTagContactConfig,
    KlickTippUntagContactConfig,
    KlickTippSearchContactConfig,
    KlickTippSearchTaggedContactsConfig,
    KlickTippListTagsConfig,
    KlickTippGetTagConfig,
    KlickTippCreateTagConfig,
    KlickTippUpdateTagConfig,
    KlickTippDeleteTagConfig,
    KlickTippListFieldsConfig,
    KlickTippGetFieldConfig,
    KlickTippCreateFieldConfig,
    KlickTippListOptinProcessesConfig,
    KlickTippGetOptinProcessConfig,
    KlickTippSearchRedirectUrlConfig,
], Field(discriminator="operation")]


class KlickTippFullConfig(NodeConfig[KlickTippConfig, KlickTippCredential]):
    pass


# Fixed routes keep config data out of the API origin and method.
ROUTES = {
    "list_contacts": ('GET', '/subscriber', ('status', 'bounceStatus', 'limit', 'cursor')),
    "get_contacts": ('GET', '/subscriber/bulk/{subscriberids}', ()),
    "list_changed_contacts": ('GET', '/subscriber/changed', ('from_timestamp', 'cursor', 'limit')),
    "get_contact": ('GET', '/subscriber/{subscriberid}', ()),
    "create_or_update_contact": ('POST', '/subscriber', ()),
    "update_contact": ('PUT', '/subscriber/{subscriberid}', ()),
    "delete_contact": ('DELETE', '/subscriber/{subscriberid}', ()),
    "unsubscribe_contact": ('POST', '/subscriber/unsubscribe', ()),
    "tag_contact": ('POST', '/subscriber/tag', ()),
    "untag_contact": ('POST', '/subscriber/untag', ()),
    "search_contact": ('POST', '/subscriber/search', ()),
    "search_tagged_contacts": ('POST', '/subscriber/tagged', ()),
    "list_tags": ('GET', '/tag', ()),
    "get_tag": ('GET', '/tag/{tagid}', ()),
    "create_tag": ('POST', '/tag', ()),
    "update_tag": ('PUT', '/tag/{tagid}', ()),
    "delete_tag": ('DELETE', '/tag/{tagid}', ()),
    "list_fields": ('GET', '/field', ('detail',)),
    "get_field": ('GET', '/field/{fieldid}', ('detail',)),
    "create_field": ('POST', '/field/create', ()),
    "list_optin_processes": ('GET', '/list', ('detail',)),
    "get_optin_process": ('GET', '/list/{listid}', ()),
    "search_redirect_url": ('POST', '/list/redirect', ()),
}


def _response(response):
    if not 200 <= response.status_code < 300:
        # Preserve the provider's rejection for the shared connection verdict.
        raise ValueError(f"KlickTipp HTTP {response.status_code}: {response.text[:2000]}")
    try:
        body = response.json()
    except ValueError:
        raise ValueError("KlickTipp returned a non-JSON response") from None
    if isinstance(body, dict) and (body.get("error") or body.get("errors")):
        raise ValueError(str(body.get("error") or body.get("errors")))
    return body


class KlickTippNode(WorkflowNode):
    integration_type = "automation-klicktipp"
    connection_evidence = ConnectionEvidence(noun="tags", operation="list_tags")

    @classmethod
    def get_config_model(cls):
        return KlickTippFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a KlickTipp API User")
        config = self.config.config
        method, route, query_fields = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for field in re.findall(r"\{([^}]+)\}", route):
            route = route.replace("{" + field + "}", str(values.pop(field)))
        params = {("from" if k == "from_timestamp" else k): values.pop(k)
                  for k in query_fields if k in values}
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            session = _response(await client.post(BASE_URL + "/account/login", json={
                "username": credential.username, "password": credential.password,
            }, headers={"Accept": "application/json"}))
            if not isinstance(session, dict):
                raise ValueError("KlickTipp login did not return a session")
            name, sessid = session.get("session_name"), session.get("sessid")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", name) or not isinstance(sessid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sessid):
                raise ValueError("KlickTipp login did not return a valid session cookie")
            headers = {"Accept": "application/json", "Cookie": name + "=" + sessid}
            try:
                response = await client.request(method, BASE_URL + route, params=params,
                    headers=headers, **({"json": values} if method in {"POST", "PUT"} else {}))
                body = _response(response)
            finally:
                # Cleanup never hides the original operation result or rejection.
                try:
                    await client.post(BASE_URL + "/account/logout", headers=headers)
                except httpx.HTTPError:
                    pass
        result = {"data": body}
        if config.operation == "list_tags":
            if not isinstance(body, dict) or any(not isinstance(v, str) for v in body.values()):
                raise ValueError("KlickTipp returned an invalid tag map")
            result["items"] = [{"id": key, "name": value} for key, value in body.items()]
        await self.emit(result)
        return result

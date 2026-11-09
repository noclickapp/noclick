"""SlickText new-platform API: one documented request per operation.

Lists return one page. Campaign acceptance never establishes SMS delivery.
Writes are not retried automatically; use the legacy API for legacy accounts.
"""
from typing import Annotated, Literal, Optional, Union
from datetime import datetime
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://dev.slicktext.com/v1"
Id = Annotated[int, Field(gt=0)]


class SlickTextAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SlickText API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.slicktext.com/docs/v2/overview#authorization",
            "x-credential-instructions": "In your SlickText dashboard, open the menu beside your name → Settings → API & Webhooks → API Keys → Create API Key. Copy the key when shown and paste it here. Use a key for the new SlickText platform; legacy accounts use a different API. The brand read checks your key and returns the brand ID needed by other operations.",
        })
    credential_type: Literal["slicktext_api_key"] = Field("slicktext_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Brand(_Input):
    brand_id: Id = Field(..., description="Brand ID returned by Get brand.")


class _Page(_Brand):
    limit: int = Field(50, ge=1, le=250, description="One page only. Use next_offset for the next request.")
    offset: int = Field(0, ge=0)


class _ContactId(_Brand):
    contact_id: Id


class _ListId(_Brand):
    list_id: Id


class _CampaignId(_Brand):
    campaign_id: Id


class _ContactFields(_Brand):
    mobile_number: Optional[str] = Field(None, pattern=r"^\+?[0-9]{10,15}$", description="US phone number including country code.")
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = Field(None, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    birthdate: Optional[str] = Field(None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[Literal["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"]] = None
    language: Optional[str] = None
    opt_in_status: Optional[Literal["not subscribed", "subscribed", "unsubscribed", "blocked"]] = Field(None,
        description="Set subscribed only for contacts who explicitly consented to text messages.")
    custom_fields: Optional[dict[str, Union[str, int, float, bool]]] = Field(None,
        description="Internal custom field names and values; sent as top-level request fields.")

    @field_validator("birthdate")
    @classmethod
    def date(cls, value):
        if value is not None:
            datetime.strptime(value, "%Y-%m-%d")
        return value

    @field_validator("custom_fields")
    @classmethod
    def custom(cls, value):
        if value is not None and set(value) & (set(cls.model_fields) | {"operation"}):
            raise ValueError("Custom fields cannot replace built-in fields")
        return value


class _ListFields(_Brand):
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None


class SlickTextAudience(_Input):
    segments: Optional[list[Id]] = Field(None, min_length=1)
    contact_lists: Optional[list[Id]] = Field(None, min_length=1)

    @model_validator(mode="after")
    def audience(self):
        if not (self.segments or self.contact_lists):
            raise ValueError("Choose audience segments or lists")
        return self


class _CampaignFields(_Brand):
    name: Optional[str] = Field(None, min_length=1)
    body: Optional[str] = Field(None, min_length=1)
    media_url: Optional[str] = Field(None, pattern=r"^https?://[^\s]+$")
    status: Optional[Literal["draft", "scheduled", "send"]] = Field(None,
        description="send submits immediately and can incur charges; delivery is not verified.")
    scheduled: Optional[str] = Field(None, description="Provider date/time YYYY-MM-DD HH:MM:SS.")
    audience: Optional[SlickTextAudience] = None

    @field_validator("scheduled")
    @classmethod
    def time(cls, value):
        if value is not None:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value

    @model_validator(mode="after")
    def schedule(self):
        if self.status == "scheduled" and self.scheduled is None:
            raise ValueError("A scheduled campaign requires a send time")
        return self


class SlickTextListMembership(_Input):
    contact_id: Id
    lists: list[Id] = Field(..., min_length=1)


class _Membership(_Brand):
    contacts: list[SlickTextListMembership] = Field(..., min_length=1,
        description="Each contact ID and its list IDs. One documented bulk request.")


class SlickTextGetBrandConfig(_Input):
    """Get brand."""
    operation: Literal["get_brand"] = Field("get_brand", json_schema_extra={"ui:hidden": True})


class SlickTextGetBrandUsageConfig(_Brand):
    """Get brand usage."""
    operation: Literal["get_brand_usage"] = Field("get_brand_usage", json_schema_extra={"ui:hidden": True})


class SlickTextListContactsConfig(_Page):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})


class SlickTextGetContactConfig(_ContactId):
    """Get contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class SlickTextCreateContactConfig(_ContactFields):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    mobile_number: str = Field(..., pattern=r"^\+?[0-9]{10,15}$")
    force_double_opt_in: Optional[bool] = None


class SlickTextUpdateContactConfig(_ContactFields):
    """Update contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: Id

    @model_validator(mode="after")
    def changes(self):
        changes = self.model_dump(exclude_none=True, exclude={"operation", "brand_id", "contact_id"})
        if not changes or changes == {"custom_fields": {}}:
            raise ValueError("Provide at least one field to update")
        return self


class SlickTextDeleteContactConfig(_ContactId):
    """Delete contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class SlickTextListListsConfig(_Page):
    """List lists."""
    operation: Literal["list_lists"] = Field("list_lists", json_schema_extra={"ui:hidden": True})


class SlickTextGetListConfig(_ListId):
    """Get list."""
    operation: Literal["get_list"] = Field("get_list", json_schema_extra={"ui:hidden": True})


class SlickTextCreateListConfig(_ListFields):
    """Create list."""
    operation: Literal["create_list"] = Field("create_list", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class SlickTextUpdateListConfig(_ListFields):
    """Update list."""
    operation: Literal["update_list"] = Field("update_list", json_schema_extra={"ui:hidden": True})
    list_id: Id

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "brand_id", "list_id"}):
            raise ValueError("Provide at least one field to update")
        return self


class SlickTextDeleteListConfig(_ListId):
    """Delete list."""
    operation: Literal["delete_list"] = Field("delete_list", json_schema_extra={"ui:hidden": True})


class SlickTextListCampaignsConfig(_Page):
    """List campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})


class SlickTextGetCampaignConfig(_CampaignId):
    """Get campaign."""
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"ui:hidden": True})


class SlickTextCreateCampaignConfig(_CampaignFields):
    """Create campaign."""
    operation: Literal["create_campaign"] = Field("create_campaign", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    status: Literal["draft", "scheduled", "send"] = "draft"
    audience: SlickTextAudience


class SlickTextUpdateCampaignConfig(_CampaignFields):
    """Update campaign. Only unsent campaigns can be edited."""
    operation: Literal["update_campaign"] = Field("update_campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: Id

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set - {"operation", "brand_id", "campaign_id"}:
            raise ValueError("Provide at least one field to update")
        return self


class SlickTextDeleteCampaignConfig(_CampaignId):
    """Delete campaign. Only unsent campaigns can be deleted."""
    operation: Literal["delete_campaign"] = Field("delete_campaign", json_schema_extra={"ui:hidden": True})


class SlickTextGetListContactCountConfig(_ListId):
    """Get list contact count."""
    operation: Literal["get_list_contact_count"] = Field("get_list_contact_count", json_schema_extra={"ui:hidden": True})


class SlickTextListListContactsConfig(_Page):
    """List list contacts."""
    operation: Literal["list_list_contacts"] = Field("list_list_contacts", json_schema_extra={"ui:hidden": True})
    list_id: Id


class SlickTextAddContactsToListsConfig(_Membership):
    """Add contacts to lists."""
    operation: Literal["add_contacts_to_lists"] = Field("add_contacts_to_lists", json_schema_extra={"ui:hidden": True})


class SlickTextRemoveContactsFromListsConfig(_Membership):
    """Remove contacts from lists."""
    operation: Literal["remove_contacts_from_lists"] = Field("remove_contacts_from_lists", json_schema_extra={"ui:hidden": True})


class SlickTextListMessagesConfig(_Page):
    """List messages."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})


class SlickTextListKeywordsConfig(_Page):
    """List keywords."""
    operation: Literal["list_keywords"] = Field("list_keywords", json_schema_extra={"ui:hidden": True})


class SlickTextGetKeywordConfig(_Brand):
    """Get keyword."""
    operation: Literal["get_keyword"] = Field("get_keyword", json_schema_extra={"ui:hidden": True})
    keyword_id: Id


SlickTextConfig = Annotated[Union[
    SlickTextGetBrandConfig,
    SlickTextGetBrandUsageConfig,
    SlickTextListContactsConfig,
    SlickTextGetContactConfig,
    SlickTextCreateContactConfig,
    SlickTextUpdateContactConfig,
    SlickTextDeleteContactConfig,
    SlickTextListListsConfig,
    SlickTextGetListConfig,
    SlickTextCreateListConfig,
    SlickTextUpdateListConfig,
    SlickTextDeleteListConfig,
    SlickTextListCampaignsConfig,
    SlickTextGetCampaignConfig,
    SlickTextCreateCampaignConfig,
    SlickTextUpdateCampaignConfig,
    SlickTextDeleteCampaignConfig,
    SlickTextGetListContactCountConfig,
    SlickTextListListContactsConfig,
    SlickTextAddContactsToListsConfig,
    SlickTextRemoveContactsFromListsConfig,
    SlickTextListMessagesConfig,
    SlickTextListKeywordsConfig,
    SlickTextGetKeywordConfig,
], Field(discriminator="operation")]


class SlickTextNodeConfig(NodeConfig[SlickTextConfig, SlickTextAPIKeyCredential]):
    pass


ROUTES = {
    'get_brand': ('GET', '/brands'),
    'get_brand_usage': ('GET', '/brands/{brand_id}/usage'),
    'list_contacts': ('GET', '/brands/{brand_id}/contacts'),
    'get_contact': ('GET', '/brands/{brand_id}/contacts/{contact_id}'),
    'create_contact': ('POST', '/brands/{brand_id}/contacts'),
    'update_contact': ('PUT', '/brands/{brand_id}/contacts/{contact_id}'),
    'delete_contact': ('DELETE', '/brands/{brand_id}/contacts/{contact_id}'),
    'list_lists': ('GET', '/brands/{brand_id}/lists'),
    'get_list': ('GET', '/brands/{brand_id}/lists/{list_id}'),
    'create_list': ('POST', '/brands/{brand_id}/lists'),
    'update_list': ('PUT', '/brands/{brand_id}/lists/{list_id}'),
    'delete_list': ('DELETE', '/brands/{brand_id}/lists/{list_id}'),
    'list_campaigns': ('GET', '/brands/{brand_id}/campaigns'),
    'get_campaign': ('GET', '/brands/{brand_id}/campaigns/{campaign_id}'),
    'create_campaign': ('POST', '/brands/{brand_id}/campaigns'),
    'update_campaign': ('PUT', '/brands/{brand_id}/campaigns/{campaign_id}'),
    'delete_campaign': ('DELETE', '/brands/{brand_id}/campaigns/{campaign_id}'),
    'get_list_contact_count': ('GET', '/brands/{brand_id}/lists/{list_id}/contacts/count'),
    'list_list_contacts': ('GET', '/brands/{brand_id}/lists/{list_id}/contacts'),
    'add_contacts_to_lists': ('POST', '/brands/{brand_id}/lists/contacts'),
    'remove_contacts_from_lists': ('DELETE', '/brands/{brand_id}/lists/contacts'),
    'list_messages': ('GET', '/brands/{brand_id}/messages'),
    'list_keywords': ('GET', '/brands/{brand_id}/keywords'),
    'get_keyword': ('GET', '/brands/{brand_id}/keywords/{keyword_id}'),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class SlickTextNode(WorkflowNode):
    integration_type = "automation-slicktext"
    connection_evidence = ConnectionEvidence(noun="SlickText brand", identity_operation="get_brand", identity_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return SlickTextNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SlickText API key")
        config = self.config.config
        token = self.config.credentials.api_key
        method, route = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        if isinstance(config, _CampaignFields):
            for name in ("media_url", "scheduled"):
                if name in config.model_fields_set:
                    values[name] = getattr(config, name)
        for name in tuple(values):
            marker = "{" + name + "}"
            if marker in route:
                route = route.replace(marker, str(values.pop(name)))
        params = {name: values.pop(name) for name in ("limit", "offset") if name in values}
        if isinstance(config, _ContactFields):
            custom = values.pop("custom_fields", None)
            if custom:
                values.update(custom)
        payload = values["contacts"] if isinstance(config, _Membership) else values
        kwargs = {"params": params}
        if method != "GET" and payload:
            kwargs["json"] = payload
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, headers=headers, **kwargs)
        except httpx.TransportError:
            raise ValueError("SlickText request did not complete" +
                ("; the write outcome is unknown, inspect before retrying" if method != "GET" else "")) from None
        if response.status_code != 200:
            raise ValueError(f"SlickText HTTP {response.status_code}: " + response.text.replace(token, "[redacted]")[:1000])
        if len(response.content) > 10_000_000:
            raise ValueError("SlickText response exceeds the supported JSON size; inspect writes before retrying")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("SlickText returned invalid JSON; inspect writes before retrying") from None
        if isinstance(body, dict) and ("error" in body or body.get("errors")):
            raise ValueError("SlickText: " + str(_redact(body, token))[:1000])
        output = {"status": "success", "data": body, "http_status": response.status_code}
        if isinstance(config, _Page):
            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise ValueError("SlickText returned an invalid collection")
            paging = body.get("pagingData")
            if not isinstance(paging, dict) or type(paging.get("hasMore")) is not bool:
                raise ValueError("SlickText pagination is missing")
            more = paging["hasMore"]
            if more and not body["data"]:
                raise ValueError("SlickText returned an empty nonterminal page")
            output.update(complete=not more, next_offset=config.offset + len(body["data"]) if more else None)
        elif config.operation.startswith("delete_"):
            if body != []:
                raise ValueError("SlickText did not acknowledge deletion; inspect before retrying")
            output["deletion_acknowledged"] = True
        elif config.operation == "get_list_contact_count":
            # The published Lists example is a JSON integer, despite the OpenAPI object schema.
            if type(body) is not int or body < 0:
                raise ValueError("SlickText returned an invalid contact count")
        elif not isinstance(body, dict):
            raise ValueError("SlickText returned an unexpected JSON shape; inspect writes before retrying")
        if config.operation == "get_brand":
            if not isinstance(body.get("name"), str) or not body["name"] or type(body.get("brand_id")) is not int:
                raise ValueError("SlickText brand identity is missing")
        if config.operation in {"create_campaign", "update_campaign"}:
            output["delivery_verified"] = False
        output = _redact(output, token)
        await self.emit(output)
        return output

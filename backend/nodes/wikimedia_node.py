"""Wikimedia structured data through the Wikibase REST API (OpenAPI 1.6).

Wikidata is the default wiki. Owner-only OAuth2 access tokens are pasted by
the account owner; no application secret or interactive OAuth flow is needed.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from utils.ssrf import guarded_async_client


class WikimediaAccessToken(BaseModel):
    model_config = ConfigDict(
        title="Wikimedia Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://meta.wikimedia.org/wiki/Special:OAuthConsumerRegistration/propose/oauth2",
            "x-credential-instructions": "Create an owner-only OAuth 2.0 client on Wikimedia Meta and paste its access token. Choose grants to read pages, edit existing pages, and create pages for the operations you use. For Wikidata keep the default wiki URL. For your own Wikibase use its HTTPS origin and a token issued for that wiki. Connect reads item Q24 and requires the API's authenticated username header; public item content alone never verifies the account. NoClick does not refresh this token; replace it if revoked.",
        },
    )
    credential_type: Literal["wikimedia_access_token"] = Field(
        "wikimedia_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token",
                              json_schema_extra={"ui:widget": "password"})
    wiki_url: str = Field("https://www.wikidata.org", title="Wiki URL",
                          description="HTTPS origin of Wikidata or your own Wikibase, e.g. https://www.wikidata.org")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token", key=True)
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token alone, without a Bearer prefix")
        return value

    @field_validator("wiki_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value, field_name="Wiki URL")
        if urlsplit(origin).scheme != "https" or urlsplit(origin).port is not None:
            raise ValueError("Use the wiki's HTTPS origin without a port")
        return origin


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemInput(Input):
    item_id: str = Field(..., title="Item ID", pattern=r"^Q[1-9]\d{0,9}$", description="Wikibase item ID, e.g. Q24")


class LanguageInput(ItemInput):
    language_code: str = Field("en", title="Language", pattern=r"^[a-z]{2}[a-z0-9-]*$")


class EditMetadata(Input):
    comment: str | None = Field(None, title="Edit summary")
    tags: list[str] = Field(default_factory=list, title="Change tags")
    bot: bool = Field(False, title="Bot edit", description="Requires the bot grant and appropriate wiki rights")


class EditInput(EditMetadata):
    if_match: str | None = Field(None, title="Expected revision",
                                pattern=r'^"[^"\r\n]+"$', description='Optional quoted ETag from a previous read, e.g. "1276705620"; a changed revision returns 412.')


class CheckConnection(Input):
    operation: Literal["check_connection"] = "check_connection"


class SearchInput(Input):
    q: str = Field(..., min_length=1, title="Search text")
    language: str = Field("en", pattern=r"^[a-z]{2}[a-z0-9-]*$", title="Search language")
    limit: int = Field(10, ge=1, le=500, title="Page size")
    offset: int = Field(0, ge=0, title="Offset", description="Advance by the page size to request another page")


class SearchItems(SearchInput):
    operation: Literal["search_items"] = "search_items"


class SearchProperties(SearchInput):
    operation: Literal["search_properties"] = "search_properties"


class GetItem(ItemInput):
    operation: Literal["get_item"] = "get_item"


class GetProperty(Input):
    operation: Literal["get_property"] = "get_property"
    property_id: str = Field(..., pattern=r"^P[1-9]\d{0,9}$", title="Property ID")


class CreateItem(EditMetadata):
    operation: Literal["create_item"] = "create_item"
    labels: dict[str, str] = Field(..., title="Labels by language", description='For example {"en": "Jane Doe"}')
    descriptions: dict[str, str] = Field(default_factory=dict, title="Descriptions by language")
    aliases: dict[str, list[str]] = Field(default_factory=dict, title="Aliases by language")


class GetItemLabels(ItemInput):
    operation: Literal["get_item_labels"] = "get_item_labels"


class SetItemLabel(LanguageInput, EditInput):
    operation: Literal["set_item_label"] = "set_item_label"
    label: str = Field(..., min_length=1, title="Label")


class DeleteItemLabel(LanguageInput, EditInput):
    operation: Literal["delete_item_label"] = "delete_item_label"


class GetItemDescriptions(ItemInput):
    operation: Literal["get_item_descriptions"] = "get_item_descriptions"


class SetItemDescription(LanguageInput, EditInput):
    operation: Literal["set_item_description"] = "set_item_description"
    description: str = Field(..., min_length=1, title="Description")


class DeleteItemDescription(LanguageInput, EditInput):
    operation: Literal["delete_item_description"] = "delete_item_description"


class GetItemAliases(ItemInput):
    operation: Literal["get_item_aliases"] = "get_item_aliases"


class AddItemAliases(LanguageInput, EditInput):
    operation: Literal["add_item_aliases"] = "add_item_aliases"
    aliases: list[str] = Field(..., min_length=1, title="Aliases")


class GetSitelinks(ItemInput):
    operation: Literal["get_sitelinks"] = "get_sitelinks"


class SiteInput(ItemInput):
    site_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$", title="Site ID", description="For example enwiki")


class SetSitelink(SiteInput, EditInput):
    operation: Literal["set_sitelink"] = "set_sitelink"
    title: str = Field(..., min_length=1, title="Linked page title")
    badges: list[str] = Field(default_factory=list, title="Badge item IDs")


class DeleteSitelink(SiteInput, EditInput):
    operation: Literal["delete_sitelink"] = "delete_sitelink"


class PropertyReference(Input):
    id: str = Field(..., pattern=r"^P[1-9]\d{0,9}$")


class StatementValue(Input):
    type: Literal["value", "somevalue", "novalue"] = "value"
    content: Any = Field(None, description="Provider value in the property's data type; omitted for somevalue and novalue")

    @model_validator(mode="after")
    def content_matches_type(self):
        if self.type == "value" and self.content is None:
            raise ValueError("A statement value needs content in the property's data type")
        if self.type != "value" and self.content is not None:
            raise ValueError("Use no content for somevalue or novalue")
        return self


class StatementPart(Input):
    property: PropertyReference
    value: StatementValue


class Reference(Input):
    parts: list[StatementPart]


class Statement(Input):
    property: PropertyReference
    value: StatementValue
    rank: Literal["normal", "preferred", "deprecated"] = "normal"
    qualifiers: list[StatementPart] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)


class GetItemStatements(ItemInput):
    operation: Literal["get_item_statements"] = "get_item_statements"
    property: str | None = Field(None, pattern=r"^P[1-9]\d{0,9}$", title="Filter by property")


class AddItemStatement(ItemInput, EditInput):
    operation: Literal["add_item_statement"] = "add_item_statement"
    statement: Statement = Field(..., title="Statement")


class StatementInput(Input):
    statement_id: str = Field(..., pattern=r"^[QqPp][1-9]\d{0,9}\$.+$", title="Statement ID")


class GetStatement(StatementInput):
    operation: Literal["get_statement"] = "get_statement"


class ReplaceStatement(StatementInput, EditInput):
    operation: Literal["replace_statement"] = "replace_statement"
    statement: Statement = Field(..., title="Replacement statement")


class DeleteStatement(StatementInput, EditInput):
    operation: Literal["delete_statement"] = "delete_statement"


class GetPropertyDataTypes(Input):
    operation: Literal["get_property_data_types"] = "get_property_data_types"


WikimediaConfig = Annotated[Union[
    CheckConnection, SearchItems, SearchProperties, GetItem, GetProperty, CreateItem,
    GetItemLabels, SetItemLabel, DeleteItemLabel, GetItemDescriptions,
    SetItemDescription, DeleteItemDescription, GetItemAliases, AddItemAliases,
    GetSitelinks, SetSitelink, DeleteSitelink, GetItemStatements, AddItemStatement,
    GetStatement, ReplaceStatement, DeleteStatement, GetPropertyDataTypes,
], Field(discriminator="operation")]


class WikimediaNodeConfig(NodeConfig[WikimediaConfig, WikimediaAccessToken]):
    pass


# Each entry is exactly one published contract operation. There are no Action
# API calls, invented endpoints, or follow-up writes hidden behind a read.
ROUTES = {
    "check_connection": ("GET", "/entities/items/Q24", "getItem"),
    "search_items": ("GET", "/search/items", "simpleItemSearch"),
    "search_properties": ("GET", "/search/properties", "simplePropertySearch"),
    "get_item": ("GET", "/entities/items/{item_id}", "getItem"),
    "get_property": ("GET", "/entities/properties/{property_id}", "getProperty"),
    "create_item": ("POST", "/entities/items", "addItem"),
    "get_item_labels": ("GET", "/entities/items/{item_id}/labels", "getItemLabels"),
    "set_item_label": ("PUT", "/entities/items/{item_id}/labels/{language_code}", "replaceItemLabel"),
    "delete_item_label": ("DELETE", "/entities/items/{item_id}/labels/{language_code}", "deleteItemLabel"),
    "get_item_descriptions": ("GET", "/entities/items/{item_id}/descriptions", "getItemDescriptions"),
    "set_item_description": ("PUT", "/entities/items/{item_id}/descriptions/{language_code}", "replaceItemDescription"),
    "delete_item_description": ("DELETE", "/entities/items/{item_id}/descriptions/{language_code}", "deleteItemDescription"),
    "get_item_aliases": ("GET", "/entities/items/{item_id}/aliases", "getItemAliases"),
    "add_item_aliases": ("POST", "/entities/items/{item_id}/aliases/{language_code}", "addItemAliasesInLanguage"),
    "get_sitelinks": ("GET", "/entities/items/{item_id}/sitelinks", "getSitelinks"),
    "set_sitelink": ("PUT", "/entities/items/{item_id}/sitelinks/{site_id}", "setSitelink"),
    "delete_sitelink": ("DELETE", "/entities/items/{item_id}/sitelinks/{site_id}", "deleteSitelink"),
    "get_item_statements": ("GET", "/entities/items/{item_id}/statements", "getItemStatements"),
    "add_item_statement": ("POST", "/entities/items/{item_id}/statements", "addItemStatement"),
    "get_statement": ("GET", "/statements/{statement_id}", "getStatement"),
    "replace_statement": ("PUT", "/statements/{statement_id}", "replaceStatement"),
    "delete_statement": ("DELETE", "/statements/{statement_id}", "deleteStatement"),
    "get_property_data_types": ("GET", "/property-data-types", "getPropertyDataTypes"),
}


class WikimediaNode(WorkflowNode):
    integration_type = "automation-wikimedia"
    connection_evidence = ConnectionEvidence(
        noun="Wikimedia account", identity_operation="check_connection",
        identity_keys=("authenticated_user",))
    edit_examples = ["Find Wikidata items by label", "Set an item's English description", "Add a sourced statement to this item"]

    @classmethod
    def get_config_model(cls):
        return WikimediaNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Wikimedia access token")
        config, credential = self.config.config, self.config.credentials
        method, template, _ = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        route = template.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        headers = {"Authorization": "Bearer " + credential.access_token,
                   "User-Agent": "NoClick/1.0 (https://noclick.com)", "Accept": "application/json"}
        params = {key: values[key] for key in ("q", "language", "limit", "offset", "property") if key in values}
        body = None
        if isinstance(config, EditMetadata):
            body = {key: values[key] for key in ("comment", "tags", "bot") if key in values}
            if isinstance(config, EditInput) and config.if_match:
                headers["If-Match"] = config.if_match
            if isinstance(config, CreateItem):
                body["item"] = {key: values[key] for key in ("labels", "descriptions", "aliases")}
            elif isinstance(config, (SetItemLabel, SetItemDescription, AddItemAliases)):
                key = "label" if isinstance(config, SetItemLabel) else "description" if isinstance(config, SetItemDescription) else "aliases"
                body[key] = values[key]
            elif isinstance(config, SetSitelink):
                body["sitelink"] = {"title": config.title, "badges": config.badges}
            elif isinstance(config, (AddItemStatement, ReplaceStatement)):
                body["statement"] = config.statement.model_dump(exclude_none=True)
        url = credential.wiki_url + "/w/rest.php/wikibase/v1" + route
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, url, headers=headers, params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                message = error.get("message", "Wikimedia request failed")
                code = error.get("code")
            except (ValueError, AttributeError):
                message, code = "Wikimedia returned an unexpected response", None
            return {"status": "error", "success": False, "http_status": response.status_code,
                    "status_code": response.status_code,
                    "message": str(message).replace(credential.access_token, "[redacted]"), "code": code}
        output = {"status": "success", "success": True, "operation": config.operation,
                  "http_status": response.status_code, "revision": response.headers.get("ETag"),
                  "last_modified": response.headers.get("Last-Modified")}
        if config.operation == "check_connection":
            # X-Authenticated-User is part of the getItem contract. Public data
            # proves nothing about the supplied credential, so require it here.
            username = response.headers.get("X-Authenticated-User")
            if not username or not username.strip():
                return {**output, "status": "unverified", "success": False,
                        "message": "The wiki did not return an authenticated username; account access could not be verified"}
            return {**output, "authenticated_user": username}
        output["data"] = None if response.status_code == 204 else response.json()
        return output

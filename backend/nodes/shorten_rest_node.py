"""Shorten.REST v1 actions, each issuing one published API operation.

Contract: https://docs.shorten.rest/swagger.json (1.0.0).
The focused setters replace only their named array, as documented by UpdateAlias.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.shorten.rest"


class ShortenRestAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Shorten Rest API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://shorten.rest",
            "x-credential-instructions": "Paste your Shorten Rest API key. NoClick sends it in the x-api-key header and reads your aliases to check the connection.",
        })
    credential_type: Literal["shorten_rest_api_key"] = Field("shorten_rest_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key", key=True)
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Destination(_Input):
    url: str = Field(..., min_length=1, description="Destination URL to redirect to.")
    country: str | None = Field(None, description="ISO alpha-2 country code; omit for the default destination.")
    os: str | None = Field(None, description="Operating system from the provider's supported OS list.")


class MetaTag(_Input):
    name: str
    content: str


class Snippet(_Input):
    id: str = Field(..., description="ID from the provider's supported snippets list.")
    parameters: dict[str, str] | None = None


class _Domain(_Input):
    domain_name: str = Field("short.fyi", description="Domain without a scheme or slash. Defaults to short.fyi.")


class _Alias(_Domain):
    alias_name: str = Field(..., min_length=1, description="Alias without a leading slash.")


class _Page(_Input):
    limit: int = Field(100, ge=1, le=1000, description="Maximum results in this page.")
    continue_from: str | None = Field(None, description="Use lastId from the previous page; omitted on the first page.")


class ListAliases(_Domain, _Page):
    operation: Literal["list_aliases"] = Field("list_aliases", json_schema_extra={"x-operation-kind": "read"})


class ListClicks(_Page):
    operation: Literal["list_clicks"] = Field("list_clicks", json_schema_extra={"x-operation-kind": "read"})


class GetAlias(_Alias):
    operation: Literal["get_alias"] = Field("get_alias", json_schema_extra={"x-operation-kind": "read"})


class DeleteAlias(_Alias):
    operation: Literal["delete_alias"] = Field("delete_alias", json_schema_extra={"x-operation-kind": "write"})


class _Properties(_Input):
    destinations: list[Destination] | None = Field(None, description="Full replacement array. Include existing destinations to retain them.")
    metatags: list[MetaTag] | None = Field(None, description="Full replacement array. Alias tags override domain tags of the same name.")
    snippets: list[Snippet] | None = Field(None, description="Full replacement array. Alias snippets override domain snippets of the same name.")


class CreateAlias(_Domain, _Properties):
    operation: Literal["create_alias"] = Field("create_alias", json_schema_extra={"x-operation-kind": "write"})
    alias_name: str | None = Field(None, description="Vanity alias, optionally containing @rnd. Omit to generate a random alias.")
    destinations: list[Destination] = Field(..., min_length=1, description="Include a default destination (omit country and os).")


class ShortenURL(_Domain):
    """Shorten a single destination with a provider-generated random alias."""
    operation: Literal["shorten_url"] = Field("shorten_url", json_schema_extra={"x-operation-kind": "write"})
    url: str = Field(..., min_length=1, description="Destination URL for the generated short link.")


class UpdateAlias(_Alias, _Properties):
    operation: Literal["update_alias"] = Field("update_alias", json_schema_extra={"x-operation-kind": "write"})

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, key) is None for key in ("destinations", "metatags", "snippets")):
            raise ValueError("Supply at least one array to replace; an empty array clears it")
        return self


class SetDestinations(_Alias):
    """Replace all destinations, leaving tags and snippets unchanged."""
    operation: Literal["set_destinations"] = Field("set_destinations", json_schema_extra={"x-operation-kind": "write"})
    destinations: list[Destination] = Field(..., description="Full destination array; include existing routes you want to keep.")


class SetMetatags(_Alias):
    """Replace alias metatags; an empty array removes alias overrides."""
    operation: Literal["set_metatags"] = Field("set_metatags", json_schema_extra={"x-operation-kind": "write"})
    metatags: list[MetaTag]


class SetSnippets(_Alias):
    """Replace alias tracking snippets; an empty array removes alias overrides."""
    operation: Literal["set_snippets"] = Field("set_snippets", json_schema_extra={"x-operation-kind": "write"})
    snippets: list[Snippet]


ShortenRestConfig = Annotated[Union[ListAliases, ListClicks, GetAlias, DeleteAlias,
    CreateAlias, ShortenURL, UpdateAlias, SetDestinations, SetMetatags, SetSnippets], Field(discriminator="operation")]


class ShortenRestFullConfig(NodeConfig[ShortenRestConfig, ShortenRestAPIKeyCredential]):
    pass


class ShortenRestNode(WorkflowNode):
    integration_type = "automation-shorten-rest"
    connection_evidence = ConnectionEvidence(noun="short links", operation="list_aliases")

    @classmethod
    def get_config_model(cls):
        return ShortenRestFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Shorten Rest API key")
        params = {}
        if isinstance(config, _Domain):
            params["domainName"] = config.domain_name
        if getattr(config, "alias_name", None) is not None:
            params["aliasName"] = config.alias_name
        if isinstance(config, _Page):
            params["limit"] = config.limit
            if config.continue_from is not None:
                params["continueFrom"] = config.continue_from
        method, path = {
            "list_aliases": ("GET", "/aliases/all"),
            "list_clicks": ("GET", "/clicks"),
            "get_alias": ("GET", "/aliases"),
            "delete_alias": ("DELETE", "/aliases"),
            "create_alias": ("POST", "/aliases"),
            "shorten_url": ("POST", "/aliases"),
            "update_alias": ("PUT", "/aliases"),
            "set_destinations": ("PUT", "/aliases"),
            "set_metatags": ("PUT", "/aliases"),
            "set_snippets": ("PUT", "/aliases"),
        }[config.operation]
        body = None
        if method in {"POST", "PUT"}:
            body = {key: value for key, value in config.model_dump(exclude_none=True).items()
                if key in {"destinations", "metatags", "snippets"}}
            if isinstance(config, ShortenURL):
                body = {"destinations": [{"url": config.url}]}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                headers={"x-api-key": credential.api_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if response.status_code != 200:
            return {"status": "error", "status_code": response.status_code,
                "error": response.text.replace(credential.api_key, "[redacted]")[:2000] or f"Shorten Rest returned HTTP {response.status_code}"}
        if method in {"PUT", "DELETE"}:
            return {"status": "success", "acknowledged": True}
        data = response.json()
        if config.operation in {"list_aliases", "list_clicks"}:
            key = "aliases" if config.operation == "list_aliases" else "clicks"
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise ValueError(f"Shorten Rest returned no {key} array")
            return {"status": "success", "data": data[key], "lastId": data.get("lastId")}
        if data is not None and not isinstance(data, dict):
            raise ValueError("Shorten Rest returned an unexpected alias response")
        return {"status": "success", "data": data}

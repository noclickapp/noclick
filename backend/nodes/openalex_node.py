"""OpenAlex scholarly metadata API, pinned to the published 1.0.0 contract.

Each operation performs one documented GET. Pagination is explicit: reuse the
provider's meta.next_cursor rather than silently fetching an unbounded corpus.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.openalex.org"


class OpenAlexAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="OpenAlex API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://openalex.org/settings/api",
            "x-credential-instructions": "Copy your API key from OpenAlex Settings → API key. Paste only the key. NoClick sends it to api.openalex.org and checks your usage budget; this verifies key acceptance, not your personal identity.",
        })
    credential_type: Literal["openalex_api_key"] = Field("openalex_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste only the OpenAlex API key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _List(_Input):
    search: str | None = Field(None, min_length=1, description="Full-text search, e.g. machine learning.")
    filter: str | None = Field(None, min_length=1, description="OpenAlex field:value filters, combined with commas (AND) or pipes (OR).")
    sort: str | None = Field(None, min_length=1, description="Provider sort expression, e.g. cited_by_count:desc.")
    group_by: str | None = Field(None, min_length=1, description="Group into counts by an entity field.")
    select: str | None = Field(None, min_length=1, description="Comma-separated fields to include in each result.")
    per_page: int = Field(25, ge=1, le=100, description="Results per request, at most 100.")
    page: int | None = Field(None, ge=1, description="Basic page number; omit when using a cursor.")
    cursor: str | None = Field(None, min_length=1, description="Use * to begin deep pagination, then meta.next_cursor from the response. A null next_cursor means the last page.")

    @model_validator(mode="after")
    def pagination(self):
        if self.page is not None and self.cursor is not None:
            raise ValueError("Choose either page or cursor pagination")
        if self.page is not None and self.page * self.per_page > 10000:
            raise ValueError("Use cursor pagination past 10000 results")
        return self


class _Get(_Input):
    id: str = Field(..., min_length=1, max_length=2048,
        description="OpenAlex ID, canonical OpenAlex URL, or a supported external ID such as doi:10.7717/peerj.4375, ORCID, ROR or ISSN.")
    select: str | None = Field(None, min_length=1, description="Comma-separated fields to include.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if value.strip() != value or any(ord(c) < 32 for c in value) or value in {".", ".."} or "?" in value or "#" in value:
            raise ValueError("Use a single OpenAlex or supported external identifier")
        return value


class OpenAlexListWorksConfig(_List):
    """List works from OpenAlex."""
    operation: Literal["list_works"] = Field("list_works", json_schema_extra={"ui:hidden": True})


class OpenAlexGetWorkConfig(_Get):
    """Get work from OpenAlex."""
    operation: Literal["get_work"] = Field("get_work", json_schema_extra={"ui:hidden": True})


class OpenAlexListAuthorsConfig(_List):
    """List authors from OpenAlex."""
    operation: Literal["list_authors"] = Field("list_authors", json_schema_extra={"ui:hidden": True})


class OpenAlexGetAuthorConfig(_Get):
    """Get author from OpenAlex."""
    operation: Literal["get_author"] = Field("get_author", json_schema_extra={"ui:hidden": True})


class OpenAlexListSourcesConfig(_List):
    """List sources from OpenAlex."""
    operation: Literal["list_sources"] = Field("list_sources", json_schema_extra={"ui:hidden": True})


class OpenAlexGetSourceConfig(_Get):
    """Get source from OpenAlex."""
    operation: Literal["get_source"] = Field("get_source", json_schema_extra={"ui:hidden": True})


class OpenAlexListInstitutionsConfig(_List):
    """List institutions from OpenAlex."""
    operation: Literal["list_institutions"] = Field("list_institutions", json_schema_extra={"ui:hidden": True})


class OpenAlexGetInstitutionConfig(_Get):
    """Get institution from OpenAlex."""
    operation: Literal["get_institution"] = Field("get_institution", json_schema_extra={"ui:hidden": True})


class OpenAlexListTopicsConfig(_List):
    """List topics from OpenAlex."""
    operation: Literal["list_topics"] = Field("list_topics", json_schema_extra={"ui:hidden": True})


class OpenAlexGetTopicConfig(_Get):
    """Get topic from OpenAlex."""
    operation: Literal["get_topic"] = Field("get_topic", json_schema_extra={"ui:hidden": True})


class OpenAlexListKeywordsConfig(_List):
    """List keywords from OpenAlex."""
    operation: Literal["list_keywords"] = Field("list_keywords", json_schema_extra={"ui:hidden": True})


class OpenAlexGetKeywordConfig(_Get):
    """Get keyword from OpenAlex."""
    operation: Literal["get_keyword"] = Field("get_keyword", json_schema_extra={"ui:hidden": True})


class OpenAlexListPublishersConfig(_List):
    """List publishers from OpenAlex."""
    operation: Literal["list_publishers"] = Field("list_publishers", json_schema_extra={"ui:hidden": True})


class OpenAlexGetPublisherConfig(_Get):
    """Get publisher from OpenAlex."""
    operation: Literal["get_publisher"] = Field("get_publisher", json_schema_extra={"ui:hidden": True})


class OpenAlexListFundersConfig(_List):
    """List funders from OpenAlex."""
    operation: Literal["list_funders"] = Field("list_funders", json_schema_extra={"ui:hidden": True})


class OpenAlexGetFunderConfig(_Get):
    """Get funder from OpenAlex."""
    operation: Literal["get_funder"] = Field("get_funder", json_schema_extra={"ui:hidden": True})


class OpenAlexListDomainsConfig(_List):
    """List domains from OpenAlex."""
    operation: Literal["list_domains"] = Field("list_domains", json_schema_extra={"ui:hidden": True})


class OpenAlexGetDomainConfig(_Get):
    """Get domain from OpenAlex."""
    operation: Literal["get_domain"] = Field("get_domain", json_schema_extra={"ui:hidden": True})


class OpenAlexListFieldsConfig(_List):
    """List fields from OpenAlex."""
    operation: Literal["list_fields"] = Field("list_fields", json_schema_extra={"ui:hidden": True})


class OpenAlexGetFieldConfig(_Get):
    """Get field from OpenAlex."""
    operation: Literal["get_field"] = Field("get_field", json_schema_extra={"ui:hidden": True})


class OpenAlexListSubfieldsConfig(_List):
    """List subfields from OpenAlex."""
    operation: Literal["list_subfields"] = Field("list_subfields", json_schema_extra={"ui:hidden": True})


class OpenAlexGetSubfieldConfig(_Get):
    """Get subfield from OpenAlex."""
    operation: Literal["get_subfield"] = Field("get_subfield", json_schema_extra={"ui:hidden": True})


class OpenAlexAutocompleteConfig(_Input):
    """Find up to ten entities by a partial name."""
    operation: Literal["autocomplete"] = Field("autocomplete", json_schema_extra={"ui:hidden": True})
    entity_type: Literal["works", "authors", "sources", "institutions", "topics", "keywords", "publishers", "funders"] = Field("works", title="Entity Type")
    q: str = Field(..., min_length=1, description="Partial name to search.")
    filter: str | None = Field(None, min_length=1, description="Optional OpenAlex filter expression.")


class OpenAlexGetRateLimitConfig(_Input):
    """Check this API key's current usage and remaining budget."""
    operation: Literal["get_rate_limit"] = Field("get_rate_limit", json_schema_extra={"ui:hidden": True})

# OpenAlex's own MCP server: agents get its tools through a person's OpenAlex sign-in.
OpenalexMcpCredential = mcp_credential("openalex", "https://mcp.openalex.org/mcp", app="OpenAlex")
OpenAlexCredential = Union[OpenAlexAPIKeyCredential, OpenalexMcpCredential]


OpenAlexOperation = Annotated[Union[
    OpenAlexOnNewWorkConfig,
    OpenAlexOnUpdatedWorkConfig,
    OpenAlexListWorksConfig,
    OpenAlexGetWorkConfig,
    OpenAlexListAuthorsConfig,
    OpenAlexGetAuthorConfig,
    OpenAlexListSourcesConfig,
    OpenAlexGetSourceConfig,
    OpenAlexListInstitutionsConfig,
    OpenAlexGetInstitutionConfig,
    OpenAlexListTopicsConfig,
    OpenAlexGetTopicConfig,
    OpenAlexListKeywordsConfig,
    OpenAlexGetKeywordConfig,
    OpenAlexListPublishersConfig,
    OpenAlexGetPublisherConfig,
    OpenAlexListFundersConfig,
    OpenAlexGetFunderConfig,
    OpenAlexListDomainsConfig,
    OpenAlexGetDomainConfig,
    OpenAlexListFieldsConfig,
    OpenAlexGetFieldConfig,
    OpenAlexListSubfieldsConfig,
    OpenAlexGetSubfieldConfig,
    OpenAlexAutocompleteConfig,
    OpenAlexGetRateLimitConfig
], Field(discriminator="operation")]


class OpenAlexNodeConfig(NodeConfig[OpenAlexOperation, OpenAlexCredential]):
    pass


# Exactly one published endpoint for each operation; no generic request escape.
ROUTES = {
    "list_works": "/works",
    "get_work": "/works/{id}",
    "list_authors": "/authors",
    "get_author": "/authors/{id}",
    "list_sources": "/sources",
    "get_source": "/sources/{id}",
    "list_institutions": "/institutions",
    "get_institution": "/institutions/{id}",
    "list_topics": "/topics",
    "get_topic": "/topics/{id}",
    "list_keywords": "/keywords",
    "get_keyword": "/keywords/{id}",
    "list_publishers": "/publishers",
    "get_publisher": "/publishers/{id}",
    "list_funders": "/funders",
    "get_funder": "/funders/{id}",
    "list_domains": "/domains",
    "get_domain": "/domains/{id}",
    "list_fields": "/fields",
    "get_field": "/fields/{id}",
    "list_subfields": "/subfields",
    "get_subfield": "/subfields/{id}",
    "autocomplete": "/autocomplete/{entity_type}",
    "get_rate_limit": "/rate-limit",
}


def _redact(value, key):
    if isinstance(value, dict):
        return {k: _redact(v, key) for k, v in value.items() if k.lower() not in {"api_key", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value.replace(key, "[redacted]") if isinstance(value, str) else value


class OpenAlexNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-openalex"
    credential_provider_labels = {"openalex": "OpenAlex Account"}
    connection_evidence = ConnectionEvidence(
        operation="get_rate_limit", noun="API usage budget", proves="reachability")
    edit_examples = ["Find open access papers about machine learning", "Look up an author by ORCID", "Group works by publication year"]

    @classmethod
    def get_config_model(cls):
        return OpenAlexNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_work", "on_new_or_updated_work"}:
            return bool(output.get("new_work_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        works = output.get("works") if isinstance(output, dict) else None
        if not isinstance(works, list):
            return super().resolve_agent_event(output)
        if not works:
            return None
        lines = []
        for work in works[:10]:
            authors = ", ".join(
                (authorship.get("author") or {}).get("display_name") or "Unknown author"
                for authorship in (work.get("authorships") or [])[:5]
            )
            lines.append(f"- {work.get('display_name') or 'Untitled work'} by {authors or 'Unknown author'}; "
                         f"OpenAlex ID: {work['id']}; DOI: {work.get('doi') or 'none'}; "
                         f"updated: {work.get('updated_date') or 'unknown'}")
        if len(works) > 10:
            lines.append(f"- … and {len(works) - 10} more works in the output")
        return {"text": "OpenAlex: new or changed scholarly works:\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_works(self, op):
        # https://help.openalex.org/api/sorting/ and /data/works/attributes/.
        updated = isinstance(op, OpenAlexOnUpdatedWorkConfig)
        sort = "updated_date:desc" if updated else "created_date:desc"
        reader = OpenAlexListWorksConfig(search=op.search, filter=op.filter, sort=sort, per_page=100)
        body = await self._request_operation(reader)
        if body.get("status") != "success":
            raise ValueError(body.get("error") or "OpenAlex polling failed")
        works = body["results"]
        if any(not isinstance(work, dict) or not work.get("id") or (updated and not work.get("updated_date")) for work in works):
            raise ValueError("OpenAlex poll response is missing a work ID or update timestamp")
        fresh = await self._filter_unseen(
            works, lambda work: f"{work['id']}:{work['updated_date']}" if updated else work["id"])
        return {"works": fresh, "new_work_count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an OpenAlex API key")
        op = self.config.config
        output = await self._poll_works(op) if isinstance(op, _WorkPoll) else await self._request_operation(op)
        await self.emit(output)
        return output

    async def _request_operation(self, op):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an OpenAlex API key")
        key = self.config.credentials.api_key
        params = op.model_dump(exclude={"operation", "id", "entity_type"}, exclude_none=True)
        params["api_key"] = key
        path = ROUTES[op.operation]
        if isinstance(op, _Get):
            path = path.replace("{id}", quote(op.id, safe=""))
        elif isinstance(op, OpenAlexAutocompleteConfig):
            path = path.replace("{entity_type}", op.entity_type)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE_URL + path,
                    params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("OpenAlex request could not be completed") from None
        if response.status_code != 200:
            message = "OpenAlex request failed"
            try:
                body = response.json()
                if isinstance(body, dict):
                    message = body.get("message") or body.get("error") or message
            except ValueError:
                pass
            output = {"status": "error", "http_status": response.status_code,
                "error": _redact(str(message), key)}
        else:
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Expected a JSON response from OpenAlex") from None
            if not isinstance(body, dict) or "error" in body or "errors" in body:
                raise ValueError("OpenAlex returned an invalid or error response")
            if isinstance(op, (_List, OpenAlexAutocompleteConfig)):
                if not isinstance(body.get("results"), list) and not (isinstance(op, _List) and op.group_by and isinstance(body.get("group_by"), list)):
                    raise ValueError("OpenAlex response is missing its result list")
            if isinstance(op, OpenAlexGetRateLimitConfig) and not isinstance(body.get("rate_limit"), dict):
                raise ValueError("OpenAlex response is missing usage data")
            output = {**_redact(body, key), "status": "success"}
        return output

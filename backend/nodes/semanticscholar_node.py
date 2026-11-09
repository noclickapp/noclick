"""Semantic Scholar Academic Graph API v1, pinned to the provider's published contract.

All operations retrieve research data, including the two POST batch reads. The
Graph API has no account identity or mutation endpoints. Pagination is explicit:
use the provider's next offset/token with the same query to retrieve another page.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.semanticscholar.org/graph/v1"


class SemanticScholarAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Semantic Scholar API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.semanticscholar.org/product/api",
            "x-credential-instructions": "Paste your Semantic Scholar API key. NoClick sends it in the x-api-key header to api.semanticscholar.org. Research data is public; the connection read checks API reachability and does not verify account identity.",
        })
    credential_type: Literal["semanticscholar_api_key"] = Field("semanticscholar_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def bounded_text(cls, value, info):
        if isinstance(value, str) and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use nonempty text without control characters")
        if info.field_name == "paper_id" and value in {".", ".."}:
            raise ValueError("Supply a supported paper identifier")
        return value


class _Fields(_Input):
    fields: str | None = Field(None, max_length=2000, description="Comma-separated response fields, for example title,year,authors. Omit for provider defaults.")

    @field_validator("fields")
    @classmethod
    def field_names(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*(?:,[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*)*", value):
            raise ValueError("Use comma-separated field names, with dots for nested fields")
        return value


class _Page(_Fields):
    offset: int = Field(0, ge=0, description="Start offset; copy the next value returned by the previous page.")
    limit: int = Field(100, ge=1, le=1000, description="Maximum number of results on this page.")


class _Filters(_Fields):
    publicationTypes: str | None = Field(None, max_length=1000, title="Publication types", description="Comma-separated publication types, such as Review,JournalArticle.")
    openAccessPdf: bool = Field(False, title="Only papers with a public PDF")
    minCitationCount: int | None = Field(None, ge=0, title="Minimum citation count")
    publicationDateOrYear: str | None = Field(None, max_length=100, title="Publication date or year", description="Inclusive date range, for example 2019:2020 or 2019-03-05:2020-06-06.")
    year: str | None = Field(None, max_length=100, description="Year or range, for example 2019, 2016-2020 or 2010-.")
    venue: str | None = Field(None, max_length=1000, description="Comma-separated publication venues.")
    fieldsOfStudy: str | None = Field(None, max_length=1000, title="Fields of study", description="Comma-separated fields, for example Computer Science,Medicine.")


class SearchPapers(_Filters):
    """Search papers by relevance; one page of at most 100 results."""
    operation: Literal["search_papers"] = "search_papers"
    query: str = Field(..., min_length=1, max_length=2000)
    offset: int = Field(0, ge=0, le=9999)
    limit: int = Field(100, ge=1, le=100)


class SearchPapersBulk(_Filters):
    """Retrieve a bulk search page; copy its token for the next page."""
    operation: Literal["search_papers_bulk"] = "search_papers_bulk"
    query: str = Field(..., min_length=1, max_length=2000)
    token: str | None = Field(None, max_length=10000, description="Opaque token from the previous bulk search response.")
    sort: Literal["paperId:asc", "paperId:desc", "publicationDate:asc", "publicationDate:desc", "citationCount:asc", "citationCount:desc"] | None = None


class MatchPaper(_Filters):
    """Find the best paper title match."""
    operation: Literal["match_paper"] = "match_paper"
    query: str = Field(..., min_length=1, max_length=2000)


class AutocompletePapers(_Input):
    """Suggest paper completions for a partial query."""
    operation: Literal["autocomplete_papers"] = "autocomplete_papers"
    query: str = Field(..., min_length=1, max_length=100)


class GetPaper(_Fields):
    """Retrieve a paper by Semantic Scholar ID, DOI, arXiv ID or other supported ID."""
    operation: Literal["get_paper"] = "get_paper"
    paper_id: str = Field(..., min_length=1, max_length=2000, description="Paper ID, for example 649def34f8be52c8b66281af98ae884c09aef38b, DOI:10.1038/nrn3241 or ARXIV:2106.15928.")


class GetPaperAuthors(_Page):
    """Retrieve one page of a paper's authors."""
    operation: Literal["get_paper_authors"] = "get_paper_authors"
    paper_id: str = Field(..., min_length=1, max_length=2000)


class GetPaperCitations(_Page):
    """Retrieve one page of papers citing this paper."""
    operation: Literal["get_paper_citations"] = "get_paper_citations"
    paper_id: str = Field(..., min_length=1, max_length=2000)
    publicationDateOrYear: str | None = Field(None, max_length=100, title="Publication date or year")


class GetPaperReferences(_Page):
    """Retrieve one page of papers referenced by this paper."""
    operation: Literal["get_paper_references"] = "get_paper_references"
    paper_id: str = Field(..., min_length=1, max_length=2000)


class BatchGetPapers(_Fields):
    """Retrieve up to 500 papers in one POST read; missing papers may be null."""
    operation: Literal["batch_get_papers"] = "batch_get_papers"
    ids: list[str] = Field(..., min_length=1, max_length=500, description="Paper IDs in request order.")

    @field_validator("ids")
    @classmethod
    def ids_valid(cls, value):
        if any(not item.strip() or len(item) > 2000 or any(ord(c) < 32 for c in item) for item in value):
            raise ValueError("Supply nonempty supported paper IDs")
        return value


class SearchAuthors(_Page):
    """Search authors by name."""
    operation: Literal["search_authors"] = "search_authors"
    query: str = Field(..., min_length=1, max_length=2000)


class GetAuthor(_Fields):
    """Retrieve an author's profile and requested research metrics."""
    operation: Literal["get_author"] = "get_author"
    author_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[0-9]+$")


class GetAuthorPapers(_Page):
    """Retrieve one page of an author's papers."""
    operation: Literal["get_author_papers"] = "get_author_papers"
    author_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[0-9]+$")
    publicationDateOrYear: str | None = Field(None, max_length=100, title="Publication date or year")


class BatchGetAuthors(_Fields):
    """Retrieve up to 1000 author profiles in one POST read."""
    operation: Literal["batch_get_authors"] = "batch_get_authors"
    ids: list[str] = Field(..., min_length=1, max_length=1000, description="Numeric author IDs in request order.")

    @field_validator("ids")
    @classmethod
    def ids_valid(cls, value):
        if any(not re.fullmatch(r"[0-9]{1,100}", item) for item in value):
            raise ValueError("Supply numeric author IDs")
        return value


SemanticScholarConfig = Annotated[Union[SearchPapers, SearchPapersBulk, MatchPaper,
    AutocompletePapers, GetPaper, GetPaperAuthors, GetPaperCitations, GetPaperReferences,
    BatchGetPapers, SearchAuthors, GetAuthor, GetAuthorPapers, BatchGetAuthors], Field(discriminator="operation")]


class SemanticScholarFullConfig(NodeConfig[SemanticScholarConfig, SemanticScholarAPIKeyCredential]):
    pass


ROUTES = {
    "search_papers": ("GET", "/paper/search"),
    "search_papers_bulk": ("GET", "/paper/search/bulk"),
    "match_paper": ("GET", "/paper/search/match"),
    "autocomplete_papers": ("GET", "/paper/autocomplete"),
    "get_paper": ("GET", "/paper/{paper_id}"),
    "get_paper_authors": ("GET", "/paper/{paper_id}/authors"),
    "get_paper_citations": ("GET", "/paper/{paper_id}/citations"),
    "get_paper_references": ("GET", "/paper/{paper_id}/references"),
    "batch_get_papers": ("POST", "/paper/batch"),
    "search_authors": ("GET", "/author/search"),
    "get_author": ("GET", "/author/{author_id}"),
    "get_author_papers": ("GET", "/author/{author_id}/papers"),
    "batch_get_authors": ("POST", "/author/batch"),
}


class SemanticScholarNode(WorkflowNode):
    integration_type = "automation-semanticscholar"
    connection_evidence = ConnectionEvidence(noun="Semantic Scholar papers", operation="search_papers",
        operation_arguments={"query": "graph", "limit": 1}, proves="reachability")

    @classmethod
    def get_config_model(cls):
        return SemanticScholarFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Semantic Scholar API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, route = ROUTES[config.operation]
        params = config.model_dump(exclude_none=True, exclude={"operation", "paper_id", "author_id", "ids"})
        for field in ("paper_id", "author_id"):
            if hasattr(config, field):
                route = route.replace("{" + field + "}", quote(getattr(config, field), safe=""))
        if "openAccessPdf" in params:
            enabled = params.pop("openAccessPdf")
            if enabled:
                params["openAccessPdf"] = ""
        if "minCitationCount" in params:
            params["minCitationCount"] = str(params["minCitationCount"])
        kwargs = {"params": params, "headers": {"x-api-key": key, "Accept": "application/json"}}
        batch = config.operation in {"batch_get_papers", "batch_get_authors"}
        if batch:
            kwargs["json"] = {"ids": config.ids}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + route, **kwargs)
        if response.status_code != 200:
            message = "Semantic Scholar request failed"
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = str(payload.get("message") or payload.get("error") or message)
            except ValueError:
                pass
            return {"status": "error", "status_code": response.status_code,
                "error": message.replace(key, "[redacted]")[:1000]}
        if len(response.content) > 11_000_000:
            raise ValueError("Semantic Scholar response exceeds the 10 MB API limit")
        payload = response.json()
        if batch:
            if not isinstance(payload, list) or any(item is not None and not isinstance(item, dict) for item in payload):
                raise ValueError("Expected a Semantic Scholar batch array")
        elif not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Expected a Semantic Scholar JSON object")
        elif config.operation not in {"get_paper", "get_author"}:
            array_key = "matches" if config.operation == "autocomplete_papers" else "data"
            if not isinstance(payload.get(array_key), list):
                raise ValueError("Expected a Semantic Scholar result list")
        # Preserve the provider's envelope, including next/offset/token/total and
        # citation/reference nesting. No implicit pagination or download follows.
        output = {"status": "success", "data": payload}
        await self.emit(output)
        return output

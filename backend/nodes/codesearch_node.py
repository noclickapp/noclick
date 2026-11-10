"""Search Debian source code through the provider's two published API operations.

The corpus is public: a successful API-key read proves reachability, not identity.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://codesearch.debian.net/api/v1"


class CodesearchAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Debian Code Search API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://codesearch.debian.net/apikeys/",
            "x-credential-instructions": "Paste your Debian Code Search API key. NoClick sends it in the x-dcs-apikey header. A search checks that the key is accepted; the public corpus does not identify your account.",
        },
    )
    credential_type: Literal["codesearch_api_key"] = Field("codesearch_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or a header")
        return value


class _SearchInput(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    query: str = Field(..., min_length=1, description="Search text or an RE2 regular expression. Supports package:, path: and filetype: keywords; see https://codesearch.debian.net/faq#keywords.")
    match_mode: Literal["literal", "regexp"] = Field("regexp", title="Match mode")


class SearchConfig(_SearchInput):
    operation: Literal["search_code"] = Field("search_code", title="Search source code", json_schema_extra={"x-operation-kind": "read"})


class SearchPerPackageConfig(_SearchInput):
    operation: Literal["search_per_package"] = Field("search_per_package", title="Search grouped by package", json_schema_extra={"x-operation-kind": "read"})


CodesearchConfig = Annotated[Union[SearchConfig, SearchPerPackageConfig], Field(discriminator="operation")]


class CodesearchNodeConfig(NodeConfig[CodesearchConfig, CodesearchAPIKeyCredential]):
    model_config = ConfigDict(title="Debian Code Search Node Configuration", hide_input_in_errors=True)


class _SearchResult(BaseModel):
    # Optional context lines are absent on some matches. Preserve provider extensions.
    model_config = ConfigDict(extra="allow", strict=True)
    package: str
    path: str
    line: int
    context: str
    context_before: list[str] | None = None
    context_after: list[str] | None = None


class _PackageResult(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    package: str
    results: list[_SearchResult]


class CodesearchNode(WorkflowNode):
    integration_type = "automation-codesearch"
    connection_evidence = ConnectionEvidence(
        noun="Debian source search results", operation="search_code",
        label_keys=("path", "package"), proves="reachability",
        operation_arguments={"query": "who knows...", "match_mode": "literal"},
    )

    @classmethod
    def get_config_model(cls):
        return CodesearchNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Debian Code Search API key")
        config = self.config.config
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=60.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get(
                    BASE_URL + "/" + ("search" if config.operation == "search_code" else "searchperpackage"),
                    params={"query": config.query, "match_mode": config.match_mode},
                    headers={"x-dcs-apikey": key, "Accept": "application/json"},
                )
        except httpx.RequestError:
            return {"status": "error", "message": "Debian Code Search could not be reached"}
        if response.status_code != 200:
            # Keep rejection text for connection diagnostics, without reflecting the key.
            message = response.text.replace(key, "[redacted]")[:2000]
            return {"status": "error", "status_code": response.status_code,
                    "message": message or "Debian Code Search did not complete the search"}
        try:
            payload = response.json()
            adapter = TypeAdapter(list[_SearchResult] if config.operation == "search_code" else list[_PackageResult])
            data = adapter.validate_python(payload)
        except (ValueError, ValidationError):
            return {"status": "error", "message": "Debian Code Search returned an unexpected search response"}
        result = {"status": "success", "operation": config.operation,
                  "data": [row.model_dump(exclude_unset=True) for row in data],
                  "identity_verified": False}
        await self.emit(result)
        return result

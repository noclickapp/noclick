"""OSV public API queries (published v1 contract, including experimental reads).

Ten task-oriented operations each issue one request to one of the six published
endpoints. POST queries do not mutate records. No account or API key is needed.
Documentation: https://google.github.io/osv.dev/api/
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api.osv.dev"
Text = Annotated[str, Field(min_length=1, max_length=4096)]
Commit = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{40}$")]


def _operation(name, label):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Package(_Input):
    name: Text | None = None
    ecosystem: Text | None = None
    purl: Annotated[str, Field(pattern=r"^pkg:.+", max_length=4096)] | None = None

    @model_validator(mode="after")
    def identifier(self):
        if self.purl is not None:
            if self.name is not None or self.ecosystem is not None:
                raise ValueError("Use a purl or name and ecosystem, not both")
        elif not self.name or not self.ecosystem:
            raise ValueError("A package needs both name and ecosystem")
        return self


class Query(_Input):
    commit: Commit | None = None
    version: Text | None = None
    package: Package | None = None
    page_token: Text | None = None

    @model_validator(mode="after")
    def query_rules(self):
        if self.commit and self.version:
            raise ValueError("Use a commit or version, not both")
        if not self.commit and not self.package:
            raise ValueError("Supply a commit or package")
        if self.version and self.package and self.package.purl:
            # A scoped npm name contains @ before its final path segment.
            if "@" in self.package.purl.split("?", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]:
                raise ValueError("Do not combine version with a versioned purl")
        return self


class _Page(_Input):
    page_token: Text | None = Field(None, description="Return next_page_token here with the same query to fetch another page.")


class QueryPackage(_Page):
    operation: Literal["query_package"] = _operation("query_package", "List Package Vulnerabilities")
    name: Text = Field(..., description="Package name, e.g. nokogiri.")
    ecosystem: Text = Field(..., description="Case-sensitive ecosystem, e.g. RubyGems or PyPI.")


class QueryPackageVersion(QueryPackage):
    operation: Literal["query_package_version"] = _operation("query_package_version", "Query Package Version")
    version: Text


class QueryPurl(_Page):
    operation: Literal["query_purl"] = _operation("query_purl", "Query Package URL")
    purl: Annotated[str, Field(pattern=r"^pkg:.+", max_length=4096)]
    version: Text | None = Field(None, description="Omit when the purl already contains a version.")

    @model_validator(mode="after")
    def version_rule(self):
        Query(package=Package(purl=self.purl), version=self.version)
        return self


class QueryCommit(_Page):
    operation: Literal["query_commit"] = _operation("query_commit", "Query Git Commit")
    commit: Commit


class QueryGitTag(_Page):
    operation: Literal["query_git_tag"] = _operation("query_git_tag", "Query Git Repository Tag")
    repository: Annotated[str, Field(pattern=r"^https://.+", max_length=4096)] = Field(..., description="Full Git repository URL, e.g. https://github.com/curl/curl.git. Sent as data; never fetched.")
    tag: Text = Field(..., description="Git tag, e.g. 8.5.0.")


class QueryBatch(_Input):
    operation: Literal["query_batch"] = _operation("query_batch", "Batch Query Vulnerabilities")
    queries: list[Query] = Field(..., min_length=1, max_length=1000, description="Package/version, purl or commit queries. Results preserve input order and contain only IDs and modification timestamps. Each result may have its own next_page_token.")


class GetVulnerability(_Input):
    operation: Literal["get_vulnerability"] = _operation("get_vulnerability", "Get Vulnerability")
    vulnerability_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")] = Field("OSV-2020-111", title="Vulnerability ID")


class FileHash(_Input):
    file_path: Text
    hash: Text = Field(..., pattern=r"^[A-Za-z0-9+/]{22}==$", description="Base64-encoded MD5 digest bytes, not the hex digest.")
    hash_type: Literal["MD5"] = "MD5"

    @field_validator("hash")
    @classmethod
    def md5_bytes(cls, value):
        try:
            valid = len(base64.b64decode(value, validate=True)) == 16
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Supply a base64-encoded 16-byte MD5 digest")
        return value


class DetermineVersion(_Input):
    operation: Literal["determine_version"] = _operation("determine_version", "Determine C/C++ Version (Experimental)")
    name: Text | None = Field(None, description="Optional library name hint.")
    file_hashes: list[FileHash] = Field(..., min_length=1, max_length=10000)


class ListImportFindings(_Input):
    operation: Literal["list_import_findings"] = _operation("list_import_findings", "List Import Findings (Experimental)")
    source: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")] = Field(..., description="Source name from OSV source.yaml; case sensitive.")


class MapUbuntuPackages(_Input):
    operation: Literal["map_ubuntu_packages"] = _operation("map_ubuntu_packages", "Map Ubuntu Binary Packages (Experimental)")
    ecosystem: Annotated[str, Field(pattern=r"^Ubuntu:(?:Pro:)?[0-9]{2}\.[0-9]{2}(?::LTS)?$")] = Field(..., description="Ubuntu release ecosystem, e.g. Ubuntu:24.04:LTS.")
    binary_names: list[Text] = Field(..., min_length=1, max_length=1000, description="Results correspond to these names in order; an empty result means no known mapping.")


OsvConfig = Annotated[Union[QueryPackage, QueryPackageVersion, QueryPurl, QueryCommit,
    QueryGitTag, QueryBatch, GetVulnerability, DetermineVersion, ListImportFindings,
    MapUbuntuPackages], Field(discriminator="operation")]


class OsvFullConfig(NodeConfig[OsvConfig, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        return None if value == {} else value


class OsvNode(WorkflowNode):
    integration_type = "automation-osv"
    connection_evidence = ConnectionEvidence(operation="get_vulnerability", noun="public vulnerability records", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return OsvFullConfig

    async def execute(self, inputs):
        config = self.config.config
        operation = config.operation
        method, path, body = "POST", "/v1/query", None
        if isinstance(config, QueryPackage):
            body = {"package": {"name": config.name, "ecosystem": config.ecosystem}}
            if isinstance(config, QueryPackageVersion):
                body["version"] = config.version
        elif isinstance(config, QueryPurl):
            body = {"package": {"purl": config.purl}}
            if config.version is not None:
                body["version"] = config.version
        elif isinstance(config, QueryCommit):
            body = {"commit": config.commit}
        elif isinstance(config, QueryGitTag):
            body = {"package": {"name": config.repository, "ecosystem": "GIT"}, "version": config.tag}
        elif isinstance(config, QueryBatch):
            path, body = "/v1/querybatch", {"queries": [q.model_dump(exclude_none=True) for q in config.queries]}
        elif isinstance(config, GetVulnerability):
            method, path = "GET", "/v1/vulns/" + quote(config.vulnerability_id, safe="")
        elif isinstance(config, DetermineVersion):
            path, body = "/v1experimental/determineversion", config.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(config, ListImportFindings):
            method, path = "GET", "/v1experimental/importfindings/" + quote(config.source, safe="")
        elif isinstance(config, MapUbuntuPackages):
            path, body = "/v1experimental/ubuntu/binary-to-source", config.model_dump(exclude={"operation"})
        if isinstance(config, _Page) and config.page_token is not None:
            body["page_token"] = config.page_token
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers={"Accept": "application/json"}, **({"json": body} if body is not None else {}))
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("OSV returned a redirect instead of JSON")
        result = response.json()
        if not isinstance(result, dict) or "error" in result or "code" in result:
            raise ValueError("OSV returned an invalid response or error envelope")
        if isinstance(config, GetVulnerability):
            if result.get("id") != config.vulnerability_id:
                raise ValueError("OSV returned a different vulnerability")
        else:
            key = "results" if isinstance(config, (QueryBatch, MapUbuntuPackages)) else "matches" if isinstance(config, DetermineVersion) else "invalid_records" if isinstance(config, ListImportFindings) else "vulns"
            # Protobuf JSON omits empty repeated fields. Empty {} is valid.
            rows = result.get(key, [])
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("OSV returned an invalid result list")
            result[key] = rows
            if isinstance(config, QueryBatch):
                if len(rows) != len(config.queries):
                    raise ValueError("OSV batch results do not match input count")
                for row in rows:
                    self._query_page(row)
            elif isinstance(config, MapUbuntuPackages):
                if len(rows) != len(config.binary_names):
                    raise ValueError("OSV mappings do not match input count")
                for row in rows:
                    if not isinstance(row.get("source_names", []), list) or any(not isinstance(name, str) for name in row.get("source_names", [])):
                        raise ValueError("OSV returned invalid source names")
        if isinstance(config, _Page):
            self._query_page(result)
        return {**result, "status": "success", "operation": operation}

    @staticmethod
    def _query_page(page):
        if not isinstance(page.get("vulns", []), list) or any(not isinstance(v, dict) for v in page.get("vulns", [])):
            raise ValueError("OSV returned invalid vulnerabilities")
        if "next_page_token" in page and not isinstance(page["next_page_token"], str):
            raise ValueError("OSV returned an invalid pagination token")

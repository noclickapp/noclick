"""CIRCL hashlookup's public v1.3 API, one request per operation.

No account or API key is needed. Session support is server-dependent and is
disabled on CIRCL's public instance; an HTTPS hashlookup-server may enable it.
Contract: https://hashlookup.circl.lu/swagger.json
Examples: https://www.circl.lu/services/hashlookup/
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://hashlookup.circl.lu"
MD5 = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{32}$")]
SHA1 = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{40}$")]
SHA256 = Annotated[str, Field(pattern=r"^[0-9A-Fa-f]{64}$")]
SessionName = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,120}$")]


def _operation(name, label):
    return Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": label})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_url: str = Field(BASE, title="Hashlookup server URL", description="Public CIRCL service by default. Use an HTTPS hashlookup-server origin for optional session support. No authentication is sent.")

    @field_validator("server_url")
    @classmethod
    def https_server(cls, value):
        try:
            parts = urlsplit(value)
            valid = (parts.scheme == "https" and parts.hostname and
                     parts.username is None and parts.password is None and
                     parts.port in (None, 443) and parts.path in ("", "/") and
                     not parts.query and not parts.fragment and
                     not any(c.isspace() for c in value))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Use an HTTPS origin without a path, query, credentials or custom port")
        return "https://" + parts.netloc.lower().removesuffix(":443").rstrip("/")


class _Lookup(_Input):
    session_name: SessionName | None = Field(None, description="Optional existing session name sent as hashlookup_session. Public CIRCL does not enable sessions.")


class LookupMD5(_Lookup):
    """Look up a file's MD5 digest in known-file datasets."""
    operation: Literal["lookup_md5"] = _operation("lookup_md5", "Look Up MD5")
    md5: MD5


class LookupSHA1(_Lookup):
    """Look up a file's SHA-1 digest in known-file datasets."""
    operation: Literal["lookup_sha1"] = _operation("lookup_sha1", "Look Up SHA-1")
    sha1: SHA1


class LookupSHA256(_Lookup):
    """Look up a file's SHA-256 digest in known-file datasets."""
    operation: Literal["lookup_sha256"] = _operation("lookup_sha256", "Look Up SHA-256")
    sha256: SHA256


class BulkMD5(_Input):
    """Search MD5 hashes in one POST query; this does not add database records."""
    operation: Literal["bulk_md5"] = _operation("bulk_md5", "Bulk Look Up MD5 Hashes")
    hashes: list[MD5] = Field(..., min_length=1, max_length=1000)


class BulkSHA1(_Input):
    """Search SHA-1 hashes in one POST query; this does not add database records."""
    operation: Literal["bulk_sha1"] = _operation("bulk_sha1", "Bulk Look Up SHA-1 Hashes")
    hashes: list[SHA1] = Field(..., min_length=1, max_length=1000)


class _Relations(_Input):
    sha1: SHA1
    count: int = Field(100, ge=1, le=1000, description="Maximum relationships to return in this page.")
    cursor: str = Field("0", pattern=r"^[A-Za-z0-9_-]{1,256}$", description="Start with 0. For another page, return the provider's opaque cursor unchanged with the same hash and count (may be numeric or a hash).")


class GetParents(_Relations):
    """Read one page of parent file hashes; preserve the provider's cursor."""
    operation: Literal["get_parents"] = _operation("get_parents", "Get Parent Hashes")


class GetChildren(_Relations):
    """Read one page of child file hashes; preserve the provider's cursor."""
    operation: Literal["get_children"] = _operation("get_children", "Get Child Hashes")


class GetInfo(_Input):
    """Read database versions and dataset statistics; proves public reachability."""
    operation: Literal["get_info"] = _operation("get_info", "Get Database Information")


class GetTop(_Input):
    """Read the 100 most queried values when public statistics are enabled."""
    operation: Literal["get_top"] = _operation("get_top", "Get Most Queried Hashes")


class _Session(_Input):
    name: SessionName = Field(..., title="Session name", description="For a server with sessions enabled. This feature is disabled on the public CIRCL instance.")


class CreateSession(_Session):
    """Create a forensic session or reset its TTL (a write, despite HTTP GET)."""
    operation: Literal["create_session"] = _operation("create_session", "Create or Renew Session (Server Feature)")


class GetSession(_Session):
    """Read matching and non-matching hashes recorded in an enabled session."""
    operation: Literal["get_session"] = _operation("get_session", "Get Session Matches (Server Feature)")


CirclConfig = Annotated[Union[LookupMD5, LookupSHA1, LookupSHA256, BulkMD5,
    BulkSHA1, GetParents, GetChildren, GetInfo, GetTop, CreateSession, GetSession],
    Field(discriminator="operation")]


class CirclFullConfig(NodeConfig[CirclConfig, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        return None if value == {} else value


class CirclNode(WorkflowNode):
    integration_type = "automation-circl"
    connection_evidence = ConnectionEvidence(operation="get_info", noun="public hashlookup database information", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return CirclFullConfig

    async def execute(self, inputs):
        config = self.config.config
        method, body = "GET", None
        headers = {"Accept": "application/json"}
        if isinstance(config, (LookupMD5, LookupSHA1, LookupSHA256)):
            algorithm = config.operation.removeprefix("lookup_")
            digest = getattr(config, algorithm)
            path = f"/lookup/{algorithm}/{digest}"
            if config.session_name is not None:
                headers["hashlookup_session"] = config.session_name
        elif isinstance(config, (BulkMD5, BulkSHA1)):
            method, path, body = "POST", "/bulk/" + config.operation.removeprefix("bulk_"), {"hashes": config.hashes}
        elif isinstance(config, _Relations):
            relation = "parents" if isinstance(config, GetParents) else "children"
            path = f"/{relation}/{config.sha1}/{config.count}/{config.cursor}"
        elif isinstance(config, _Session):
            action = "create" if isinstance(config, CreateSession) else "get"
            path = f"/session/{action}/{quote(config.name, safe='')}"
        else:
            path = "/info" if isinstance(config, GetInfo) else "/stats/top"
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, config.server_url + path, headers=headers,
                **({"json": body} if body is not None else {}))
        # A missing hash is an expected lookup result, not a broken connection.
        if response.status_code == 404 and isinstance(config, _Lookup):
            missing = self._json(response)
            if not isinstance(missing, dict) or not isinstance(missing.get("message"), str):
                raise ValueError("Hashlookup did not return a JSON nonmatch message")
            return {"status": "success", "operation": config.operation, "found": False,
                    "data": missing, "http_status": 404}
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("Hashlookup returned a redirect instead of JSON")
        result = self._json(response)
        if isinstance(config, _Lookup):
            key = {"md5": "MD5", "sha1": "SHA-1", "sha256": "SHA-256"}[algorithm]
            returned = result.get(key) if isinstance(result, dict) else None
            if not isinstance(returned, str) or returned.casefold() != digest.casefold():
                raise ValueError("Hashlookup did not return the requested file hash")
        # The contract has no response schemas. Preserve all provider fields and
        # pagination verbatim, including colon/hyphen keys and mixed metadata.
        return {"status": "success", "operation": config.operation, "data": result,
                "http_status": response.status_code,
                **({"found": True} if isinstance(config, _Lookup) else {})}

    @staticmethod
    def _json(response):
        if len(response.content) > 10_000_000:
            raise ValueError("Hashlookup response exceeds 10 MB; use a smaller batch or page")
        media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            raise ValueError("Expected a JSON response from hashlookup")
        result = response.json()
        if not isinstance(result, (dict, list)) or isinstance(result, dict) and "error" in result:
            raise ValueError("Hashlookup returned an invalid response or error envelope")
        return result

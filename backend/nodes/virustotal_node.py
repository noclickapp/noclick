"""VirusTotal v3 reports, URL submissions and rescans using a personal API key."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://www.virustotal.com/api/v3"


class VirusTotalAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="VirusTotal API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.virustotal.com/gui/my-apikey",
            "x-credential-instructions": "Paste your VirusTotal API key from your account's API key page. Your plan's permissions and quotas apply. Indicators submitted or queried may be scanned and shared with the community; do not use sensitive or confidential indicators.",
        })
    credential_type: Literal["virustotal_api_key"] = Field("virustotal_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _File(_Operation):
    file_id: str = Field(..., min_length=1, max_length=256, description="File SHA-256, SHA-1 or MD5 hash.")


class _URL(_Operation):
    url_id: str = Field(..., min_length=1, max_length=4096, description="URL identifier: SHA-256 or URL-safe base64 of the URL without padding.")


class _Domain(_Operation):
    domain: str = Field(..., min_length=1, max_length=253, description="Domain name, for example example.com.")


class _IP(_Operation):
    ip: str = Field(..., min_length=1, max_length=45, description="IPv4 or IPv6 address.")


class _Page(_Operation):
    limit: int = Field(10, ge=1, le=40, description="Maximum results in this page.")
    cursor: str | None = Field(None, description="Continuation cursor from the preceding response's meta.cursor.")


class GetAccount(_Operation):
    """Read the account that owns this API key."""
    operation: Literal["get_account"] = "get_account"


class GetFile(_File):
    """Get a file report."""
    operation: Literal["get_file"] = "get_file"


class GetURL(_URL):
    """Get a URL report."""
    operation: Literal["get_url"] = "get_url"


class GetDomain(_Domain):
    """Get a domain report."""
    operation: Literal["get_domain"] = "get_domain"


class GetIP(_IP):
    """Get an IP address report."""
    operation: Literal["get_ip"] = "get_ip"


class GetAnalysis(_Operation):
    """Get the status and results of a URL or file analysis."""
    operation: Literal["get_analysis"] = "get_analysis"
    analysis_id: str = Field(..., min_length=1, max_length=1024, description="Analysis ID returned by a submission or rescan.")


class ScanURL(_Operation):
    """Submit a URL to VirusTotal for scanning."""
    operation: Literal["scan_url"] = "scan_url"
    url: str = Field(..., min_length=1, max_length=16384, pattern=r"^https?://.+$", description="Public HTTP(S) URL to submit to VirusTotal.")


class RescanFile(_File):
    """Request another analysis of a previously submitted file."""
    operation: Literal["rescan_file"] = "rescan_file"


class RescanURL(_URL):
    """Request another analysis of a previously submitted URL."""
    operation: Literal["rescan_url"] = "rescan_url"


class GetFileBehaviorSummary(_File):
    """Get the summary of sandbox behavior reports for a file."""
    operation: Literal["get_file_behavior_summary"] = "get_file_behavior_summary"


class ListFileComments(_File, _Page):
    """Get one page of comments for this file."""
    operation: Literal["list_file_comments"] = "list_file_comments"


class ListFileVotes(_File, _Page):
    """Get one page of votes for this file."""
    operation: Literal["list_file_votes"] = "list_file_votes"


class ListURLComments(_URL, _Page):
    """Get one page of comments for this url."""
    operation: Literal["list_url_comments"] = "list_url_comments"


class ListURLVotes(_URL, _Page):
    """Get one page of votes for this url."""
    operation: Literal["list_url_votes"] = "list_url_votes"


class ListDomainComments(_Domain, _Page):
    """Get one page of comments for this domain."""
    operation: Literal["list_domain_comments"] = "list_domain_comments"


class ListDomainVotes(_Domain, _Page):
    """Get one page of votes for this domain."""
    operation: Literal["list_domain_votes"] = "list_domain_votes"


class ListIPComments(_IP, _Page):
    """Get one page of comments for this ip."""
    operation: Literal["list_ip_comments"] = "list_ip_comments"


class ListIPVotes(_IP, _Page):
    """Get one page of votes for this ip."""
    operation: Literal["list_ip_votes"] = "list_ip_votes"


Operation = Annotated[Union[
    GetAccount, GetFile, GetURL, GetDomain, GetIP, GetAnalysis, ScanURL, RescanFile, RescanURL, GetFileBehaviorSummary, ListFileComments, ListFileVotes, ListURLComments, ListURLVotes, ListDomainComments, ListDomainVotes, ListIPComments, ListIPVotes
], Field(discriminator="operation")]


class VirusTotalConfig(NodeConfig[Operation, VirusTotalAPIKeyCredential]):
    pass


# Each operation makes exactly one request to one published v3 endpoint.
ROUTES = {
    "get_account": ("GET", "/users/{api_key}"),
    "get_file": ("GET", "/files/{file_id}"),
    "get_url": ("GET", "/urls/{url_id}"),
    "get_domain": ("GET", "/domains/{domain}"),
    "get_ip": ("GET", "/ip_addresses/{ip}"),
    "get_analysis": ("GET", "/analyses/{analysis_id}"),
    "scan_url": ("POST", "/urls"),
    "rescan_file": ("POST", "/files/{file_id}/analyse"),
    "rescan_url": ("POST", "/urls/{url_id}/analyse"),
    "get_file_behavior_summary": ("GET", "/files/{file_id}/behaviour_summary"),
    "list_file_comments": ("GET", "/files/{file_id}/comments"),
    "list_file_votes": ("GET", "/files/{file_id}/votes"),
    "list_url_comments": ("GET", "/urls/{url_id}/comments"),
    "list_url_votes": ("GET", "/urls/{url_id}/votes"),
    "list_domain_comments": ("GET", "/domains/{domain}/comments"),
    "list_domain_votes": ("GET", "/domains/{domain}/votes"),
    "list_ip_comments": ("GET", "/ip_addresses/{ip}/comments"),
    "list_ip_votes": ("GET", "/ip_addresses/{ip}/votes"),
}


def _segment(value):
    if value in {".", ".."} or any(c in value for c in "/?#\\") or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValueError("Use a resource identifier, not a URL or path")
    return quote(value, safe="")


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()
                if key.lower().replace("-", "_") not in {"apikey", "api_key", "password", "token"}}
    return value


class VirusTotalNode(WorkflowNode):
    integration_type = "automation-virustotal"
    connection_evidence = ConnectionEvidence(noun="VirusTotal account", identity_operation="get_account",
        identity_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return VirusTotalConfig

    async def execute(self, inputs):
        config = self.config
        if not config.credentials:
            raise ValueError("Attach a VirusTotal API key")
        token = config.credentials.api_key
        op = config.config
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        values["api_key"] = token
        for field in ("file_id", "url_id", "domain", "ip", "analysis_id", "api_key"):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", _segment(values[field]))
        params = {name: values[name] for name in ("limit", "cursor") if name in values}
        request_args = {}
        if isinstance(op, ScanURL):
            parsed = urlsplit(op.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Use a complete HTTP(S) URL")
            request_args["data"] = {"url": op.url}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + route, params=params,
                    headers={"x-apikey": token, "Accept": "application/json", "x-tool": "NoClick"}, **request_args)
            if not response.is_success:
                try:
                    error = response.json().get("error", {})
                    message = error.get("message") or error.get("code") or f"VirusTotal returned HTTP {response.status_code}"
                except (ValueError, AttributeError):
                    message = f"VirusTotal returned HTTP {response.status_code}"
                return {"status": "error", "error": _redact(str(message), token), "http_status": response.status_code}
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Expected a VirusTotal JSON object")
            if body.get("error"):
                return {"status": "error", "error": _redact(str(body["error"]), token)}
            result = {"status": "success", **_redact(body, token)}
            if isinstance(op, GetAccount):
                account = body.get("data")
                if not isinstance(account, dict) or account.get("type") != "user" or not account.get("id"):
                    raise ValueError("Expected a VirusTotal user object")
                result["id"] = _redact(str(account["id"]), token)
                result["name"] = _redact(str(account.get("attributes", {}).get("first_name") or account["id"]), token)
            return result
        except httpx.RequestError:
            # Request exceptions include the account URL, which contains the API key.
            raise ValueError("VirusTotal request failed; retry or check connectivity") from None

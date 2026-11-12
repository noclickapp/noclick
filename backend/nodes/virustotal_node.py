"""VirusTotal v3 reports, URL submissions and rescans using a personal API key."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin, _scope_of_op_config
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


class OnNewIOCNotification(PollTriggerConfigBase):
    """Watch new IoC Stream notifications; requires IoC Stream access on your plan."""
    operation: Literal["on_new_ioc_notification"] = Field("on_new_ioc_notification", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New IoC Notification",
    })
    filter: str | None = Field(None, title="Notification filter", description=
        "Optional IoC Stream filter, for example entity_type:file or source_id:7926136120. "
        "Existing notifications are recorded when armed; only later notifications start runs.")


class OnNewLivehuntMatch(PollTriggerConfigBase):
    """Watch new Livehunt YARA matches; requires Livehunt access on your plan."""
    operation: Literal["on_new_livehunt_match"] = Field("on_new_livehunt_match", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "New Livehunt Match",
    })
    ruleset_id: str | None = Field(None, title="Ruleset ID", description=
        "Optional Livehunt ruleset ID. Leave empty to watch all your Livehunt rulesets.")


# VirusTotal's own MCP server: agents get its tools through a person's VirusTotal sign-in.
# Signs in to a VirusTotal AI account, apart from any VirusTotal API plan.
VirustotalMcpCredential = mcp_credential("virustotal", "https://ai.virustotal.com/mcp", app="VirusTotal")
VirusTotalCredential = Union[VirusTotalAPIKeyCredential, VirustotalMcpCredential]


Operation = Annotated[Union[
    GetAccount, GetFile, GetURL, GetDomain, GetIP, GetAnalysis, ScanURL, RescanFile, RescanURL, GetFileBehaviorSummary, ListFileComments, ListFileVotes, ListURLComments, ListURLVotes, ListDomainComments, ListDomainVotes, ListIPComments, ListIPVotes, OnNewIOCNotification, OnNewLivehuntMatch
], Field(discriminator="operation")]


class VirusTotalConfig(NodeConfig[Operation, VirusTotalCredential]):
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


class VirusTotalNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-virustotal"
    credential_provider_labels = {"virustotal": "VirusTotal Account"}
    connection_evidence = ConnectionEvidence(noun="VirusTotal account", identity_operation="get_account",
        identity_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return VirusTotalConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in {"on_new_ioc_notification", "on_new_livehunt_match"}:
            return bool(output.get("new_notification_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        notifications = output.get("notifications") if isinstance(output, dict) else None
        if not isinstance(notifications, list):
            return super().resolve_agent_event(output)
        if not notifications:
            return None
        lines = []
        for item in notifications[:10]:
            context = item["context_attributes"]
            sources = ", ".join(f"{source.get('label') or source.get('type')} (id {source.get('id')})"
                                for source in context.get("sources", []))
            rule = context.get("hunting_info", {}).get("rule_name")
            lines.append(f"- {context.get('origin', 'IoC Stream')} notification {context['notification_id']}: "
                         f"{item.get('type')} {item.get('id')} at {context.get('notification_date')}"
                         + (f"; matched rule {rule}" if rule else "")
                         + (f"; source {sources}" if sources else "")
                         + (f"; tags {', '.join(context['tags'])}" if context.get("tags") else ""))
        if len(notifications) > 10:
            lines.append(f"… and {len(notifications) - 10} more notifications in the output.")
        return {"text": f"VirusTotal: {len(notifications)} new notification(s):\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_notifications(self, op):
        # Snapshot only the latest page when arming. Subsequent polls walk
        # newest-first until the previous window, so bursts span multiple pages.
        state = await self._update_node_state(lambda state: (None, state), skip_result=None)
        if state is None:
            raise ValueError("Could not read VirusTotal trigger state; retry the poll")
        baseline = "seen_ids" not in state or state.get("scope", _scope_of_op_config(op)) != _scope_of_op_config(op)
        known = set(state.get("seen_ids", [])) if not baseline else set()
        params = {"limit": 40, "order": "date-", "descriptors_only": True}
        if isinstance(op, OnNewLivehuntMatch):
            params["filter"] = "origin:hunting source_type:hunting_ruleset"
            if op.ruleset_id:
                params["filter"] += " source_id:" + _segment(op.ruleset_id)
        elif op.filter:
            params["filter"] = op.filter
        items, collected = [], set()
        for _ in range(100):
            result = await self._request("GET", "/ioc_stream", params=params, check_error=False, redact=False)
            if result.get("status") == "error":
                return result
            page = result.get("data")
            if not isinstance(page, list):
                raise ValueError("Expected a VirusTotal IoC Stream list")
            reached_known = False
            for item in page:
                context = item.get("context_attributes") if isinstance(item, dict) else None
                notification_id = context.get("notification_id") if isinstance(context, dict) else None
                if not isinstance(notification_id, str) or not notification_id:
                    raise ValueError("Expected a VirusTotal notification ID")
                if notification_id in known or notification_id in collected:
                    reached_known = True
                if notification_id not in collected:
                    items.append(item)
                    collected.add(notification_id)
            if baseline or reached_known or not page or not result.get("links", {}).get("next"):
                break
            cursor = result.get("meta", {}).get("cursor")
            if not cursor or cursor == params.get("cursor"):
                raise ValueError("VirusTotal returned a missing or repeated continuation cursor")
            params["cursor"] = cursor
        else:
            raise ValueError("More than 4,000 new notifications; narrow the trigger filter and retry")
        fresh = await self._filter_unseen(items, lambda item: item["context_attributes"]["notification_id"])
        return {"status": "success", "notifications": _redact(fresh, self.config.credentials.api_key), "new_notification_count": len(fresh)}

    async def execute(self, inputs):
        op = self.config.config
        if isinstance(op, (OnNewIOCNotification, OnNewLivehuntMatch)):
            return await self._poll_notifications(op)
        method, route = ROUTES[op.operation]
        return await self._request(method, route, values=op.model_dump(exclude_none=True), scan_url=op.url if isinstance(op, ScanURL) else None,
                                   account=isinstance(op, GetAccount))

    async def _request(self, method, route, *, values=None, params=None, scan_url=None, account=False, check_error=True, redact=True):
        config = self.config
        if not config.credentials:
            raise ValueError("Attach a VirusTotal API key")
        token = config.credentials.api_key
        values = dict(values or {})
        values["api_key"] = token
        for field in ("file_id", "url_id", "domain", "ip", "analysis_id", "api_key"):
            if "{" + field + "}" in route:
                route = route.replace("{" + field + "}", _segment(values[field]))
        params = params if params is not None else {name: values[name] for name in ("limit", "cursor") if name in values}
        request_args = {}
        if scan_url is not None:
            parsed = urlsplit(scan_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Use a complete HTTP(S) URL")
            request_args["data"] = {"url": scan_url}
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
            if check_error and body.get("error"):
                return {"status": "error", "error": _redact(str(body["error"]), token)}
            result = {"status": "success", **(_redact(body, token) if redact else body)}
            if account:
                account = body.get("data")
                if not isinstance(account, dict) or account.get("type") != "user" or not account.get("id"):
                    raise ValueError("Expected a VirusTotal user object")
                result["id"] = _redact(str(account["id"]), token)
                result["name"] = _redact(str(account.get("attributes", {}).get("first_name") or account["id"]), token)
            return result
        except httpx.RequestError:
            # Request exceptions include the account URL, which contains the API key.
            raise ValueError("VirusTotal request failed; retry or check connectivity") from None

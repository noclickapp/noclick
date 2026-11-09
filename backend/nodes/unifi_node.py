"""UniFi Site Manager v1.0.0 inventory, metrics and console connector.

https://developer.ui.com/site-manager/v1.0.0/openapi.json
"""
from __future__ import annotations
import re
import json
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.binary_output import BinaryOutput
from utils.ssrf import guarded_async_client

BASE = "https://api.ui.com"

class UnifiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="UniFi API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://unifi.ui.com/",
            "x-credential-instructions": "Create an API key in UniFi Site Manager Settings > API Keys and paste it here. Inventory and metrics use the key owner's access. Console requests require firmware 5.0.3 or later and access to the owner's console, or a console in the key's organization."})
    credential_type: Literal["unifi_api_key"] = Field("unifi_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("body", "sites", "host_ids", mode="before", check_fields=False)
    @classmethod
    def json_field(cls, value):
        # The config UI can supply JSON text; expressions can supply native values.
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                raise ValueError("Enter valid JSON") from None
        return value

class _Page(_Input):
    page_size: str | None = Field(None, description="Items per page (pageSize).")
    next_token: str | None = Field(None, description="Opaque nextToken from the previous response. One page per execution.")

class _ID(_Input):
    id: str = Field(..., min_length=1, max_length=512, description="Host or SD-WAN configuration ID from its list operation.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_:.~-]+", value):
            raise ValueError("Use a single UniFi ID")
        return value

class _Metrics(_Input):
    type: Literal["5m", "1h"] = Field("5m", title="Metric interval")

class _Window(_Input):
    begin_timestamp: str | None = None
    end_timestamp: str | None = None

    @field_validator("begin_timestamp", "end_timestamp")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if stamp.tzinfo is None: raise ValueError()
            except ValueError:
                raise ValueError("Use an RFC3339 timestamp with timezone") from None
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.begin_timestamp and self.end_timestamp:
            if datetime.fromisoformat(self.begin_timestamp.replace("Z", "+00:00")) >= datetime.fromisoformat(self.end_timestamp.replace("Z", "+00:00")):
                raise ValueError("End timestamp must be after begin timestamp")
        return self

class UnifiMetricSite(_Window):
    host_id: str = Field(..., min_length=1)
    site_id: str = Field(..., min_length=1)

class _Connector(_ID):
    path: str = Field(..., min_length=1, max_length=4096, description="Application API path, e.g. network/integration/v1/sites. No host, /proxy prefix, query or fragment. Requires firmware >=5.0.3 and access to the console.")

    @field_validator("path")
    @classmethod
    def application_path(cls, value):
        if not re.fullmatch(r"(?:network|protect|innerspace)/integration/v[0-9]+(?:/[A-Za-z0-9_~-]+)*", value):
            raise ValueError("Use a UniFi application integration API path without a leading slash")
        return value

class _ConnectorBody(_Connector):
    body: dict[str, Any] = Field(..., description="JSON object for the target application's documented endpoint. Sent unchanged. No automatic retries.")

class UnifiListHostsConfig(_Page):
    """List hosts associated with your UI account."""
    operation: Literal["list_hosts"] = Field("list_hosts", json_schema_extra={"ui:hidden": True})

class UnifiGetHostConfig(_ID):
    """Get a host by ID."""
    operation: Literal["get_host"] = Field("get_host", json_schema_extra={"ui:hidden": True})

class UnifiListSitesConfig(_Page):
    """List Network sites and statistics."""
    operation: Literal["list_sites"] = Field("list_sites", json_schema_extra={"ui:hidden": True})

class UnifiListDevicesConfig(_Page):
    """List devices managed by your hosts."""
    operation: Literal["list_devices"] = Field("list_devices", json_schema_extra={"ui:hidden": True})
    host_ids: list[str] | None = None
    time: str | None = Field(None, description="Last processed timestamp in RFC3339 format.")

class UnifiGetISPMetricsConfig(_Metrics, _Window):
    """Get ISP metrics across all sites."""
    operation: Literal["get_isp_metrics"] = Field("get_isp_metrics", json_schema_extra={"ui:hidden": True})
    duration: Literal["24h", "7d", "30d"] | None = None

    @model_validator(mode="after")
    def duration_window(self):
        if self.duration and (self.begin_timestamp or self.end_timestamp):
            raise ValueError("Use duration or timestamps, not both")
        if self.duration and ((self.type == "5m" and self.duration != "24h") or (self.type == "1h" and self.duration == "24h")):
            raise ValueError("Use 24h for 5m metrics, or 7d/30d for 1h metrics")
        return self

class UnifiQueryISPMetricsConfig(_Metrics):
    """Query ISP metrics for host/site pairs; partialSuccess is preserved."""
    operation: Literal["query_isp_metrics"] = Field("query_isp_metrics", json_schema_extra={"ui:hidden": True})
    sites: list[UnifiMetricSite] = Field(..., min_length=1)

class UnifiListSDWanConfigsConfig(_Input):
    """List SD-WAN configurations."""
    operation: Literal["list_sd_wan_configs"] = Field("list_sd_wan_configs", json_schema_extra={"ui:hidden": True})

class UnifiGetSDWanConfigConfig(_ID):
    """Get a SD-WAN configuration."""
    operation: Literal["get_sd_wan_config"] = Field("get_sd_wan_config", json_schema_extra={"ui:hidden": True})

class UnifiGetSDWanConfigStatusConfig(_ID):
    """Get SD-WAN deployment status."""
    operation: Literal["get_sd_wan_config_status"] = Field("get_sd_wan_config_status", json_schema_extra={"ui:hidden": True})

class UnifiConnectorGetConfig(_Connector):
    """Forward one GET request to a console application. Consult the application API contract for its payload."""
    operation: Literal["connector_get"] = Field("connector_get", json_schema_extra={"ui:hidden": True})

class UnifiConnectorPostConfig(_ConnectorBody):
    """Forward one POST request to a console application. Consult the application API contract for its payload."""
    operation: Literal["connector_post"] = Field("connector_post", json_schema_extra={"ui:hidden": True})

class UnifiConnectorPutConfig(_ConnectorBody):
    """Forward one PUT request to a console application. Consult the application API contract for its payload."""
    operation: Literal["connector_put"] = Field("connector_put", json_schema_extra={"ui:hidden": True})

class UnifiConnectorPatchConfig(_ConnectorBody):
    """Forward one PATCH request to a console application. Consult the application API contract for its payload."""
    operation: Literal["connector_patch"] = Field("connector_patch", json_schema_extra={"ui:hidden": True})

class UnifiConnectorDeleteConfig(_Connector):
    """Forward one DELETE request to a console application. Consult the application API contract for its payload."""
    operation: Literal["connector_delete"] = Field("connector_delete", json_schema_extra={"ui:hidden": True})


UnifiConfig = Annotated[Union[
    UnifiListHostsConfig,
    UnifiGetHostConfig,
    UnifiListSitesConfig,
    UnifiListDevicesConfig,
    UnifiGetISPMetricsConfig,
    UnifiQueryISPMetricsConfig,
    UnifiListSDWanConfigsConfig,
    UnifiGetSDWanConfigConfig,
    UnifiGetSDWanConfigStatusConfig,
    UnifiConnectorGetConfig,
    UnifiConnectorPostConfig,
    UnifiConnectorPutConfig,
    UnifiConnectorPatchConfig,
    UnifiConnectorDeleteConfig
], Field(discriminator="operation")]

class UnifiFullConfig(NodeConfig[UnifiConfig, UnifiAPIKeyCredential]):
    pass

class UnifiNode(WorkflowNode):
    integration_type = "automation-unifi"
    connection_evidence = ConnectionEvidence(noun="UniFi hosts", operation="list_hosts")

    @classmethod
    def get_config_model(cls):
        return UnifiFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a UniFi API key")
        cfg = self.config.config
        operation = cfg.operation
        params = {}
        body = None
        method = "GET"
        if operation.startswith("connector_"):
            method = operation.removeprefix("connector_").upper()
            path = "/v1/connector/consoles/" + quote(cfg.id, safe="") + "/" + cfg.path
            if isinstance(cfg, _ConnectorBody): body = cfg.body
        elif operation in {"get_isp_metrics", "query_isp_metrics"}:
            path = "/v1/isp-metrics/" + cfg.type
            if operation == "query_isp_metrics":
                method = "POST"
                path += "/query"
                body = {"sites": [{
                    {"host_id": "hostId", "site_id": "siteId", "begin_timestamp": "beginTimestamp", "end_timestamp": "endTimestamp"}[k]: v
                    for k, v in site.model_dump(exclude_none=True).items()
                } for site in cfg.sites]}
            else:
                for field, wire in (("begin_timestamp", "beginTimestamp"), ("end_timestamp", "endTimestamp"), ("duration", "duration")):
                    if getattr(cfg, field) is not None: params[wire] = getattr(cfg, field)
        else:
            routes = {"list_hosts": "/v1/hosts", "get_host": "/v1/hosts/{id}",
                "list_sites": "/v1/sites", "list_devices": "/v1/devices",
                "list_sd_wan_configs": "/v1/sd-wan-configs",
                "get_sd_wan_config": "/v1/sd-wan-configs/{id}",
                "get_sd_wan_config_status": "/v1/sd-wan-configs/{id}/status"}
            path = routes[operation]
            if isinstance(cfg, _ID): path = path.replace("{id}", quote(cfg.id, safe=""))
        if isinstance(cfg, _Page):
            if cfg.page_size is not None: params["pageSize"] = cfg.page_size
            if cfg.next_token is not None: params["nextToken"] = cfg.next_token
        if operation == "list_devices":
            if cfg.host_ids is not None: params["hostIds[]"] = cfg.host_ids
            if cfg.time is not None: params["time"] = cfg.time
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers={"X-API-Key": self.config.credentials.api_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = "UniFi request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(self.config.credentials.api_key, "[redacted]")
            except ValueError:
                pass
            result = {"status": "error", "success": False, "http_status": response.status_code, "message": message}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("UniFi response exceeds the connector's 10 MB limit")
            if not response.content:
                data = None
            elif "json" in response.headers.get("content-type", "").lower():
                data = response.json()
            elif operation.startswith("connector_"):
                data = BinaryOutput(response.content, response.headers.get("content-type", "application/octet-stream"), "unifi-response")
            else:
                raise ValueError("Expected JSON from UniFi Site Manager")
            if isinstance(data, dict) and (data.get("httpStatusCode", 200) >= 400 or data.get("code") in {"unauthorized", "forbidden", "server_error"}):
                raise ValueError("UniFi returned an error envelope")
            result = {"status": "success", "success": True, "data": data}
        await self.emit(result)
        return result

"""Smartproxy (now Decodo) public proxy management and dashboard statistics API."""
from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.decodo.com"


class SmartproxyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Smartproxy API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.decodo.com/profile?tab=api-keys",
        "x-credential-instructions": "Smartproxy is now Decodo. In Account and Settings → Settings → API Keys, create a Public API key and paste it here. Residential proxies support management operations; mobile proxies support only dashboard traffic and targets. Datacenter and ISP products are not supported by this API.",
    })
    credential_type: Literal["smartproxy_api_key"] = Field("smartproxy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without an Authorization header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Residential(Input):
    service_type: Literal["residential_proxies"] = Field("residential_proxies", title="Service Type")


class SubUser(Input):
    sub_user_id: int = Field(..., title="Subuser ID", gt=0)


class ListSubUsers(Residential):
    operation: Literal["list_sub_users"] = Field("list_sub_users", title="List Subusers", json_schema_extra={"ui:hidden": True})


class CreateSubUser(Residential):
    operation: Literal["create_sub_user"] = Field("create_sub_user", title="Create Subuser", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=6, max_length=64, pattern=r"^[A-Za-z0-9_]+$", title="Username")
    password: str = Field(..., min_length=12, max_length=64, title="Password", description="12–64 characters, including uppercase, lowercase, a number and one of _ ~ + =. Do not use @ or :.", json_schema_extra={"ui:widget": "password"})
    traffic_limit: float | None = Field(None, ge=0, title="Traffic Limit (GB)")
    auto_disable: bool = Field(False, title="Disable at Traffic Limit")


class GetSubUser(SubUser):
    operation: Literal["get_sub_user"] = Field("get_sub_user", title="Get Subuser", json_schema_extra={"ui:hidden": True})


class UpdateSubUser(SubUser):
    operation: Literal["update_sub_user"] = Field("update_sub_user", title="Update Subuser", json_schema_extra={"ui:hidden": True})
    traffic_limit: float | None = Field(None, ge=0, title="Traffic Limit (GB)")
    auto_disable: bool | None = Field(None, title="Disable at Traffic Limit")
    password: str | None = Field(None, min_length=12, max_length=64, title="New Password", json_schema_extra={"ui:widget": "password"})
    status: Literal["active", "disabled"] | None = Field(None, title="Subuser Status")

    @model_validator(mode="after")
    def has_update(self):
        if not any(getattr(self, key) is not None for key in ("traffic_limit", "auto_disable", "password", "status")):
            raise ValueError("Supply at least one subuser change")
        return self


class DeleteSubUser(SubUser):
    operation: Literal["delete_sub_user"] = Field("delete_sub_user", title="Delete Subuser", json_schema_extra={"ui:hidden": True})


class GetSubUserTraffic(SubUser, Residential):
    operation: Literal["get_sub_user_traffic"] = Field("get_sub_user_traffic", title="Get Subuser Traffic", json_schema_extra={"ui:hidden": True})
    period: Literal["24h", "7days", "month", "custom"] = Field("month", title="Period")
    from_date: str | None = Field(None, title="From Date", description="YYYY-MM-DD; applies to custom period")
    to_date: str | None = Field(None, title="To Date", description="YYYY-MM-DD; applies to custom period")

    @field_validator("from_date", "to_date")
    @classmethod
    def date(cls, value):
        if value is not None:
            datetime.strptime(value, "%Y-%m-%d")
        return value


class GetAllocatedTraffic(Residential):
    operation: Literal["get_allocated_traffic"] = Field("get_allocated_traffic", title="Get Allocated Subuser Traffic", json_schema_extra={"ui:hidden": True})


class ListWhitelistedIPs(Input):
    operation: Literal["list_whitelisted_ips"] = Field("list_whitelisted_ips", title="List Whitelisted IPs", json_schema_extra={"ui:hidden": True})


class AddWhitelistedIPs(Input):
    operation: Literal["add_whitelisted_ips"] = Field("add_whitelisted_ips", title="Add Whitelisted IPs", json_schema_extra={"ui:hidden": True})
    ip_addresses: list[str] = Field(..., min_length=1, title="IP Addresses")

    @field_validator("ip_addresses")
    @classmethod
    def ips(cls, value):
        for item in value:
            ip_address(item)
        return value


class DeleteWhitelistedIP(Input):
    operation: Literal["delete_whitelisted_ip"] = Field("delete_whitelisted_ip", title="Delete Whitelisted IP", json_schema_extra={"ui:hidden": True})
    whitelist_id: str = Field(..., min_length=1, max_length=128, title="Whitelist Entry ID", pattern=r"^[A-Za-z0-9_-]+$")


class ListEndpointTypes(Input):
    operation: Literal["list_endpoint_types"] = Field("list_endpoint_types", title="List Endpoint Types", json_schema_extra={"ui:hidden": True})


class GetEndpointsByType(Input):
    operation: Literal["get_endpoints_by_type"] = Field("get_endpoints_by_type", title="Get Endpoints by Type", json_schema_extra={"ui:hidden": True})
    session_type: Literal["random", "sticky"] = Field("random", title="Session Type")


class GetSubscriptions(Input):
    operation: Literal["get_subscriptions"] = Field("get_subscriptions", title="Get Subscriptions", json_schema_extra={"ui:hidden": True})


class Statistics(Input):
    proxy_type: Literal["residential_proxies", "mobile_proxies", "rtc_universal_proxies", "rtc_universal_core_proxies", "modular_scraper"] = Field("residential_proxies", title="Proxy Type")
    start_date: str = Field(..., title="Start Date", description="UTC YYYY-MM-DD HH:MM:SS; interval at most 180 days")
    end_date: str = Field(..., title="End Date", description="UTC YYYY-MM-DD HH:MM:SS")
    proxy_users: list[str] | None = Field(None, title="Proxy User IDs", description="Residential proxies only")

    @model_validator(mode="after")
    def date_range(self):
        start = datetime.strptime(self.start_date, "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(self.end_date, "%Y-%m-%d %H:%M:%S")
        if not 0 < (end - start).total_seconds() <= 180 * 86400:
            raise ValueError("Select a positive date interval of at most 180 days")
        return self


class GetTargets(Statistics):
    operation: Literal["get_targets"] = Field("get_targets", title="Get Traffic Targets", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, min_length=3, title="Search Targets")


class GetTraffic(Statistics):
    operation: Literal["get_traffic"] = Field("get_traffic", title="Get Traffic Statistics", json_schema_extra={"ui:hidden": True})
    group_by: Literal["day", "target", "country", "protocol", "proxy_user", "hour", "week", "month"] = Field("target", title="Group By")
    targets: list[str] | None = Field(None, title="Target URLs")
    locations: list[str] | None = Field(None, title="Country Codes", description="ISO-2 codes, for example US or IT")
    limit: int = Field(500, ge=1, title="Page Size")
    page: int = Field(1, ge=1, title="Page")
    sort_by: Literal["grouping_key", "requests", "totals"] = Field("grouping_key", title="Sort By")
    sort_order: Literal["asc", "desc"] = Field("asc", title="Sort Order")
    protocols: list[Literal["http", "https", "socks5"]] | None = Field(None, title="Protocols")


Operation = Annotated[Union[ListSubUsers, CreateSubUser, GetSubUser, UpdateSubUser, DeleteSubUser,
    GetSubUserTraffic, GetAllocatedTraffic, ListWhitelistedIPs, AddWhitelistedIPs, DeleteWhitelistedIP,
    ListEndpointTypes, GetEndpointsByType, GetSubscriptions, GetTargets, GetTraffic], Field(discriminator="operation")]


class SmartproxyConfig(NodeConfig[Operation, SmartproxyAPIKeyCredential]):
    pass


# Each entry corresponds to exactly one operation in the public v1.2 contracts.
ROUTES = {
    "list_sub_users": ("GET", "/v2/sub-users"),
    "create_sub_user": ("POST", "/v2/sub-users"),
    "get_sub_user": ("GET", "/v2/sub-users/{sub_user_id}"),
    "update_sub_user": ("PUT", "/v2/sub-users/{sub_user_id}"),
    "delete_sub_user": ("DELETE", "/v2/sub-users/{sub_user_id}"),
    "get_sub_user_traffic": ("GET", "/v2/sub-users/{sub_user_id}/traffic"),
    "get_allocated_traffic": ("GET", "/v2/allocated-traffic-limit"),
    "list_whitelisted_ips": ("GET", "/v2/whitelisted-ips"),
    "add_whitelisted_ips": ("POST", "/v2/whitelisted-ips"),
    "delete_whitelisted_ip": ("DELETE", "/v2/whitelisted-ips/{whitelist_id}"),
    "list_endpoint_types": ("GET", "/v2/endpoints"),
    "get_endpoints_by_type": ("GET", "/v2/endpoints/{session_type}"),
    "get_subscriptions": ("GET", "/v2/subscriptions"),
    "get_targets": ("POST", "/api/v2/statistics/targets"),
    "get_traffic": ("POST", "/api/v2/statistics/traffic"),
}
ALIASES = {"period": "type", "from_date": "from", "to_date": "to", "ip_addresses": "IPAddressList",
    "proxy_type": "proxyType", "start_date": "startDate", "end_date": "endDate", "proxy_users": "proxyUsers",
    "group_by": "groupBy", "sort_by": "sortBy", "sort_order": "sortOrder"}


class SmartproxyNode(WorkflowNode):
    integration_type = "automation-smartproxy"
    connection_evidence = ConnectionEvidence(noun="subusers", operation="list_sub_users", label_keys=("username", "id"))

    @classmethod
    def get_config_model(cls):
        return SmartproxyConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Smartproxy API key")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for name in ("sub_user_id", "whitelist_id", "session_type"):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(str(values.pop(name)), safe=""))
        payload = {ALIASES.get(key, key): value for key, value in values.items()}
        headers = {"Authorization": self.config.credentials.api_key, "Accept": "application/json"}
        kwargs = {"params": payload} if method == "GET" else {"json": payload} if method in {"POST", "PUT"} else {}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                error = response.json()
            except ValueError:
                raise exc from None
            if not isinstance(error, dict) or not isinstance(error.get("message"), str):
                raise exc from None
            message = error["message"]
            for secret in (self.config.credentials.api_key, getattr(op, "password", None)):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise httpx.HTTPStatusError(f"{message} (HTTP {response.status_code})",
                request=response.request, response=response) from None
        if response.status_code == 204:
            data = None
        else:
            data = response.json()
            if isinstance(data, dict) and data.get("error_code"):
                message = str(data.get("message", "Smartproxy API error"))
                for secret in (self.config.credentials.api_key, getattr(op, "password", None)):
                    if secret:
                        message = message.replace(secret, "[redacted]")
                raise ValueError(message)
        output = {"status": "success", "operation": op.operation, "data": data}
        await self.emit(output)
        return output

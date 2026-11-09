"""Kibana public REST operations with a manually supplied Elastic API key.

Data view, alerting and connector operations target the default space. Each
operation makes one request; a successful write is an API acknowledgement.
Contract: https://www.elastic.co/docs/api/doc/kibana.json
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class KibanaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Kibana API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.elastic.co/docs/api/doc/kibana/authentication",
            "x-credential-instructions": "Enter your public HTTPS Kibana origin and paste an encoded Elastic API key from Stack Management > API Keys, without the ApiKey prefix. Grant the Kibana privileges needed for your operations. Data views, rules and connectors use the default space. The connection check lists your accessible spaces; it does not verify write permissions. Reverse-proxy base paths are not supported.",
        })
    credential_type: Literal["kibana_api_key"] = Field("kibana_api_key", json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="Kibana URL", description="Public HTTPS origin, for example https://my-deployment.kb.us-east-1.aws.elastic.cloud. Include a port if needed; omit paths and /app.")
    api_key: str = Field(..., title="Encoded API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_base_url", mode="before")
    @classmethod
    def base_url(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a public HTTPS Kibana origin")
        value = value.strip()
        try:
            u = urlsplit(value)
            host = u.hostname or ""
            port = u.port
            if (u.scheme != "https" or u.username is not None or u.password is not None
                    or u.query or u.fragment or u.path not in {"", "/"}
                    or not host or "." not in host or len(host) > 253
                    or any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in host.split("."))
                    or all(c.isdigit() or c == "." for c in host)
                    or (port is not None and not 1 <= port <= 65535)):
                raise ValueError()
        except ValueError:
            raise ValueError("Enter a public HTTPS Kibana origin without a path, query or user information") from None
        return "https://" + host.lower() + (":" + str(port) if port and port != 443 else "")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Encoded API Key")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9+/_=-]{1,8192}", value):
            raise ValueError("Paste the encoded API key without the ApiKey prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Resource(_Input):
    id: str = Field(..., min_length=1, max_length=512, description="Exact Kibana resource ID.")

    @field_validator("id")
    @classmethod
    def resource_id(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 or c in "/\\?#%" for c in value):
            raise ValueError("Paste a single resource ID, not a URL or path")
        return value


class _SpaceFields(_Input):
    name: str = Field(..., min_length=1, max_length=1000, title="Space Name")
    description: str | None = Field(None, max_length=10000)
    color: str | None = Field(None, pattern=r"^#[a-fA-F0-9]{6}$")
    initials: str | None = Field(None, max_length=2)
    disabled_features: list[str] | None = Field(None, max_length=100, description="Feature identifiers to disable. Omit to use the provider default.")


class _SpaceID(_Resource):
    id: str = Field(..., min_length=1, max_length=512, pattern=r"^[a-z0-9_-]+$", title="Space ID")


class _DataViewFields(_Input):
    title: str = Field(..., min_length=1, max_length=1000, description="Index pattern, for example logs-*.")
    name: str | None = Field(None, max_length=1000)
    time_field_name: str | None = Field(None, max_length=1000)
    allow_no_index: bool | None = None


class KibanaListSpacesConfig(_Input):
    operation: Literal["list_spaces"] = Field("list_spaces", title="List Spaces",
        json_schema_extra={"ui:hidden": True, "x-category": "Spaces", "x-display-name": "List Spaces", "x-is-trigger": False})

class KibanaGetSpaceConfig(_SpaceID):
    operation: Literal["get_space"] = Field("get_space", title="Get Space",
        json_schema_extra={"ui:hidden": True, "x-category": "Spaces", "x-display-name": "Get Space", "x-is-trigger": False})

class KibanaCreateSpaceConfig(_SpaceFields, _SpaceID):
    operation: Literal["create_space"] = Field("create_space", title="Create Space",
        json_schema_extra={"ui:hidden": True, "x-category": "Spaces", "x-display-name": "Create Space", "x-is-trigger": False})

class KibanaUpdateSpaceConfig(_SpaceFields, _SpaceID):
    operation: Literal["update_space"] = Field("update_space", title="Update Space",
        json_schema_extra={"ui:hidden": True, "x-category": "Spaces", "x-display-name": "Update Space", "x-is-trigger": False})

class KibanaDeleteSpaceConfig(_SpaceID):
    operation: Literal["delete_space"] = Field("delete_space", title="Delete Space",
        json_schema_extra={"ui:hidden": True, "x-category": "Spaces", "x-display-name": "Delete Space", "x-is-trigger": False})

class KibanaListDataViewsConfig(_Input):
    operation: Literal["list_data_views"] = Field("list_data_views", title="List Data Views",
        json_schema_extra={"ui:hidden": True, "x-category": "Data Views", "x-display-name": "List Data Views", "x-is-trigger": False})

class KibanaGetDataViewConfig(_Resource):
    operation: Literal["get_data_view"] = Field("get_data_view", title="Get Data View",
        json_schema_extra={"ui:hidden": True, "x-category": "Data Views", "x-display-name": "Get Data View", "x-is-trigger": False})

class KibanaCreateDataViewConfig(_DataViewFields):
    operation: Literal["create_data_view"] = Field("create_data_view", title="Create Data View",
        json_schema_extra={"ui:hidden": True, "x-category": "Data Views", "x-display-name": "Create Data View", "x-is-trigger": False})
    override: bool = Field(False, description="Replace an existing data view with the same title.")

class KibanaUpdateDataViewConfig(_DataViewFields, _Resource):
    operation: Literal["update_data_view"] = Field("update_data_view", title="Update Data View",
        json_schema_extra={"ui:hidden": True, "x-category": "Data Views", "x-display-name": "Update Data View", "x-is-trigger": False})
    refresh_fields: bool = False

class KibanaDeleteDataViewConfig(_Resource):
    operation: Literal["delete_data_view"] = Field("delete_data_view", title="Delete Data View",
        json_schema_extra={"ui:hidden": True, "x-category": "Data Views", "x-display-name": "Delete Data View", "x-is-trigger": False})

class KibanaGetDefaultDataViewConfig(_Input):
    operation: Literal["get_default_data_view"] = Field("get_default_data_view", title="Get Default Data View",
        json_schema_extra={"ui:hidden": True, "x-category": "Data Views", "x-display-name": "Get Default Data View", "x-is-trigger": False})

class KibanaSetDefaultDataViewConfig(_Input):
    operation: Literal["set_default_data_view"] = Field("set_default_data_view", title="Set Default Data View",
        json_schema_extra={"ui:hidden": True, "x-category": "Data Views", "x-display-name": "Set Default Data View", "x-is-trigger": False})
    data_view_id: str = Field(..., min_length=1, max_length=512, title="Data View ID")
    force: bool = Field(False, description="Replace an existing default.")

class KibanaListRulesConfig(_Input):
    operation: Literal["list_rules"] = Field("list_rules", title="List Rules",
        json_schema_extra={"ui:hidden": True, "x-category": "Alert Rules", "x-display-name": "List Rules", "x-is-trigger": False})
    page: int = Field(1, ge=1)
    per_page: int = Field(10, ge=1, le=1000)
    search: str | None = Field(None, max_length=1000)
    filter: str | None = Field(None, max_length=10000, description="KQL filter for alert saved objects.")

class KibanaGetRuleConfig(_Resource):
    operation: Literal["get_rule"] = Field("get_rule", title="Get Rule",
        json_schema_extra={"ui:hidden": True, "x-category": "Alert Rules", "x-display-name": "Get Rule", "x-is-trigger": False})

class KibanaDeleteRuleConfig(_Resource):
    operation: Literal["delete_rule"] = Field("delete_rule", title="Delete Rule",
        json_schema_extra={"ui:hidden": True, "x-category": "Alert Rules", "x-display-name": "Delete Rule", "x-is-trigger": False})

class KibanaEnableRuleConfig(_Resource):
    operation: Literal["enable_rule"] = Field("enable_rule", title="Enable Rule",
        json_schema_extra={"ui:hidden": True, "x-category": "Alert Rules", "x-display-name": "Enable Rule", "x-is-trigger": False})

class KibanaDisableRuleConfig(_Resource):
    operation: Literal["disable_rule"] = Field("disable_rule", title="Disable Rule",
        json_schema_extra={"ui:hidden": True, "x-category": "Alert Rules", "x-display-name": "Disable Rule", "x-is-trigger": False})

class KibanaMuteRuleConfig(_Resource):
    operation: Literal["mute_rule"] = Field("mute_rule", title="Mute Rule",
        json_schema_extra={"ui:hidden": True, "x-category": "Alert Rules", "x-display-name": "Mute Rule", "x-is-trigger": False})

class KibanaUnmuteRuleConfig(_Resource):
    operation: Literal["unmute_rule"] = Field("unmute_rule", title="Unmute Rule",
        json_schema_extra={"ui:hidden": True, "x-category": "Alert Rules", "x-display-name": "Unmute Rule", "x-is-trigger": False})

class KibanaListConnectorsConfig(_Input):
    operation: Literal["list_connectors"] = Field("list_connectors", title="List Connectors",
        json_schema_extra={"ui:hidden": True, "x-category": "Connectors", "x-display-name": "List Connectors", "x-is-trigger": False})

class KibanaGetConnectorConfig(_Resource):
    operation: Literal["get_connector"] = Field("get_connector", title="Get Connector",
        json_schema_extra={"ui:hidden": True, "x-category": "Connectors", "x-display-name": "Get Connector", "x-is-trigger": False})

class KibanaDeleteConnectorConfig(_Resource):
    operation: Literal["delete_connector"] = Field("delete_connector", title="Delete Connector",
        json_schema_extra={"ui:hidden": True, "x-category": "Connectors", "x-display-name": "Delete Connector", "x-is-trigger": False})


KibanaConfig = Annotated[Union[
    KibanaListSpacesConfig,
    KibanaGetSpaceConfig,
    KibanaCreateSpaceConfig,
    KibanaUpdateSpaceConfig,
    KibanaDeleteSpaceConfig,
    KibanaListDataViewsConfig,
    KibanaGetDataViewConfig,
    KibanaCreateDataViewConfig,
    KibanaUpdateDataViewConfig,
    KibanaDeleteDataViewConfig,
    KibanaGetDefaultDataViewConfig,
    KibanaSetDefaultDataViewConfig,
    KibanaListRulesConfig,
    KibanaGetRuleConfig,
    KibanaDeleteRuleConfig,
    KibanaEnableRuleConfig,
    KibanaDisableRuleConfig,
    KibanaMuteRuleConfig,
    KibanaUnmuteRuleConfig,
    KibanaListConnectorsConfig,
    KibanaGetConnectorConfig,
    KibanaDeleteConnectorConfig], Field(discriminator="operation")]


class KibanaFullConfig(NodeConfig[KibanaConfig, KibanaAPIKeyCredential]):
    pass


ROUTES = {
    "list_spaces": ("GET", "/api/spaces/space"),
    "get_space": ("GET", "/api/spaces/space/{id}"),
    "create_space": ("POST", "/api/spaces/space"),
    "update_space": ("PUT", "/api/spaces/space/{id}"),
    "delete_space": ("DELETE", "/api/spaces/space/{id}"),
    "list_data_views": ("GET", "/api/data_views"),
    "get_data_view": ("GET", "/api/data_views/data_view/{id}"),
    "create_data_view": ("POST", "/api/data_views/data_view"),
    "update_data_view": ("POST", "/api/data_views/data_view/{id}"),
    "delete_data_view": ("DELETE", "/api/data_views/data_view/{id}"),
    "get_default_data_view": ("GET", "/api/data_views/default"),
    "set_default_data_view": ("POST", "/api/data_views/default"),
    "list_rules": ("GET", "/api/alerting/rules/_find"),
    "get_rule": ("GET", "/api/alerting/rule/{id}"),
    "delete_rule": ("DELETE", "/api/alerting/rule/{id}"),
    "enable_rule": ("POST", "/api/alerting/rule/{id}/_enable"),
    "disable_rule": ("POST", "/api/alerting/rule/{id}/_disable"),
    "mute_rule": ("POST", "/api/alerting/rule/{id}/_mute_all"),
    "unmute_rule": ("POST", "/api/alerting/rule/{id}/_unmute_all"),
    "list_connectors": ("GET", "/api/actions/connectors"),
    "get_connector": ("GET", "/api/actions/connector/{id}"),
    "delete_connector": ("DELETE", "/api/actions/connector/{id}"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()
                if k.lower() not in {"api_key", "apikey", "authorization", "secrets", "password"}}
    return value


class KibanaNode(WorkflowNode):
    integration_type = "automation-kibana"
    connection_evidence = ConnectionEvidence(operation="list_spaces", noun="Kibana spaces")

    @classmethod
    def get_config_model(cls):
        return KibanaFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Kibana API key")
        credential = self.config.credentials
        config = self.config.config
        action = config.operation
        method, path = ROUTES[action]
        if "{id}" in path:
            path = path.replace("{id}", quote(config.id, safe=""))
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        body, params = None, None
        if action in {"create_space", "update_space"}:
            body = {("disabledFeatures" if k == "disabled_features" else k): v for k, v in values.items()}
        elif action in {"create_data_view", "update_data_view"}:
            fields = {"time_field_name": "timeFieldName", "allow_no_index": "allowNoIndex"}
            body = {"data_view": {fields.get(k, k): v for k, v in values.items()
                                   if k not in {"id", "override", "refresh_fields"}}}
            option = "override" if action == "create_data_view" else "refresh_fields"
            body[option] = values[option]
        elif action == "set_default_data_view":
            body = values
        elif action == "list_rules":
            params = values
        headers = {"Authorization": "ApiKey " + credential.api_key, "Accept": "application/json", "kbn-xsrf": "true"}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.api_base_url + path,
                                            headers=headers, params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text so manual connect can explain the refusal.
            message = response.text[:2000]
            output = {"status": "error", "success": False, "http_status": response.status_code,
                      "message": message or "Kibana rejected the request"}
        elif response.status_code == 204 or not response.content:
            if method == "GET":
                raise ValueError("Kibana returned an empty read response")
            output = {"status": "success", "success": True, "http_status": response.status_code,
                      "acknowledged": True}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Kibana JSON response exceeds 10 MB")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime != "application/json":
                raise ValueError("Kibana returned a non-JSON response; check the Kibana URL")
            data = response.json()
            if not isinstance(data, (dict, list)):
                raise ValueError("Kibana returned an unexpected JSON shape")
            if isinstance(data, dict) and (data.get("error") or data.get("statusCode", 200) >= 400):
                output = {"status": "error", "success": False, "http_status": response.status_code,
                          "message": data.get("message") or str(data.get("error"))}
            else:
                if action in {"list_spaces", "list_connectors"}:
                    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                        raise ValueError("Kibana returned an unexpected resource list")
                elif not isinstance(data, dict):
                    raise ValueError("Kibana returned an unexpected resource object")
                if action in {"list_rules", "list_data_views"}:
                    key = "data" if action == "list_rules" else "data_view"
                    if not isinstance(data.get(key), list):
                        raise ValueError("Kibana returned an unexpected list envelope")
                output = {"status": "success", "success": True, "http_status": response.status_code, "data": data}
                if action == "list_rules":
                    output["page"] = config.page
                    output["per_page"] = config.per_page
                    output["total"] = data.get("total") if isinstance(data, dict) else None
                    output["items"] = data.get("data", []) if isinstance(data, dict) else data
                elif action == "list_data_views":
                    output["items"] = data.get("data_view", []) if isinstance(data, dict) else data
        output = _redact(output, credential.api_key)
        await self.emit(output)
        return output

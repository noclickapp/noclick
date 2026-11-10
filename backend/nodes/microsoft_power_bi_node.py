"""Power BI workspace automation through delegated Microsoft sign-in.

Each operation maps to one operation in Microsoft's v1.0 REST contract. The
shared sign-in retains its Graph identity token; a separately cached Power BI
token uses the same refresh chain through the audited refresh choke point.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_refresh import ensure_fresh_oauth_token, freshen_oauth_credential
from nodes.microsoft_power_bi_operations import OPERATIONS
from nodes.scopes.microsoft_power_bi import CONNECT_SCOPES, POWER_BI_SCOPES, RESOURCE_SCOPES
from utils.ssrf import guarded_async_client

API_ROOT = "https://api.powerbi.com/v1.0/myorg"


class PowerBIOAuthCredential(BaseModel):
    credential_type: Literal["microsoft_oauth"] = Field("microsoft_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str
    refresh_token: str
    expires_at: str
    email: str
    # Populated only by a scoped token grant, never the connect form.
    power_bi_access_token: str | None = Field(None, json_schema_extra={"ui:hidden": True})
    power_bi_expires_at: str | None = Field(None, json_schema_extra={"ui:hidden": True})
    scope: str | None = Field(None, json_schema_extra={"ui:hidden": True})

    model_config = ConfigDict(title="Microsoft Power BI OAuth", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "microsoft",
        "x-oauth-scopes": CONNECT_SCOPES,
        "x-credential-url": "https://learn.microsoft.com/en-us/power-bi/developer/embedded/register-app",
        "x-credential-instructions": "Sign in with your Microsoft work or school account with access to Power BI. Allow workspace, dataset, report and dashboard permissions. Push datasets are required for table and row operations; DAX queries require the tenant Execute Queries setting and dataset Build permission.",
    })


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*")
    @classmethod
    def safe_strings(cls, value, info):
        if isinstance(value, str) and info.field_name != "operation":
            if not value.strip() or (any(ord(c) < 32 for c in value) and info.field_name != "query"):
                raise ValueError("Supply nonempty text without control characters")
            if info.field_name.endswith("_id") or info.field_name == "table_name":
                if value in {".", ".."} or re.search(r"[/\\?#%]", value):
                    raise ValueError("Supply an ID or name, not a URL or path")
        return value


class PushColumn(_Input):
    name: str = Field(..., min_length=1, max_length=100)
    dataType: Literal["Int64", "Double", "Boolean", "DateTime", "String", "string", "bool"]


class PushTable(_Input):
    name: str = Field(..., min_length=1, max_length=100)
    columns: list[PushColumn] = Field(..., min_length=1, max_length=75)


FIELDS: dict[str, tuple[Any, Any]] = {
    "workspace_id": (str, Field(..., title="Workspace ID", min_length=1, description="Power BI workspace (group) ID")),
    "dataset_id": (str, Field(..., title="Dataset ID", min_length=1)),
    "report_id": (str, Field(..., title="Report ID", min_length=1)),
    "dashboard_id": (str, Field(..., title="Dashboard ID", min_length=1)),
    "table_name": (str, Field(..., title="Table Name", min_length=1, max_length=100)),
    "top": (int, Field(100, title="Limit", ge=1, le=5000)),
    "skip": (int, Field(0, title="Skip", ge=0)),
    "filter": (str | None, Field(None, title="Workspace Filter", description="Optional OData filter, for example contains(name,'marketing')")),
    "name": (str, Field(..., title="Name", min_length=1, max_length=200)),
    "tables": (list[PushTable], Field(..., title="Tables", min_length=1, max_length=75, description="Push dataset tables with name and columns (name and dataType)")),
    "rows": (list[dict[str, Any]], Field(..., title="Rows", min_length=1, max_length=10000, description="Rows keyed by the existing table's column names")),
    "notify_option": (Literal["NoNotification", "MailOnFailure", "MailOnCompletion"], Field("NoNotification", title="Refresh Notification")),
    "query": (str, Field(..., title="DAX Query", min_length=1, description="One DAX query; tenant Execute Queries setting and dataset Build permission required")),
    "include_nulls": (bool, Field(False, title="Include Null Values")),
    "target_workspace_id": (str | None, Field(None, title="Target Workspace ID", pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")),
    "target_dataset_id": (str, Field(..., title="Target Dataset ID", min_length=1)),
}


def _model(name, spec):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True}))}
    for key in spec.fields:
        fields[key] = FIELDS[key]
    if name == "clone_report":
        fields["target_dataset_id"] = (str | None, Field(None, title="Target Dataset ID"))
    return create_model("PowerBI" + "".join(w.title() for w in name.split("_")) + "Config", __base__=_Input, **fields)


CONFIG_MODELS = {name: _model(name, spec) for name, spec in OPERATIONS.items()}
PowerBIConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class PowerBIFullConfig(NodeConfig[PowerBIConfig, PowerBIOAuthCredential]):
    pass


async def _refresh_power_bi(refresh_token: str):
    from nodes.oauth.microsoft_oauth import refresh_access_token
    return await refresh_access_token(refresh_token, scope=RESOURCE_SCOPES)


class MicrosoftPowerBINode(WorkflowNode):
    integration_type = "automation-microsoft-power-bi"
    borrowed_credential_types = frozenset({"microsoft_oauth"})
    credential_provider_labels = {"microsoft": "Microsoft Account"}
    scope_registry = POWER_BI_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_workspaces", noun="Power BI workspaces")

    @classmethod
    def get_config_model(cls):
        return PowerBIFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Graph identity and Power BI have independent expiries. Both grants
        # use the same refresh-token lock and persist any successor token.
        from nodes.oauth.microsoft_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="microsoft")

    async def _token(self):
        credential = self.config.credentials
        data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=_refresh_power_bi, provider="microsoft",
            access_token_key="power_bi_access_token", expires_at_key="power_bi_expires_at",
            stale=lambda current: not current.get("power_bi_access_token"), caller_path="execute",
        )
        for key in ("refresh_token", "power_bi_access_token", "power_bi_expires_at", "scope"):
            if key in data:
                setattr(credential, key, data[key])
        return token

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, PowerBIFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Microsoft account with Power BI access")
        cfg = self.config.config
        spec = OPERATIONS[cfg.operation]
        values = cfg.model_dump(exclude_none=True)
        path = spec.path
        for key in spec.fields:
            path = path.replace("{" + key + "}", quote(str(values.get(key, "")), safe=""))
        params = {}
        for key, wire in (("top", "$top"), ("skip", "$skip"), ("filter", "$filter")):
            if key in values:
                params[wire] = values[key]
        body = None
        if cfg.operation == "create_push_dataset":
            body = {"name": cfg.name, "defaultMode": "Push", "tables": values["tables"]}
        elif cfg.operation == "add_rows":
            body = {"rows": cfg.rows}
        elif cfg.operation == "refresh_dataset":
            body = {"notifyOption": cfg.notify_option}
        elif cfg.operation == "execute_query":
            body = {"queries": [{"query": cfg.query}], "serializerSettings": {"includeNulls": cfg.include_nulls}}
        elif cfg.operation == "clone_report":
            body = {"name": cfg.name}
            if cfg.target_workspace_id is not None:
                body["targetWorkspaceId"] = cfg.target_workspace_id
            if cfg.target_dataset_id is not None:
                body["targetModelId"] = cfg.target_dataset_id
        elif cfg.operation == "rebind_report":
            body = {"datasetId": cfg.target_dataset_id}
        elif cfg.operation == "create_dashboard":
            body = {"name": cfg.name}
        token = await self._token()
        kwargs = {"headers": {"Authorization": f"Bearer {token}", "Accept": "application/json"}, "params": params}
        if body is not None:
            kwargs["json"] = body
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(spec.method, API_ROOT + path, **kwargs)
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Power BI API error ({response.status_code}): {response.text[:2000]}")
        result = {"status": "success", "operation": cfg.operation, "http_status": response.status_code}
        expects_list = cfg.operation.startswith("list_") or cfg.operation == "get_refresh_history"
        if not response.content and (expects_list or cfg.operation in {"get_dataset", "get_report", "execute_query"}):
            raise ValueError("Power BI returned an empty read response")
        if response.content:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Power BI returned an invalid JSON object")
            if expects_list and not isinstance(data.get("value"), list):
                raise ValueError("Power BI returned an invalid list envelope")
            if cfg.operation == "execute_query" and not isinstance(data.get("results"), list):
                raise ValueError("Power BI returned an invalid query envelope")
            if "error" in data:
                raise ValueError(f"Power BI API error: {data['error']}")
            if cfg.operation == "execute_query" and any(
                "error" in item or any("error" in table for table in item.get("tables", []))
                for item in data.get("results", [])
            ):
                raise ValueError("Power BI reported a query error or incomplete query result")
            result["data"] = data
            if isinstance(data.get("value"), list):
                result["items"] = data["value"]
                result["count"] = len(data["value"])
                if cfg.operation == "list_workspaces":
                    result["next_skip"] = cfg.skip + len(data["value"]) if len(data["value"]) == cfg.top else None
                if data.get("@odata.nextLink"):
                    result["next_link"] = data["@odata.nextLink"]
        if cfg.operation == "refresh_dataset":
            result["refresh_requested"] = True
            result["refresh_completed"] = False
            result["request_id"] = response.headers.get("x-ms-request-id")
        return result

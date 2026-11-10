"""Apache Superset REST API v1: pasted API keys and scheduled change monitoring.

Contract: https://raw.githubusercontent.com/apache/superset/master/docs/static/resources/openapi.json
API keys use Bearer authentication. No password exchange or implicit retry of writes.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Optional, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class SupersetAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Superset API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://superset.apache.org/developer-docs/api/",
        "x-credential-instructions": "Enter your Superset server origin and paste an existing API key. API key support must be enabled by your administrator. Use HTTPS for a remote server. The key inherits its user's permissions and configured scopes. NoClick checks the current user; it does not request a password or create a key.",
    })
    credential_type: Literal["superset_api_key"] = Field("superset_api_key", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="Your Superset origin, for example https://superset.example.com. Deployments under a URL subpath are not supported.")
    api_key: str = Field(..., min_length=1, max_length=8192, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value, field_name="Superset server URL")
        if not origin:
            raise ValueError("Enter your Superset server URL")
        parts = urlsplit(origin)
        if parts.scheme != "https" and parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Use HTTPS for a remote Superset server")
        return origin

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _List(_Input):
    page: int = Field(0, ge=0, description="Zero-based page. Request the next page until count is exhausted.")
    page_size: int = Field(100, ge=1, le=100)


class _DashboardWrite(_Input):
    dashboard_title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    slug: Optional[str] = Field(None, min_length=1, max_length=255)
    published: Optional[bool] = None
    position_json: Optional[str] = Field(None, description="Serialized dashboard layout JSON from Superset.")
    json_metadata: Optional[str] = Field(None, description="Serialized dashboard metadata JSON from Superset.")


class _ChartWrite(_Input):
    slice_name: str = Field(..., min_length=1, max_length=250, title="Chart name")
    description: Optional[str] = None
    viz_type: Optional[str] = Field(None, max_length=250)
    params: Optional[str] = Field(None, description="Serialized chart parameters copied from Superset Explore.")
    query_context: Optional[str] = Field(None, description="Serialized chart query context copied from Superset Explore.")
    dashboards: Optional[list[int]] = None
    cache_timeout: Optional[int] = None


class _DatasetCreate(_Input):
    database: int = Field(..., ge=1, title="Database ID")
    table_name: str = Field(..., min_length=1, max_length=250)
    schema_name: Optional[str] = Field(None, max_length=250, description="Database schema; sent as schema.")
    catalog: Optional[str] = Field(None, max_length=250)
    sql: Optional[str] = Field(None, description="SQL for a virtual dataset; the provider executes it with the connected user's permissions.")


class _DatasetUpdate(_Input):
    table_name: str = Field(..., min_length=1, max_length=250)
    description: Optional[str] = None
    sql: Optional[str] = None
    schema_name: Optional[str] = Field(None, max_length=255)
    cache_timeout: Optional[int] = None


class _Poll(PollTriggerConfigBase):
    page_size: int = Field(100, ge=1, le=100, description="Monitor the most recently changed resources in this window. Changes that leave the window between polls can be missed; choose a frequent schedule.")


# Each operation maps to one method/path in the published contract. Order puts
# the common discovery and content automation actions before administration.
OPERATIONS = {
    "get_current_user": ("GET", "/api/v1/me/"),
    "list_dashboards": ("GET", "/api/v1/dashboard/"),
    "get_dashboard": ("GET", "/api/v1/dashboard/{id_or_slug}"),
    "create_dashboard": ("POST", "/api/v1/dashboard/"),
    "update_dashboard": ("PUT", "/api/v1/dashboard/{pk}"),
    "delete_dashboard": ("DELETE", "/api/v1/dashboard/{pk}"),
    "list_charts": ("GET", "/api/v1/chart/"),
    "get_chart": ("GET", "/api/v1/chart/{id_or_uuid}"),
    "create_chart": ("POST", "/api/v1/chart/"),
    "update_chart": ("PUT", "/api/v1/chart/{pk}"),
    "delete_chart": ("DELETE", "/api/v1/chart/{pk}"),
    "list_datasets": ("GET", "/api/v1/dataset/"),
    "get_dataset": ("GET", "/api/v1/dataset/{id_or_uuid}"),
    "create_dataset": ("POST", "/api/v1/dataset/"),
    "update_dataset": ("PUT", "/api/v1/dataset/{pk}"),
    "delete_dataset": ("DELETE", "/api/v1/dataset/{pk}"),
    "list_dashboard_charts": ("GET", "/api/v1/dashboard/{id_or_slug}/charts"),
    "get_chart_data": ("GET", "/api/v1/chart/{pk}/data/"),
    "refresh_dataset": ("PUT", "/api/v1/dataset/{pk}/refresh"),
    "list_databases": ("GET", "/api/v1/database/"),
    "get_database": ("GET", "/api/v1/database/{pk}"),
    "on_new_or_updated_dashboard": ("GET", "/api/v1/dashboard/"),
    "on_new_or_updated_chart": ("GET", "/api/v1/chart/"),
}


class SupersetGetCurrentUserConfig(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Current User', 'x-category': 'Account'})


class SupersetListDashboardsConfig(_List):
    operation: Literal["list_dashboards"] = Field("list_dashboards", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Dashboards', 'x-category': 'Dashboards'})


class SupersetGetDashboardConfig(_Input):
    operation: Literal["get_dashboard"] = Field("get_dashboard", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Dashboard', 'x-category': 'Dashboards'})
    dashboard_id: int = Field(..., ge=1)


class SupersetCreateDashboardConfig(_DashboardWrite):
    operation: Literal["create_dashboard"] = Field("create_dashboard", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create Dashboard', 'x-category': 'Dashboards'})


class SupersetUpdateDashboardConfig(_DashboardWrite):
    operation: Literal["update_dashboard"] = Field("update_dashboard", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update Dashboard', 'x-category': 'Dashboards'})
    dashboard_id: int = Field(..., ge=1)


class SupersetDeleteDashboardConfig(_Input):
    """Delete this dashboard. Soft deletion depends on the server SOFT_DELETE feature flag."""
    operation: Literal["delete_dashboard"] = Field("delete_dashboard", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Delete Dashboard', 'x-category': 'Dashboards'})
    dashboard_id: int = Field(..., ge=1)


class SupersetListChartsConfig(_List):
    operation: Literal["list_charts"] = Field("list_charts", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Charts', 'x-category': 'Charts'})


class SupersetGetChartConfig(_Input):
    operation: Literal["get_chart"] = Field("get_chart", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Chart', 'x-category': 'Charts'})
    chart_id: int = Field(..., ge=1)


class SupersetCreateChartConfig(_ChartWrite):
    operation: Literal["create_chart"] = Field("create_chart", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create Chart', 'x-category': 'Charts'})
    datasource_id: int = Field(..., ge=1)
    datasource_type: Literal['table', 'dataset', 'query', 'saved_query', 'view', 'semantic_view'] = Field(...)


class SupersetUpdateChartConfig(_ChartWrite):
    operation: Literal["update_chart"] = Field("update_chart", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update Chart', 'x-category': 'Charts'})
    chart_id: int = Field(..., ge=1)


class SupersetDeleteChartConfig(_Input):
    """Delete this chart. Soft deletion depends on the server SOFT_DELETE feature flag."""
    operation: Literal["delete_chart"] = Field("delete_chart", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Delete Chart', 'x-category': 'Charts'})
    chart_id: int = Field(..., ge=1)


class SupersetListDatasetsConfig(_List):
    operation: Literal["list_datasets"] = Field("list_datasets", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Datasets', 'x-category': 'Datasets'})


class SupersetGetDatasetConfig(_Input):
    operation: Literal["get_dataset"] = Field("get_dataset", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Dataset', 'x-category': 'Datasets'})
    dataset_id: int = Field(..., ge=1)


class SupersetCreateDatasetConfig(_DatasetCreate):
    operation: Literal["create_dataset"] = Field("create_dataset", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create Dataset', 'x-category': 'Datasets'})


class SupersetUpdateDatasetConfig(_DatasetUpdate):
    operation: Literal["update_dataset"] = Field("update_dataset", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update Dataset', 'x-category': 'Datasets'})
    dataset_id: int = Field(..., ge=1)


class SupersetDeleteDatasetConfig(_Input):
    """Delete this dataset. Soft deletion depends on the server SOFT_DELETE feature flag."""
    operation: Literal["delete_dataset"] = Field("delete_dataset", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Delete Dataset', 'x-category': 'Datasets'})
    dataset_id: int = Field(..., ge=1)


class SupersetListDashboardChartsConfig(_Input):
    operation: Literal["list_dashboard_charts"] = Field("list_dashboard_charts", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Dashboard Charts', 'x-category': 'Dashboards'})
    dashboard_id: int = Field(..., ge=1)


class SupersetGetChartDataConfig(_Input):
    operation: Literal["get_chart_data"] = Field("get_chart_data", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Chart Data', 'x-category': 'Charts'})
    chart_id: int = Field(..., ge=1)


class SupersetRefreshDatasetConfig(_Input):
    operation: Literal["refresh_dataset"] = Field("refresh_dataset", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Refresh Dataset', 'x-category': 'Datasets'})
    dataset_id: int = Field(..., ge=1)


class SupersetListDatabasesConfig(_List):
    operation: Literal["list_databases"] = Field("list_databases", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Databases', 'x-category': 'Databases'})


class SupersetGetDatabaseConfig(_Input):
    operation: Literal["get_database"] = Field("get_database", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Database', 'x-category': 'Databases'})
    database_id: int = Field(..., ge=1)


class SupersetOnNewOrUpdatedDashboardConfig(_Poll):
    operation: Literal["on_new_or_updated_dashboard"] = Field("on_new_or_updated_dashboard", json_schema_extra={'ui:hidden': True, 'x-display-name': 'On New Or Updated Dashboard', 'x-category': 'Triggers', 'x-is-trigger': True})


class SupersetOnNewOrUpdatedChartConfig(_Poll):
    operation: Literal["on_new_or_updated_chart"] = Field("on_new_or_updated_chart", json_schema_extra={'ui:hidden': True, 'x-display-name': 'On New Or Updated Chart', 'x-category': 'Triggers', 'x-is-trigger': True})


SupersetConfig = Annotated[Union[SupersetGetCurrentUserConfig, SupersetListDashboardsConfig, SupersetGetDashboardConfig, SupersetCreateDashboardConfig, SupersetUpdateDashboardConfig, SupersetDeleteDashboardConfig, SupersetListChartsConfig, SupersetGetChartConfig, SupersetCreateChartConfig, SupersetUpdateChartConfig, SupersetDeleteChartConfig, SupersetListDatasetsConfig, SupersetGetDatasetConfig, SupersetCreateDatasetConfig, SupersetUpdateDatasetConfig, SupersetDeleteDatasetConfig, SupersetListDashboardChartsConfig, SupersetGetChartDataConfig, SupersetRefreshDatasetConfig, SupersetListDatabasesConfig, SupersetGetDatabaseConfig, SupersetOnNewOrUpdatedDashboardConfig, SupersetOnNewOrUpdatedChartConfig], Field(discriminator="operation")]


class SupersetNodeConfig(NodeConfig[SupersetConfig, SupersetAPIKeyCredential]):
    pass


class SupersetNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-superset"
    connection_evidence = ConnectionEvidence(noun="Superset account", identity_operation="get_current_user", identity_keys=("username", "email"))
    edit_examples = ["List Superset dashboards", "Create a Superset chart", "Monitor updated Superset dashboards", "Refresh a Superset dataset"]

    @classmethod
    def get_config_model(cls):
        return SupersetNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, credential.server_url + path, headers=headers, params=params,
                                         **({"json": body} if body is not None else {})) as response:
                    raw = await response.aread()
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError("Superset response exceeds 8 MB; reduce the requested page or chart data")
                    if not 200 <= response.status_code < 300:
                        message = f"Superset HTTP {response.status_code}"
                        try:
                            error = json.loads(raw)
                            detail = error.get("message") if isinstance(error, dict) else None
                            if isinstance(detail, str):
                                message += ": " + detail[:2000].replace(credential.api_key, "[redacted]")
                        except (ValueError, UnicodeError):
                            pass
                        raise ValueError(message)
                    if not raw.strip() and response.status_code == 204:
                        return {"http_status": 204}
                    try:
                        data = response.json()
                    except (ValueError, UnicodeError):
                        raise ValueError("Superset returned an invalid JSON response; inspect the server before retrying a write") from None
                    if not isinstance(data, dict):
                        raise ValueError("Superset returned an unexpected response envelope")
                    return data
        except httpx.TransportError:
            raise ValueError("Superset transport failed; a write outcome is unverified. Inspect the server before retrying") from None

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Superset API key")
        credential = self.config.credentials
        config = self.config.config
        name = config.operation
        method, path = OPERATIONS[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in ("dashboard_id", "chart_id", "dataset_id", "database_id"):
            if field in values:
                identifier = str(values.pop(field))
                for placeholder in ("{pk}", "{id_or_slug}", "{id_or_uuid}"):
                    path = path.replace(placeholder, identifier)
        params, body = None, None
        is_poll = isinstance(config, _Poll)
        if isinstance(config, _List) or is_poll:
            query = {"page": 0 if is_poll else config.page, "page_size": config.page_size}
            if is_poll and name.endswith("dashboard"):
                query.update(order_column="changed_on", order_direction="desc")
            # ChartRestApi.base_order is (changed_on, desc); changed_on is not
            # in its explicit order_columns. Preserve the published default:
            # https://github.com/apache/superset/blob/master/superset/charts/api.py
            params = {"q": json.dumps(query, separators=(",", ":"))}
        elif method in {"POST", "PUT"} and name != "refresh_dataset":
            body = values
            if "schema_name" in body:
                body["schema"] = body.pop("schema_name")
        data = await self._request(credential, method, path, params=params, body=body)
        if isinstance(config, _List) or is_poll:
            rows = data.get("result")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Superset list response is missing result items")
            if is_poll:
                # changed_on_utc and id are declared on both list item schemas.
                # A version fingerprint detects updates as well as new IDs.
                def version(row):
                    identifier, changed = row.get("id"), row.get("changed_on_utc")
                    if identifier is None or changed is None:
                        raise ValueError("Superset change monitoring needs id and changed_on_utc in each list item")
                    return str(identifier) + ":" + str(changed)
                fresh = await self._filter_unseen(rows, version)
                data = {"items": fresh, "resource": "dashboard" if name.endswith("dashboard") else "chart", "new_or_updated_count": len(fresh)}
            else:
                count = data.get("count")
                if type(count) is not int or count < 0:
                    raise ValueError("Superset list response is missing count")
                data = {**data, "next_page": config.page + 1 if (config.page + 1) * config.page_size < count else None}
        elif name == "get_current_user" and not isinstance(data.get("result"), dict):
            raise ValueError("Superset current user response is missing result")
        await self.emit(data)
        return data

    @classmethod
    def resolve_agent_event(cls, output):
        items = output.get("items") if isinstance(output, dict) else None
        if not isinstance(items, list):
            return super().resolve_agent_event(output)
        if not items:
            return None
        kind = output["resource"]
        lines = []
        for row in items[:20]:
            title = row.get("dashboard_title") if kind == "dashboard" else row.get("slice_name")
            actor = row.get("changed_by_name") or "a Superset user"
            location = row.get("url") or f"{kind} ID {row.get('id')}"
            description = row.get("description") or ""
            lines.append(f"- {actor} changed {title or kind.title()} (ID {row.get('id')}) at {row.get('changed_on_utc')}. {location} {description}")
        return {"text": f"Superset: {len(items)} new or updated {kind}(s).\n" + "\n".join(lines), "conversation_key": None}

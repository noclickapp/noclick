"""Agenty v2 agent, job, input, list and scheduler automation.

Contract: https://api.agenty.com/openapi.json (version 2.0).
List reads return the provider's page unchanged; advance offset explicitly.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, Json

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api.agenty.com"
ResourceID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]
NumericID = Annotated[int, Field(gt=0)]
Name = Annotated[str, Field(min_length=1, max_length=100)]


class AgentyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Agenty API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://cloud.agenty.com/settings/api-keys",
            "x-credential-instructions": "In Agenty, open Settings, then API keys. Copy your API key and paste it here without the Bearer prefix. NoClick verifies the key by listing your agents."})
    credential_type: Literal["agenty_api_key"] = Field("agenty_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, repr=False, title="API Key",
        json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    offset: int = Field(0, ge=0, description="Records to skip. Each call returns one provider page.")
    limit: int = Field(100, ge=1, le=1000, title="Page Size")
    sort: str | None = Field(None, description="Provider field to sort by.")
    order: Literal["asc", "desc"] | None = None
    search: str | None = None


class ManualInput(_Input):
    type: Literal["manual"] = "manual"
    data: list[str] = Field(..., min_length=1, max_length=50000)


class URLInput(_Input):
    type: Literal["url"] = "url"
    data: list[str] = Field(..., min_length=1)


class ListInput(_Input):
    type: Literal["list"] = "list"
    id: str = Field(..., min_length=1)
    field: str = Field(..., min_length=1)


class AgentInput(_Input):
    type: Literal["agent"] = "agent"
    id: str = Field(..., min_length=1)
    field: str = Field(..., min_length=1)
    collection: int = 1


InputSource = Annotated[Union[ManualInput, URLInput, ListInput, AgentInput], Field(discriminator="type")]


class ListAgents(_Page):
    operation: Literal["list_agents"] = Field("list_agents", title="List Agents", json_schema_extra={"ui:hidden": True})


class ListJobs(_Page):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Jobs", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID | None = None


class GetJob(_Input):
    operation: Literal["get_job"] = Field("get_job", title="Get Job", json_schema_extra={"ui:hidden": True})
    job_id: NumericID


class StartJob(_Input):
    operation: Literal["start_job"] = Field("start_job", title="Start Job", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID


class StopJob(_Input):
    operation: Literal["stop_job"] = Field("stop_job", title="Stop Job", json_schema_extra={"ui:hidden": True})
    job_id: NumericID


class GetJobResult(_Page):
    operation: Literal["get_job_result"] = Field("get_job_result", title="Get Job Result", json_schema_extra={"ui:hidden": True})
    job_id: NumericID
    collection: int = Field(1, ge=1)


class GetJobLogs(_Page):
    operation: Literal["get_job_logs"] = Field("get_job_logs", title="Get Job Logs", json_schema_extra={"ui:hidden": True})
    job_id: NumericID


class GetInput(_Input):
    operation: Literal["get_input"] = Field("get_input", title="Get Input", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID


class UpdateInput(_Input):
    operation: Literal["update_input"] = Field("update_input", title="Update Input", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID
    input_source: Json[InputSource] = Field(..., description="Agenty input source JSON, for example {\"type\":\"manual\",\"data\":[\"https://example.com/page-1\"]}.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class ListLists(_Page):
    operation: Literal["list_lists"] = Field("list_lists", title="List Lists", json_schema_extra={"ui:hidden": True})


class GetList(_Page):
    operation: Literal["get_list"] = Field("get_list", title="Get List", json_schema_extra={"ui:hidden": True})
    list_id: NumericID


class CreateList(_Input):
    operation: Literal["create_list"] = Field("create_list", title="Create List", json_schema_extra={"ui:hidden": True})
    name: Name
    description: str | None = None


class UpdateList(_Input):
    operation: Literal["update_list"] = Field("update_list", title="Update List", json_schema_extra={"ui:hidden": True})
    list_id: NumericID
    name: Name
    description: str | None = None


class DeleteList(_Input):
    operation: Literal["delete_list"] = Field("delete_list", title="Delete List", json_schema_extra={"ui:hidden": True})
    id: NumericID = Field(..., title="List ID")


class ListRows(_Page):
    operation: Literal["list_rows"] = Field("list_rows", title="List Rows", json_schema_extra={"ui:hidden": True})
    list_id: NumericID


class GetRow(_Input):
    operation: Literal["get_row"] = Field("get_row", title="Get Row", json_schema_extra={"ui:hidden": True})
    list_id: NumericID
    id: ResourceID = Field(..., title="Row ID")


class AddRows(_Input):
    operation: Literal["add_rows"] = Field("add_rows", title="Add Rows", json_schema_extra={"ui:hidden": True})
    list_id: NumericID
    rows: Json[Annotated[list[dict[str, str | int | float | bool | None]], Field(min_length=1)]] = Field(..., description="Rows keyed by your list column names; sent as a JSON array.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class UpdateRow(_Input):
    operation: Literal["update_row"] = Field("update_row", title="Update Row", json_schema_extra={"ui:hidden": True})
    list_id: NumericID
    id: ResourceID = Field(..., title="Row ID")
    row: Json[Annotated[dict[str, str | int | float | bool | None], Field(min_length=1)]] = Field(..., description="Values keyed by your list column names.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class DeleteRow(_Input):
    operation: Literal["delete_row"] = Field("delete_row", title="Delete Row", json_schema_extra={"ui:hidden": True})
    list_id: NumericID
    id: ResourceID = Field(..., title="Row ID")


class GetSchedule(_Input):
    operation: Literal["get_schedule"] = Field("get_schedule", title="Get Schedule", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID


class SetSchedule(_Input):
    operation: Literal["set_schedule"] = Field("set_schedule", title="Set Schedule", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID
    type: Literal["cron", "interval"] = "cron"
    expression: str = Field(..., min_length=1, description="Agenty cron or interval expression.")
    frequency: float | None = None
    description: str | None = None
    is_enabled: bool = True


class ToggleSchedule(_Input):
    operation: Literal["toggle_schedule"] = Field("toggle_schedule", title="Toggle Schedule", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID
    is_enabled: bool


class DeleteSchedule(_Input):
    operation: Literal["delete_schedule"] = Field("delete_schedule", title="Delete Schedule", json_schema_extra={"ui:hidden": True})
    agent_id: ResourceID


Operation = Annotated[Union[ListAgents, ListJobs, GetJob, StartJob, StopJob, GetJobResult, GetJobLogs, GetInput, UpdateInput, ListLists, GetList, CreateList, UpdateList, DeleteList, ListRows, GetRow, AddRows, UpdateRow, DeleteRow, GetSchedule, SetSchedule, ToggleSchedule, DeleteSchedule], Field(discriminator="operation")]


class AgentyConfig(NodeConfig[Operation, AgentyAPIKeyCredential]):
    pass


ROUTES = {'list_agents': ('GET', '/v2/agents'), 'list_jobs': ('GET', '/v2/jobs'), 'get_job': ('GET', '/v2/jobs/{job_id}'), 'start_job': ('POST', '/v2/jobs/start'), 'stop_job': ('GET', '/v2/jobs/{job_id}/stop'), 'get_job_result': ('GET', '/v2/jobs/{job_id}/result'), 'get_job_logs': ('GET', '/v2/jobs/{job_id}/logs'), 'get_input': ('GET', '/v2/inputs/{agent_id}'), 'update_input': ('PUT', '/v2/inputs/{agent_id}'), 'list_lists': ('GET', '/v2/lists'), 'get_list': ('GET', '/v2/lists/{list_id}'), 'create_list': ('POST', '/v2/lists'), 'update_list': ('PUT', '/v2/lists/{list_id}'), 'delete_list': ('DELETE', '/v2/lists/{id}'), 'list_rows': ('GET', '/v2/lists/{list_id}/rows'), 'get_row': ('GET', '/v2/lists/{list_id}/rows/{id}'), 'add_rows': ('POST', '/v2/lists/{list_id}/rows'), 'update_row': ('PUT', '/v2/lists/{list_id}/rows/{id}'), 'delete_row': ('DELETE', '/v2/lists/{list_id}/rows/{id}'), 'get_schedule': ('GET', '/v2/scheduler/{agent_id}'), 'set_schedule': ('PUT', '/v2/scheduler/{agent_id}'), 'toggle_schedule': ('PATCH', '/v2/scheduler/{agent_id}'), 'delete_schedule': ('DELETE', '/v2/scheduler/{agent_id}')}


class AgentyNode(WorkflowNode):
    integration_type = "automation-agenty"
    connection_evidence = ConnectionEvidence(noun="Agenty agents", operation="list_agents")

    @classmethod
    def get_config_model(cls):
        return AgentyConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Agenty API key")
        cfg = self.config.config
        method, path = ROUTES[cfg.operation]
        values = cfg.model_dump(exclude_none=True)
        values.pop("operation")
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params, body = None, None
        if method == "GET":
            params = values
        elif method in {"POST", "PUT", "PATCH"}:
            if cfg.operation == "update_input":
                body = values["input_source"]
            elif cfg.operation == "add_rows":
                body = values["rows"]
            elif cfg.operation == "update_row":
                body = values["row"]
            else:
                body = values
        token = self.config.credentials.api_key
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                "error": response.text[:1000].replace(token, "[redacted]")}
        if not response.content:
            return {"status": "success", "data": None}
        data = response.json()
        if isinstance(data, dict) and (data.get("error") or (isinstance(data.get("statusCode"), int) and data["statusCode"] >= 400)):
            return {"status": "error", "error": str(data).replace(token, "[redacted]")[:1000]}
        return {"status": "success", "data": data}

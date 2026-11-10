"""Apache Airflow 2.x Stable REST API, pinned to the 2.10.0 contract.

Basic auth must be enabled on the user's deployment. Every action is one
contract operation; no arbitrary HTTP requests or Airflow 3 token exchange.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

CONTRACT = "https://airflow.apache.org/docs/apache-airflow/2.10.0/_specs/v1.yaml"
AUTH_DOCS = "https://airflow.apache.org/docs/apache-airflow/2.10.0/security/api.html"


class ApacheBasicCredential(BaseModel):
    model_config = ConfigDict(title="Apache Airflow Username and Password", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": AUTH_DOCS,
            "x-credential-instructions": "Connect an Airflow 2.x deployment with Basic API authentication enabled. Enter its HTTPS API root, username and password. Ask your Airflow administrator to enable the Basic authentication backend and grant the DAG, run, variable or pool permissions your workflow needs."})
    credential_type: Literal["apache_basic"] = Field("apache_basic", json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="API Root", description="HTTPS API root, for example https://airflow.example.com/api/v1. An origin alone is expanded to /api/v1.")
    username: str = Field(..., min_length=1, max_length=512, title="Username")
    password: str = Field(..., min_length=1, max_length=4096, title="Password", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_base_url", mode="before")
    @classmethod
    def api_root(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter the HTTPS Airflow API root")
        value = value.strip().rstrip("/")
        try:
            p = urlsplit(value)
            if p.scheme != "https" or not p.hostname or p.username is not None or p.password is not None or p.query or p.fragment or p.port == 0:
                raise ValueError()
            if any(c.isspace() or ord(c) < 32 for c in value):
                raise ValueError()
            if p.path and (not p.path.endswith("/api/v1") or any(s in {".", ".."} for s in p.path.split("/")) or "%" in p.path):
                raise ValueError()
        except ValueError:
            raise ValueError("Use a HTTPS API root ending in /api/v1, without credentials or query parameters") from None
        return value if p.path else value + "/api/v1"

    @field_validator("username", mode="before")
    @classmethod
    def basic_username(cls, value):
        if not isinstance(value, str) or ":" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter an Airflow username without a colon or control characters")
        return value.strip()

    @field_validator("password", mode="before")
    @classmethod
    def basic_password(cls, value):
        return clean_secret(value, field_name="Password")


def _op(name, title, description=None):
    return Field(name, title=title, description=description, json_schema_extra={"ui:hidden": True})


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name in {"dag_id", "dag_run_id", "task_id", "variable_key", "pool_name", "name", "key"} and isinstance(value, str):
            if not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#%") or any(ord(c) < 32 for c in value):
                raise ValueError("Enter a single resource identifier without URL delimiters")
        return value


class _Page(_Input):
    limit: int = Field(100, ge=1, le=100, title="Page Size")
    offset: int = Field(0, ge=0, title="Offset", description="Use next_offset from the previous response to continue.")


class _DAG(_Input):
    dag_id: str = Field(..., min_length=1, max_length=250, title="DAG ID")


class _Run(_DAG):
    dag_run_id: str = Field(..., min_length=1, max_length=250, title="Run ID")


class _Task(_DAG):
    task_id: str = Field(..., min_length=1, max_length=250, title="Task ID")


class ListDAGs(_Page):
    operation: Literal["list_dags"] = _op("list_dags", "List DAGs")
    dag_id_pattern: str | None = Field(None, title="DAG ID Pattern")
    only_active: bool = Field(True, title="Only Active DAGs")
    paused: bool | None = Field(None, title="Paused")


class GetDAG(_DAG):
    operation: Literal["get_dag"] = _op("get_dag", "Get DAG")


class UpdateDAG(_DAG):
    operation: Literal["update_dag"] = _op("update_dag", "Pause or Resume DAG")
    is_paused: bool = Field(..., title="Paused", description="True pauses scheduling; false resumes it.")


class ListDAGRuns(_DAG, _Page):
    operation: Literal["list_dag_runs"] = _op("list_dag_runs", "List DAG Runs")
    order_by: Literal["start_date", "-start_date", "execution_date", "-execution_date"] = Field("-start_date", title="Order By")
    start_date_gte: str | None = Field(None, title="Started At or After", json_schema_extra={"format": "date-time"}, description="RFC 3339 timestamp with timezone.")
    start_date_lte: str | None = Field(None, title="Started At or Before", json_schema_extra={"format": "date-time"}, description="RFC 3339 timestamp with timezone.")

    @field_validator("start_date_gte", "start_date_lte")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise ValueError("Use an RFC 3339 timestamp with timezone") from None
        return value


class CreateDAGRun(_DAG):
    operation: Literal["create_dag_run"] = _op("create_dag_run", "Trigger DAG Run", "Creates a run. A paused DAG keeps it queued until scheduling resumes.")
    dag_run_id: str | None = Field(None, title="Run ID", max_length=250)
    conf_json: str = Field("{}", title="Run Configuration", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("conf_json")
    @classmethod
    def configuration(cls, value):
        if not isinstance(json.loads(value), dict):
            raise ValueError("Run configuration must be a JSON object")
        return value


class GetDAGRun(_Run):
    operation: Literal["get_dag_run"] = _op("get_dag_run", "Get DAG Run")


class UpdateDAGRunState(_Run):
    operation: Literal["update_dag_run_state"] = _op("update_dag_run_state", "Set DAG Run State")
    state: Literal["success", "failed", "queued"] = Field(..., title="State")


class ClearDAGRun(_Run):
    operation: Literal["clear_dag_run"] = _op("clear_dag_run", "Clear DAG Run", "Preview affected task instances or clear them to rerun the DAG.")
    dry_run: bool = Field(True, title="Preview Only", description="False clears task instances and permits the run to execute again.")


class SetDAGRunNote(_Run):
    operation: Literal["set_dag_run_note"] = _op("set_dag_run_note", "Set DAG Run Note")
    note: str = Field(..., title="Note")


class DeleteDAGRun(_Run):
    operation: Literal["delete_dag_run"] = _op("delete_dag_run", "Delete DAG Run", "Permanently deletes this run's metadata.")


class ListTaskInstances(_Run, _Page):
    operation: Literal["list_task_instances"] = _op("list_task_instances", "List Task Instances")


class GetTaskInstance(_Run, _Task):
    operation: Literal["get_task_instance"] = _op("get_task_instance", "Get Task Instance")


class ListTasks(_DAG):
    operation: Literal["list_tasks"] = _op("list_tasks", "List DAG Tasks")


class GetTask(_Task):
    operation: Literal["get_task"] = _op("get_task", "Get DAG Task")


class ListVariables(_Page):
    operation: Literal["list_variables"] = _op("list_variables", "List Variables")


class _Variable(_Input):
    variable_key: str = Field(..., min_length=1, title="Variable Key")


class GetVariable(_Variable):
    operation: Literal["get_variable"] = _op("get_variable", "Get Variable")


class CreateVariable(_Input):
    operation: Literal["create_variable"] = _op("create_variable", "Create Variable")
    key: str = Field(..., min_length=1, title="Key")
    value: str = Field(..., title="Value")


class UpdateVariable(_Variable):
    operation: Literal["update_variable"] = _op("update_variable", "Update Variable")
    value: str = Field(..., title="Value")


class DeleteVariable(_Variable):
    operation: Literal["delete_variable"] = _op("delete_variable", "Delete Variable")


class ListPools(_Page):
    operation: Literal["list_pools"] = _op("list_pools", "List Pools")


class _Pool(_Input):
    pool_name: str = Field(..., min_length=1, title="Pool Name")


class GetPool(_Pool):
    operation: Literal["get_pool"] = _op("get_pool", "Get Pool")


class CreatePool(_Input):
    operation: Literal["create_pool"] = _op("create_pool", "Create Pool")
    name: str = Field(..., min_length=1, title="Pool Name")
    slots: int = Field(..., ge=-1, title="Slots", description="-1 means unlimited slots.")
    description: str = Field("", title="Description")


class UpdatePool(_Pool):
    operation: Literal["update_pool"] = _op("update_pool", "Update Pool Slots")
    slots: int = Field(..., ge=-1, title="Slots", description="-1 means unlimited slots.")


class OnNewDAGRun(PollTriggerConfigBase):
    operation: Literal["on_new_dag_run"] = Field("on_new_dag_run", title="On New DAG Run", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New DAG Run"})
    dag_id: str = Field(..., min_length=1, max_length=250, title="DAG ID", description="DAG to monitor. Use ~ for all visible DAGs. Polls up to 2,000 runs; narrow the DAG if the limit is exceeded.")
    start_date_gte: str | None = Field(None, title="Started At or After", json_schema_extra={"format": "date-time"}, description="Optional RFC 3339 lower bound to exclude older history from this poll scope.")
    _timestamp = field_validator("start_date_gte")(ListDAGRuns.timestamp.__func__)


Operation = Annotated[Union[ListDAGs, GetDAG, UpdateDAG, ListDAGRuns, CreateDAGRun, GetDAGRun,
    UpdateDAGRunState, ClearDAGRun, SetDAGRunNote, DeleteDAGRun, ListTaskInstances,
    GetTaskInstance, ListTasks, GetTask, ListVariables, GetVariable, CreateVariable,
    UpdateVariable, DeleteVariable, ListPools, GetPool, CreatePool, UpdatePool, OnNewDAGRun], Field(discriminator="operation")]


class ApacheNodeConfig(NodeConfig[Operation, ApacheBasicCredential]):
    model_config = ConfigDict(title="Airflow API (Stable) Configuration")


# method, contract path, query fields, body fields, list envelope
_RUNS = "/dags/{dag_id}/dagRuns"
_RUN = _RUNS + "/{dag_run_id}"
_TASKS = "/dags/{dag_id}/tasks"
ROUTES = {
    "list_dags": ("GET", "/dags", ("limit", "offset", "dag_id_pattern", "only_active", "paused"), (), "dags"),
    "get_dag": ("GET", "/dags/{dag_id}", (), (), None),
    "update_dag": ("PATCH", "/dags/{dag_id}", (), ("is_paused",), None),
    "list_dag_runs": ("GET", _RUNS, ("limit", "offset", "order_by", "start_date_gte", "start_date_lte"), (), "dag_runs"),
    "create_dag_run": ("POST", _RUNS, (), ("dag_run_id", "conf_json"), None),
    "get_dag_run": ("GET", _RUN, (), (), None),
    "update_dag_run_state": ("PATCH", _RUN, (), ("state",), None),
    "clear_dag_run": ("POST", _RUN + "/clear", (), ("dry_run",), None),
    "set_dag_run_note": ("PATCH", _RUN + "/setNote", (), ("note",), None),
    "delete_dag_run": ("DELETE", _RUN, (), (), None),
    "list_task_instances": ("GET", _RUN + "/taskInstances", ("limit", "offset"), (), "task_instances"),
    "get_task_instance": ("GET", _RUN + "/taskInstances/{task_id}", (), (), None),
    "list_tasks": ("GET", _TASKS, (), (), "tasks"),
    "get_task": ("GET", _TASKS + "/{task_id}", (), (), None),
    "list_variables": ("GET", "/variables", ("limit", "offset"), (), "variables"),
    "get_variable": ("GET", "/variables/{variable_key}", (), (), None),
    "create_variable": ("POST", "/variables", (), ("key", "value"), None),
    "update_variable": ("PATCH", "/variables/{variable_key}", (), ("value",), None),
    "delete_variable": ("DELETE", "/variables/{variable_key}", (), (), None),
    "list_pools": ("GET", "/pools", ("limit", "offset"), (), "pools"),
    "get_pool": ("GET", "/pools/{pool_name}", (), (), None),
    "create_pool": ("POST", "/pools", (), ("name", "slots", "description"), None),
    "update_pool": ("PATCH", "/pools/{pool_name}", (), ("slots",), None),
}


class ApacheNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-apache"
    connection_evidence = ConnectionEvidence(noun="DAGs", operation="list_dags", label_keys=("dag_display_name", "dag_id"))

    @classmethod
    def get_config_model(cls):
        return ApacheNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        auth = base64.b64encode(f"{credential.username}:{credential.password}".encode()).decode("ascii")
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, credential.api_base_url + path,
                    headers={"Authorization": "Basic " + auth, "Accept": "application/json"}, params=params,
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Airflow request did not complete; inspect the server before retrying a write") from None
        if response.is_error or response.is_redirect:
            # Preserve the provider's problem detail for the connection verdict.
            detail = "Request rejected"
            try:
                payload = response.json()
                detail = payload.get("detail") or payload.get("title") or detail
            except (ValueError, AttributeError):
                pass
            detail = str(detail).replace(credential.password, "[redacted]").replace(auth, "[redacted]")
            raise ValueError(f"Airflow API error {response.status_code}: {detail[:2000]}")
        if response.status_code == 204:
            return {"deleted": True, "http_status": 204}
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Airflow returned a non-JSON response; check the API root")
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Airflow returned an invalid JSON object")
        return result

    async def _perform(self, config):
        method, path, query, fields, envelope = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in query if key in values}
        body = {key: values[key] for key in fields if key in values} if fields else None
        if config.operation == "create_dag_run":
            body["conf"] = json.loads(body.pop("conf_json"))
        if config.operation in {"update_dag", "update_variable", "update_pool"}:
            params["update_mask"] = ",".join(fields)
        result = await self._request(method, path, params=params, body=body)
        if envelope:
            rows = result.get(envelope)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Airflow returned an invalid list envelope")
            if "limit" in values:
                total = result.get("total_entries")
                if type(total) is not int or total < 0:
                    raise ValueError("Airflow returned an invalid list total")
                following = values["offset"] + len(rows)
                if following < total and not rows:
                    raise ValueError("Airflow returned an empty page before the end")
                result = {**result, "next_offset": following if following < total else None}
        return result

    async def _poll_runs(self, config):
        rows = []
        offset = 0
        for _ in range(20):
            result = await self._perform(ListDAGRuns(dag_id=config.dag_id, start_date_gte=config.start_date_gte, limit=100, offset=offset))
            rows.extend(result["dag_runs"])
            offset = result["next_offset"]
            if offset is None:
                break
        else:
            raise ValueError("More than 2,000 Airflow runs in this scope; monitor a narrower DAG")
        fresh = await self._filter_unseen(rows, lambda row: json.dumps([row["dag_id"], row["dag_run_id"]]))
        return {"dag_runs": fresh, "new_run_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_run_count")) if config.get("operation") == "on_new_dag_run" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if "new_run_count" not in output:
            return super().resolve_agent_event(output)
        runs = output.get("dag_runs", [])
        if not runs:
            return None
        lines = [f"- DAG {row['dag_id']}: run {row['dag_run_id']}, state {row.get('state') or 'unknown'}, started {row.get('start_date') or 'not yet'}" for row in runs[:20]]
        return {"text": f"Apache Airflow: {len(runs)} new DAG run(s).\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ApacheNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an Apache Airflow account")
        config = self.config.config
        if isinstance(config, OnNewDAGRun):
            return await self._poll_runs(config)
        return await self._perform(config)

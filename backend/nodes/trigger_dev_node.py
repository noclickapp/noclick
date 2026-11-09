"""Trigger.dev environment-key API: one published endpoint per operation.

Contract: https://trigger.dev/docs/v3-openapi.yaml (2024-04).
Lists return one provider page, including its pagination metadata.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class TriggerDevAPIKey(BaseModel):
    model_config = ConfigDict(title="Trigger.dev API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://cloud.trigger.dev",
            "x-credential-instructions": "In your Trigger.dev project, open API Keys and create a named environment API key with access to the operations you need, including listing runs for connection verification. Paste the key here. Personal access tokens use different endpoints and are not supported by this credential.",
            "x-help-url": "https://trigger.dev/docs/management/authentication",
        })
    credential_type: Literal["trigger_dev_api_key"] = Field("trigger_dev_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Environment API key", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Environment API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key without the Bearer prefix or whitespace")
        if value.startswith("tr_pat_"):
            raise ValueError("Use an environment API key, not a personal access token")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Run(_Input):
    run_id: str = Field(..., min_length=1, description="Trigger.dev run ID, such as run_1234.")


class _Schedule(_Input):
    schedule_id: str = Field(..., min_length=1, description="Trigger.dev schedule ID, such as sched_1234.")


class _Batch(_Input):
    batch_id: str = Field(..., min_length=1)


class _Page(_Input):
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


class TriggerOptions(_Input):
    concurrencyKey: str | None = None
    idempotencyKey: str | None = None
    delay: str | None = None
    tags: list[Annotated[str, Field(max_length=128)]] | None = Field(None, max_length=10)
    machine: Literal["micro", "small-1x", "small-2x", "medium-1x", "medium-2x", "large-1x", "large-2x"] | None = None


class TriggerItem(_Input):
    payload: JsonValue = None
    context: JsonValue = None
    options: TriggerOptions | None = None


class BatchTaskItem(TriggerItem):
    task: str = Field(..., min_length=1)


class TriggerTask(TriggerItem):
    operation: Literal["trigger_task"] = Field("trigger_task", title="Trigger task", json_schema_extra={"ui:hidden": True})
    task_identifier: str = Field(..., min_length=1)


class BatchTriggerTask(_Input):
    operation: Literal["batch_trigger_task"] = Field("batch_trigger_task", title="Batch trigger one task", json_schema_extra={"ui:hidden": True})
    task_identifier: str = Field(..., min_length=1)
    items: list[TriggerItem] = Field(..., min_length=1, max_length=1000)


class BatchTriggerTasks(_Input):
    operation: Literal["batch_trigger_tasks"] = Field("batch_trigger_tasks", title="Batch trigger tasks", json_schema_extra={"ui:hidden": True})
    items: list[BatchTaskItem] = Field(..., min_length=1, max_length=1000)


class ListRuns(_Input):
    operation: Literal["list_runs"] = Field("list_runs", title="List runs", json_schema_extra={"ui:hidden": True})
    page_size: int = Field(25, ge=10, le=100)
    after: str | None = None
    before: str | None = None
    task_identifier: str | None = None
    status: list[Literal["PENDING_VERSION", "QUEUED", "EXECUTING", "REATTEMPTING", "FROZEN", "COMPLETED", "CANCELED", "FAILED", "CRASHED", "INTERRUPTED", "SYSTEM_FAILURE"]] | None = None

    @model_validator(mode="after")
    def cursor(self):
        if self.after and self.before:
            raise ValueError("Supply after or before, not both")
        return self


class AddRunTags(_Run):
    operation: Literal["add_run_tags"] = Field("add_run_tags", title="Add run tags", json_schema_extra={"ui:hidden": True})
    tags: list[Annotated[str, Field(max_length=128)]] = Field(..., min_length=1, max_length=10)


class UpdateRunMetadata(_Run):
    operation: Literal["update_run_metadata"] = Field("update_run_metadata", title="Update run metadata", json_schema_extra={"ui:hidden": True})
    metadata: dict[str, JsonValue]


class RescheduleRun(_Run):
    operation: Literal["reschedule_run"] = Field("reschedule_run", title="Reschedule run", json_schema_extra={"ui:hidden": True})
    delay: str = Field(..., min_length=1, description="Duration such as 10m, or an ISO 8601 date-time.")


class CreateSchedule(_Input):
    operation: Literal["create_schedule"] = Field("create_schedule", title="Create schedule", json_schema_extra={"ui:hidden": True})
    task: str = Field(..., min_length=1)
    cron: str = Field(..., min_length=1)
    deduplication_key: str = Field(..., min_length=1)
    external_id: str | None = None
    timezone: str | None = Field(None, description="IANA timezone, for example America/New_York; defaults to UTC.")


class UpdateSchedule(_Schedule):
    operation: Literal["update_schedule"] = Field("update_schedule", title="Update schedule", json_schema_extra={"ui:hidden": True})
    task: str = Field(..., min_length=1)
    cron: str = Field(..., min_length=1)
    external_id: str | None = None
    timezone: str | None = None


class _Queue(_Input):
    queue: str = Field(..., min_length=1, description="Queue ID, task identifier or custom queue name according to queue_type.")
    queue_type: Literal["id", "task", "custom"] = "id"


class PauseQueue(_Queue):
    operation: Literal["pause_queue"] = Field("pause_queue", title="Pause or resume queue", json_schema_extra={"ui:hidden": True})
    action: Literal["pause", "resume"]


class GetRun(_Run):
    operation: Literal["get_run"] = Field("get_run", title="Get run", json_schema_extra={"ui:hidden": True})


class ReplayRun(_Run):
    operation: Literal["replay_run"] = Field("replay_run", title="Replay run", json_schema_extra={"ui:hidden": True})


class CancelRun(_Run):
    operation: Literal["cancel_run"] = Field("cancel_run", title="Cancel run", json_schema_extra={"ui:hidden": True})


class GetRunResult(_Run):
    operation: Literal["get_run_result"] = Field("get_run_result", title="Get run result", json_schema_extra={"ui:hidden": True})


class GetBatch(_Batch):
    operation: Literal["get_batch"] = Field("get_batch", title="Get batch", json_schema_extra={"ui:hidden": True})


class GetBatchResults(_Batch):
    operation: Literal["get_batch_results"] = Field("get_batch_results", title="Get batch results", json_schema_extra={"ui:hidden": True})


class ListSchedules(_Page):
    operation: Literal["list_schedules"] = Field("list_schedules", title="List schedules", json_schema_extra={"ui:hidden": True})


class GetSchedule(_Schedule):
    operation: Literal["get_schedule"] = Field("get_schedule", title="Get schedule", json_schema_extra={"ui:hidden": True})


class DeleteSchedule(_Schedule):
    operation: Literal["delete_schedule"] = Field("delete_schedule", title="Delete schedule", json_schema_extra={"ui:hidden": True})


class ActivateSchedule(_Schedule):
    operation: Literal["activate_schedule"] = Field("activate_schedule", title="Activate schedule", json_schema_extra={"ui:hidden": True})


class DeactivateSchedule(_Schedule):
    operation: Literal["deactivate_schedule"] = Field("deactivate_schedule", title="Deactivate schedule", json_schema_extra={"ui:hidden": True})


class ListQueues(_Page):
    operation: Literal["list_queues"] = Field("list_queues", title="List queues", json_schema_extra={"ui:hidden": True})


class GetQueue(_Queue):
    operation: Literal["get_queue"] = Field("get_queue", title="Get queue", json_schema_extra={"ui:hidden": True})


TriggerDevConfig = Annotated[Union[TriggerTask, BatchTriggerTask, BatchTriggerTasks, ListRuns, AddRunTags, UpdateRunMetadata, RescheduleRun, CreateSchedule, UpdateSchedule, PauseQueue, GetRun, ReplayRun, CancelRun, GetRunResult, GetBatch, GetBatchResults, ListSchedules, GetSchedule, DeleteSchedule, ActivateSchedule, DeactivateSchedule, ListQueues, GetQueue], Field(discriminator="operation")]


class TriggerDevFullConfig(NodeConfig[TriggerDevConfig, TriggerDevAPIKey]):
    pass


ROUTES = {'get_run': ('GET', '/api/v3/runs/{run_id}'),
 'replay_run': ('POST', '/api/v1/runs/{run_id}/replay'),
 'cancel_run': ('POST', '/api/v2/runs/{run_id}/cancel'),
 'get_run_result': ('GET', '/api/v1/runs/{run_id}/result'),
 'get_batch': ('GET', '/api/v1/batches/{batch_id}'),
 'get_batch_results': ('GET', '/api/v1/batches/{batch_id}/results'),
 'list_schedules': ('GET', '/api/v1/schedules'),
 'get_schedule': ('GET', '/api/v1/schedules/{schedule_id}'),
 'delete_schedule': ('DELETE', '/api/v1/schedules/{schedule_id}'),
 'activate_schedule': ('POST', '/api/v1/schedules/{schedule_id}/activate'),
 'deactivate_schedule': ('POST', '/api/v1/schedules/{schedule_id}/deactivate'),
 'list_queues': ('GET', '/api/v1/queues'),
 'get_queue': ('GET', '/api/v1/queues/{queue}'),
 'trigger_task': ('POST', '/api/v1/tasks/{task_identifier}/trigger'),
 'batch_trigger_task': ('POST', '/api/v1/tasks/{task_identifier}/batch'),
 'batch_trigger_tasks': ('POST', '/api/v1/tasks/batch'),
 'list_runs': ('GET', '/api/v1/runs'),
 'add_run_tags': ('POST', '/api/v1/runs/{run_id}/tags'),
 'update_run_metadata': ('PUT', '/api/v1/runs/{run_id}/metadata'),
 'reschedule_run': ('POST', '/api/v1/runs/{run_id}/reschedule'),
 'create_schedule': ('POST', '/api/v1/schedules'),
 'update_schedule': ('PUT', '/api/v1/schedules/{schedule_id}'),
 'pause_queue': ('POST', '/api/v1/queues/{queue}/pause')}


class TriggerDevNode(WorkflowNode):
    integration_type = "automation-trigger-dev"
    connection_evidence = ConnectionEvidence(operation="list_runs", noun="runs")

    @classmethod
    def get_config_model(cls):
        return TriggerDevFullConfig

    async def execute(self, input_data):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Trigger.dev environment API key")
        values = config.model_dump(exclude_none=True)
        operation = values.pop("operation")
        method, path = ROUTES[operation]
        for name in ("run_id", "batch_id", "schedule_id", "task_identifier", "queue"):
            if "{" + name + "}" in path:
                value = values.pop(name)
                if value in {".", ".."} or any(c in value for c in "/\\?#"):
                    raise ValueError("Use a single resource ID or name, without URL separators")
                path = path.replace("{" + name + "}", quote(value, safe=""))
        params = {}
        body = None
        if operation == "list_runs":
            params = {"page[size]": values.pop("page_size")}
            for name in ("after", "before"):
                if name in values:
                    params[f"page[{name}]"] = values.pop(name)
            for name, wire in (("task_identifier", "taskIdentifier"), ("status", "status")):
                if name in values:
                    value = values.pop(name)
                    params[f"filter[{wire}]"] = ",".join(value) if isinstance(value, list) else value
        elif operation in {"list_schedules", "list_queues"}:
            params = {"page": values["page"], "perPage": values["per_page"]}
        elif operation == "get_queue":
            params = {"type": values["queue_type"]}
        elif operation == "pause_queue":
            body = {"type": values["queue_type"], "action": values["action"]}
        elif operation in {"create_schedule", "update_schedule"}:
            body = { {"deduplication_key": "deduplicationKey", "external_id": "externalId"}.get(k, k): v for k, v in values.items()}
        elif operation in {"trigger_task", "batch_trigger_task", "batch_trigger_tasks", "add_run_tags", "update_run_metadata", "reschedule_run"}:
            body = values
            # Explicit JSON null is a valid payload and must survive serialization.
            def item_body(item):
                result = item.model_dump(exclude_none=True)
                for key in ("payload", "context"):
                    if key in item.model_fields_set:
                        result[key] = getattr(item, key)
                return result
            if operation == "trigger_task":
                for key in ("payload", "context"):
                    if key in config.model_fields_set:
                        body[key] = getattr(config, key)
            elif operation in {"batch_trigger_task", "batch_trigger_tasks"}:
                body["items"] = [item_body(item) for item in config.items]
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.trigger.dev" + path,
                params=params, **({"json": body} if body is not None else {}),
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"})
        response.raise_for_status()
        if response.status_code == 204 or (operation == "delete_schedule" and not response.content):
            return {"success": True}
        result = response.json()
        # A failed task result is data, not a failure of this retrieval request.
        if operation == "get_run_result":
            return {"result": result}
        return result if isinstance(result, dict) else {"data": result}

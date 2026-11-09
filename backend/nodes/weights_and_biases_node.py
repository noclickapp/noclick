"""Automate W&B Weave traces, versioned objects, tables, feedback and costs.

Each operation uses one published Trace Service API endpoint on W&B Cloud.
The pasted API key and project also power the connection's object-list proof.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://trace.wandb.ai"
DOCS = "https://docs.coreweave.com/products/wandb/weave/reference/service-api"


class WeightsAndBiasesAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Weights And Biases API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://wandb.ai/authorize",
            "x-credential-instructions": "Paste your W&B API key and the entity/project of a Weave project you can access. NoClick verifies access by listing that project's objects. Reads and writes use the key's existing permissions on W&B Cloud.",
        })
    credential_type: Literal["weights_and_biases_api_key"] = Field("weights_and_biases_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    project_id: str = Field(..., title="Project", min_length=3, max_length=512,
        description="W&B entity/project, for example my-team/my-project.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your W&B API key")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without an Authorization header")
        return value

    @field_validator("project_id")
    @classmethod
    def project(cls, value):
        value = value.strip()
        parts = value.split("/")
        if len(parts) != 2 or any(not p or p in {".", ".."} or any(c.isspace() or c in "?#\\" for c in p) for p in parts):
            raise ValueError("Enter the W&B entity/project, not a URL")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    limit: int = Field(100, ge=1, le=1000, description="Maximum items in this page. A full page may have a following page.")
    offset: int = Field(0, ge=0, description="Number of items to skip; use next_offset to continue.")


class CallFilter(Input):
    call_ids: list[str] | None = None
    trace_ids: list[str] | None = None
    parent_ids: list[str] | None = None
    op_names: list[str] | None = None
    trace_roots_only: bool | None = None


class ObjectFilter(Input):
    object_ids: list[str] | None = None
    base_object_classes: list[str] | None = Field(None, description="For example Dataset, Model or Evaluation.")
    latest_only: bool | None = None
    is_op: bool | None = None
    tags: list[str] | None = None
    aliases: list[str] | None = None


class ListCalls(Page):
    operation: Literal["list_calls"] = "list_calls"
    filter: CallFilter | None = None
    include_costs: bool = False
    include_feedback: bool = False


class GetCall(Input):
    operation: Literal["get_call"] = "get_call"
    id: str = Field(..., min_length=1, title="Call ID")
    include_costs: bool = False


class UpdateCall(Input):
    operation: Literal["update_call"] = "update_call"
    call_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1, description="New display name of the call.")


class DeleteCalls(Input):
    operation: Literal["delete_calls"] = "delete_calls"
    call_ids: list[str] = Field(..., min_length=1, max_length=1000,
        description="Explicit call IDs to delete. Deletion may also remove their descendants.")


class GetCallStats(Input):
    operation: Literal["get_call_stats"] = "get_call_stats"
    filter: CallFilter | None = None


class ListObjects(Page):
    operation: Literal["list_objects"] = "list_objects"
    filter: ObjectFilter | None = None
    metadata_only: bool = True


class GetObject(Input):
    operation: Literal["get_object"] = "get_object"
    object_id: str = Field(..., min_length=1)
    digest: str = Field(..., min_length=1, description="Version digest or alias, such as latest.")


class CreateObject(Input):
    operation: Literal["create_object"] = "create_object"
    object_id: str = Field(..., min_length=1)
    val: Any = Field(..., description="JSON value to publish as a new version of the object.")


class DeleteObject(Input):
    operation: Literal["delete_object"] = "delete_object"
    object_id: str = Field(..., min_length=1)
    digests: list[str] = Field(..., min_length=1, description="Explicit versions or aliases to delete; this operation requires a selection.")


class CreateTable(Input):
    operation: Literal["create_table"] = "create_table"
    rows: list[dict[str, Any]] = Field(..., max_length=1000, description="JSON rows for a new immutable Weave table.")


class QueryTable(Page):
    operation: Literal["query_table"] = "query_table"
    digest: str = Field(..., min_length=1)


class GetTableStats(Input):
    operation: Literal["get_table_stats"] = "get_table_stats"
    digest: str = Field(..., min_length=1)


class ReadRefs(Input):
    operation: Literal["read_refs"] = "read_refs"
    refs: list[str] = Field(..., min_length=1, max_length=1000, description="Weave references to resolve in one batch.")


class CreateFeedback(Input):
    operation: Literal["create_feedback"] = "create_feedback"
    weave_ref: str = Field(..., min_length=1)
    feedback_type: str = Field(..., min_length=1, description="Feedback type, for example custom.")
    payload: dict[str, Any] = Field(..., description="JSON payload required by the chosen feedback type.")
    creator: str | None = None


class ListFeedback(Page):
    operation: Literal["list_feedback"] = "list_feedback"


class ListCosts(Page):
    operation: Literal["list_costs"] = "list_costs"


class GetProjectStats(Input):
    operation: Literal["get_project_stats"] = "get_project_stats"


Operation = Annotated[Union[ListCalls, GetCall, UpdateCall, DeleteCalls, GetCallStats,
    ListObjects, GetObject, CreateObject, DeleteObject, CreateTable, QueryTable,
    GetTableStats, ReadRefs, CreateFeedback, ListFeedback, ListCosts, GetProjectStats], Field(discriminator="operation")]


class WeightsAndBiasesConfig(NodeConfig[Operation, WeightsAndBiasesAPIKeyCredential]):
    pass


# Fixed routes prevent caller-controlled hosts, methods and arbitrary API requests.
ROUTES = {
    "list_calls": "/calls/stream_query", "get_call": "/call/read",
    "update_call": "/call/update", "delete_calls": "/calls/delete",
    "get_call_stats": "/calls/query_stats", "list_objects": "/objs/query",
    "get_object": "/obj/read", "create_object": "/obj/create", "delete_object": "/obj/delete",
    "create_table": "/table/create", "query_table": "/table/query",
    "get_table_stats": "/table/query_stats", "read_refs": "/refs/read_batch",
    "create_feedback": "/feedback/create", "list_feedback": "/feedback/query",
    "list_costs": "/cost/query", "get_project_stats": "/project/stats",
}
LIST_KEYS = {"list_objects": "objs", "query_table": "rows", "list_feedback": "result", "list_costs": "results"}
WRITES = {"update_call", "delete_calls", "create_object", "delete_object", "create_table", "create_feedback"}


class WeightsAndBiasesNode(WorkflowNode):
    integration_type = "automation-weights-and-biases"
    connection_evidence = ConnectionEvidence(noun="Weave objects", operation="list_objects", label_keys=("object_id", "digest"))

    @classmethod
    def get_config_model(cls):
        return WeightsAndBiasesConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Weights And Biases API key and project")
        op = self.config.config
        credential = self.config.credentials
        action = op.operation
        body = op.model_dump(exclude={"operation"}, exclude_none=True)
        if action == "create_object":
            # JSON null is a valid required object value; do not omit it.
            body["val"] = op.val
        if action != "read_refs":
            body["project_id"] = credential.project_id
        if action == "create_object":
            body = {"obj": body}
        elif action == "create_table":
            body = {"table": body}
        headers = {"Authorization": "Bearer " + credential.api_key,
            "Accept": "application/jsonl" if action == "list_calls" else "application/json"}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request("POST", BASE_URL + ROUTES[action], json=body, headers=headers)
        except Exception:
            # A write may have reached the server. Never retry automatically.
            raise ValueError("W&B request could not be confirmed; inspect the project before retrying a write") from None
        if response.status_code != 200:
            # Preserve the provider's rejection for the shared connection verdict.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            output = {"status": "error", "http_status": response.status_code, "message": message,
                "write_outcome": "unverified" if action in WRITES else None}
            await self.emit(output)
            return output
        try:
            if len(response.content) > 10_000_000:
                raise ValueError()
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if action == "list_calls" and mime in {"application/json", "application/jsonl", "application/x-ndjson", "application/ndjson"}:
                try:
                    parsed = response.json()
                    data = parsed if isinstance(parsed, list) else [parsed]
                except ValueError:
                    data = [json.loads(line) for line in response.text.splitlines() if line.strip()]
            else:
                if mime != "application/json":
                    raise ValueError()
                data = response.json()
            if action == "list_calls":
                if not isinstance(data, list) or any(not isinstance(row, dict) or "id" not in row for row in data):
                    raise ValueError()
            elif not isinstance(data, dict) or "error" in data or "detail" in data:
                raise ValueError()
            if action in {"create_object", "create_table"} and not isinstance(data.get("digest"), str):
                raise ValueError()
            if action in {"delete_calls", "delete_object"} and type(data.get("num_deleted")) is not int:
                raise ValueError()
            if action in {"get_call_stats", "get_table_stats"} and type(data.get("count")) is not int:
                raise ValueError()
            if action == "get_call" and ("call" not in data or (data["call"] is not None and not isinstance(data["call"], dict))):
                raise ValueError()
            if action == "get_object" and not isinstance(data.get("obj"), dict):
                raise ValueError()
            if action == "read_refs" and not isinstance(data.get("vals"), list):
                raise ValueError()
            if action == "create_feedback" and not isinstance(data.get("id"), str):
                raise ValueError()
            items = data if action == "list_calls" else data.get(LIST_KEYS.get(action, ""))
            if action in LIST_KEYS and (not isinstance(items, list) or any(not isinstance(row, dict) for row in items)):
                raise ValueError()
            output = {"status": "success", "operation": action, "data": data}
            if isinstance(op, Page):
                if len(items) > op.limit:
                    raise ValueError()
                # No total exists on most endpoints: full pages MAY have more.
                output.update(items=items, next_offset=op.offset + len(items) if len(items) == op.limit else None,
                    has_more_possible=len(items) == op.limit)
            if action in WRITES:
                output["write_acknowledged"] = True
        except Exception:
            raise ValueError("W&B response could not be parsed; inspect the project before retrying a write") from None
        await self.emit(output)
        return output

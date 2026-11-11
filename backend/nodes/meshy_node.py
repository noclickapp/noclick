"""Meshy task automation using the provider's published REST API.

Creates return task IDs for later polling; each operation issues one request.
No asset URL is downloaded and mutations are never automatically retried.
"""
from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.meshy.ai/openapi"


class MeshyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Meshy API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.meshy.ai/developers/keys",
            "x-credential-instructions": "Create an API key in Meshy's Developer Platform and paste it here. Generation consumes your Meshy credits."
        })
    credential_type: Literal["meshy_api_key"] = Field("meshy_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("task_id", "input_task_id", "preview_task_id", check_fields=False)
    @classmethod
    def task_identifier(cls, value):
        if value is not None:
            return str(UUID(value))
        return value

    @field_validator("image_url", "model_url", check_fields=False)
    @classmethod
    def asset_url(cls, value):
        if value is not None:
            parsed = urlsplit(value)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Supply an HTTP(S) asset URL accessible to Meshy")
        return value


class Page(Input):
    page_num: int = Field(1, ge=1, le=255, description="One-based page. Fetch another page explicitly.")
    page_size: int = Field(10, ge=1, le=100)
    sort_by: Literal["created_at", "-created_at"] = "-created_at"


class TaskInput(Input):
    task_id: str = Field(..., description="Meshy task UUID returned by create or list.")


class Generation(Input):
    name: str | None = Field(None, max_length=100)
    ai_model: Literal["meshy-6", "meshy-6-lite", "meshy-7.1", "latest"] | None = Field(None,
        description="Choose for your project: https://docs.meshy.ai/api/models. Omission uses Meshy's default, or inherits the preview model for refine.")
    topology: Literal["quad", "triangle"] | None = None
    target_polycount: int | None = Field(None, ge=100, le=300000)
    enable_pbr: bool | None = None


class CreateTextTo3D(Generation):
    """Create geometry with preview; texture it separately with refine. Consumes credits."""
    operation: Literal["create_text_to_3d"] = "create_text_to_3d"
    mode: Literal["preview", "refine"]
    prompt: str | None = Field(None, min_length=1, max_length=800)
    preview_task_id: str | None = None
    texture_prompt: str | None = Field(None, max_length=800)
    negative_prompt: str | None = Field(None, max_length=800)

    @model_validator(mode="after")
    def phase_input(self):
        if self.mode == "preview" and not self.prompt:
            raise ValueError("Preview requires a prompt")
        if self.mode == "refine" and not self.preview_task_id:
            raise ValueError("Refine requires a preview task ID")
        return self


class CreateImageTo3D(Generation):
    """Generate a model from an image or a previous image task. Consumes credits."""
    operation: Literal["create_image_to_3d"] = "create_image_to_3d"
    image_url: str | None = None
    input_task_id: str | None = None
    should_texture: bool | None = None
    texture_prompt: str | None = Field(None, max_length=800)

    @model_validator(mode="after")
    def source(self):
        if sum(x is not None for x in (self.image_url, self.input_task_id)) != 1:
            raise ValueError("Supply exactly one image URL or input task ID")
        return self


class CreateMultiImageTo3D(Generation):
    """Generate a model from one to four views of the same object. Consumes credits."""
    operation: Literal["create_multi_image_to_3d"] = "create_multi_image_to_3d"
    image_urls: list[str] | None = Field(None, min_length=1, max_length=4)
    input_task_id: str | None = None
    should_texture: bool | None = None

    @field_validator("image_urls")
    @classmethod
    def images(cls, value):
        if value is not None:
            for image in value:
                cls.asset_url(image)
        return value

    @model_validator(mode="after")
    def source(self):
        if sum(x is not None for x in (self.image_urls, self.input_task_id)) != 1:
            raise ValueError("Supply exactly one image URL list or input task ID")
        return self


class ModelSource(Input):
    input_task_id: str | None = None
    model_url: str | None = Field(None, description="Public model URL; retexture requires a GLB.")

    @model_validator(mode="after")
    def source(self):
        if sum(x is not None for x in (self.model_url, self.input_task_id)) != 1:
            raise ValueError("Supply exactly one model URL or input task ID")
        return self


class CreateRetexture(ModelSource):
    """Apply a text style to an existing model. Consumes credits."""
    operation: Literal["create_retexture"] = "create_retexture"
    text_style_prompt: str = Field(..., min_length=1, max_length=800)
    ai_model: Literal["meshy-6", "meshy-6-lite", "meshy-7", "latest"] | None = None
    enable_pbr: bool | None = None
    enable_original_uv: bool | None = None
    texture_resolution: Literal["2k", "4k", "8k"] | None = None


class CreateRemesh(ModelSource):
    """Change topology or polygon budget of an existing model. Consumes credits."""
    operation: Literal["create_remesh"] = "create_remesh"
    topology: Literal["quad", "triangle"] | None = None
    target_polycount: int | None = Field(None, ge=100, le=300000)
    target_formats: list[Literal["glb", "obj", "fbx", "stl", "usdz", "blend", "3mf"]] | None = None


class ListTextTo3D(Page):
    """List text to 3d tasks using one REST request."""
    operation: Literal["list_text_to_3d"] = "list_text_to_3d"


class GetTextTo3D(TaskInput):
    """Get text to 3d tasks using one REST request."""
    operation: Literal["get_text_to_3d"] = "get_text_to_3d"


class DeleteTextTo3D(TaskInput):
    """Delete text to 3d tasks using one REST request."""
    operation: Literal["delete_text_to_3d"] = "delete_text_to_3d"


class ListImageTo3D(Page):
    """List image to 3d tasks using one REST request."""
    operation: Literal["list_image_to_3d"] = "list_image_to_3d"


class GetImageTo3D(TaskInput):
    """Get image to 3d tasks using one REST request."""
    operation: Literal["get_image_to_3d"] = "get_image_to_3d"


class DeleteImageTo3D(TaskInput):
    """Delete image to 3d tasks using one REST request."""
    operation: Literal["delete_image_to_3d"] = "delete_image_to_3d"


class ListMultiImageTo3D(Page):
    """List multi image to 3d tasks using one REST request."""
    operation: Literal["list_multi_image_to_3d"] = "list_multi_image_to_3d"


class GetMultiImageTo3D(TaskInput):
    """Get multi image to 3d tasks using one REST request."""
    operation: Literal["get_multi_image_to_3d"] = "get_multi_image_to_3d"


class DeleteMultiImageTo3D(TaskInput):
    """Delete multi image to 3d tasks using one REST request."""
    operation: Literal["delete_multi_image_to_3d"] = "delete_multi_image_to_3d"


class ListRetexture(Page):
    """List retexture tasks using one REST request."""
    operation: Literal["list_retexture"] = "list_retexture"


class GetRetexture(TaskInput):
    """Get retexture tasks using one REST request."""
    operation: Literal["get_retexture"] = "get_retexture"


class DeleteRetexture(TaskInput):
    """Delete retexture tasks using one REST request."""
    operation: Literal["delete_retexture"] = "delete_retexture"


class ListRemesh(Page):
    """List remesh tasks using one REST request."""
    operation: Literal["list_remesh"] = "list_remesh"


class GetRemesh(TaskInput):
    """Get remesh tasks using one REST request."""
    operation: Literal["get_remesh"] = "get_remesh"


class DeleteRemesh(TaskInput):
    """Delete remesh tasks using one REST request."""
    operation: Literal["delete_remesh"] = "delete_remesh"


class GetBalance(Input):
    """Read the API account's remaining credits without creating a task."""
    operation: Literal["get_balance"] = "get_balance"


class NewTasks(PollTriggerConfigBase):
    """Baseline existing tasks, then emit newly created tasks of this kind.

    Meshy's webhooks require dashboard setup; its API lists tasks by creation time.
    Each poll scans at most 10,000 tasks and fails without advancing state if truncated.
    """


class OnNewTextTo3D(NewTasks):
    """Watch newly created text-to-3D tasks. Existing history is baselined; fewer than 10,000 tasks are supported."""
    operation: Literal["on_new_text_to_3d"] = Field("on_new_text_to_3d", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Text to 3D Task"})


class OnNewImageTo3D(NewTasks):
    """Watch newly created image-to-3D tasks. Existing history is baselined; fewer than 10,000 tasks are supported."""
    operation: Literal["on_new_image_to_3d"] = Field("on_new_image_to_3d", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Image to 3D Task"})


class OnNewMultiImageTo3D(NewTasks):
    """Watch newly created multi-image tasks. Existing history is baselined; fewer than 10,000 tasks are supported."""
    operation: Literal["on_new_multi_image_to_3d"] = Field("on_new_multi_image_to_3d", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Multi-Image to 3D Task"})


class OnNewRetexture(NewTasks):
    """Watch newly created retexture tasks. Existing history is baselined; fewer than 10,000 tasks are supported."""
    operation: Literal["on_new_retexture"] = Field("on_new_retexture", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Retexture Task"})


class OnNewRemesh(NewTasks):
    """Watch newly created remesh tasks. Existing history is baselined; fewer than 10,000 tasks are supported."""
    operation: Literal["on_new_remesh"] = Field("on_new_remesh", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Remesh Task"})


POLL_OPERATIONS = {
    "on_new_text_to_3d": ListTextTo3D,
    "on_new_image_to_3d": ListImageTo3D,
    "on_new_multi_image_to_3d": ListMultiImageTo3D,
    "on_new_retexture": ListRetexture,
    "on_new_remesh": ListRemesh,
}


MeshyOperation = Annotated[Union[CreateTextTo3D, CreateImageTo3D, CreateMultiImageTo3D, CreateRetexture, CreateRemesh, ListTextTo3D, GetTextTo3D, DeleteTextTo3D, ListImageTo3D, GetImageTo3D, DeleteImageTo3D, ListMultiImageTo3D, GetMultiImageTo3D, DeleteMultiImageTo3D, ListRetexture, GetRetexture, DeleteRetexture, ListRemesh, GetRemesh, DeleteRemesh, GetBalance, OnNewTextTo3D, OnNewImageTo3D, OnNewMultiImageTo3D, OnNewRetexture, OnNewRemesh], Field(discriminator="operation")]


class MeshyConfig(NodeConfig[MeshyOperation, MeshyAPIKeyCredential]):
    pass


# Each entry maps to exactly one operation in Meshy's published OpenAPI contract.
ROUTES = {
    'create_text_to_3d': ('POST', '/v2/text-to-3d'),
    'list_text_to_3d': ('GET', '/v2/text-to-3d'),
    'get_text_to_3d': ('GET', '/v2/text-to-3d/{id}'),
    'delete_text_to_3d': ('DELETE', '/v2/text-to-3d/{id}'),
    'create_image_to_3d': ('POST', '/v1/image-to-3d'),
    'list_image_to_3d': ('GET', '/v1/image-to-3d'),
    'get_image_to_3d': ('GET', '/v1/image-to-3d/{id}'),
    'delete_image_to_3d': ('DELETE', '/v1/image-to-3d/{id}'),
    'create_multi_image_to_3d': ('POST', '/v1/multi-image-to-3d'),
    'list_multi_image_to_3d': ('GET', '/v1/multi-image-to-3d'),
    'get_multi_image_to_3d': ('GET', '/v1/multi-image-to-3d/{id}'),
    'delete_multi_image_to_3d': ('DELETE', '/v1/multi-image-to-3d/{id}'),
    'create_retexture': ('POST', '/v1/retexture'),
    'list_retexture': ('GET', '/v1/retexture'),
    'get_retexture': ('GET', '/v1/retexture/{id}'),
    'delete_retexture': ('DELETE', '/v1/retexture/{id}'),
    'create_remesh': ('POST', '/v1/remesh'),
    'list_remesh': ('GET', '/v1/remesh'),
    'get_remesh': ('GET', '/v1/remesh/{id}'),
    'delete_remesh': ('DELETE', '/v1/remesh/{id}'),
    'get_balance': ('GET', '/v1/balance'),
}


class MeshyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-meshy"
    connection_evidence = ConnectionEvidence(operation="get_balance", noun="Meshy account credit balance")

    @classmethod
    def get_config_model(cls):
        return MeshyConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in POLL_OPERATIONS:
            return output.get("status") == "success" and bool(output.get("new_task_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if "new_task_count" not in output:
            return super().resolve_agent_event(output)
        tasks = output.get("tasks", [])
        if not tasks:
            return None
        kind = output["task_kind"]
        path = ROUTES["list_" + kind][1]
        content_field = "prompt" if kind == "text_to_3d" else (
            "text_style_prompt" if kind == "retexture" else "object_prompt")
        lines = []
        for task in tasks[:10]:
            title = task.get("name") or task.get(content_field) or "Untitled task"
            line = (f"- {title}: {task['status']} "
                    f"(task ID {task['id']}; {BASE_URL}{path}/{task['id']})")
            model_url = (task.get("model_urls") or {}).get("glb")
            if model_url:
                line += f"; GLB model: {model_url}"
            lines.append(line)
        if len(tasks) > 10:
            lines.append(f"- {len(tasks) - 10} more tasks in the trigger output")
        return {"text": f"Your Meshy account has {len(tasks)} new {kind.replace('_', ' ')} task(s):\n"
                + "\n".join(lines), "conversation_key": None}

    async def _poll_new_tasks(self, operation):
        tasks = []
        list_config = POLL_OPERATIONS[operation]
        for page_num in range(1, 101):
            result = await self._execute_operation(list_config(page_num=page_num, page_size=100))
            if result["status"] != "success":
                return result
            rows = result["tasks"]
            if any(not row["id"] or row.get("status") not in {
                    "PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED", "CANCELED"} for row in rows):
                return {"status": "error", "error": "Meshy returned an unexpected task list"}
            tasks.extend(rows)
            if len(rows) < 100:
                break
        else:
            raise ValueError("Meshy task history exceeds the 10,000-task polling limit")
        # Oldest first, so a batch reaches the agent in creation order.
        unique = {task["id"]: task for task in reversed(tasks)}
        fresh = await self._filter_unseen(list(unique.values()), lambda task: task["id"])
        return {"status": "success", "tasks": fresh, "new_task_count": len(fresh),
                "task_kind": operation.removeprefix("on_new_")}

    async def execute(self, inputs):
        cfg = self.config
        if not cfg.credentials:
            raise ValueError("Connect a Meshy API key")
        op = cfg.config
        if isinstance(op, NewTasks):
            return await self._poll_new_tasks(op.operation)
        return await self._execute_operation(op)

    async def _execute_operation(self, op):
        cfg = self.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        task_id = values.pop("task_id", None)
        if task_id:
            path = path.replace("{id}", task_id)
        kwargs = {"params": values} if method == "GET" else {"json": values} if method == "POST" else {}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + cfg.credentials.api_key, "Accept": "application/json"}, **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "Meshy request could not be confirmed. Inspect recent tasks before retrying a create.", "outcome_unknown": method == "POST"}
        expected = 202 if method == "POST" else 200
        if method == "DELETE":
            expected = 200
        if response.status_code != expected:
            # Preserve provider rejection text for connect evidence without leaking the key.
            try:
                error = response.json().get("message") or response.json().get("error")
            except (ValueError, AttributeError):
                error = None
            error = str(error or "Meshy rejected the request").replace(cfg.credentials.api_key, "[redacted]")[:1000]
            return {"status": "error", "error": error, "http_status": response.status_code,
                    "outcome_unknown": method == "POST" and response.status_code >= 500}
        if method == "DELETE":
            return {"status": "success", "deleted_task_id": task_id, "http_status": response.status_code}
        try:
            data = response.json()
            if method == "POST":
                if not isinstance(data, dict) or not isinstance(data.get("result"), str) or not data["result"]:
                    raise ValueError()
                return {"status": "success", "task_id": data["result"], "task_completed": False, "http_status": response.status_code}
            if op.operation.startswith("list_"):
                if not isinstance(data, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in data):
                    raise ValueError()
                return {"status": "success", "tasks": data, "page_num": op.page_num,
                        "next_page_num": op.page_num + 1 if len(data) == op.page_size and op.page_num < 255 else None,
                        "has_more": None if len(data) == op.page_size else False, "http_status": response.status_code}
            if not isinstance(data, dict):
                raise ValueError()
            if op.operation == "get_balance":
                if type(data.get("balance")) is not int:
                    raise ValueError()
            elif not isinstance(data.get("id"), str) or data.get("status") not in {"PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED", "CANCELED"}:
                raise ValueError()
            return {"status": "success", "data": data, "http_status": response.status_code}
        except ValueError:
            return {"status": "error", "error": "Meshy returned an unexpected response; inspect tasks before retrying a create.",
                    "http_status": response.status_code, "outcome_unknown": method == "POST"}

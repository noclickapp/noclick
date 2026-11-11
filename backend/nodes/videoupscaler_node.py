"""VideoUpscaler's five published OpenAPI operations and newest-task polling.

Contract: https://videoupscaler.co/openapi.json (1.0.0).
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://videoupscaler.co/api/v1"


def operation(name, label, *, trigger=False):
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-display-name": label,
        "x-category": "Triggers" if trigger else "Video", "x-is-trigger": trigger,
    })


class VideoUpscalerAPIKey(BaseModel):
    model_config = ConfigDict(title="VideoUpscaler API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://videoupscaler.co/settings/apikeys",
            "x-credential-instructions": "Paste an API key from Settings → API Keys. API access requires an account that has bought credits or subscribed. Creating an upscale spends your account's credits.",
        })
    credential_type: Literal["videoupscaler_api_key"] = Field("videoupscaler_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class UpscaleOps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["flashvsr", "anime"] | None = None
    denoise: Literal[0, 1, 2, 3] | None = None
    deinterlace: bool | None = None
    deflicker: bool | None = None
    stabilize: bool | None = None
    faceRestore: bool | None = Field(None, title="Restore Faces", description="Doubles the credit rate.")
    fpsMultiplier: Literal[1, 2, 4, 8] | None = Field(None, title="Frame Rate Multiplier", description="Values above 1 double the credit rate.")
    slowMotion: bool | None = Field(None, title="Slow Motion")
    hdr: Literal["none", "hdr10", "hlg"] | None = None


class CreateUpscaleConfig(BaseModel):
    operation: Literal["create_upscale_task"] = operation("create_upscale_task", "Create Upscale Task")
    video_url: str = Field(..., title="Video URL", description="Public MP4, MOV or WebM URL, or video_url from Create Upload URL.")
    resolution: Literal["1080p", "2k", "4k"] = Field(..., title="Resolution")
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, title="Idempotency Key", description="Reuse the same key when retrying to avoid a second charge.")
    webhook_url: str | None = Field(None, title="Completion Webhook URL", description="Optional HTTPS URL receiving the Task on completion or failure.")
    ops: UpscaleOps | None = Field(None, title="Enhancement Options")

    @field_validator("idempotency_key")
    @classmethod
    def ascii_key(cls, value):
        if value is not None and any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("Use 1–255 printable ASCII characters")
        return value

    @field_validator("video_url", "webhook_url")
    @classmethod
    def public_url(cls, value, info):
        if value is None:
            return value
        parsed = urlsplit(value)
        schemes = {"https"} if info.field_name == "webhook_url" else {"http", "https"}
        if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use a public video URL or HTTPS webhook URL")
        return value


class CreateUploadConfig(BaseModel):
    operation: Literal["create_upload_url"] = operation("create_upload_url", "Create Upload URL")
    content_type: Literal["video/mp4", "video/quicktime", "video/webm"] = Field(..., title="Content Type")
    size: int = Field(..., ge=1, le=104857600, title="File Size in Bytes", description="Upload the file with PUT to the returned URL using its headers, then pass video_url to Create Upscale Task.")


class GetTaskConfig(BaseModel):
    operation: Literal["get_upscale_task"] = operation("get_upscale_task", "Get Upscale Task")
    task_id: str = Field(..., min_length=1, title="Task ID")
    wait: int = Field(0, ge=0, le=45, title="Wait Seconds", description="Hold the request until completion/failure or this timeout.")


class ListTasksConfig(BaseModel):
    operation: Literal["list_upscale_tasks"] = operation("list_upscale_tasks", "List Upscale Tasks")
    page: int = Field(1, ge=1, title="Page")
    limit: int = Field(20, ge=1, le=100, title="Tasks per Page")


class GetAccountConfig(BaseModel):
    operation: Literal["get_account_balance"] = operation("get_account_balance", "Get Account Balance")


class OnNewTaskConfig(PollTriggerConfigBase):
    operation: Literal["on_new_task"] = operation("on_new_task", "On New Upscale Task", trigger=True)


class OnTaskUpdatedConfig(PollTriggerConfigBase):
    operation: Literal["on_task_updated"] = operation("on_task_updated", "On Upscale Task Updated", trigger=True)


VideoUpscalerConfig = Annotated[Union[CreateUpscaleConfig, CreateUploadConfig, GetTaskConfig,
    ListTasksConfig, GetAccountConfig, OnNewTaskConfig, OnTaskUpdatedConfig], Field(discriminator="operation")]


class VideoUpscalerNodeConfig(NodeConfig[VideoUpscalerConfig, VideoUpscalerAPIKey]):
    pass


class VideoUpscalerNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-videoupscaler"
    connection_evidence = ConnectionEvidence(noun="upscale tasks", operation="list_upscale_tasks",
        label_keys=("video_url", "id"), identity_operation="get_account_balance", identity_keys=("credits",))

    @classmethod
    def get_config_model(cls):
        return VideoUpscalerNodeConfig

    @staticmethod
    async def _request(key, method, path, *, params=None, body=None, headers=None):
        # No automatic retries: POST /upscale charges credits.
        async with httpx.AsyncClient(timeout=300, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json", **(headers or {})})
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(f"VideoUpscaler returned a non-JSON response ({response.status_code})") from None
        if response.is_error:
            error = payload.get("error") if isinstance(payload, dict) else None
            detail = error.get("message") if isinstance(error, dict) else error
            raise ValueError(f"VideoUpscaler API error {response.status_code}: {str(detail or 'Request failed').replace(key, '[redacted]')}")
        if response.is_redirect:
            raise ValueError("VideoUpscaler returned an unexpected redirect")
        return payload

    async def _poll_tasks(self, key, *, updated=False):
        tasks = []
        # Fail before advancing the seen set if the account exceeds the bound.
        for page in range(1, 101):
            payload = await self._request(key, "GET", "/tasks", params={"page": page, "limit": 100})
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or not isinstance(payload.get("has_more"), bool):
                raise ValueError("VideoUpscaler returned an invalid task list")
            rows = payload["data"]
            if any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in rows):
                raise ValueError("VideoUpscaler returned a task without an ID")
            if updated and any(not isinstance(row.get("updated_at"), str) or not row["updated_at"] for row in rows):
                raise ValueError("VideoUpscaler returned a task without an update timestamp")
            tasks.extend(rows)
            if not payload["has_more"]:
                break
        else:
            raise ValueError("VideoUpscaler task polling exceeds 10,000 tasks")
        fresh = await self._filter_unseen(tasks, lambda task: task["id"] + (":" + task["updated_at"] if updated else ""))
        return {"tasks": fresh, "new_task_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_task_count")) if config.get("operation") in {"on_new_task", "on_task_updated"} else True

    @classmethod
    def resolve_agent_event(cls, output):
        tasks = output.get("tasks")
        if not isinstance(tasks, list):
            return super().resolve_agent_event(output)
        if not tasks:
            return None
        lines = [f"- Task {task['id']}: {task.get('status')}; video {task.get('video_url')}; resolution {task.get('resolution')}; output {task.get('output_url')}; error {task.get('error')}" for task in tasks[:10]]
        return {"text": f"VideoUpscaler account: {len(tasks)} new or updated upscale task(s)\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        if self.config.credentials is None:
            raise ValueError("Connect a VideoUpscaler API key")
        key = self.config.credentials.api_key
        if isinstance(config, (OnNewTaskConfig, OnTaskUpdatedConfig)):
            return await self._poll_tasks(key, updated=isinstance(config, OnTaskUpdatedConfig))
        if isinstance(config, CreateUpscaleConfig):
            body = config.model_dump(exclude_none=True, exclude={"operation", "idempotency_key"})
            headers = {"Idempotency-Key": config.idempotency_key} if config.idempotency_key else None
            data = await self._request(key, "POST", "/upscale", body=body, headers=headers)
        elif isinstance(config, CreateUploadConfig):
            data = await self._request(key, "POST", "/uploads", body=config.model_dump(exclude={"operation"}))
        elif isinstance(config, GetTaskConfig):
            data = await self._request(key, "GET", "/tasks/" + quote(config.task_id, safe=""), params={"wait": config.wait})
        elif isinstance(config, ListTasksConfig):
            data = await self._request(key, "GET", "/tasks", params={"page": config.page, "limit": config.limit})
        else:
            data = await self._request(key, "GET", "/account")
        return {"status": "success", "operation": config.operation, "data": data}

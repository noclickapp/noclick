"""AbyssHub v1 widgets and runs, from the provider's published OpenAPI contract.

Run/start and read/wait each make one request; a held response may still be
queued or running. Callers must inspect status, and re-read expiring file URLs.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin, poll_scope
from utils.ssrf import guarded_async_client

BASE = "https://api.abysshub.com"
DOCS = "https://raw.githubusercontent.com/Abysshub/abysshub-sdk/main/contract/openapi.json"


class AbyssHubAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="AbyssHub API Key", json_schema_extra={
        "x-credential-url": "https://abysshub.com/cave",
        "x-credential-instructions": "Create an API key in your AbyssHub Cave and paste it here. The key acts as you and runs are paid from your wallet. Paste only the key, without Bearer.",
    })
    credential_type: Literal["abysshub_api_key"] = Field("abysshub_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
                         json_schema_extra={"ui:widget": "password"})


class GetKeyConfig(BaseModel):
    operation: Literal["get_key"] = Field("get_key", title="Get Key and Account")


class _Widget(BaseModel):
    widget_id: str = Field(..., min_length=1, title="Widget ID or Private Token",
                           description="The widget_ ID or the private token from an unlisted Widget's link.")


class GetWidgetConfig(_Widget):
    operation: Literal["get_widget"] = Field("get_widget", title="Get Widget Price and Input Schema")


class PrepareUploadConfig(_Widget):
    operation: Literal["prepare_upload"] = Field("prepare_upload", title="Prepare File Upload",
        description="Returns an upload ID and S3 form. Send the form fields and file to upload.url separately, then use the ID in a Widget input.")
    field: str = Field(..., min_length=1, max_length=255, title="File Field Name")
    filename: str = Field(..., min_length=1, max_length=255, title="Filename")
    size: int | None = Field(None, ge=0, title="Size in Bytes")


class _Press(_Widget):
    input: Json[dict[str, Any]] = Field("{}", validate_default=True, title="Widget Input",
        description="JSON object matching the Widget's input_schema. File fields accept a public HTTPS URL or an upload ID.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    max_price: float | None = Field(None, title="Maximum Price", description="Refuse the run before charging if its price exceeds this amount.")
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[\x21-\x7E]+$",
        title="Idempotency Key", description="Use the same key and input to retry safely within 24 hours. Use a new key for each new run.")

    @field_validator("input", mode="before")
    @classmethod
    def json_input(cls, value):
        # The editor supplies JSON text; workflow expressions and agent tools
        # can supply a native object. Both must be an object, never a scalar.
        return json.dumps(value) if isinstance(value, dict) else value


class RunWidgetConfig(_Press):
    operation: Literal["run_widget"] = Field("run_widget", title="Run Widget and Wait",
        description="Starts a paid run and holds for its ending. A busy API or an hour's hold can return queued/running; inspect status and read again.")


class StartWidgetConfig(_Press):
    operation: Literal["start_widget"] = Field("start_widget", title="Start Widget Run",
        description="Starts a paid run with wait=false and returns immediately. Use Get Run or Wait for Run afterwards.")


class ListRunsConfig(BaseModel):
    operation: Literal["list_runs"] = Field("list_runs", title="List Runs")
    limit: int = Field(20, ge=1, le=100, title="Page Size")
    starting_after: str | None = Field(None, pattern=r"^run_[A-Za-z0-9]{24}$", title="Starting After",
        description="Last run ID of the previous page. Runs from this API key only, newest first.")


class _Run(BaseModel):
    run_id: str = Field(..., pattern=r"^run_[A-Za-z0-9]{24}$", title="Run ID")


class GetRunConfig(_Run):
    operation: Literal["get_run"] = Field("get_run", title="Get Run",
        description="Read the current status, result and fresh signed file URLs without waiting.")


class WaitForRunConfig(_Run):
    operation: Literal["wait_for_run"] = Field("wait_for_run", title="Wait for Run",
        description="Read with wait=true. A busy API or an hour's hold can return before completion; inspect status.")


class WakeRunConfig(_Run):
    operation: Literal["wake_run"] = Field("wake_run", title="Wake Run Files",
        description="Restore files from deep storage within 12 hours. AbyssHub emails you when ready. Already awake runs are unchanged.")


class OnNewRunConfig(PollTriggerConfigBase):
    operation: Literal["on_new_run"] = Field("on_new_run", title="On New Run", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Run", "ui:hidden": True,
    })


AbyssHubConfig = Annotated[Union[GetKeyConfig, GetWidgetConfig, PrepareUploadConfig,
    RunWidgetConfig, StartWidgetConfig, ListRunsConfig, GetRunConfig, WaitForRunConfig,
    WakeRunConfig, OnNewRunConfig], Field(discriminator="operation")]


class AbyssHubNodeConfig(NodeConfig[AbyssHubConfig, AbyssHubAPIKeyCredential]):
    pass


class AbyssHubNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-abysshub"
    connection_evidence = ConnectionEvidence(noun="AbyssHub API key", identity_operation="get_key", identity_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return AbyssHubNodeConfig

    async def _request(self, method, path, *, params=None, body=None, headers=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an AbyssHub API key")
        # A held run sends whitespace every two seconds. Allow long runs while
        # bounding an idle connection, and never retry a paid press implicitly.
        async with guarded_async_client(timeout=httpx.Timeout(90, connect=15),
                                        follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": f"Bearer {credential.api_key}", "Accept": "application/json", **(headers or {})})
        if response.is_error:
            try:
                error = response.json().get("error", {})
                detail = error.get("message") or "Request failed"
                code = error.get("code") or str(response.status_code)
            except (ValueError, AttributeError):
                detail, code = "Request failed", str(response.status_code)
            raise ValueError(f"AbyssHub {code}: {detail}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected an AbyssHub JSON object")
        return {"status": "success", "data": data}

    async def _poll_new_runs(self):
        state = await self._load_node_state()
        scope = poll_scope(type(self), {"operation": "on_new_run"})
        known = set(state.get("seen_ids", [])) if state.get("scope") in (None, scope) else set()
        runs, cursor, cursors = [], None, set()
        # Newest-first listing: stop at the previous baseline, so old history
        # cannot crowd out new runs. Fail without advancing state on overflow.
        for _ in range(100):
            page = (await self._request("GET", "/v1/runs", params={"limit": 100, **({"starting_after": cursor} if cursor else {})}))["data"]
            items = page["data"]
            runs.extend(items)
            if any(item["id"] in known for item in items) or not page["has_more"]:
                break
            if not items or items[-1]["id"] in cursors:
                raise ValueError("AbyssHub run pagination did not advance")
            cursor = items[-1]["id"]
            cursors.add(cursor)
        else:
            raise ValueError("More than 10,000 AbyssHub runs since the last poll; poll more often")
        fresh = await self._filter_unseen(runs, lambda run: run["id"])
        return {"runs": list(reversed(fresh)), "new_run_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        runs = output.get("runs") if isinstance(output, dict) else None
        if not isinstance(runs, list):
            return super().resolve_agent_event(output)
        if not runs:
            return None
        lines = [f"AbyssHub: {len(runs)} new run(s) made by this API key:"]
        for run in runs[:10]:
            lines.append(f"- {run['widget']}: {run['status']} at {run['created_at']} (run_id={run['id']})")
            if run.get("result") is not None:
                lines.append("  Result: " + json.dumps(run["result"], ensure_ascii=False)[:1500])
            if run.get("error"):
                lines.append("  Error: " + str(run["error"]["message"])[:1500])
        lines.append("Use Get Run with run_id to read status, results and fresh output file URLs.")
        return {"text": "\n".join(lines), "conversation_key": runs[0]["id"] if len(runs) == 1 else None}

    async def execute(self, inputs):
        config = self.config.config
        operation = config.operation
        if operation == "on_new_run":
            return await self._poll_new_runs()
        if operation == "get_key":
            return await self._request("GET", "/v1/key")
        if operation == "list_runs":
            return await self._request("GET", "/v1/runs", params=config.model_dump(exclude_none=True, exclude={"operation"}))
        if isinstance(config, _Widget):
            path = "/v1/widgets/" + quote(config.widget_id, safe="")
            if operation == "get_widget":
                return await self._request("GET", path)
            if operation == "prepare_upload":
                return await self._request("POST", path + "/uploads", body=config.model_dump(exclude_none=True, exclude={"operation", "widget_id"}))
            body = {"input": config.input, "wait": operation == "run_widget"}
            if config.max_price is not None:
                body["max_price"] = config.max_price
            headers = {"Idempotency-Key": config.idempotency_key} if config.idempotency_key else {}
            return await self._request("POST", path + "/runs", body=body, headers=headers)
        path = "/v1/runs/" + quote(config.run_id, safe="")
        if operation == "wake_run":
            return await self._request("POST", path + "/wake")
        return await self._request("GET", path, params={"wait": "true" if operation == "wait_for_run" else "false"})

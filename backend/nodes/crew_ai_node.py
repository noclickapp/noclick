"""CrewAI AMP's four published deployment operations, using a pasted bearer token."""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_provider_https_origin


class CrewAIBearerCredential(BaseModel):
    model_config = ConfigDict(
        title="CrewAI Bearer Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.crewai.com/v1.15.37/en/api-reference/introduction",
            "x-credential-instructions": "Open your deployed crew in CrewAI AMP and copy its deployment URL and Bearer Token or User Bearer Token from the Status tab. Paste the token without the Bearer prefix. NoClick reads this deployment's inputs to check access; this does not verify your identity or write permissions.",
        },
    )
    credential_type: Literal["crew_ai_bearer"] = Field("crew_ai_bearer", json_schema_extra={"ui:hidden": True})
    deployment_url: str = Field(..., title="Deployment URL", description="Your crew's HTTPS origin, such as https://my-travel-crew.crewai.com.")
    bearer_token: str = Field(..., title="Bearer token", json_schema_extra={"ui:widget": "password"})

    @field_validator("deployment_url")
    @classmethod
    def deployment(cls, value):
        return normalize_provider_https_origin(value, "crewai.com", field_name="Deployment URL")

    @field_validator("bearer_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Bearer token")
        if len(value) > 8192 or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the bearer token, without a header or whitespace")
        return value


class GetInputs(BaseModel):
    """Discover accepted inputs and the subset required to start this crew."""
    operation: Literal["get_inputs"] = Field("get_inputs", title="Get Inputs", json_schema_extra={"ui:hidden": True})


class Webhooks(BaseModel):
    taskWebhookUrl: str | None = Field(None, title="Task webhook URL", description="Callback after each task. Resend the original URL when resuming.", json_schema_extra={"format": "uri"})
    stepWebhookUrl: str | None = Field(None, title="Step webhook URL", description="Callback after each agent thought/action. Resend when resuming.", json_schema_extra={"format": "uri"})
    crewWebhookUrl: str | None = Field(None, title="Crew webhook URL", description="Callback when execution completes. Resend when resuming.", json_schema_extra={"format": "uri"})


class StartExecution(Webhooks):
    """Start one crew execution and return its kickoff ID for later polling."""
    operation: Literal["start_execution"] = Field("start_execution", title="Start Execution", json_schema_extra={"ui:hidden": True})
    inputs: dict[str, str] = Field(..., description="Key/value inputs required by this deployment. Use Get Inputs to discover them.", json_schema_extra={"ui:widget": "state_editor", "placeholder": '{"budget": "1000 USD"}'})
    meta: dict[str, Any] | None = Field(None, description="Additional metadata passed to the crew.", json_schema_extra={"ui:widget": "state_editor"})


class GetStatus(BaseModel):
    """Read running, completed or error status and available execution results."""
    operation: Literal["get_status"] = Field("get_status", title="Get Execution Status", json_schema_extra={"ui:hidden": True})
    kickoff_id: str = Field(..., min_length=1, description="Kickoff ID returned by Start Execution.", json_schema_extra={"format": "uuid"})


class ResumeExecution(Webhooks):
    """Resume a paused task with approval or revision feedback.

    Send the original webhook URLs again: CrewAI does not carry them over.
    """
    operation: Literal["resume_execution"] = Field("resume_execution", title="Resume Execution", json_schema_extra={"ui:hidden": True})
    execution_id: str = Field(..., min_length=1, description="Execution ID from kickoff.", json_schema_extra={"format": "uuid"})
    task_id: str = Field(..., min_length=1, description="Task waiting for human input.")
    human_feedback: str = Field(..., description="Feedback supplied as context for subsequent tasks.")
    is_approve: bool = Field(..., description="Yes continues; No retries the task with your feedback.")


CrewAIConfig = Annotated[Union[GetInputs, StartExecution, GetStatus, ResumeExecution], Field(discriminator="operation")]


class CrewAINodeConfig(NodeConfig[CrewAIConfig, CrewAIBearerCredential]):
    pass


class CrewAINode(WorkflowNode):
    integration_type = "automation-crew-ai"
    connection_evidence = ConnectionEvidence(operation="get_inputs", noun="CrewAI deployment inputs", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return CrewAINodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CrewAI deployment and bearer token")
        credential = self.config.credentials
        op = self.config.config
        method, path = {
            "get_inputs": ("GET", "/inputs"),
            "start_execution": ("POST", "/kickoff"),
            "get_status": ("GET", "/status/" + quote(getattr(op, "kickoff_id", ""), safe="")),
            "resume_execution": ("POST", "/resume"),
        }[op.operation]
        body = op.model_dump(exclude={"operation"}, exclude_none=True) if method == "POST" else None
        # Revalidate at the network boundary. Never forward the bearer on a redirect.
        origin = CrewAIBearerCredential.deployment(credential.deployment_url)
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            try:
                response = await client.request(
                    method, origin + path,
                    headers={"Authorization": "Bearer " + credential.bearer_token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}),
                )
            except httpx.HTTPError:
                raise ValueError("CrewAI request failed; check execution status before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("CrewAI returned a non-JSON response; check the deployment URL") from None
        if response.status_code != 200:
            message = (data.get("message") or data.get("error")) if isinstance(data, dict) else "CrewAI request was rejected"
            message = str(message).replace(credential.bearer_token, "[redacted]")
            result = {"status": "error", "status_code": response.status_code, "message": message}
        else:
            if not isinstance(data, dict):
                raise ValueError("CrewAI returned an unexpected response shape")
            if op.operation == "get_inputs":
                accepted, required = data.get("inputs"), data.get("required_inputs")
                if not isinstance(accepted, list) or not isinstance(required, list) or any(not isinstance(v, str) for v in accepted + required) or not set(required) <= set(accepted):
                    raise ValueError("CrewAI returned an unexpected inputs response")
            elif op.operation == "start_execution":
                if not isinstance(data.get("kickoff_id"), str) or not data["kickoff_id"]:
                    raise ValueError("CrewAI did not return a kickoff ID; check the deployment before retrying")
            elif op.operation == "get_status":
                if data.get("status") not in {"running", "completed", "error"}:
                    raise ValueError("CrewAI returned an unexpected execution status")
            elif data.get("status") not in {"resumed", "retrying", "completed"}:
                raise ValueError("CrewAI returned an unexpected resume status; check execution status before retrying")
            # Request success is not crew completion: preserve execution state inside data.
            result = {"status": "success", "data": data}
        await self.emit(result)
        return result

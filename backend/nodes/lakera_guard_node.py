"""Lakera Guard's four published Guard API operations (OpenAPI 1.0.0).

Platform policy/project CRUD is a separate API, absent from this contract.
The published lint operation has no request body; do not invent policy input.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class LakeraGuardApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Lakera Guard API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://platform.lakera.ai/",
            "x-credential-instructions": "Create an API key in the Lakera Guard dashboard and paste it here without the Bearer prefix. Choose the region for that key. The connection check calls the published policy-lint endpoint and proves key reachability, not account identity or screening permissions.",
        },
    )
    credential_type: Literal["lakera_guard_api_key"] = Field("lakera_guard_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    api_base_url: Literal[
        "https://api.lakera.ai", "https://eu.api.lakera.ai",
        "https://us.api.lakera.ai", "https://ap-southeast-1.api.lakera.ai",
    ] = Field("https://api.lakera.ai", title="API Region", description="Use the documented API region associated with your key.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TextPart(_Input):
    type: Literal["text"] = "text"
    text: str


class FunctionCall(_Input):
    name: str
    arguments: str = Field(..., description="JSON-encoded function arguments, as returned by the LLM.")


class ToolCall(_Input):
    function: FunctionCall
    type: Literal["function"] = "function"
    id: str


class Message(_Input):
    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | list[TextPart] | None = None
    tool_calls: list[ToolCall] | None = None

    @model_validator(mode="after")
    def content_or_calls(self):
        if self.content is None and not (self.role == "assistant" and self.tool_calls):
            raise ValueError("Messages need content, except assistant messages with tool calls")
        if self.tool_calls is not None and self.role != "assistant":
            raise ValueError("Only assistant messages may include tool calls")
        return self


class ToolFunction(_Input):
    name: str = Field(..., min_length=1)
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class ToolDefinition(_Input):
    type: Literal["function"] = "function"
    function: ToolFunction


class _Screening(_Input):
    messages: list[Message] | None = Field(None, description="Original LLM conversation. Provide messages, tools, or both.")
    tools: list[ToolDefinition] | None = Field(None, description="OpenAI-format function definitions to screen, with or without messages.")
    project_id: str | None = Field(None, description="Project whose policy to apply; omit to use the default policy.")
    conversation_id: str | None = Field(None, min_length=1, max_length=512, pattern=r"^[A-Za-z0-9._:@;=-]+$")
    metadata: dict[str, Any] | None = Field(None, description="Optional user/session tags attached to this request.")
    dev_info: bool | None = None

    @model_validator(mode="after")
    def has_content(self):
        if not self.messages and not self.tools:
            raise ValueError("Provide at least one message or tool definition")
        return self


class ScreenContent(_Screening):
    """Screen an LLM interaction using the project's runtime Guard policy.

    Guard can create screening logs. In detect mode flagged is always false;
    use the returned action and breakdown when interpreting results.
    """
    operation: Literal["screen_content"] = "screen_content"
    payload: bool | None = Field(None, description="Include PII, profanity and regex match locations.")
    breakdown: bool | None = Field(None, description="Include individual detector decisions and confidence levels.")


class GetDetectionResults(_Screening):
    """Analyze historic content and calibrate detectors without screening logs.

    This endpoint does not make a flagging decision. Do not use its results
    for runtime security decisions; use Screen Content for runtime screening.
    """
    operation: Literal["get_detection_results"] = "get_detection_results"


class CheckPolicyHealth(_Input):
    """Check the policy configuration of an explicit project."""
    operation: Literal["check_policy_health"] = "check_policy_health"
    project_id: str = Field(..., min_length=1, description="Project ID required by the published request schema.")


class ValidatePolicy(_Input):
    """Call the published policy-lint endpoint with no request body.

    The provider publishes no policy-input schema for this endpoint. For an
    arbitrary policy file, use the dashboard's policy-linter editor instead.
    """
    operation: Literal["validate_policy"] = "validate_policy"


LakeraGuardOperation = Annotated[Union[ScreenContent, GetDetectionResults, CheckPolicyHealth, ValidatePolicy], Field(discriminator="operation")]


class LakeraGuardConfig(NodeConfig[LakeraGuardOperation, LakeraGuardApiKeyCredential]):
    pass


class LakeraGuardNode(WorkflowNode):
    integration_type = "automation-lakera-guard"
    connection_evidence = ConnectionEvidence(
        operation="validate_policy", noun="Lakera Guard API", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return LakeraGuardConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Lakera Guard API key")
        credential = self.config.credentials
        config = self.config.config
        route = {
            "screen_content": "/v2/guard",
            "get_detection_results": "/v2/guard/results",
            "check_policy_health": "/v2/policies/health",
            "validate_policy": "/v2/policies/lint",
        }[config.operation]
        kwargs = {} if isinstance(config, ValidatePolicy) else {
            "json": config.model_dump(mode="json", exclude={"operation"}, exclude_none=True),
        }
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.post(
                credential.api_base_url + route,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                **kwargs,
            )
        if not 200 <= response.status_code < 300:
            # Keep the provider's definitive rejection, but never echo the key
            # or an HTML/redirect response (nor retry a logged screening call).
            message = "Lakera Guard did not complete the request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("error"), str):
                    message = error["error"][:2000].replace(credential.api_key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Lakera Guard returned a non-JSON response") from None
        if not isinstance(data, dict) or data.get("error") is not None:
            raise ValueError("Lakera Guard returned an invalid response")
        if isinstance(config, ScreenContent) and type(data.get("flagged")) is not bool:
            raise ValueError("Lakera Guard did not return a screening decision")
        if isinstance(config, GetDetectionResults) and not (
            isinstance(data.get("results"), list) or isinstance(data.get("tools"), dict)
        ):
            raise ValueError("Lakera Guard did not return detection results")
        if isinstance(config, CheckPolicyHealth) and data.get("status") not in {"ok", "error"}:
            raise ValueError("Lakera Guard did not return policy health")
        if isinstance(config, ValidatePolicy) and type(data.get("passed")) is not bool:
            raise ValueError("Lakera Guard did not return policy validation")
        return {"status": "success", "operation": config.operation, "data": data}

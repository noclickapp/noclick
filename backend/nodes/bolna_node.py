"""Bolna voice agents, calls and campaign reads using the published v1.0.0 API.

Each operation makes exactly one request. List results retain provider pagination;
call and agent writes are never retried automatically.
"""
from __future__ import annotations
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class BolnaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bolna API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://platform.bolna.ai/",
        "x-credential-instructions": "Copy your API key from the Bolna dashboard and paste it here. NoClick verifies it by reading your Bolna account."})
    credential_type: Literal["bolna_api_key"] = Field("bolna_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def resource_id(cls, value, info):
        if info.field_name in {"agent_id", "execution_id", "batch_id", "rag_id"}:
            if not isinstance(value, str) or not value or len(value)>200 or any(c in value for c in '/?#%\\') or any(c.isspace() for c in value):
                raise ValueError("Paste a single Bolna resource ID")
        return value

class BolnaGetAccountConfig(_Input):
    """Get user information"""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class BolnaListAgentsConfig(_Input):
    """List all agents"""
    operation: Literal["list_agents"] = Field("list_agents", json_schema_extra={"ui:hidden": True})


class BolnaCreateAgentConfig(_Input):
    """Creates a new agent"""
    operation: Literal["create_agent"] = Field("create_agent", json_schema_extra={"ui:hidden": True})
    agent_config: dict[str, Any] = Field(..., description="Configuration from the Bolna agent API")
    agent_prompts: dict[str, Any] = Field(..., description="Configuration from the Bolna agent API")


class BolnaGetAgentConfig(_Input):
    """Retrieve an agent"""
    operation: Literal["get_agent"] = Field("get_agent", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1, description="Bolna agent id", json_schema_extra={"format": "uuid"})


class BolnaPatchAgentConfig(_Input):
    """Patch update an agent"""
    operation: Literal["patch_agent"] = Field("patch_agent", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1, description="Bolna agent id", json_schema_extra={"format": "uuid"})
    agent_config: dict[str, Any] | None = None
    agent_prompts: dict[str, Any] | None = None


class BolnaDeleteAgentConfig(_Input):
    """Delete an agent"""
    operation: Literal["delete_agent"] = Field("delete_agent", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1, description="Bolna agent id", json_schema_extra={"format": "uuid"})


class BolnaStopAgentConfig(_Input):
    """Stop all queued calls for a given agent_id"""
    operation: Literal["stop_agent"] = Field("stop_agent", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1, description="Bolna agent id", json_schema_extra={"format": "uuid"})


class BolnaListAgentVersionsConfig(_Input):
    """List an agent's versions, newest first: every version saved with Save as new version, plus the live one. Each version appears once, as its latest save."""
    operation: Literal["list_agent_versions"] = Field("list_agent_versions", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1, description="Bolna agent id", json_schema_extra={"format": "uuid"})
    page_number: int | None = Field(None, ge=1, description='page_number')
    page_size: int | None = Field(None, ge=1, le=50, description='page_size')


class BolnaListExecutionsConfig(_Input):
    """Retrieve all executions by an agent"""
    operation: Literal["list_executions"] = Field("list_executions", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1, description="Bolna agent id", json_schema_extra={"format": "uuid"})
    page_number: int | None = Field(None, ge=1, description='The page number to retrieve (starts from `1`)')
    page_size: int | None = Field(None, ge=1, le=50, description='Number of results per page. Maximum allowed is `50`.')
    status: Literal['scheduled', 'queued', 'rescheduled', 'ringing', 'initiated', 'in-progress', 'call-disconnected', 'completed', 'balance-low', 'busy', 'no-answer', 'canceled', 'failed', 'stopped', 'error'] | None = Field(None, description='status')
    call_type: Literal['inbound', 'outbound'] | None = Field(None, description='call_type')
    provider: Literal['twilio', 'plivo', 'exotel', 'vobiz', 'trunk', 'sip-trunk', 'web-call', 'websocket'] | None = Field(None, description='provider')
    answered_by_voice_mail: bool | None = Field(None, description='answered_by_voice_mail')
    batch_id: str | None = Field(None, description='batch_id')
    from_time: str = Field(..., description='from')
    to_time: str = Field(..., description='to')

    @model_validator(mode="after")
    def date_range(self):
        start, end = (datetime.fromisoformat(v.replace("Z", "+00:00")) for v in (self.from_time, self.to_time))
        if start.utcoffset() is None or end.utcoffset() is None or not 0 <= (end-start).total_seconds() <= 7*86400:
            raise ValueError("Use a timezone-aware execution date range of at most seven days")
        return self


class BolnaGetExecutionConfig(_Input):
    """Retrieve specific execution by `execution_id`"""
    operation: Literal["get_execution"] = Field("get_execution", json_schema_extra={"ui:hidden": True})
    execution_id: str = Field(..., min_length=1, description="Bolna execution id", json_schema_extra={"format": "uuid"})


class BolnaGetExecutionLogConfig(_Input):
    """Retrieve raw logs of specific `execution_id`"""
    operation: Literal["get_execution_log"] = Field("get_execution_log", json_schema_extra={"ui:hidden": True})
    execution_id: str = Field(..., min_length=1, description="Bolna execution id", json_schema_extra={"format": "uuid"})


class BolnaMakeCallConfig(_Input):
    """Initiate calls"""
    operation: Literal["make_call"] = Field("make_call", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1, json_schema_extra={"format": "uuid"})
    recipient_phone_number: str = Field(..., pattern=r"^\+[1-9][0-9]{1,14}$")
    from_phone_number: str | None = Field(None, pattern=r"^\+[1-9][0-9]{1,14}$")
    scheduled_at: str | None = None
    user_data: dict[str, Any] | None = None
    agent_data: dict[str, Any] | None = None
    retry_config: dict[str, Any] | None = None
    agent_version_id: str | None = None


class BolnaStopCallConfig(_Input):
    """Stop a queued or scheduled call"""
    operation: Literal["stop_call"] = Field("stop_call", json_schema_extra={"ui:hidden": True})
    execution_id: str = Field(..., min_length=1, description="Bolna execution id", json_schema_extra={"format": "uuid"})


class BolnaListBatchesConfig(_Input):
    """List all batches for agent"""
    operation: Literal["list_batches"] = Field("list_batches", json_schema_extra={"ui:hidden": True})
    agent_id: str = Field(..., min_length=1, description="Bolna agent id", json_schema_extra={"format": "uuid"})


class BolnaGetBatchConfig(_Input):
    """Retrieve a batch"""
    operation: Literal["get_batch"] = Field("get_batch", json_schema_extra={"ui:hidden": True})
    batch_id: str = Field(..., min_length=1, description="Bolna batch id", json_schema_extra={"format": "uuid"})


class BolnaDeleteBatchConfig(_Input):
    """Delete a batch"""
    operation: Literal["delete_batch"] = Field("delete_batch", json_schema_extra={"ui:hidden": True})
    batch_id: str = Field(..., min_length=1, description="Bolna batch id", json_schema_extra={"format": "uuid"})


class BolnaStopBatchConfig(_Input):
    """Stop a running batch"""
    operation: Literal["stop_batch"] = Field("stop_batch", json_schema_extra={"ui:hidden": True})
    batch_id: str = Field(..., min_length=1, description="Bolna batch id", json_schema_extra={"format": "uuid"})


class BolnaListKnowledgeBasesConfig(_Input):
    """List all knowledge bases for your account"""
    operation: Literal["list_knowledge_bases"] = Field("list_knowledge_bases", json_schema_extra={"ui:hidden": True})


class BolnaGetKnowledgeBaseConfig(_Input):
    """Retrieve a knowledge base"""
    operation: Literal["get_knowledge_base"] = Field("get_knowledge_base", json_schema_extra={"ui:hidden": True})
    rag_id: str = Field(..., min_length=1, description="Bolna rag id", json_schema_extra={"format": "uuid"})


class BolnaDeleteKnowledgeBaseConfig(_Input):
    """Delete a knowledge base"""
    operation: Literal["delete_knowledge_base"] = Field("delete_knowledge_base", json_schema_extra={"ui:hidden": True})
    rag_id: str = Field(..., min_length=1, description="Bolna rag id", json_schema_extra={"format": "uuid"})


class BolnaListPhoneNumbersConfig(_Input):
    """List all phone numbers for your account"""
    operation: Literal["list_phone_numbers"] = Field("list_phone_numbers", json_schema_extra={"ui:hidden": True})


BolnaConfig = Annotated[
    Union[
        BolnaGetAccountConfig,
        BolnaListAgentsConfig,
        BolnaCreateAgentConfig,
        BolnaGetAgentConfig,
        BolnaPatchAgentConfig,
        BolnaDeleteAgentConfig,
        BolnaStopAgentConfig,
        BolnaListAgentVersionsConfig,
        BolnaListExecutionsConfig,
        BolnaGetExecutionConfig,
        BolnaGetExecutionLogConfig,
        BolnaMakeCallConfig,
        BolnaStopCallConfig,
        BolnaListBatchesConfig,
        BolnaGetBatchConfig,
        BolnaDeleteBatchConfig,
        BolnaStopBatchConfig,
        BolnaListKnowledgeBasesConfig,
        BolnaGetKnowledgeBaseConfig,
        BolnaDeleteKnowledgeBaseConfig,
        BolnaListPhoneNumbersConfig,
    ],
    Field(discriminator="operation"),
]

class BolnaFullConfig(NodeConfig[BolnaConfig, BolnaAPIKeyCredential]):
    pass

ROUTES = {
    'get_account': ('GET', '/user/me', [], [], False),
    'list_agents': ('GET', '/v2/agent/all', [], [], False),
    'create_agent': ('POST', '/v2/agent', [], [], True),
    'get_agent': ('GET', '/v2/agent/{agent_id}', ['agent_id'], [], False),
    'patch_agent': ('PATCH', '/v2/agent/{agent_id}', ['agent_id'], [], True),
    'delete_agent': ('DELETE', '/v2/agent/{agent_id}', ['agent_id'], [], False),
    'stop_agent': ('POST', '/v2/agent/{agent_id}/stop', ['agent_id'], [], False),
    'list_agent_versions': ('GET', '/v2/agent/{agent_id}/versions', ['agent_id'], [('page_number', 'page_number'), ('page_size', 'page_size')], False),
    'list_executions': ('GET', '/v2/agent/{agent_id}/executions', ['agent_id'], [('page_number', 'page_number'), ('page_size', 'page_size'), ('status', 'status'), ('call_type', 'call_type'), ('provider', 'provider'), ('answered_by_voice_mail', 'answered_by_voice_mail'), ('batch_id', 'batch_id'), ('from_time', 'from'), ('to_time', 'to')], False),
    'get_execution': ('GET', '/executions/{execution_id}', ['execution_id'], [], False),
    'get_execution_log': ('GET', '/executions/{execution_id}/log', ['execution_id'], [], False),
    'make_call': ('POST', '/call', [], [], True),
    'stop_call': ('POST', '/call/{execution_id}/stop', ['execution_id'], [], False),
    'list_batches': ('GET', '/batches/{agent_id}/all', ['agent_id'], [], False),
    'get_batch': ('GET', '/batches/{batch_id}', ['batch_id'], [], False),
    'delete_batch': ('DELETE', '/batches/{batch_id}', ['batch_id'], [], False),
    'stop_batch': ('POST', '/batches/{batch_id}/stop', ['batch_id'], [], False),
    'list_knowledge_bases': ('GET', '/knowledgebase/all', [], [], False),
    'get_knowledge_base': ('GET', '/knowledgebase/{rag_id}', ['rag_id'], [], False),
    'delete_knowledge_base': ('DELETE', '/knowledgebase/{rag_id}', ['rag_id'], [], False),
    'list_phone_numbers': ('GET', '/phone-numbers/all', [], [], False),
}

class BolnaNode(WorkflowNode):
    integration_type = "automation-bolna"
    connection_evidence = ConnectionEvidence(noun="Bolna account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return BolnaFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Bolna API key")
        method, path, path_fields, query_fields, has_body = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key in path_fields:
            path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        params = {wire: values.pop(key) for key, wire in query_fields if key in values}
        # Keep the provider's response intact, including cursors and execution metadata.
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, "https://api.bolna.ai" + path,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                params=params, **({"json": values} if has_body else {}))
        if response.is_error:
            # Provider rejection text is used by the manual connection verdict.
            detail = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"Bolna HTTP {response.status_code}: {detail}")
        if response.status_code == 204 or not response.content:
            return {"success": True}
        result = response.json()
        if isinstance(result, dict) and (result.get("error") or result.get("errors")):
            raise ValueError("Bolna returned an error: " + str(result).replace(credential.api_key, "[redacted]")[:2000])
        return {"data": result}

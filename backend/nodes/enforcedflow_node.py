"""EnforcedFlow's provider-key API, pinned to its published v1 contract."""
from typing import Annotated, Any, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://app.enforcedflow.com/api/v1/advanced-round-robin"


class EnforcedflowCredential(BaseModel):
    model_config = ConfigDict(title="Enforcedflow Provider Key", json_schema_extra={
        "x-credential-url": "https://app.enforcedflow.com",
        "x-credential-instructions": "Generate a Provider Key in your EnforcedFlow account dashboard and paste it here. The key is sent directly in the Authorization header."})
    credential_type: Literal["enforcedflow_provider_key"] = Field("enforcedflow_provider_key", json_schema_extra={"ui:hidden": True})
    provider_key: str = Field(..., min_length=1, title="Provider key", json_schema_extra={"ui:widget": "password"})

    @field_validator("provider_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Provider key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the Provider Key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListGroups(Input):
    operation: Literal["list_groups"] = "list_groups"


class Group(Input):
    group_id: int = Field(..., gt=0, title="Group ID")


class GetFields(Group):
    operation: Literal["get_fields"] = "get_fields"


class ListAgents(Group):
    operation: Literal["list_agents"] = "list_agents"
    active: StrictBool | None = Field(None, description="Filter by active status; omit to list all agents.")


class NextAgent(Group):
    operation: Literal["next_agent"] = "next_agent"
    criteria: dict[str, str | list[str]] = Field(default_factory=dict, description="Field names mapped to MultiSelect string arrays or AISelect raw text. Empty matches any agent.")


class EmailNextAgent(Group):
    operation: Literal["email_next_agent"] = "email_next_agent"
    content: str = Field(..., min_length=1, description="Message to send. EnforcedFlow extracts routing criteria and queues delivery.")


class AgentFilter(Input):
    id: int | None = None
    name: str | None = None
    active: StrictBool | None = None
    meta: dict[str, Any] | None = None


class AgentData(Input):
    name: str | None = Field(None, min_length=1)
    active: StrictBool | None = None
    meta: dict[str, Any] | None = None
    fields: dict[str, Any] | None = Field(None, description="Evaluator values: option label arrays, numeric weights, or timezone configuration objects.")


class UpsertAgent(Group):
    operation: Literal["upsert_agent"] = "upsert_agent"
    filter: AgentFilter = Field(default_factory=AgentFilter)
    data: AgentData


class CreateAgent(Group):
    operation: Literal["create_agent"] = "create_agent"
    name: str = Field(..., min_length=1)
    active: StrictBool = True
    meta: dict[str, Any] = Field(default_factory=dict)
    fields: dict[str, Any] = Field(default_factory=dict)


class UpdateAgent(Group):
    """Provider upsert by ID: a missing ID may create an agent; inspect created."""
    operation: Literal["update_agent"] = "update_agent"
    agent_id: int = Field(..., gt=0)
    data: AgentData


class ActivateAgent(Group):
    """Provider upsert by ID with active=true; a missing ID may fail or create."""
    operation: Literal["activate_agent"] = "activate_agent"
    agent_id: int = Field(..., gt=0)


class DeactivateAgent(Group):
    """Provider upsert by ID with active=false; inspect the provider's created flag."""
    operation: Literal["deactivate_agent"] = "deactivate_agent"
    agent_id: int = Field(..., gt=0)


Operations = Annotated[Union[ListGroups, GetFields, ListAgents, NextAgent, EmailNextAgent, UpsertAgent, CreateAgent, UpdateAgent, ActivateAgent, DeactivateAgent], Field(discriminator="operation")]


class EnforcedflowConfig(NodeConfig[Operations, EnforcedflowCredential]):
    pass


class EnforcedflowNode(WorkflowNode):
    integration_type = "automation-enforcedflow"
    connection_evidence = ConnectionEvidence(operation="list_groups", noun="groups")

    @classmethod
    def get_config_model(cls):
        return EnforcedflowConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect an Enforcedflow Provider Key")
        op = self.config.config
        action = op.operation
        method, body, params = "GET", None, None
        if action == "list_groups":
            path = "/groups"
        else:
            path = f"/{op.group_id}"
            if action == "get_fields":
                path += "/fields"
            elif action == "list_agents":
                path += "/agents"
                if op.active is not None:
                    params = {"active": str(op.active).lower()}
            elif action == "next_agent":
                path += "/next-agent"
                method, body = "POST", op.criteria
            elif action == "email_next_agent":
                path += "/email-next-agent"
                method, body = "POST", {"content": op.content}
            else:
                path += "/agents"
                method = "PUT"
                if action == "create_agent":
                    body = {"data": op.model_dump(exclude={"operation", "group_id"})}
                elif action == "upsert_agent":
                    body = {"filter": op.filter.model_dump(exclude_none=True), "data": op.data.model_dump(exclude_none=True)}
                elif action == "update_agent":
                    body = {"filter": {"id": op.agent_id}, "data": op.data.model_dump(exclude_none=True)}
                else:
                    body = {"filter": {"id": op.agent_id}, "data": {"active": action == "activate_agent"}}
        key = self.config.credentials.provider_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers={"Authorization": key, "Accept": "application/json"}, params=params, **({"json": body} if body is not None else {}))
        if response.is_error:
            raise ValueError(f"Enforcedflow HTTP {response.status_code}: " + response.text.replace(key, "[redacted]")[:1000])
        result = response.json()
        await self.emit(result)
        return result

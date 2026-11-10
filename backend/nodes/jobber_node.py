"""Jobber actions bounded to the pinned official GraphQL documentation.

Webhooks require manual per-app Developer Center configuration. The documented
queries expose no created/updated ordering or filter, so this node has no trigger.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.jobber_operations import QUERIES
from nodes.oauth.jobber_oauth import API_URL, API_VERSION, refresh_access_token
from nodes.scopes.jobber import JOBBER_SCOPES


class JobberOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Jobber Account", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "jobber",
        "x-oauth-scopes": JOBBER_SCOPES.declared_scopes(),
        "x-credential-url": "https://developer.getjobber.com/apps",
        "x-credential-instructions": "Connect a Jobber account using OAuth. Enable client read/write, job read, quote read and custom field configuration read/write scopes on your developer app. Custom fields require a Jobber Connect, Grow or Plus plan. Access tokens expire after one hour; keep refresh token rotation enabled.",
    })
    credential_type: Literal["jobber_oauth"] = Field("jobber_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = Field(None, title="Token Expiry")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetAccount(Input):
    """Read the connected account's name and ID."""
    operation: Literal["get_account"] = "get_account"


class ListClients(Input):
    """Read the first 25 clients, billing city and pagination cursors."""
    operation: Literal["list_clients"] = "list_clients"


class CreateClient(Input):
    """Create a client without sending a notification."""
    operation: Literal["create_client"] = "create_client"
    first_name: str = Field(..., min_length=1, title="First Name")
    last_name: str = Field(..., min_length=1, title="Last Name")
    company_name: str | None = Field(None, title="Company Name")


class NumericCustomField(Input):
    customFieldConfigurationId: str = Field(..., min_length=1, title="Custom Field Configuration ID")
    valueNumeric: float = Field(..., allow_inf_nan=False, title="Numeric Value")


class EditClientCustomFields(Input):
    """Update numeric custom fields on a client using existing configurations."""
    operation: Literal["edit_client_custom_fields"] = "edit_client_custom_fields"
    client_id: str = Field(..., min_length=1, title="Client ID")
    custom_fields: list[NumericCustomField] = Field(..., min_length=1, title="Custom Fields")


class ListJobs(Input):
    """Read the first ten jobs with their job numbers and titles."""
    operation: Literal["list_jobs"] = "list_jobs"


class GetJob(Input):
    """Read a job by its encoded ID; an absent job returns null."""
    operation: Literal["get_job"] = "get_job"
    job_id: str = Field(..., min_length=1, title="Job ID")


class ListQuotes(Input):
    """Read the first ten quotes, their status, title and cost."""
    operation: Literal["list_quotes"] = "list_quotes"


class GetQuote(Input):
    """Read a quote, its cost and client by encoded ID."""
    operation: Literal["get_quote"] = "get_quote"
    quote_id: str = Field(..., min_length=1, title="Quote ID")


class ListCustomFieldConfigurations(Input):
    """Read up to 50 custom field configurations across documented types."""
    operation: Literal["list_custom_field_configurations"] = "list_custom_field_configurations"


class CreateLinkConfiguration(Input):
    """Create a link custom field configuration applying to all jobs.

    Requires Custom Field Configurations read/write access and a Jobber
    Connect, Grow or Plus plan. Job write access alone does not grant this."""
    operation: Literal["create_link_configuration"] = "create_link_configuration"
    name: str = Field(..., min_length=1, title="Name")
    text: str = Field(..., min_length=1, title="Default Link Text")
    url: str = Field(..., pattern=r"^https?://\S+$", title="Default Link URL")


JobberConfig = Annotated[Union[GetAccount, ListClients, CreateClient, EditClientCustomFields,
    ListJobs, GetJob, ListQuotes, GetQuote, ListCustomFieldConfigurations, CreateLinkConfiguration],
    Field(discriminator="operation")]


class JobberNodeConfig(NodeConfig[JobberConfig, JobberOAuthCredential]):
    pass


def _literal(value):
    """Serialize only validated GraphQL input values; keys are fixed by models."""
    if isinstance(value, dict):
        return "{" + ", ".join(k + ": " + _literal(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def build_query(op):
    query = QUERIES[op.operation]
    if isinstance(op, CreateClient):
        body = {"firstName": op.first_name, "lastName": op.last_name}
        if op.company_name is not None:
            body["companyName"] = op.company_name
        return query.replace("INPUT", _literal(body))
    if isinstance(op, EditClientCustomFields):
        return query.replace("ID", _literal(op.client_id)).replace("INPUT", _literal({
            "customFields": [field.model_dump() for field in op.custom_fields]}))
    if isinstance(op, (GetJob, GetQuote)):
        return query.replace("ID", _literal(op.job_id if isinstance(op, GetJob) else op.quote_id))
    if isinstance(op, CreateLinkConfiguration):
        body = {"name": op.name, "transferable": False, "readOnly": False,
                "defaultValue": {"text": op.text, "url": op.url}}
        # This enum value is fixed by the pinned mutation example.
        return query.replace("INPUT", '{appliesTo: ALL_JOBS, ' + _literal(body)[1:])
    return query


class JobberNode(WorkflowNode):
    integration_type = "automation-jobber"
    scope_registry = JOBBER_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_account", identity_operation="get_account", noun="Jobber account")

    @classmethod
    def get_config_model(cls):
        return JobberNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="jobber")

    async def execute(self, inputs):
        if not isinstance(self.config, JobberNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Jobber account")
        credential = self.config.credentials
        op = self.config.config
        self.scope_registry.require(op.operation)
        token = credential.access_token
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            data = credential.model_dump()
            token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id, credential=data, refresh=refresh_access_token,
                provider="jobber", caller_path="execute")
            credential.access_token = data["access_token"]
            credential.refresh_token = data.get("refresh_token")
            credential.expires_at = data.get("expires_at")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request("POST", API_URL,
                headers={"Authorization": f"Bearer {token}", "X-JOBBER-GRAPHQL-VERSION": API_VERSION,
                         "Content-Type": "application/json", "Accept": "application/json"},
                json={"query": build_query(op)})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("errors"):
            raise ValueError("Jobber GraphQL request failed: " + json.dumps(body.get("errors") if isinstance(body, dict) else "invalid response"))
        data = body.get("data")
        if not isinstance(data, dict):
            raise ValueError("Jobber returned no GraphQL data")
        for value in data.values():
            if isinstance(value, dict) and value.get("userErrors"):
                raise ValueError("Jobber mutation rejected: " + json.dumps(value["userErrors"]))
        result = {"status": "success", "operation": op.operation, "data": data}
        await self.emit(result)
        return result

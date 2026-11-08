"""Bluebarry Data API v1: shopper data, quiz events and webhook management.

Contract: https://data.bluebarry.ai/docs/api.json
Authentication: https://bluebarry.ai/help/developer-platform/api-authentication-overview
"""
from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://data.bluebarry.ai"

class BluebarryCredential(BaseModel):
    model_config = ConfigDict(title="Bluebarry API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://bluebarry.ai/help/developer-platform/api-authentication-overview",
            "x-credential-instructions": "Copy your API key from Store data > Integrations > Developer area. Paste the raw key without a Bearer prefix. Copy the Tenant ID from Store data > Integrations; it is used only for Identify shopper."})
    credential_type: Literal["bluebarry_api_key"] = Field("bluebarry_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    tenant_id: str = Field(..., min_length=1, title="Tenant ID", description="Store data > Integrations. Required for identifying shoppers.")

    @field_validator("api_key", "tenant_id")
    @classmethod
    def header_value(cls, value):
        value = clean_secret(value, field_name="Key or Tenant ID")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the value without spaces or a header prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _Page(_Input):
    select: str | None = Field(None, description="OData $select: comma-separated fields.")
    filter: str | None = Field(None, description="OData $filter expression.")
    orderby: str = Field("createdDate asc", description="Stable OData ordering for paging; add id for ties if supported.")
    top: int = Field(100, ge=1, le=5000, description="Rows per page, at most 5000.")
    skip: int = Field(0, ge=0, description="Rows to skip. Increment by page size for the next page.")

class _CountPage(_Page):
    count: bool = Field(False, description="Include total as @odata.count.")

class ListIdentities(_CountPage):
    operation: Literal["list_identities"] = Field("list_identities", json_schema_extra={"ui:hidden": True})

class ListProfiles(_CountPage):
    operation: Literal["list_profiles"] = Field("list_profiles", json_schema_extra={"ui:hidden": True})

class ListQuizStarts(_CountPage):
    operation: Literal["list_quiz_starts"] = Field("list_quiz_starts", json_schema_extra={"ui:hidden": True})

class ListQuestionsShown(_CountPage):
    operation: Literal["list_questions_shown"] = Field("list_questions_shown", json_schema_extra={"ui:hidden": True})
    expand: Literal["answers"] | None = Field(None, description="Expand answers.")

class ListAnsweredQuestions(_CountPage):
    operation: Literal["list_answered_questions"] = Field("list_answered_questions", json_schema_extra={"ui:hidden": True})
    expand: Literal["answers"] | None = Field(None, description="Expand answers.")

class ListResultsShown(_CountPage):
    operation: Literal["list_results_shown"] = Field("list_results_shown", json_schema_extra={"ui:hidden": True})
    expand: Literal["results"] | None = Field(None, description="Expand results.")

class ListOpenedResults(_CountPage):
    operation: Literal["list_opened_results"] = Field("list_opened_results", json_schema_extra={"ui:hidden": True})
    expand: Literal["results"] | None = Field(None, description="Expand results.")

class ListOrders(_CountPage):
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})
    expand: Literal["items"] | None = Field(None, description="Expand items.")

class ListPastResults(_Page):
    operation: Literal["list_past_results"] = Field("list_past_results", json_schema_extra={"ui:hidden": True})

class ListWebhooks(_CountPage):
    operation: Literal["list_webhooks"] = Field("list_webhooks", json_schema_extra={"ui:hidden": True})

class CreateWebhook(_Input):
    operation: Literal["create_webhook"] = Field("create_webhook", json_schema_extra={"ui:hidden": True})
    topic: str = Field(..., min_length=1, max_length=128, description="Webhook topic, for example result.viewed.")
    url: str = Field(..., max_length=1024, description="Webhook delivery URL. Bluebarry sends events to this address.")
    name: str | None = None
    disabled: bool = False

class _Webhook(_Input):
    id: UUID = Field(..., title="Webhook ID")

class DeleteWebhook(_Webhook):
    operation: Literal["delete_webhook"] = Field("delete_webhook", json_schema_extra={"ui:hidden": True})

class IssueSigningSecret(_Webhook):
    operation: Literal["issue_signing_secret"] = Field("issue_signing_secret", description="Replaces the signing secret immediately; the old secret stops working. Save the returned secret securely.", json_schema_extra={"ui:hidden": True})

class IdentifyShopper(_Input):
    operation: Literal["identify_shopper"] = Field("identify_shopper", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., max_length=256)
    user_id: UUID = Field(..., description="Visitor ID from window.barry.getUid().")
    session_id: UUID | None = None

Operation = Annotated[Union[ListIdentities, ListProfiles, ListQuizStarts, ListQuestionsShown, ListAnsweredQuestions, ListResultsShown, ListOpenedResults, ListOrders, ListPastResults, ListWebhooks, CreateWebhook, DeleteWebhook, IssueSigningSecret, IdentifyShopper], Field(discriminator="operation")]

class BluebarryConfig(NodeConfig[Operation, BluebarryCredential]):
    pass

class BluebarryNode(WorkflowNode):
    integration_type = "automation-bluebarry"
    connection_evidence = ConnectionEvidence(noun="Bluebarry shopper identities", operation="list_identities")

    @classmethod
    def get_config_model(cls):
        return BluebarryConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Bluebarry API key")
        op, credential = self.config.config, self.config.credentials
        params, body = None, None
        headers = {"Accept": "application/json"}
        expected = 200
        if op.operation in READS:
            method, path = "GET", "/data/" + READS[op.operation]
            params = {"$" + key: str(value).lower() if isinstance(value, bool) else value
                for key, value in op.model_dump(exclude_none=True).items() if key != "operation"}
        elif isinstance(op, CreateWebhook):
            method, path, expected = "POST", "/data/WebhookSubscriptions", 201
            body = op.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(op, DeleteWebhook):
            method, path, expected = "DELETE", f"/data/WebhookSubscriptions({op.id})", 204
        elif isinstance(op, IssueSigningSecret):
            method, path = "POST", f"/data/WebhookSubscriptions/{op.id}/signing-secret"
        else:
            method, path, expected = "POST", "/data/identify", 204
            headers["BB-Tenant-Id"] = credential.tenant_id
            body = {"email": op.email, "userId": str(op.user_id)}
            if op.session_id is not None:
                body["sessionId"] = str(op.session_id)
        if not isinstance(op, IdentifyShopper):
            headers["Authorization"] = credential.api_key
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
        response.raise_for_status()
        if response.status_code != expected:
            raise ValueError("Bluebarry did not return the documented completion status")
        if expected == 204:
            return {"status": "success", "data": None, "http_status": 204}
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("Expected a Bluebarry JSON object")
        if op.operation in READS and not isinstance(data.get("value"), list):
            raise ValueError("Expected an OData value array")
        return {"status": "success", "data": data, "http_status": expected}

READS = {'list_identities': 'Identities', 'list_profiles': 'Profiles', 'list_quiz_starts': 'AdvisorStartedEvents', 'list_questions_shown': 'AdvisorQuestionOpenedEvents', 'list_answered_questions': 'AdvisorQuestionAnsweredEvents', 'list_results_shown': 'AdvisorResultViewedEvents', 'list_opened_results': 'AdvisorResultOpenedEvents', 'list_orders': 'ConversionEvents', 'list_past_results': 'AdvisorResultViewedSyncRecords', 'list_webhooks': 'WebhookSubscriptions'}

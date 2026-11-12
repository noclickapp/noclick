"""Simplesat v1 customer feedback operations using a pasted, scoped API key.

Each operation makes one request. List/search operations return a single page;
next URLs are returned as data and are never followed. Writes may replace tags
and custom attributes, and sending a survey email has an external email effect.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.simplesat.io"

class SimplesatAPIKey(BaseModel):
    model_config = ConfigDict(title="Simplesat API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.simplesat.io/settings/api-keys/",
            "x-credential-instructions": "Paste an API key from Simplesat Settings → API keys. Enable read customers for the connection check, plus read or write scopes for the resources your workflow uses: answers, customers, team members, responses, surveys and questions. NoClick sends the key in X-Simplesat-Token to api.simplesat.io."
        })
    credential_type: Literal["simplesat_api_key"] = "simplesat_api_key"
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"answer_id", "customer_id", "response_id", "team_member_id", "survey_token"}:
            if not isinstance(value, str) or not value or len(value) > 256 or value in {".", ".."} or any(c in value for c in "/?#\\") or any(ord(c) < 33 for c in value):
                raise ValueError("Use a single Simplesat resource ID or survey token")
        return value

class GetAnswerConfig(_Input):
    """Get answer by ID. Get an answer by ID.  Required scopes: `read answers` """
    operation: Literal['get_answer'] = 'get_answer'
    answer_id: str = Field(...)

class UpdateAnswerConfig(_Input):
    """Update answer by ID. Update an answer by ID.  One of `choice`, `choices`, or `comment` is required.  Required scopes: `write answers` """
    operation: Literal['update_answer'] = 'update_answer'
    answer_id: str = Field(...)
    choice: str | None = Field(None)
    choices: list[str] | None = Field(None)
    comment: str | None = Field(None)
    follow_up_answer: str | None = Field(None)
    follow_up_answer_choice: str | None = Field(None)
    follow_up_answer_choices: list[str] | None = Field(None)

    @model_validator(mode="after")
    def update_fields(self):
        if not any(getattr(self, key) is not None for key in ("choice", "choices", "comment")):
            raise ValueError("Provide choice, choices or comment")
        return self

class SearchAnswersConfigFiltersItem(_Input):
    key: str | None = Field(None)
    values: list[str] | None = Field(None)
    comparison: str | None = Field(None)

class SearchAnswersConfig(_Input):
    """Search answers. Search for answers.  Required scopes: `read answers`  Accepted `comparison` values are: - `is` - `is_not` - `contains` - `does_not_contain` - `is_unknown` - `has_any_value`  Accepted `key` values are: - `choice_value` - `comment` - `metric` - `sentiment` - `survey` (token) """
    operation: Literal['search_answers'] = 'search_answers'
    page: int | None = Field(None, ge=1)
    page_size: int | None = Field(None, ge=1, le=250)
    start_date: datetime | None = Field(None)
    end_date: datetime | None = Field(None)
    filters: list[SearchAnswersConfigFiltersItem] | None = Field(None)

class UpdateCustomerConfig(_Input):
    """Update customer by ID. Update a customer by ID.  Updating the `custom_attributes` or `tags` fields will overwrite any existing values.  Customers accept arrays in `custom_attributes`.  Required scopes: `write customers` """
    operation: Literal['update_customer'] = 'update_customer'
    customer_id: str = Field(...)
    external_id: str | None = Field(None)
    name: str | None = Field(None)
    company: str | None = Field(None)
    language: str | None = Field(None)
    tags: list[str] | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class GetCustomerConfig(_Input):
    """Get customer by ID. Get a customer by ID.  Required scopes: `read customers` """
    operation: Literal['get_customer'] = 'get_customer'
    customer_id: str = Field(...)

class CreateOrUpdateCustomerConfig(_Input):
    """Create or update customer. Create or update a customer.   If the customer with the specified email address already exists, the existing customer will be updated.  Updating the `custom_attributes` or `tags` fields will overwrite any existing values.  Customers accept arrays in `custom_attributes`.  Required scopes: `write customers` """
    operation: Literal['create_or_update_customer'] = 'create_or_update_customer'
    external_id: str | None = Field(None)
    email: str = Field(...)
    name: str | None = Field(None)
    company: str | None = Field(None)
    language: str | None = Field(None)
    tags: list[str] | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class ListCustomersConfig(_Input):
    """List customers. Get a paginated list of customers with optional filtering by creation/modification dates and subscription status.  Required scopes: `read customers` """
    operation: Literal['list_customers'] = 'list_customers'
    page: int | None = Field(None, ge=1)
    page_size: int | None = Field(None, ge=1, le=250)
    created_after: datetime | None = Field(None)
    created_before: datetime | None = Field(None)
    modified_after: datetime | None = Field(None)
    modified_before: datetime | None = Field(None)
    subscribed: bool | None = Field(None)

class GetTeamMemberConfig(_Input):
    """Get team member by ID. Get a team member by ID.  Required scopes: `read team members` """
    operation: Literal['get_team_member'] = 'get_team_member'
    team_member_id: str = Field(...)

class CreateOrUpdateTeamMemberConfig(_Input):
    """Create or update team member. Create or update a team member.  If the team member with the specified email address already exists, the existing team member will be updated.  Updating the `custom_attributes` field will overwrite any existing custom attributes.  Required scopes: `write team members` """
    operation: Literal['create_or_update_team_member'] = 'create_or_update_team_member'
    external_id: str | None = Field(None)
    name: str | None = Field(None)
    email: str = Field(...)
    custom_attributes: dict[str, object] | None = Field(None)

class GetResponseConfig(_Input):
    """Get response by ID. Get a response by ID.  Required scopes: `read responses` """
    operation: Literal['get_response'] = 'get_response'
    response_id: str = Field(...)

class SearchResponsesConfigFiltersItem(_Input):
    key: str | None = Field(None)
    values: list[str] | None = Field(None)
    attribute: str | None = Field(None)
    comparison: str | None = Field(None)

class SearchResponsesConfig(_Input):
    """Search for responses. Search for responses.  Required scopes: `read responses`  Accepted date filters are:   - `created_start_date`   - `created_end_date`   - `modified_start_date`   - `modified_end_date`  Accepted `comparison` values are:   - `is`   - `is_not`   - `contains`   - `does_not_contain`   - `is_unknown`   - `has_any_value`  Accepted `key` values are:   - `choice_value`   - `collaborator`   - `company`   - `comment`   - `customer` (name)   - `customer.email`   - `ip`   - `metric`   - `sentiment`   - `source`   - `survey` (token)   - `tag`   - `team_member` (name)   - `team_member.email`   - `team_member.id` (external_id)   - `ticket_id` (external_id)   - `customer.attribute` (add the `attribute` field to the filter to specify the attribute to filter on)   - `ticket.attribute` (add the `attribute` field to the filter to specify the attribute to filter on) """
    operation: Literal['search_responses'] = 'search_responses'
    page_size: int | None = Field(None, ge=1, le=250)
    page: int | None = Field(None, ge=1)
    start_date: datetime | None = Field(None)
    created_start_date: datetime | None = Field(None)
    end_date: datetime | None = Field(None)
    created_end_date: datetime | None = Field(None)
    modified_start_date: datetime | None = Field(None)
    modified_end_date: datetime | None = Field(None)
    filters: list[SearchResponsesConfigFiltersItem] | None = Field(None)

class CreateOrUpdateResponseConfigAnswersItem(_Input):
    question_id: int = Field(..., ge=1)
    choice: str | None = Field(None)
    choices: list[str] | None = Field(None)
    comment: str | None = Field(None)
    sentiment: str | None = Field(None)
    follow_up_answer: str | None = Field(None)
    follow_up_answer_choice: str | None = Field(None)
    follow_up_answer_choices: list[str] | None = Field(None)

class CreateOrUpdateResponseConfigTeamMembersItem(_Input):
    external_id: str | None = Field(None)
    name: str | None = Field(None)
    email: str = Field(...)
    custom_attributes: dict[str, object] | None = Field(None)
    role: str = Field(...)
    is_primary: bool = Field(...)

class CreateOrUpdateResponseConfigTicket(_Input):
    external_id: str | None = Field(None)
    subject: str | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class CreateOrUpdateResponseConfigCustomer(_Input):
    external_id: str | None = Field(None)
    name: str | None = Field(None)
    email: str = Field(...)
    tags: list[str] | None = Field(None)
    company: str | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class CreateOrUpdateResponseConfig(_Input):
    """Create or update response. Create or update a response.  If the response with the specified external ID already exists, the existing response will be updated.  When creating a new response, the `survey_id` and `answers` fields are required. The `answers` array should have at least one item with the `question_id` and either a `choice` or `choices` field.  The customer and team members will be created if they do not already exist with the specified email address. Otherwise, the response will be linked to the existing customer and team member. Team members and customers without emails will be ignored.  Updating any `tags` or `custom_attributes` field will overwrite any existing values.  When updating a response none of the fields are required, but at least one field must be provided.  Required scopes: `write responses` """
    operation: Literal['create_or_update_response'] = 'create_or_update_response'
    survey_id: int = Field(..., ge=1)
    language: str | None = Field(None)
    created: datetime | None = Field(None, description='Optional date and time to set as the response creation timestamp (for example when importing or syncing historical responses).')
    tags: list[str] | None = Field(None)
    answers: list[CreateOrUpdateResponseConfigAnswersItem] = Field(...)
    team_members: list[CreateOrUpdateResponseConfigTeamMembersItem] | None = Field(None)
    ticket: CreateOrUpdateResponseConfigTicket | None = Field(None)
    customer: CreateOrUpdateResponseConfigCustomer | None = Field(None)

    @model_validator(mode="after")
    def answer_choices(self):
        if not self.answers or any(a.choice is None and not a.choices for a in self.answers):
            raise ValueError("Provide answers with question_id and choice or choices")
        return self

class UpdateResponseConfigAnswersItem(_Input):
    question_id: int = Field(..., ge=1)
    choice: str | None = Field(None)
    choices: list[str] | None = Field(None)
    comment: str | None = Field(None)
    sentiment: str | None = Field(None)
    follow_up_answer: str | None = Field(None)
    follow_up_answer_choice: str | None = Field(None)
    follow_up_answer_choices: list[str] | None = Field(None)

class UpdateResponseConfigTeamMembersItem(_Input):
    external_id: str | None = Field(None)
    name: str | None = Field(None)
    email: str = Field(...)
    custom_attributes: dict[str, object] | None = Field(None)
    role: str | None = Field(None)
    is_primary: bool | None = Field(None)

class UpdateResponseConfigTicket(_Input):
    external_id: str | None = Field(None)
    subject: str | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class UpdateResponseConfigCustomer(_Input):
    external_id: str | None = Field(None)
    name: str | None = Field(None)
    email: str = Field(...)
    tags: list[str] | None = Field(None)
    company: str | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class UpdateResponseConfig(_Input):
    """Update response by ID. Update a response by ID.  Updating the `tags` field, or any of the `custom_attributes` fields will overwrite any existing values.  Required scopes: `write responses` """
    operation: Literal['update_response'] = 'update_response'
    response_id: str = Field(...)
    survey_id: int = Field(..., ge=1)
    language: str | None = Field(None)
    created: datetime | None = Field(None)
    tags: list[str] | None = Field(None)
    answers: list[UpdateResponseConfigAnswersItem] | None = Field(None)
    team_members: list[UpdateResponseConfigTeamMembersItem] | None = Field(None)
    ticket: UpdateResponseConfigTicket | None = Field(None)
    customer: UpdateResponseConfigCustomer | None = Field(None)

class ListSurveysConfig(_Input):
    """List surveys. List active surveys, newest first. Archived surveys are not returned.  Required scopes: `read surveys` """
    operation: Literal['list_surveys'] = 'list_surveys'
    name: str | None = Field(None)
    page_size: int | None = Field(None, ge=1, le=250)
    page: int | None = Field(None, ge=1)

class SendSurveyByEmailConfigCustomer(_Input):
    id: str | None = Field(None)
    email: str = Field(...)
    name: str | None = Field(None)
    company: str | None = Field(None)
    language: str | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class SendSurveyByEmailConfigTeamMember(_Input):
    id: str | None = Field(None)
    email: str | None = Field(None)
    name: str | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class SendSurveyByEmailConfigTicket(_Input):
    id: str | None = Field(None)
    subject: str | None = Field(None)
    custom_attributes: dict[str, object] | None = Field(None)

class SendSurveyByEmailConfig(_Input):
    """Send survey by email. Send a survey email.  Only survey tokens of surveys with survey type `event_based_email` are accepted.  Required scopes: `write surveys` """
    operation: Literal['send_survey_by_email'] = 'send_survey_by_email'
    survey_token: str = Field(...)
    customer: SendSurveyByEmailConfigCustomer = Field(...)
    team_member: SendSurveyByEmailConfigTeamMember | None = Field(None)
    ticket: SendSurveyByEmailConfigTicket | None = Field(None)

class ListQuestionsConfig(_Input):
    """List questions. List questions.  Required scopes: `read questions` """
    operation: Literal['list_questions'] = 'list_questions'
    survey_id: int | None = Field(None, ge=1)
    metric: str | None = Field(None)
    page_size: int | None = Field(None, ge=1, le=250)
    page: int | None = Field(None, ge=1)

# Simplesat's own MCP server: agents get its tools through a person's Simplesat sign-in.
SimplesatMcpCredential = mcp_credential("simplesat", "https://api.simplesat.io/mcp/", app="Simplesat")
SimplesatCredential = Union[SimplesatAPIKey, SimplesatMcpCredential]


SimplesatConfig = Annotated[Union[GetAnswerConfig, UpdateAnswerConfig, SearchAnswersConfig, UpdateCustomerConfig, GetCustomerConfig, CreateOrUpdateCustomerConfig, ListCustomersConfig, GetTeamMemberConfig, CreateOrUpdateTeamMemberConfig, GetResponseConfig, SearchResponsesConfig, CreateOrUpdateResponseConfig, UpdateResponseConfig, ListSurveysConfig, SendSurveyByEmailConfig, ListQuestionsConfig], Field(discriminator="operation")]

class SimplesatFullConfig(NodeConfig[SimplesatConfig, SimplesatCredential]):
    pass

ROUTES = {'get_answer': ('GET', '/api/v1/answers/{answer_id}', [], ['answer_id'], []), 'update_answer': ('PUT', '/api/v1/answers/{answer_id}', [], ['answer_id'], ['choice', 'choices', 'comment', 'follow_up_answer', 'follow_up_answer_choice', 'follow_up_answer_choices']), 'search_answers': ('POST', '/api/v1/answers/search', ['page', 'page_size'], [], ['start_date', 'end_date', 'filters']), 'update_customer': ('PUT', '/api/v1/customers/{customer_id}', [], ['customer_id'], ['external_id', 'name', 'company', 'language', 'tags', 'custom_attributes']), 'get_customer': ('GET', '/api/v1/customers/{customer_id}', [], ['customer_id'], []), 'create_or_update_customer': ('POST', '/api/v1/customers', [], [], ['external_id', 'email', 'name', 'company', 'language', 'tags', 'custom_attributes']), 'list_customers': ('GET', '/api/v1/customers', ['page', 'page_size', 'created_after', 'created_before', 'modified_after', 'modified_before', 'subscribed'], [], []), 'get_team_member': ('GET', '/api/v1/team-members/{team_member_id}', [], ['team_member_id'], []), 'create_or_update_team_member': ('POST', '/api/v1/team-members', [], [], ['external_id', 'name', 'email', 'custom_attributes']), 'get_response': ('GET', '/api/v1/responses/{response_id}', [], ['response_id'], []), 'search_responses': ('POST', '/api/v1/responses/search', ['page_size', 'page'], [], ['start_date', 'created_start_date', 'end_date', 'created_end_date', 'modified_start_date', 'modified_end_date', 'filters']), 'create_or_update_response': ('POST', '/api/v1/responses/create-or-update', [], [], ['survey_id', 'language', 'created', 'tags', 'answers', 'team_members', 'ticket', 'customer']), 'update_response': ('PUT', '/api/v1/responses/{response_id}/update', [], ['response_id'], ['survey_id', 'language', 'created', 'tags', 'answers', 'team_members', 'ticket', 'customer']), 'list_surveys': ('GET', '/api/v1/surveys', ['name', 'page_size', 'page'], [], []), 'send_survey_by_email': ('POST', '/api/v1/surveys/{survey_token}/email', [], ['survey_token'], ['customer', 'team_member', 'ticket']), 'list_questions': ('GET', '/api/v1/questions', ['survey_id', 'metric', 'page_size', 'page'], [], [])}

class SimplesatNode(WorkflowNode):
    integration_type = "automation-simplesat"
    credential_provider_labels = {"simplesat": "Simplesat Account"}
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers")

    @classmethod
    def get_config_model(cls):
        return SimplesatFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Simplesat API key")
        config = self.config.config
        method, path, query_fields, path_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_unset=True)
        for field in path_fields:
            path = path.replace("{" + field + "}", quote(getattr(config, field), safe=""))
        params = {key: values[key] for key in query_fields if values.get(key) is not None}
        body = {key: values[key] for key in body_fields if key in values}
        headers = {"X-Simplesat-Token": self.config.credentials.api_key,
                   "Accept": "application/json", "Content-Type": "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                headers=headers, **({"json": body} if body_fields else {}))
        if response.status_code >= 300:
            # Keep the provider's rejection available to credential verification.
            message = response.text[:2000].replace(self.config.credentials.api_key, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message}
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Expected a JSON object or list from Simplesat")
        return {"status": "success", "data": data}

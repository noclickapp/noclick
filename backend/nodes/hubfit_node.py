"""HubFit coaching operations and signed, API-registered event triggers.

The fixed v1 routes use a pasted workspace API key; event payloads contain only
record references, which the agent can follow with the matching read operation.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import time
from datetime import date, datetime
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.hubfit_operations import OPERATIONS, EVENTS
from nodes.scopes.hubfit import HUBFIT_SCOPES

BASE_URL = "https://api.hubfit.com/v1"


class HubFitAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="HubFit API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://hubfit.com/developers/authentication",
            "x-credential-instructions": "In HubFit Settings > API, create an API key (Ultimate plan, workspace owner). Paste the key alone. Select clients:read for connection verification and reads; clients:create, clients:write, messages:write, check-ins:review and tasks:write for their actions. Triggers require webhooks:write and an owner or admin key. The key acts as its owner in that workspace."})
    credential_type: Literal["hubfit_api_key"] = Field("hubfit_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def preserve_optional_empty_values(cls, values):
        # The shared union config lens may coerce null to "" when another
        # operation requires the same field. Restore this operation's optional
        # strings, retaining field presence so PATCH can explicitly clear them.
        if isinstance(values, dict):
            values = dict(values)
            for name, field in cls.model_fields.items():
                if field.annotation == Optional[str] and values.get(name) == "":
                    values[name] = None
        return values

    @model_validator(mode="after")
    def validate_dates_and_update(self):
        for key in ("start_date", "end_date", "due_date"):
            value = getattr(self, key, None)
            if value is not None:
                date.fromisoformat(value)
        for key in ("submitted_after", "submitted_before"):
            value = getattr(self, key, None)
            if value is not None:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Use a timestamp with a timezone")
        if getattr(self, "start_date", None) and getattr(self, "end_date", None):
            if self.start_date > self.end_date:
                raise ValueError("End date must be on or after start date")
        if self.operation == "create_client" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.email):
            raise ValueError("Use a valid client email address")
        if self.operation == "update_task":
            body_fields = OPERATIONS[self.operation]["body"]
            nullable = {"due_date", "assignee_id", "client_id"}
            if not any(getattr(self, key) is not None or
                       (key in nullable and key in self.model_fields_set) for key in body_fields):
                raise ValueError("Choose at least one task field to update")
        return self


class HubFitListClientsConfig(_Input):
    """List clients."""
    operation: Literal['list_clients'] = Field('list_clients', title='List clients', json_schema_extra={"ui:hidden": True, "x-display-name": 'List clients', "x-category": 'Clients', "x-is-trigger": False})
    search: Optional[str] = Field(None, title='Search', min_length=1, max_length=100, description='Case-insensitive match on part of a name or email.')
    email: Optional[str] = Field(None, title='Email', min_length=1, max_length=320, description='Only the client with exactly this email, ignoring case. Use it to find one specific client; `search` also matches partial emails.')
    tag_id: Optional[str] = Field(None, title='Tag id', pattern='^[0-9a-fA-F]{24}$', description='Only clients with this tag. An id from `GET /tags`.', json_schema_extra={'x-dynamic-options': {'field_name': 'tag_id', 'allow_custom': True, 'searchable': True}})
    status: Optional[Literal['active', 'archived', 'all']] = Field('active', title='Status', description='`active` (the default) for current clients, `archived` for archived ones, `all` for both. An archived client is only ever listed: anything else about them answers `409 client_archived` until you unarchive them in HubFit.')
    limit: Optional[int] = Field(25, title='Limit', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', min_length=1, max_length=200, description='The `nextCursor` from the previous page.')


class HubFitCreateClientConfig(_Input):
    """Create a client."""
    operation: Literal['create_client'] = Field('create_client', title='Create a client', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create a client', "x-category": 'Clients', "x-is-trigger": False})
    name: str = Field(..., title='Name', min_length=1, max_length=50, pattern='^[^@]*$', description="The client's full name. Can't contain `@`.")
    email: str = Field(..., title='Email', max_length=254, json_schema_extra={'format': 'email'})
    send_login_instructions: Optional[bool] = Field(False, title='Send login instructions', description='Email the client their login instructions now.')
    onboarding_flow_id: Optional[str] = Field(None, title='Onboarding flow id', pattern='^[0-9a-fA-F]{24}$', description='An onboarding flow to run for the new client, by an `id` from `GET /onboarding-flows`.', json_schema_extra={'x-dynamic-options': {'field_name': 'onboarding_flow_id', 'allow_custom': True, 'searchable': True}})
    idempotency_key: Optional[str] = Field(None, title='Idempotency key', min_length=1, max_length=255, description='Reuse the same key when retrying this write within 24 hours.')


class HubFitGetClientConfig(_Input):
    """Get a client."""
    operation: Literal['get_client'] = Field('get_client', title='Get a client', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a client', "x-category": 'Clients', "x-is-trigger": False})
    client_id: str = Field(..., title='Client id', pattern='^[0-9a-fA-F]{24}$', json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})


class HubFitListClientNotesConfig(_Input):
    """List a client's notes."""
    operation: Literal['list_client_notes'] = Field('list_client_notes', title="List a client's notes", json_schema_extra={"ui:hidden": True, "x-display-name": "List a client's notes", "x-category": 'Notes', "x-is-trigger": False})
    client_id: str = Field(..., title='Client id', pattern='^[0-9a-fA-F]{24}$', json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    limit: Optional[int] = Field(10, title='Limit', ge=1, le=50, description='How many notes a page holds. 10 unless you ask for more, and at most 50, fewer than other lists, as a note can be 5,000 characters.')
    cursor: Optional[str] = Field(None, title='Cursor', min_length=1, max_length=200, description='The `nextCursor` from the previous page.')


class HubFitCreateClientNoteConfig(_Input):
    """Add a note to a client."""
    operation: Literal['create_client_note'] = Field('create_client_note', title='Add a note to a client', json_schema_extra={"ui:hidden": True, "x-display-name": 'Add a note to a client', "x-category": 'Notes', "x-is-trigger": False})
    client_id: str = Field(..., title='Client id', pattern='^[0-9a-fA-F]{24}$', json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    title: Optional[str] = Field(None, title='Title', max_length=100, description='A heading for the note.')
    text: str = Field(..., title='Text', max_length=5000, pattern='\\S', description="The note. Can't be blank.")
    visibility: Literal['private', 'shared'] = Field(..., title='Visibility', description='`private` if only your team sees the note. `shared` if the client sees it in their app too; adding a shared note sends them a push notification with its text.')
    idempotency_key: Optional[str] = Field(None, title='Idempotency key', min_length=1, max_length=255, description='Reuse the same key when retrying this write within 24 hours.')


class HubFitSendClientMessageConfig(_Input):
    """Send a message to a client."""
    operation: Literal['send_client_message'] = Field('send_client_message', title='Send a message to a client', json_schema_extra={"ui:hidden": True, "x-display-name": 'Send a message to a client', "x-category": 'Messages', "x-is-trigger": False})
    client_id: str = Field(..., title='Client id', pattern='^[0-9a-fA-F]{24}$', json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    text: str = Field(..., title='Text', max_length=5000, pattern='\\S', description="The message. Can't be blank.")
    idempotency_key: Optional[str] = Field(None, title='Idempotency key', min_length=1, max_length=255, description='Reuse the same key when retrying this write within 24 hours.')


class HubFitListTagsConfig(_Input):
    """List tags."""
    operation: Literal['list_tags'] = Field('list_tags', title='List tags', json_schema_extra={"ui:hidden": True, "x-display-name": 'List tags', "x-category": 'Tags', "x-is-trigger": False})


class HubFitListOnboardingFlowsConfig(_Input):
    """List onboarding flows."""
    operation: Literal['list_onboarding_flows'] = Field('list_onboarding_flows', title='List onboarding flows', json_schema_extra={"ui:hidden": True, "x-display-name": 'List onboarding flows', "x-category": 'Onboarding flows', "x-is-trigger": False})


class HubFitListCompletedWorkoutsConfig(_Input):
    """List completed workouts."""
    operation: Literal['list_completed_workouts'] = Field('list_completed_workouts', title='List completed workouts', json_schema_extra={"ui:hidden": True, "x-display-name": 'List completed workouts', "x-category": 'Completed workouts', "x-is-trigger": False})
    client_id: Optional[str] = Field(None, title='Client id', pattern='^[0-9a-fA-F]{24}$', description="Only this client's workouts.", json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    start_date: Optional[str] = Field(None, title='Start date', description='Only workouts from this day, included, as `YYYY-MM-DD`, in your own calendar (the timezone in your HubFit settings), as the app shows workouts to you.', json_schema_extra={'format': 'date'})
    end_date: Optional[str] = Field(None, title='End date', description='Only workouts up to this day, included, as `YYYY-MM-DD`, in your own calendar.', json_schema_extra={'format': 'date'})
    limit: Optional[int] = Field(25, title='Limit', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', min_length=1, max_length=200, description='The `nextCursor` from the previous page.')


class HubFitGetCompletedWorkoutConfig(_Input):
    """Get a completed workout."""
    operation: Literal['get_completed_workout'] = Field('get_completed_workout', title='Get a completed workout', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a completed workout', "x-category": 'Completed workouts', "x-is-trigger": False})
    workout_id: str = Field(..., title='Workout id', pattern='^[0-9a-fA-F]{24}$')


class HubFitListCheckInSubmissionsConfig(_Input):
    """List check-in submissions."""
    operation: Literal['list_check_in_submissions'] = Field('list_check_in_submissions', title='List check-in submissions', json_schema_extra={"ui:hidden": True, "x-display-name": 'List check-in submissions', "x-category": 'Check-in submissions', "x-is-trigger": False})
    status: Optional[Literal['awaiting_review', 'reviewed', 'all']] = Field('awaiting_review', title='Status')
    client_id: Optional[str] = Field(None, title='Client id', pattern='^[0-9a-fA-F]{24}$', description="Only this client's submissions.", json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    submitted_after: Optional[str] = Field(None, title='Submitted after', description="Only submissions received after this time, e.g. `2026-10-05T00:00:00Z` (encode a `+` offset as `%2B`). To fetch what's new since your last run, pass the time of that run.", json_schema_extra={'format': 'date-time'})
    submitted_before: Optional[str] = Field(None, title='Submitted before', description='Only submissions received before this time.', json_schema_extra={'format': 'date-time'})
    limit: Optional[int] = Field(25, title='Limit', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', min_length=1, max_length=200, description='The `nextCursor` from the previous page.')


class HubFitGetCheckInSubmissionConfig(_Input):
    """Get a check-in submission."""
    operation: Literal['get_check_in_submission'] = Field('get_check_in_submission', title='Get a check-in submission', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a check-in submission', "x-category": 'Check-in submissions', "x-is-trigger": False})
    submission_id: str = Field(..., title='Submission id', pattern='^[0-9a-fA-F]{24}$', json_schema_extra={'x-dynamic-options': {'field_name': 'submission_id', 'allow_custom': True, 'searchable': True}})


class HubFitReviewCheckInSubmissionConfig(_Input):
    """Review a check-in submission."""
    operation: Literal['review_check_in_submission'] = Field('review_check_in_submission', title='Review a check-in submission', json_schema_extra={"ui:hidden": True, "x-display-name": 'Review a check-in submission', "x-category": 'Check-in submissions', "x-is-trigger": False})
    submission_id: str = Field(..., title='Submission id', pattern='^[0-9a-fA-F]{24}$', json_schema_extra={'x-dynamic-options': {'field_name': 'submission_id', 'allow_custom': True, 'searchable': True}})
    comment: Optional[str] = Field(None, title='Comment', max_length=5000, pattern='\\S', description="Your review comment, sent to the client. Can't be blank.")
    idempotency_key: Optional[str] = Field(None, title='Idempotency key', min_length=1, max_length=255, description='Reuse the same key when retrying this write within 24 hours.')


class HubFitGetQuestionnaireSubmissionConfig(_Input):
    """Get a questionnaire submission."""
    operation: Literal['get_questionnaire_submission'] = Field('get_questionnaire_submission', title='Get a questionnaire submission', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a questionnaire submission', "x-category": 'Questionnaire submissions', "x-is-trigger": False})
    submission_id: str = Field(..., title='Submission id', pattern='^[0-9a-fA-F]{24}$')


class HubFitListPackagePurchasesConfig(_Input):
    """List package purchases."""
    operation: Literal['list_package_purchases'] = Field('list_package_purchases', title='List package purchases', json_schema_extra={"ui:hidden": True, "x-display-name": 'List package purchases', "x-category": 'Package purchases', "x-is-trigger": False})
    client_id: Optional[str] = Field(None, title='Client id', pattern='^[0-9a-fA-F]{24}$', description="Only this client's purchases.", json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    start_date: Optional[str] = Field(None, title='Start date', description='Only purchases from this day, included, as `YYYY-MM-DD`, in your own calendar (the timezone in your HubFit settings).', json_schema_extra={'format': 'date'})
    end_date: Optional[str] = Field(None, title='End date', description='Only purchases up to this day, included, as `YYYY-MM-DD`, in your own calendar.', json_schema_extra={'format': 'date'})
    limit: Optional[int] = Field(25, title='Limit', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', min_length=1, max_length=200, description='The `nextCursor` from the previous page.')


class HubFitGetPackagePurchaseConfig(_Input):
    """Get a package purchase."""
    operation: Literal['get_package_purchase'] = Field('get_package_purchase', title='Get a package purchase', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a package purchase', "x-category": 'Package purchases', "x-is-trigger": False})
    purchase_id: str = Field(..., title='Purchase id', pattern='^[0-9a-fA-F]{24}$')


class HubFitListTasksConfig(_Input):
    """List tasks."""
    operation: Literal['list_tasks'] = Field('list_tasks', title='List tasks', json_schema_extra={"ui:hidden": True, "x-display-name": 'List tasks', "x-category": 'Tasks', "x-is-trigger": False})
    status: Optional[Literal['open', 'completed']] = Field('open', title='Status', description='`open` (the default) or `completed`.')
    client_id: Optional[str] = Field(None, title='Client id', pattern='^[0-9a-fA-F]{24}$', description='Only tasks about this client.', json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    assignee_id: Optional[str] = Field(None, title='Assignee id', pattern='^[0-9a-fA-F]{24}$', description='Only tasks assigned to this coach (an `assignee.id`).')
    limit: Optional[int] = Field(25, title='Limit', ge=1, le=100)
    cursor: Optional[str] = Field(None, title='Cursor', min_length=1, max_length=200, description='The `nextCursor` from the previous page.')


class HubFitCreateTaskConfig(_Input):
    """Add a task."""
    operation: Literal['create_task'] = Field('create_task', title='Add a task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Add a task', "x-category": 'Tasks', "x-is-trigger": False})
    title: str = Field(..., title='Title', max_length=200, pattern='\\S', description="What needs doing. Can't be blank.")
    due_date: Optional[str] = Field(None, title='Due date', description="The day it's due, as `YYYY-MM-DD`, in your own calendar.", json_schema_extra={'format': 'date'})
    assignee_id: Optional[str] = Field(None, title='Assignee id', pattern='^[0-9a-fA-F]{24}$', description='The team member to give it to (a coach who has joined your workspace). Defaults to you.')
    client_id: Optional[str] = Field(None, title='Client id', pattern='^[0-9a-fA-F]{24}$', description="The client the task is about. Only your team sees the task; the client isn't told.", json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    idempotency_key: Optional[str] = Field(None, title='Idempotency key', min_length=1, max_length=255, description='Reuse the same key when retrying this write within 24 hours.')


class HubFitGetTaskConfig(_Input):
    """Get a task."""
    operation: Literal['get_task'] = Field('get_task', title='Get a task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get a task', "x-category": 'Tasks', "x-is-trigger": False})
    task_id: str = Field(..., title='Task id', pattern='^[0-9a-fA-F]{24}$', description='A task `id` from `GET /tasks`.', json_schema_extra={'x-dynamic-options': {'field_name': 'task_id', 'allow_custom': True, 'searchable': True}})


class HubFitUpdateTaskConfig(_Input):
    """Change a task."""
    operation: Literal['update_task'] = Field('update_task', title='Change a task', json_schema_extra={"ui:hidden": True, "x-display-name": 'Change a task', "x-category": 'Tasks', "x-is-trigger": False})
    task_id: str = Field(..., title='Task id', pattern='^[0-9a-fA-F]{24}$', description='A task `id` from `GET /tasks`.', json_schema_extra={'x-dynamic-options': {'field_name': 'task_id', 'allow_custom': True, 'searchable': True}})
    title: Optional[str] = Field(None, title='Title', max_length=200, pattern='\\S')
    due_date: Optional[str] = Field(None, title='Due date', description='`YYYY-MM-DD` in your own calendar, or `null` for no due date.', json_schema_extra={'format': 'date'})
    assignee_id: Optional[str] = Field(None, title='Assignee id', pattern='^[0-9a-fA-F]{24}$', description='A coach who has joined your workspace, or `null` to unassign it.')
    client_id: Optional[str] = Field(None, title='Client id', pattern='^[0-9a-fA-F]{24}$', description="The client it's about, or `null` for none.", json_schema_extra={'x-dynamic-options': {'field_name': 'client_id', 'allow_custom': True, 'searchable': True}})
    status: Optional[Literal['open', 'completed']] = Field(None, title='Status')


class HubFitOnClientCreatedConfig(WebhookTriggerConfigBase):
    """Receive the documented client.created record reference."""
    operation: Literal['on_client_created'] = Field('on_client_created', title='On client created', json_schema_extra={"ui:hidden": True, "x-display-name": 'On client created', "x-category": "Triggers", "x-is-trigger": True})
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with HubFit automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class HubFitOnCheckInSubmittedConfig(WebhookTriggerConfigBase):
    """Receive the documented check_in_submission.created record reference."""
    operation: Literal['on_check_in_submitted'] = Field('on_check_in_submitted', title='On check in submitted', json_schema_extra={"ui:hidden": True, "x-display-name": 'On check in submitted', "x-category": "Triggers", "x-is-trigger": True})
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with HubFit automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class HubFitOnWorkoutCompletedConfig(WebhookTriggerConfigBase):
    """Receive the documented completed_workout.created record reference."""
    operation: Literal['on_workout_completed'] = Field('on_workout_completed', title='On workout completed', json_schema_extra={"ui:hidden": True, "x-display-name": 'On workout completed', "x-category": "Triggers", "x-is-trigger": True})
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with HubFit automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class HubFitOnPackagePurchasedConfig(WebhookTriggerConfigBase):
    """Receive the documented package_purchase.created record reference."""
    operation: Literal['on_package_purchased'] = Field('on_package_purchased', title='On package purchased', json_schema_extra={"ui:hidden": True, "x-display-name": 'On package purchased', "x-category": "Triggers", "x-is-trigger": True})
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with HubFit automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


class HubFitOnQuestionnaireSubmittedConfig(WebhookTriggerConfigBase):
    """Receive the documented questionnaire_submission.created record reference."""
    operation: Literal['on_questionnaire_submitted'] = Field('on_questionnaire_submitted', title='On questionnaire submitted', json_schema_extra={"ui:hidden": True, "x-display-name": 'On questionnaire submitted', "x-category": "Triggers", "x-is-trigger": True})
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with HubFit automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


HubFitOperation = Annotated[Union[HubFitListClientsConfig, HubFitCreateClientConfig, HubFitGetClientConfig, HubFitListClientNotesConfig, HubFitCreateClientNoteConfig, HubFitSendClientMessageConfig, HubFitListTagsConfig, HubFitListOnboardingFlowsConfig, HubFitListCompletedWorkoutsConfig, HubFitGetCompletedWorkoutConfig, HubFitListCheckInSubmissionsConfig, HubFitGetCheckInSubmissionConfig, HubFitReviewCheckInSubmissionConfig, HubFitGetQuestionnaireSubmissionConfig, HubFitListPackagePurchasesConfig, HubFitGetPackagePurchaseConfig, HubFitListTasksConfig, HubFitCreateTaskConfig, HubFitGetTaskConfig, HubFitUpdateTaskConfig, HubFitOnClientCreatedConfig, HubFitOnCheckInSubmittedConfig, HubFitOnWorkoutCompletedConfig, HubFitOnPackagePurchasedConfig, HubFitOnQuestionnaireSubmittedConfig], Field(discriminator="operation")]


class HubFitNodeConfig(NodeConfig[HubFitOperation, HubFitAPIKeyCredential]):
    pass


class HubFitNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-hubfit"
    scope_registry = HUBFIT_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_clients", noun="clients", label_keys=("name", "email", "id"))
    edit_examples = ["Add a HubFit client", "Review a client's check-in", "Send a client a message", "Start when a client completes a workout"]

    @classmethod
    def get_config_model(cls):
        return HubFitNodeConfig

    @staticmethod
    async def _request(credential, method, route, *, params=None, body=None, idempotency_key=None):
        key = HubFitAPIKeyCredential.model_validate(credential).api_key
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + route, headers=headers, params=params, json=body)
        if response.is_error or response.is_redirect:
            try:
                problem = response.json()
                detail = problem.get("detail") or problem.get("title") or "Request failed"
                code = problem.get("code") or "api_error"
            except (ValueError, AttributeError):
                detail, code = "Request failed", "api_error"
            message = f"HubFit {response.status_code} ({code}): {detail}".replace(key, "[redacted]")
            raise ValueError(message)
        if response.status_code == 204:
            return {}
        result = response.json()
        if not isinstance(result, dict) or "data" not in result:
            raise ValueError("HubFit returned an unexpected response envelope")
        return result

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.config or self.config.credentials is None:
            raise ValueError("Connect a HubFit API key")
        op = self.config.config
        if op.operation in EVENTS:
            return self.no_event_output(op.operation)
        self.scope_registry.require(op.operation)
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        route = spec["route"]
        for field, wire in spec["path"].items():
            route = route.replace("{" + wire + "}", quote(str(values[field]), safe=""))
        params = {wire: values[field] for field, wire in spec["query"].items() if field in values}
        body = {wire: values[field] for field, wire in spec["body"].items() if field in values}
        if op.operation == "update_task":
            body.update({wire: None for field, wire in spec["body"].items()
                         if field in {"due_date", "assignee_id", "client_id"} and
                         field in op.model_fields_set and getattr(op, field) is None})
        result = await self._request(self.config.credentials.model_dump(), spec["method"], route,
            params=params or None, body=body if spec["method"] in {"POST", "PATCH"} else None,
            idempotency_key=getattr(op, "idempotency_key", None))
        output = {"status": "success", "action": op.operation, **result}
        await self.emit(output)
        return output

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = EVENTS.get(config.get("operation"))
        if not event:
            raise ValueError("Choose a HubFit trigger")
        result = await cls._request(credential, "POST", "/webhook-endpoints",
            body={"name": f"NoClick {node_id}"[:100], "url": webhook_url, "events": [event]})
        endpoint = result["data"]
        if not isinstance(endpoint, dict) or not endpoint.get("id") or not result.get("secret"):
            raise ValueError("HubFit did not return an endpoint ID and signing secret; inspect Settings > API before retrying")
        return {"external_webhook_id": endpoint["id"], "signing_secret": result["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint_id = config.get("external_webhook_id")
        if not endpoint_id:
            raise ValueError("HubFit endpoint ID is missing")
        if not credential:
            raise ValueError("The original HubFit key is required to remove its endpoint")
        await cls._request(credential, "DELETE", "/webhook-endpoints/" + quote(str(endpoint_id), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = config.get("signing_secret")
        headers = {key.lower(): value for key, value in headers.items()}
        msg_id, timestamp = headers.get("webhook-id"), headers.get("webhook-timestamp")
        if not isinstance(secret, str) or not secret.startswith("whsec_") or not msg_id or not timestamp:
            return False
        try:
            if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
                return False
            key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
            if len(key) != 32:
                return False
            signed = f"{msg_id}.{timestamp}.".encode() + body
            expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
            return any(hmac.compare_digest(entry.removeprefix("v1,"), expected)
                       for entry in headers.get("webhook-signature", "").split()
                       if entry.startswith("v1,"))
        except (ValueError, TypeError, binascii.Error):
            return False

    @classmethod
    def filter_trigger_payload(cls, payload: dict[str, Any], config: dict[str, Any]) -> bool:
        event = EVENTS.get(config.get("operation"))
        if not event or payload.get("type") != event:
            return False
        data = payload.get("data")
        return isinstance(data, dict) and all(isinstance(data.get(key), str) and
            re.fullmatch(r"[0-9a-fA-F]{24}", data[key]) for key in ("id", "clientId"))

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not isinstance(output, dict) or output.get("type") not in EVENTS.values():
            return None
        event, record = output["type"], output.get("data")
        if not isinstance(record, dict) or not record.get("id") or not record.get("clientId"):
            return None
        action, field, heading = {
            "client.created": ("get_client", "client_id", "Client added"),
            "check_in_submission.created": ("get_check_in_submission", "submission_id", "Client submitted a check-in"),
            "completed_workout.created": ("get_completed_workout", "workout_id", "Client completed a workout"),
            "package_purchase.created": ("get_package_purchase", "purchase_id", "Client bought a package"),
            "questionnaire_submission.created": ("get_questionnaire_submission", "submission_id", "Client submitted a questionnaire"),
        }[event]
        text = (f"HubFit: {heading}.\nClient ID: {record['clientId']}\n"
                f"Record ID: {record['id']}\nAt: {output.get('createdAt')}\nEvent ID: {output.get('id')}\n"
                f"Fetch the current record with {action} {field}={record['id']}. "
                "The delivery contains record references; fetch the record to read its content. "
                "Skip it if HubFit returns 404 or 409 (deleted, archived or inaccessible).")
        return {"text": text, "conversation_key": record["clientId"], "title": "HubFit: " + heading}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        routes = {"client_id": "/clients", "tag_id": "/tags", "onboarding_flow_id": "/onboarding-flows",
                  "task_id": "/tasks", "submission_id": "/check-in-submissions"}
        if field_name not in routes:
            return []
        paged = field_name in {"client_id", "task_id", "submission_id"}
        params = {"limit": 100} if paged else {}
        if page_token and paged:
            params["cursor"] = page_token
        if search and field_name == "client_id":
            params["search"] = search
        if field_name == "submission_id":
            params["status"] = "all"
        result = await cls._request(credential_data, "GET", routes[field_name], params=params or None)
        options = []
        for row in result["data"]:
            label = row.get("name") or row.get("title") or row["id"]
            if search and field_name != "client_id" and search.casefold() not in label.casefold():
                continue
            options.append({"value": row["id"], "label": label})
        return {"options": options, "next_page_token": result.get("nextCursor") if paged else None}

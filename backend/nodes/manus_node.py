"""Manus v2 task and workspace automation using a personal API key.

Contract: https://open.manus.ai/docs/v2/openapi_v2.json (2.0.0).
Every operation makes exactly one request. Lists retain the provider's cursor
and has_more fields; task creation returns an asynchronous task acknowledgement.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

BASE_URL = "https://api.manus.ai/v2/"


class ManusAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Manus API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://manus.im/app#settings/developers",
            "x-credential-instructions": "In Manus Developers settings, create an API key and paste it here. The key grants full access to your Manus account. NoClick sends it in x-manus-api-key and checks the account with the read-only user.me endpoint.",
        },
    )
    credential_type: Literal["manus_api_key"] = Field(
        "manus_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError("Paste only the Manus API key without a header or spaces")
        return value


class ManusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def combinations(self):
        if getattr(self, "oauth_client_id", None) and getattr(self, "api_key_id", None):
            raise ValueError(
                "Choose either an OAuth client filter or an API key filter"
            )
        scope = getattr(self, "scope", None)
        if scope == "project" and not getattr(self, "project_id", None):
            raise ValueError("Project scope requires a project ID")
        if scope == "agent_subtask" and not getattr(self, "agent_id", None):
            raise ValueError("Agent subtask scope requires an agent ID")
        if getattr(self, "cursor", None) and getattr(self, "start_event_id", None):
            raise ValueError("Choose either cursor or start event ID")
        if getattr(self, "clear_connectors", False) and getattr(
            getattr(self, "message", None), "connectors", None
        ):
            raise ValueError(
                "Clearing connectors cannot be combined with a connector selection"
            )
        return self


class ManusWebsite(ManusInput):
    id: str = Field(
        ...,
        min_length=1,
        description="Existing web website ID owned by this Manus account.",
    )


AgentProfile = Annotated[
    str,
    Field(
        pattern=r"^(?:standard|lite|max(?:-(?:medium|high|extra|ultra))?|(?:(?:manus-)?[0-9]+(?:\.[0-9]+)+(?:-(?:standard|lite|max(?:-(?:medium|high|extra|ultra))?))?)?)$"
    ),
]


class ManusMessage(ManusInput):
    """Plain text messages with optional connector and skill selections."""

    content: str = Field(
        ...,
        min_length=1,
        description="Prompt text, limited by Manus to approximately 5,000 estimated tokens.",
    )
    connectors: list[str] | None = None
    enable_skills: list[str] | None = None
    force_skills: list[str] | None = None
    task_references: list[
        Annotated[str, Field(pattern=r"^[A-Za-z0-9]{22}$")]
    ] | None = Field(None, max_length=20)

    @field_validator("content")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Provide a nonempty prompt")
        return value


class ManusGetCurrentUserConfig(ManusInput):
    """Returns the Manus user ID associated with the authenticated API key or OAuth2 access token. API Key and Trusted client callers also receive the user's display name, email, and avatar. This endpoint is read-only and does not require an OAuth scope."""

    operation: Literal["get_current_user"] = Field(
        "get_current_user", json_schema_extra={"ui:hidden": True}
    )


class ManusCreateTaskConfig(ManusInput):
    """Creates a new task. The task runs asynchronously. Poll for progress with [task.listMessages](https://open.manus.ai/docs/v2/task.listMessages), send follow-ups with [task.sendMessage](https://open.manus.ai/docs/v2/task.sendMessage)."""

    operation: Literal["create_task"] = Field(
        "create_task", json_schema_extra={"ui:hidden": True}
    )
    message: ManusMessage = Field(
        ...,
        description="The message to start the task with. Contains the prompt text, optional file attachments, and connector/skill configuration.",
    )
    website: ManusWebsite | None = Field(
        None,
        description="Optional. An existing website for the new task to edit — the same as attaching the website in the Manus app. `message.content` must also contain a non-empty text instruction; a `hidden` text part also counts. Only web websites owned by the authorized user are accepted; mobile apps and games are not. Only task.create has this field: follow-up messages through [task.sendMessage](https://open.manus.ai/docs/v2/task.sendMessage) only need the instruction.",
    )
    project_id: str | None = Field(
        None,
        description="Project ID to associate this task with. The project's instruction will be automatically applied. Use [project.list](https://open.manus.ai/docs/v2/project.list) to get available project IDs.",
    )
    locale: str | None = Field(
        None,
        description='Locale for the task output language (e.g., "en", "zh-CN", "ja"). Defaults to the user\'s account locale setting.',
    )
    interactive_mode: bool | None = Field(
        None,
        description="When enabled, the agent may pause and ask follow-up questions if the input is insufficient. When disabled (default), the agent proceeds with best-effort execution without asking.",
    )
    hide_in_task_list: bool | None = Field(
        None,
        description="When true, the task does not appear in the Manus webapp task list. It remains accessible through the `task_url` in the response.",
    )
    share_visibility: Literal["private", "team", "public"] | None = Field(
        None, description="Who can view the task."
    )
    agent_profile: AgentProfile | None = Field(
        None,
        description="Agent profile to use for the task. Use the stable values `standard` (default), `lite`, or `max`. For `max`, you can also choose a thinking level with `max-medium`, `max-high`, `max-extra`, or `max-ultra` (deepest reasoning, slowest, and highest credit usage); plain `max` uses the default Max thinking level, currently equivalent to `max-extra`. Versioned aliases such as `1.6-lite`, `2.0-max`, `2.0-max-ultra`, and the legacy `manus-1.6-lite` form are also accepted; the version segment is ignored because model versions are not selected independently. A version without a suffix, such as `1.6` or `manus-1.6`, means `standard`. Omit the field (or pass an empty string) to use `standard`. Free personal accounts are downgraded to `lite` regardless of the requested value.",
    )
    title: str | None = Field(
        None,
        description="Custom title for the task. If not provided, a title is generated from the input message. If generation times out, `task_title` is the placeholder `generating title...`; fetch `task.detail` later for the updated title.",
    )
    async_title: bool | None = Field(
        None,
        description="When `true` and `title` is omitted, the task is created without waiting for title generation. `task_title` is the placeholder `generating title...` until the title is ready; fetch `task.detail` later for the updated title. Ignored when `title` is provided.",
    )
    structured_output_schema: dict[str, Any] | None = Field(
        None,
        description="JSON Schema for structured output extraction. When provided, the agent runs normally, then a post-processing step extracts a result conforming to your schema. The schema must follow the [Structured Output](https://open.manus.ai/docs/v2/structured-output) subset of JSON Schema: all object properties must be listed in `required`, and `additionalProperties` must be `false`.",
    )
    clear_connectors: bool | None = Field(
        None,
        description="Clears the connector selection for the new task. The task starts without connectors; the project's default connectors and your default connectors are not loaded. Cannot be combined with a non-empty `message.connectors`. Other task features may still provide tools.",
    )


class ManusGetTaskConfig(ManusInput):
    """Retrieves a task's status and metadata. Use [task.listMessages](https://open.manus.ai/docs/v2/task.listMessages) for the full event history, or [task.sendMessage](https://open.manus.ai/docs/v2/task.sendMessage) to continue the conversation."""

    operation: Literal["get_task"] = Field(
        "get_task", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ...,
        description="The unique identifier of the task to retrieve. Supports the shortcut `agent-default-main_task` for the IM agent's main task.",
        min_length=1,
    )


class ManusListTasksConfig(ManusInput):
    """Lists tasks with optional filtering and cursor-based pagination. Use `scope` to filter by task type, e.g. `agent_subtask` with `agent_id` for agent subtasks."""

    operation: Literal["list_tasks"] = Field(
        "list_tasks", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(
        None,
        description="Number of tasks to return per page. Default: 20, Max: 100.",
        ge=1,
        le=100,
    )
    cursor: str | None = Field(
        None,
        description="Pagination cursor from the previous response's next_cursor field. Omit for the first page.",
    )
    order: Literal["asc", "desc"] | None = Field(
        None,
        description='Sort direction by creation time. "desc" (default) returns newest first, "asc" returns oldest first.',
    )
    scope: Literal["all", "agent_subtask", "project", "standard"] | None = Field(
        None, description="Filter by task type."
    )
    agent_id: str | None = Field(
        None,
        description='Filter tasks by agent. Required when scope="agent_subtask". Supports the shortcut `agent-default` for the IM agent. Use [agent.list](https://open.manus.ai/docs/v2/agent.list) to get available agent IDs.',
    )
    project_id: str | None = Field(
        None,
        description='Filter tasks by project. Required when scope="project". Use [project.list](https://open.manus.ai/docs/v2/project.list) to get available project IDs.',
    )
    oauth_client_id: str | None = Field(
        None,
        description="Return only tasks created by this Open App. Mutually exclusive with `api_key_id`; passing both returns `invalid_argument`. Unknown IDs return an empty list.",
    )
    api_key_id: str | None = Field(
        None,
        description="Return only tasks created by this API key. Mutually exclusive with `oauth_client_id`; passing both returns `invalid_argument`. Unknown IDs return an empty list.",
    )
    include_deleted: bool | None = Field(
        None, description="Include deleted tasks in the results. Default: `false`."
    )


class ManusStopTaskConfig(ManusInput):
    """Stops a running task. The task status will change to `stopped`. A stopped task can still be resumed with [task.sendMessage](https://open.manus.ai/docs/v2/task.sendMessage)."""

    operation: Literal["stop_task"] = Field(
        "stop_task", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ...,
        description="The unique identifier of the running task to stop. Supports the shortcut `agent-default-main_task` for the IM agent's main task.",
        min_length=1,
    )


class ManusDeleteTaskConfig(ManusInput):
    """Deletes a task permanently. If the task is still running, use [task.stop](https://open.manus.ai/docs/v2/task.stop) first."""

    operation: Literal["delete_task"] = Field(
        "delete_task", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ...,
        description="The unique identifier of the task to delete. Agent-related tasks cannot be deleted.",
        min_length=1,
    )


class ManusUpdateTaskConfig(ManusInput):
    """Updates a task's metadata (title, sharing, visibility). Use [task.detail](https://open.manus.ai/docs/v2/task.detail) to see the current values before updating."""

    operation: Literal["update_task"] = Field(
        "update_task", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ...,
        description="The unique identifier of the task to update. Supports the shortcut `agent-default-main_task` for the IM agent's main task.",
        min_length=1,
    )
    title: str | None = Field(
        None, description="New title for the task. Replaces the auto-generated title."
    )
    share_visibility: Literal["private", "team", "public"] | None = Field(
        None,
        description='Controls who can view the task. "private" — only the task creator can view. "team" — all team members can view. "public" — anyone with the share_url can view.',
    )
    enable_visible_in_task_list: bool | None = Field(
        None,
        description="When true, the task appears in the Manus webapp task list. When false, hides the task from the list (still accessible via direct URL).",
    )


class ManusSendMessageConfig(ManusInput):
    """Sends a follow-up message to a task for multi-turn conversation. Use this after [task.create](https://open.manus.ai/docs/v2/task.create) to continue talking, or to answer `messageAskUser` / `cascadeAskUser` questions with ordinary message.content. For supported action confirmations, review confirm_input_schema and the target tool event, then use [task.confirmAction](https://open.manus.ai/docs/v2/task.confirmAction). Do not automatically confirm unrecognized waiting types."""

    operation: Literal["send_message"] = Field(
        "send_message", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ...,
        description="The unique identifier of the task to send the message to. Supports the shortcut `agent-default-main_task` for the IM agent's main task.",
        min_length=1,
    )
    message: ManusMessage = Field(
        ...,
        description="The follow-up message. Supports the same content formats as task.create (plain text or multi-part with files). A non-empty `message.connectors` replaces the task's connector selection; omitting it or passing an empty array keeps the task's current selection. To clear the selection, use the top-level `clear_connectors` field.",
    )
    agent_profile: AgentProfile | None = Field(
        None,
        description="Agent profile override for this turn and subsequent turns. Use the stable values `standard`, `lite`, or `max`, or a Max thinking level: `max-medium`, `max-high`, `max-extra`, or `max-ultra`. The thinking level also applies to subsequent turns; plain `max` keeps the level the task already uses; a task that has never selected a level uses the default, currently equivalent to `max-extra`. Versioned aliases such as `1.6-lite`, `2.0-max`, `2.0-max-ultra`, and the legacy `manus-1.6-lite` form are also accepted; the version segment is ignored because model versions are not selected independently. A version without a suffix, such as `1.6` or `manus-1.6`, means `standard`. Omit the field (or pass an empty string) to keep the task's current profile and thinking level; unlike [task.create](https://open.manus.ai/docs/v2/task.create), this endpoint does not default to `standard`. Free personal accounts are downgraded to `lite` when an override is provided.",
    )
    structured_output_schema: dict[str, Any] | None = Field(
        None,
        description="JSON Schema for structured output extraction, armed for the next time this task finishes (`stop_reason: finish`).",
    )
    clear_connectors: bool | None = Field(
        None,
        description="Clears the task's connector selection for this and subsequent turns. Cannot be combined with a non-empty `message.connectors`. Other task features may still provide tools.",
    )


class ManusListMessagesConfig(ManusInput):
    """Lists event messages for a task with cursor-based pagination. Use this to poll for progress after [task.create](https://open.manus.ai/docs/v2/task.create) or [task.sendMessage](https://open.manus.ai/docs/v2/task.sendMessage)."""

    operation: Literal["list_messages"] = Field(
        "list_messages", json_schema_extra={"ui:hidden": True}
    )
    task_id: str = Field(
        ...,
        description="The unique identifier of the task to list messages for. Supports the shortcut `agent-default-main_task` for the IM agent's main task.",
        min_length=1,
    )
    limit: int | None = Field(
        None,
        description="Number of messages to return per page. Default: 50, Range: 1-200.",
        ge=1,
        le=200,
    )
    cursor: str | None = Field(
        None,
        description="Pagination cursor from the previous response's next_cursor field. Omit for the first page.",
    )
    start_event_id: str | None = Field(
        None,
        description="Start at this event, inclusive. Use a value from `messages[].id`. Cannot be combined with `cursor`. The response may still include `next_cursor` for following pages. If the ID appears only in `verbose=true` responses, use `verbose=true` or the event is not found.",
    )
    order: Literal["asc", "desc"] | None = Field(
        None, description="Sort direction by timestamp."
    )
    verbose: bool | None = Field(None, description="Include detailed events.")
    slides_format: Literal["html", "pptx"] | None = Field(
        None, description="Format of slides attachments in the response."
    )
    markdown_format: Literal["markdown", "pdf", "docx"] | None = Field(
        None,
        description="Format of Markdown attachments in `assistant_message.attachments`. An attachment is treated as Markdown when its filename ends in `.md` or `.markdown`, or its `content_type` contains `markdown`.",
    )
    include_cover: bool | None = Field(
        None, description="Include cover images for `assistant_message.attachments`."
    )


class ManusCreateProjectConfig(ManusInput):
    """Creates a new project. Projects let you group related tasks and apply shared instructions. Pass the returned ID as `project_id` in [task.create](https://open.manus.ai/docs/v2/task.create) to create tasks within this project."""

    operation: Literal["create_project"] = Field(
        "create_project", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., description="Display name for the project.", min_length=1)
    instruction: str | None = Field(
        None,
        description='Default instruction that will be automatically prepended to all tasks created within this project. Use this to enforce consistent behavior across related tasks (e.g., "Always respond in formal English" or "Focus on financial analysis").',
    )


class ManusListProjectsConfig(ManusInput):
    """Lists all projects. Use the returned IDs as `project_id` in [task.create](https://open.manus.ai/docs/v2/task.create) or [task.list](https://open.manus.ai/docs/v2/task.list)."""

    operation: Literal["list_projects"] = Field(
        "list_projects", json_schema_extra={"ui:hidden": True}
    )


class ManusGetProjectConfig(ManusInput):
    """Retrieves a project's full configuration: name, instruction, default connectors, and default skills. [project.list](https://open.manus.ai/docs/v2/project.list) returns only each project's ID, name, and creation time; call this endpoint before [project.update](https://open.manus.ai/docs/v2/project.update) to read the current values."""

    operation: Literal["get_project"] = Field(
        "get_project", json_schema_extra={"ui:hidden": True}
    )
    project_id: str = Field(
        ...,
        description="The unique identifier of the project to retrieve. Use [project.list](https://open.manus.ai/docs/v2/project.list) to get project IDs.",
        min_length=1,
    )


class ManusUpdateProjectConfig(ManusInput):
    """Updates a project's name, instruction, default connectors, or default skills. Omitted fields are unchanged; a request with no updatable field returns `400 invalid_argument`. `connector_ids` and `skill_ids` replace the entire list. Returns the full updated configuration in the same shape as [project.detail](https://open.manus.ai/docs/v2/project.detail)."""

    operation: Literal["update_project"] = Field(
        "update_project", json_schema_extra={"ui:hidden": True}
    )
    project_id: str = Field(
        ...,
        description="The unique identifier of the project to update. Use [project.list](https://open.manus.ai/docs/v2/project.list) to get project IDs.",
        min_length=1,
    )
    name: str | None = Field(
        None,
        description="New display name, 1–255 characters. Cannot be empty or whitespace only.",
        min_length=1,
        max_length=255,
    )
    clear_instruction: bool = Field(
        False,
        description="Clear the project's default instruction. Takes precedence over Instruction.",
    )
    instruction: str | None = Field(
        None,
        description="New default instruction applied to tasks in this project, up to 65,535 UTF-8 bytes. Use Clear instruction to remove it; leave this blank to keep it unchanged.",
    )
    connector_ids: list[str] | None = Field(
        None,
        description="Replaces the project's default connectors with this list. Pass `[]` to remove all default connectors; omit the field to keep them unchanged. Accepts up to 500 connector IDs from [connector.list](https://open.manus.ai/docs/v2/connector.list); duplicates are ignored. Each connector must be installed and authorized in the user's account. A Standard OAuth client can set only connectors the user granted to the app, and the My Browser connector also requires the `use_my_browsers` scope.",
        max_length=500,
    )
    skill_ids: list[str] | None = Field(
        None,
        description="Replaces the project's default skills with this list. Pass `[]` to remove all default skills; omit the field to keep them unchanged. Accepts up to 50 skill IDs from [skill.list](https://open.manus.ai/docs/v2/skill.list); duplicates are ignored. Each skill must be an official skill, a Skill Hub skill, a skill of the user's team, or a skill of this project; other skills, including personal and Open App skills, return `404 not_found`. Project members' individual skill preferences are kept.",
        max_length=50,
    )


class ManusListArtifactsConfig(ManusInput):
    """Lists generated task artifacts from the authenticated user's Manus Library, newest first. Temporary input files from file.upload are not included."""

    operation: Literal["list_artifacts"] = Field(
        "list_artifacts", json_schema_extra={"ui:hidden": True}
    )
    limit: int | None = Field(
        None,
        description="Maximum artifacts per page. Default 20, maximum 100. A page can be short or empty while `has_more` is true.",
        ge=1,
        le=100,
    )
    cursor: str | None = Field(
        None,
        description="Opaque `next_cursor` from the previous page. Omit for the first page.",
    )
    name: str | None = Field(
        None,
        description="Search the artifact display name. Results stay ordered by creation time.",
    )
    type: Literal[
        "all",
        "website",
        "mobile_app",
        "game",
        "documents",
        "slides",
        "spreadsheets",
        "images",
        "videos",
        "audio",
        "others",
    ] | None = Field(
        None,
        description="Filter by Library category. Default `all`. The ten specific categories are mutually exclusive.",
    )
    favorite: bool | None = Field(
        None,
        description="When `true`, return only favorited artifacts. Omitted or `false` applies no favorite filter.",
    )
    oauth_client_id: str | None = Field(
        None,
        description="Return only artifacts from tasks created by this Open App. Mutually exclusive with `api_key_id`; passing both returns `400 invalid_argument`.",
    )
    api_key_id: str | None = Field(
        None,
        description="Return only artifacts from tasks created by this API key. Mutually exclusive with `oauth_client_id`; passing both returns `400 invalid_argument`.",
    )


class ManusGetFileConfig(ManusInput):
    """Retrieves a file's details including upload status, size, and expiration time. For an uploaded, unexpired file, also returns a temporary GET download URL and its expiration time at the top level of the response. Use this to download an uploaded attachment for validation before creating a task. Check that `file.status` is `uploaded` before using the file in [task.create](https://open.manus.ai/docs/v2/task.create). Files expire 48 hours after upload."""

    operation: Literal["get_file"] = Field(
        "get_file", json_schema_extra={"ui:hidden": True}
    )
    file_id: str = Field(
        ..., description="The unique identifier of the file to retrieve.", min_length=1
    )


class ManusDeleteFileConfig(ManusInput):
    """Deletes a file. Files are automatically deleted 48 hours after upload, so manual deletion is only needed for early cleanup."""

    operation: Literal["delete_file"] = Field(
        "delete_file", json_schema_extra={"ui:hidden": True}
    )
    file_id: str = Field(
        ..., description="The unique identifier of the file to delete.", min_length=1
    )


class ManusCreateWebhookConfig(ManusInput):
    """Creates a webhook for receiving task event notifications. Use [webhook.publicKey](https://open.manus.ai/docs/v2/webhook.publicKey) to get the key for verifying signatures."""

    operation: Literal["create_webhook"] = Field(
        "create_webhook", json_schema_extra={"ui:hidden": True}
    )
    url: str = Field(
        ...,
        description="The HTTPS endpoint URL that will receive POST webhook notifications. Must be publicly accessible and return a 2xx status code.",
        min_length=1,
    )


class ManusListWebhooksConfig(ManusInput):
    """Lists all webhooks in your account. Use the returned IDs with [webhook.delete](https://open.manus.ai/docs/v2/webhook.delete) to remove a webhook."""

    operation: Literal["list_webhooks"] = Field(
        "list_webhooks", json_schema_extra={"ui:hidden": True}
    )


class ManusDeleteWebhookConfig(ManusInput):
    """Deletes a webhook. The endpoint will stop receiving notifications immediately. Use [webhook.list](https://open.manus.ai/docs/v2/webhook.list) to find the webhook ID."""

    operation: Literal["delete_webhook"] = Field(
        "delete_webhook", json_schema_extra={"ui:hidden": True}
    )
    webhook_id: str = Field(
        ..., description="The unique identifier of the webhook to delete.", min_length=1
    )


class ManusGetAvailableCreditsConfig(ManusInput):
    """Returns the credit balance, subscription period, and refresh information for the authenticated caller. For a team sub-account, the team's shared pool balance is returned; for a personal account, the personal balance is returned. Standard OAuth clients cannot access this endpoint; trusted clients can."""

    operation: Literal["get_available_credits"] = Field(
        "get_available_credits", json_schema_extra={"ui:hidden": True}
    )


class ManusListConnectorsConfig(ManusInput):
    """Lists connectors installed in the current user's account. Use the returned IDs in the `connectors` array of [task.create](https://open.manus.ai/docs/v2/task.create) or [task.sendMessage](https://open.manus.ai/docs/v2/task.sendMessage)."""

    operation: Literal["list_connectors"] = Field(
        "list_connectors", json_schema_extra={"ui:hidden": True}
    )


class ManusListSkillsConfig(ManusInput):
    """Lists installed skills available for task selection."""

    operation: Literal["list_skills"] = Field(
        "list_skills", json_schema_extra={"ui:hidden": True}
    )
    project_id: str | None = Field(
        None,
        description="Only API Keys and trusted OAuth clients can pass `project_id`; when provided, the response also includes project skills. Standard OAuth clients that pass this parameter receive InvalidArgument (HTTP 400). Use [project.list](https://open.manus.ai/docs/v2/project.list) to get available project IDs.",
    )


class ManusGetSkillConfig(ManusInput):
    """Retrieves one skill's details and a temporary download URL for its current archive."""

    operation: Literal["get_skill"] = Field(
        "get_skill", json_schema_extra={"ui:hidden": True}
    )
    skill_id: str = Field(
        ...,
        description="Use [skill.list](https://open.manus.ai/docs/v2/skill.list) to get skill IDs.",
        min_length=1,
    )


class ManusOnTaskEventConfig(WebhookTriggerConfigBase):
    """Start a workflow or agent from Manus's documented task lifecycle events."""

    operation: Literal["on_task_event"] = Field(
        "on_task_event", title="On Task Event",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True,
                           "x-category": "Triggers", "x-display-name": "On Task Event"},
    )
    event_type: Literal["all", "task_created", "task_stopped", "task_deleted"] = Field(
        "task_stopped", title="Event", description="Task lifecycle event to receive, or all events.")
    stop_reason: Literal["all", "finish", "ask"] = Field(
        "all", title="Stop Reason", description="For task_stopped: completed (finish), needs input (ask), or both.")
    webhook_url: str | None = Field(
        None, title="Webhook URL", description="Registered with Manus automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True},
    )


ManusOperation = Annotated[
    Union[
        ManusOnTaskEventConfig,
        ManusGetCurrentUserConfig,
        ManusCreateTaskConfig,
        ManusGetTaskConfig,
        ManusListTasksConfig,
        ManusStopTaskConfig,
        ManusDeleteTaskConfig,
        ManusUpdateTaskConfig,
        ManusSendMessageConfig,
        ManusListMessagesConfig,
        ManusCreateProjectConfig,
        ManusListProjectsConfig,
        ManusGetProjectConfig,
        ManusUpdateProjectConfig,
        ManusListArtifactsConfig,
        ManusGetFileConfig,
        ManusDeleteFileConfig,
        ManusCreateWebhookConfig,
        ManusListWebhooksConfig,
        ManusDeleteWebhookConfig,
        ManusGetAvailableCreditsConfig,
        ManusListConnectorsConfig,
        ManusListSkillsConfig,
        ManusGetSkillConfig,
    ],
    Field(discriminator="operation"),
]


class ManusConfig(NodeConfig[ManusOperation, ManusAPIKeyCredential]):
    pass


ROUTES = {
    "get_current_user": ("GET", "user.me"),
    "create_task": ("POST", "task.create"),
    "get_task": ("GET", "task.detail"),
    "list_tasks": ("GET", "task.list"),
    "stop_task": ("POST", "task.stop"),
    "delete_task": ("POST", "task.delete"),
    "update_task": ("POST", "task.update"),
    "send_message": ("POST", "task.sendMessage"),
    "list_messages": ("GET", "task.listMessages"),
    "create_project": ("POST", "project.create"),
    "list_projects": ("GET", "project.list"),
    "get_project": ("GET", "project.detail"),
    "update_project": ("POST", "project.update"),
    "list_artifacts": ("GET", "artifact.list"),
    "get_file": ("GET", "file.detail"),
    "delete_file": ("POST", "file.delete"),
    "create_webhook": ("POST", "webhook.create"),
    "list_webhooks": ("GET", "webhook.list"),
    "delete_webhook": ("POST", "webhook.delete"),
    "get_available_credits": ("GET", "usage.availableCredits"),
    "list_connectors": ("GET", "connector.list"),
    "list_skills": ("GET", "skill.list"),
    "get_skill": ("GET", "skill.detail"),
}


class ManusNode(ExternalWebhookTriggerMixin, WorkflowNode):
    webhook_replace_stale_endpoint = True
    integration_type = "automation-manus"
    connection_evidence = ConnectionEvidence(
        identity_operation="get_current_user",
        noun="Manus account",
        identity_keys=("name", "email", "user_id"),
    )

    @classmethod
    def get_config_model(cls):
        return ManusConfig

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        key = credential.get("api_key")
        if not key:
            raise ValueError("Connect a Manus API key")
        # Cache the provider public key with this registration, before creating an endpoint.
        public = await cls._request("GET", "webhook.publicKey", {}, key)
        if not public.get("public_key") or public.get("algorithm") != "RSA-SHA256":
            raise ValueError("Manus did not return its RSA-SHA256 webhook public key")
        result = await cls._request("POST", "webhook.create", {"url": webhook_url}, key)
        webhook_id = (result.get("webhook") or {}).get("id")
        if not webhook_id:
            raise ValueError("Manus did not return a webhook ID")
        # The row's signing material is authoritative even before the config autosave.
        return {"external_webhook_id": str(webhook_id), "signing_secret": json.dumps({
            "public_key": public["public_key"], "url": webhook_url})}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = (config or {}).get("external_webhook_id")
        if not webhook_id:
            return
        if not credential or not credential.get("api_key"):
            raise ValueError("Connect a Manus API key to remove its webhook")
        await cls._request("POST", "webhook.delete", {"webhook_id": str(webhook_id)}, credential["api_key"])

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        """RSA PKCS#1 v1.5 / SHA-256, exactly as Manus's webhook security guide."""
        try:
            lower = {k.lower(): v for k, v in headers.items()}
            timestamp = lower.get("x-webhook-timestamp", "")
            if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
                return False
            material = json.loads((config or {}).get("signing_secret") or "{}")
            key = serialization.load_pem_public_key(material["public_key"].encode())
            if not isinstance(key, rsa.RSAPublicKey):
                return False
            content = f"{timestamp}.{material['url']}.{hashlib.sha256(body).hexdigest()}".encode()
            key.verify(base64.b64decode(lower.get("x-webhook-signature", ""), validate=True),
                       content, padding.PKCS1v15(), hashes.SHA256())
            return True
        except (ValueError, KeyError, TypeError, AttributeError, InvalidSignature):
            return False

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        kind = payload.get("event_type")
        if kind not in ("task_created", "task_stopped", "task_deleted"):
            return False
        selected = (config or {}).get("event_type", "task_stopped")
        if selected != "all" and kind != selected:
            return False
        reason = (config or {}).get("stop_reason", "all")
        return kind != "task_stopped" or reason == "all" or (payload.get("task_detail") or {}).get("stop_reason") == reason

    @classmethod
    def resolve_agent_event(cls, output):
        kind = output.get("event_type")
        detail = output.get("task_detail") or {}
        task_id = detail.get("task_id")
        if kind not in ("task_created", "task_stopped", "task_deleted") or not task_id:
            return None
        title = detail.get("task_title") or str(task_id)
        action = {"task_created": "created a task", "task_deleted": "deleted a task",
                  "task_stopped": "stopped a task"}[kind]
        lines = [f"Manus {action}: {title}", f"Task ID: {task_id}",
                 f"Event ID: {output.get('event_id')}", f"URL: {detail.get('task_url')}"]
        if kind == "task_stopped":
            lines += [f"Stop reason: {detail.get('stop_reason')}", str(detail.get("message") or "")]
            for attachment in detail.get("attachments") or []:
                lines.append(f"File: {attachment.get('file_name')} ({attachment.get('size_bytes')} bytes): {attachment.get('url')}")
            if detail.get("stop_reason") == "ask":
                question = detail.get("question_expectation") or {}
                if question:
                    lines.append("Question: " + json.dumps(question, ensure_ascii=False))
                lines.append(f"Reply with send_message using task_id={task_id} and message.content; do not auto-confirm actions.")
        return {"text": "\n".join(lines), "conversation_key": str(task_id), "title": title}

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Manus API key")
        config = self.config.config
        if isinstance(config, ManusOnTaskEventConfig):
            return inputs
        method, route = ROUTES[config.operation]
        payload = config.model_dump(
            mode="json", exclude={"operation", "clear_instruction"}, exclude_none=True
        )
        if isinstance(config, ManusUpdateProjectConfig) and config.clear_instruction:
            payload["instruction"] = ""
        result = await self._request(method, route, payload, self.config.credentials.api_key)
        if config.operation == "get_current_user" and not result.get("user_id"):
            raise ValueError("Manus did not return the account ID")
        return result

    @classmethod
    async def _request(cls, method, route, payload, key):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(
                method,
                BASE_URL + route,
                headers={"x-manus-api-key": key, "Accept": "application/json"},
                **({"params": payload} if method == "GET" else {"json": payload}),
            )
        if response.is_redirect:
            raise ValueError("Manus redirected the API request")
        if response.is_error:
            detail = response.text.replace(key, "[redacted]")
            raise httpx.HTTPStatusError(
                f"Manus API error {response.status_code}: {detail}",
                request=response.request,
                response=response,
            )
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Expected a Manus JSON object")
        if result.get("ok") is False or result.get("error"):
            detail = str(result.get("error", "Request failed")).replace(
                key, "[redacted]"
            )
            raise ValueError("Manus API error: " + detail)
        if result.get("ok") is not True:
            raise ValueError("Manus did not acknowledge the request")
        return result

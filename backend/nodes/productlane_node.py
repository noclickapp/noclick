"""Productlane API v2 (2.0.0): one documented request per operation.

Contract: https://productlane.com/api/v2/openapi.json
Authentication: https://productlane.com/docs/authentication
Lists return one cursor page; pass data.page.cursor into the next execution.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.productlane import PRODUCTLANE_SCOPES
from utils.ssrf import guarded_async_client

PathId = Annotated[str, StringConstraints(min_length=1, max_length=512, pattern=r"^[^/\\?#\s]+$")]


def _picker(field):
    return {"x-dynamic-options": {"field_name": field, "searchable": False,
        "allow_custom": True, "custom_placeholder": "Paste Productlane ID"}}


class ProductlaneApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Productlane API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://productlane.com/docs/authentication",
            "x-credential-instructions": "In Productlane, open Settings → Integrations → API and create a v2 API key. Choose the read/write scopes for the resources your workflow uses: threads, contacts, companies, changelogs, tags, projects and issues; sending messages needs messages:write and internal comments need comments:write. Paste the secret without Bearer. The key's workspace is verified with GET /me."})
    credential_type: Literal["productlane_api_key"] = Field("productlane_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or Bearer")
        if value.startswith("pl_v1_"):
            raise ValueError("Create a v2 API key; v1 keys cannot access this API")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def canvas_bookkeeping(cls, value):
        if not isinstance(value, dict):
            return value
        labels = {"thread_id__label", "contact_id__label", "company_id__label", "changelog_id__label", "credentialIds"}
        return {key: item for key, item in value.items() if key not in labels}

    @field_validator("*", mode="after")
    @classmethod
    def valid_path(cls, value, info):
        if info.field_name in {"thread_id", "contact_id", "company_id", "changelog_id"} and value in {".", ".."}:
            raise ValueError("Use a Productlane resource ID")
        return value

    @model_validator(mode="after")
    def coherent_write(self):
        op = self.operation
        if op == "create_thread" and not (self.contact_email or self.contact_external_id):
            raise ValueError("Provide a contact email or external ID")
        if op in {"create_contact", "update_contact"}:
            if sum(getattr(self, key) is not None for key in ("company_id", "company_name", "company_external_id")) > 1:
                raise ValueError("Choose only one company reference")
        if op == "update_thread" and self.status == "snoozed" and not self.snoozed_until:
            raise ValueError("Snoozing requires snoozed_until")
        if op.startswith("update_"):
            _, _, _, body_names, nullable, _ = ROUTES[op]
            if not any(getattr(self, name) is not None or (name in self.model_fields_set and name in nullable) for name in body_names):
                raise ValueError("Provide at least one field to update")
        return self


class GetMeConfig(_Input):
    """Get authenticated identity."""
    operation: Literal['get_me'] = Field('get_me', json_schema_extra={"ui:hidden": True})


class ListThreadsConfig(_Input):
    """List threads."""
    operation: Literal['list_threads'] = Field('list_threads', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')
    status: Literal['open', 'snoozed', 'done'] | None = Field(None, title='Status')
    tab: Literal['open', 'new', 'needs-response', 'my', 'snoozed', 'done'] | None = Field(None, title='Tab', description='Inbox tab. `my` and `needs-response` require an API key with an associated user.')
    assignee_id: str | None = Field(None, title='Assignee Id')
    contact_id: str | None = Field(None, title='Contact Id')
    company_id: str | None = Field(None, title='Company Id')
    tag_id: str | None = Field(None, title='Tag Id', description='Comma-separated tag ids; matches threads with at least one.')
    pain_level: Literal['UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'URGENT'] | None = Field(None, title='Pain Level')
    origin: Literal['in_app', 'portal', 'support_portal', 'email', 'slack', 'slack_connect', 'intercom', 'intercom_attachment', 'zendesk', 'zendesk_attachment', 'front_attachment', 'zapier', 'hubspot', 'plain', 'api', 'live_chat', 'ai_chat', 'calendar', 'widget', 'teams', 'linear', 'upvote', 'custom'] | None = Field(None, title='Origin', description='Portal and roadmap upvotes arrive as `upvote` threads; pair it with `project_id` or `issue_id` to export the upvotes for one item.')
    issue_id: str | None = Field(None, title='Issue Id', description='Matches customer needs and portal upvotes on the issue.')
    project_id: str | None = Field(None, title='Project Id', description='Matches customer needs and portal upvotes on the project.')
    external_id: str | None = Field(None, title='External Id', description="Matches one of the thread's own external_ids. A bare id also matches a namespaced one with the same tail.")
    number: int | None = Field(None, title='Number', ge=0, description='Ticket number, as shown to customers without the `#`.')
    created_after: AwareDatetime | None = Field(None, title='Created After')
    created_before: AwareDatetime | None = Field(None, title='Created Before')
    updated_after: AwareDatetime | None = Field(None, title='Updated After')
    updated_before: AwareDatetime | None = Field(None, title='Updated Before')


class GetThreadConfig(_Input):
    """Get thread."""
    operation: Literal['get_thread'] = Field('get_thread', json_schema_extra={"ui:hidden": True})
    thread_id: PathId = Field(..., title='Thread Id', json_schema_extra=_picker('thread_id'))
    expand: str | None = Field(None, title='Expand', description='Comma-separated list of related resources to inline on the response. Allowed values: `messages` (inlines the conversation), `comments` (inlines internal comments). Pass either one alone or both separated by a comma, e.g. `messages,comments`. Unknown values are ignored.')


class CreateThreadConfig(_Input):
    """Create thread."""
    operation: Literal['create_thread'] = Field('create_thread', json_schema_extra={"ui:hidden": True})
    text: str = Field(..., title='Text', min_length=1, description='Thread body (HTML).')
    title: str | None = Field(None, title='Title', max_length=512)
    pain_level: Literal['UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'URGENT'] = Field(..., title='Pain Level')
    contact_email: EmailStr | None = Field(None, title='Contact Email', description='Email of the contact. The contact is upserted by email within the workspace. Send this or `contact_external_id`.')
    contact_external_id: str | None = Field(None, title='Contact External Id', min_length=1, max_length=128, description='Your id for a contact without an email, such as `whatsapp:+61400111222`. The contact is upserted by it and never receives email. Send this or `contact_email`.')
    contact_name: str | None = Field(None, title='Contact Name', description='Applied only when the contact is newly created.')
    status: Literal['open', 'snoozed', 'done'] | None = Field(None, title='Status', description='Initial status. Defaults to `open`.')
    assignee_id: str | None = Field(None, title='Assignee Id', description='Workspace user id (not a Linear user id).')
    company_id: str | None = Field(None, title='Company Id')
    project_id: str | None = Field(None, title='Project Id')
    issue_id: str | None = Field(None, title='Issue Id')
    external_ids: list[str] | None = Field(None, title='External Ids', description='Caller-owned identifiers. Replaces the full set.', json_schema_extra={"ui:widget": "list"})


class UpdateThreadConfig(_Input):
    """Update thread."""
    operation: Literal['update_thread'] = Field('update_thread', json_schema_extra={"ui:hidden": True})
    thread_id: PathId = Field(..., title='Thread Id', json_schema_extra=_picker('thread_id'))
    text: str | None = Field(None, title='Text', min_length=1)
    title: str | None = Field(None, title='Title', max_length=512)
    pain_level: Literal['UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'URGENT'] | None = Field(None, title='Pain Level')
    assignee_id: str | None = Field(None, title='Assignee Id', description='Workspace user id. Pass `null` to unassign.')
    contact_id: str | None = Field(None, title='Contact Id')
    company_id: str | None = Field(None, title='Company Id', description="Pass `null` to detach. Also propagates onto the thread's contact.")
    tag_ids: list[str] | None = Field(None, title='Tag Ids', description="Replaces the thread's full tag set.", json_schema_extra={"ui:widget": "list"})
    project_id: str | None = Field(None, title='Project Id')
    status: Literal['open', 'snoozed', 'done'] | None = Field(None, title='Status', description='When `snoozed`, `snoozed_until` is required.')
    snoozed_until: AwareDatetime | None = Field(None, title='Snoozed Until')
    closed_loop: bool | None = Field(None, title='Closed Loop', description='With `status=done`, marks the thread as fully closed.')
    external_ids: list[str] | None = Field(None, title='External Ids', description='Caller-owned identifiers. Replaces the full set.', json_schema_extra={"ui:widget": "list"})


class ListMessagesConfig(_Input):
    """List thread messages."""
    operation: Literal['list_messages'] = Field('list_messages', json_schema_extra={"ui:hidden": True})
    thread_id: PathId = Field(..., title='Thread Id', json_schema_extra=_picker('thread_id'))
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')
    order: Literal['asc', 'desc'] | None = Field(None, title='Order', description='Sort by `created_at`. `asc` returns oldest first (default, matches the conversation timeline); `desc` returns newest first.')
    type: Literal['email', 'slack', 'chat', 'live_chat', 'feedback', 'portal'] | None = Field(None, title='Type', description='Filter to a single channel. `email` for email replies, `slack` for Slack and Slack Connect, `chat` for Microsoft Teams (and any future chat platforms), `live_chat` for in-app live chat sessions, `portal` for replies a contact leaves on the portal, `feedback` for the synthesized initial message that the thread was opened with.')
    direction: Literal['inbound', 'outbound'] | None = Field(None, title='Direction', description='Filter by message direction. `inbound` is from the contact, `outbound` is from your workspace. For live chat, `inbound` maps to `USER` messages and `outbound` to both `AGENT` and `AI`.')
    user_id: str | None = Field(None, title='User Id', description='Workspace user id. Filters to outbound messages sent by this user. Live chat messages have no user attribution and are excluded when this is set.')
    q: str | None = Field(None, title='Q', min_length=1, description='Case-insensitive substring search across the message body. Searches email subject and text, slack/chat/live-chat text.')
    created_after: AwareDatetime | None = Field(None, title='Created After')
    created_before: AwareDatetime | None = Field(None, title='Created Before')
    updated_after: AwareDatetime | None = Field(None, title='Updated After')
    updated_before: AwareDatetime | None = Field(None, title='Updated Before')


class SendMessageConfig(_Input):
    """Send a message."""
    operation: Literal['send_message'] = Field('send_message', json_schema_extra={"ui:hidden": True})
    thread_id: PathId = Field(..., title='Thread Id', json_schema_extra=_picker('thread_id'))
    content: str = Field(..., title='Content', min_length=1, description='Message body (HTML).')
    channel_id: str | None = Field(None, title='Channel Id', description='Slack channel id. Required for Slack threads unless one is stored on the thread.')
    author: Literal['user', 'contact'] | None = Field(None, title='Author', description="`user` (default) sends the message as your workspace user. On a `custom` thread nothing is delivered: `message.sent` carries the reply to your integration. `contact` records the message as inbound from the thread's contact. On email and live chat threads that triggers nothing; on a `custom` thread it works like an inbound email: the thread reopens, notifications fire and the AI agent may answer. Not supported on Slack and Teams threads.")
    external_message_id: str | None = Field(None, title='External Message Id', min_length=1, max_length=255, description='Custom channel threads only: your id for an inbound message. A repeat with the same id returns the stored message and creates nothing.')


class ListCommentsConfig(_Input):
    """List internal comments."""
    operation: Literal['list_comments'] = Field('list_comments', json_schema_extra={"ui:hidden": True})
    thread_id: PathId = Field(..., title='Thread Id', json_schema_extra=_picker('thread_id'))
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')


class CreateCommentConfig(_Input):
    """Post an internal comment."""
    operation: Literal['create_comment'] = Field('create_comment', json_schema_extra={"ui:hidden": True})
    thread_id: PathId = Field(..., title='Thread Id', json_schema_extra=_picker('thread_id'))
    content: str = Field(..., title='Content', min_length=1)


class ListContactsConfig(_Input):
    """List contacts."""
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')
    email: str | None = Field(None, title='Email', description='Case-insensitive substring match.')
    name_contains: str | None = Field(None, title='Name Contains', min_length=1, max_length=255)
    company_id: str | None = Field(None, title='Company Id')
    external_id: str | None = Field(None, title='External Id', description="Matches one of the contact's own external_ids. A bare id also matches a namespaced one with the same tail.")
    created_after: AwareDatetime | None = Field(None, title='Created After')
    created_before: AwareDatetime | None = Field(None, title='Created Before')
    updated_after: AwareDatetime | None = Field(None, title='Updated After')
    updated_before: AwareDatetime | None = Field(None, title='Updated Before')


class GetContactConfig(_Input):
    """Get contact."""
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    contact_id: PathId = Field(..., title='Contact Id', json_schema_extra=_picker('contact_id'))


class CreateContactConfig(_Input):
    """Create contact."""
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={"ui:hidden": True})
    email: EmailStr = Field(..., title='Email', max_length=254)
    name: str | None = Field(None, title='Name', min_length=1, max_length=255)
    is_subscribed: bool | None = Field(None, title='Is Subscribed', description='Receives changelog and per-project/issue update emails. Defaults to `true`.')
    external_ids: list[str] | None = Field(None, title='External Ids', description='Caller-owned identifiers. Replaces the full set.', json_schema_extra={"ui:widget": "list"})
    company_id: str | None = Field(None, title='Company Id', min_length=1, max_length=255, description='Productlane company id. Mutually exclusive with `company_name` and `company_external_id`.')
    company_name: str | None = Field(None, title='Company Name', min_length=1, max_length=255, description='Resolves a company by exact name. Errors if multiple companies share the name.')
    company_external_id: str | None = Field(None, title='Company External Id', min_length=1, max_length=255, description='Resolves a company by an entry in its `external_ids` array.')


class UpdateContactConfig(_Input):
    """Update contact."""
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True})
    contact_id: PathId = Field(..., title='Contact Id', json_schema_extra=_picker('contact_id'))
    name: str | None = Field(None, title='Name', min_length=1, max_length=255)
    email: EmailStr | None = Field(None, title='Email', max_length=254)
    is_subscribed: bool | None = Field(None, title='Is Subscribed', description='Receives changelog and per-project/issue update emails. Same flag flipped by the email-footer unsubscribe link.')
    external_ids: list[str] | None = Field(None, title='External Ids', description='Caller-owned identifiers. Replaces the full set.', json_schema_extra={"ui:widget": "list"})
    company_id: str | None = Field(None, title='Company Id', min_length=1, max_length=255, description='Productlane company id. Mutually exclusive with `company_name` and `company_external_id`.')
    company_name: str | None = Field(None, title='Company Name', min_length=1, max_length=255, description='Resolves a company by exact name. Errors if multiple companies share the name.')
    company_external_id: str | None = Field(None, title='Company External Id', min_length=1, max_length=255, description='Resolves a company by an entry in its `external_ids` array.')


class ListCompaniesConfig(_Input):
    """List companies."""
    operation: Literal['list_companies'] = Field('list_companies', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')
    external_id: str | None = Field(None, title='External Id', description="Matches an entry in the company's `external_ids` array.")
    domain: str | None = Field(None, title='Domain', description="Matches an entry in the company's `domains` array.")
    name_contains: str | None = Field(None, title='Name Contains', min_length=1, max_length=255)
    status_id: str | None = Field(None, title='Status Id')
    tier_id: str | None = Field(None, title='Tier Id')
    size_gte: int | None = Field(None, title='Size Gte', ge=0)
    size_lte: int | None = Field(None, title='Size Lte', ge=0)
    revenue_gte: int | None = Field(None, title='Revenue Gte', ge=0)
    revenue_lte: int | None = Field(None, title='Revenue Lte', ge=0)
    created_after: AwareDatetime | None = Field(None, title='Created After')
    created_before: AwareDatetime | None = Field(None, title='Created Before')
    updated_after: AwareDatetime | None = Field(None, title='Updated After')
    updated_before: AwareDatetime | None = Field(None, title='Updated Before')


class GetCompanyConfig(_Input):
    """Get company."""
    operation: Literal['get_company'] = Field('get_company', json_schema_extra={"ui:hidden": True})
    company_id: PathId = Field(..., title='Companie Id', json_schema_extra=_picker('company_id'))


class CreateCompanyConfig(_Input):
    """Create company."""
    operation: Literal['create_company'] = Field('create_company', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name', min_length=1, max_length=255)
    domains: list[str] | None = Field(None, title='Domains', json_schema_extra={"ui:widget": "list"})
    size: int | None = Field(None, title='Size', ge=0)
    revenue: int | None = Field(None, title='Revenue', ge=0)
    external_ids: list[str] | None = Field(None, title='External Ids', description="Replaces the company's full external-id set. Use for cross-system identifiers (CRM ids, etc.).", json_schema_extra={"ui:widget": "list"})


class UpdateCompanyConfig(_Input):
    """Update company."""
    operation: Literal['update_company'] = Field('update_company', json_schema_extra={"ui:hidden": True})
    company_id: PathId = Field(..., title='Companie Id', json_schema_extra=_picker('company_id'))
    name: str | None = Field(None, title='Name', min_length=1, max_length=255)
    domains: list[str] | None = Field(None, title='Domains', description='Replaces the full domain set.', json_schema_extra={"ui:widget": "list"})
    size: int | None = Field(None, title='Size', ge=0)
    revenue: int | None = Field(None, title='Revenue', ge=0)
    external_ids: list[str] | None = Field(None, title='External Ids', description='Replaces the full external-id set.', json_schema_extra={"ui:widget": "list"})


class ListTagsConfig(_Input):
    """List tags."""
    operation: Literal['list_tags'] = Field('list_tags', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')
    name_contains: str | None = Field(None, title='Name Contains', min_length=1, max_length=255)
    tag_group_id: str | None = Field(None, title='Tag Group Id')
    created_after: AwareDatetime | None = Field(None, title='Created After')
    created_before: AwareDatetime | None = Field(None, title='Created Before')
    updated_after: AwareDatetime | None = Field(None, title='Updated After')
    updated_before: AwareDatetime | None = Field(None, title='Updated Before')


class ListProjectsConfig(_Input):
    """List projects."""
    operation: Literal['list_projects'] = Field('list_projects', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')
    state: Literal['backlog', 'planned', 'started', 'completed', 'canceled'] | None = Field(None, title='State', description='Lifecycle category. Distinct from `linear_status_id`, which selects a specific status within the category.')
    name_contains: str | None = Field(None, title='Name Contains', min_length=1, max_length=255)
    linear_team_id: str | None = Field(None, title='Linear Team Id', min_length=1, max_length=128, description='Linear team id. Matches projects pinned to that team.')
    portal_instance_id: str | None = Field(None, title='Portal Instance Id', description='Filter to a single portal by its id (from GET /portal/instances). Pass `__main__` for the Main (Root) portal. Omit to return items across all portals.')
    visibility: Literal['visible', 'hidden', 'pending'] | None = Field(None, title='Visibility', description='`visible` items show on their portals, `hidden` items were taken down, `pending` items were never reviewed.')
    sort: Literal['created_at', 'total_score'] | None = Field(None, title='Sort', description='`created_at` (newest first) or `total_score` (highest demand first). Both break ties by id.')
    created_after: AwareDatetime | None = Field(None, title='Created After')
    created_before: AwareDatetime | None = Field(None, title='Created Before')
    updated_after: AwareDatetime | None = Field(None, title='Updated After')
    updated_before: AwareDatetime | None = Field(None, title='Updated Before')


class ListIssuesConfig(_Input):
    """List issues."""
    operation: Literal['list_issues'] = Field('list_issues', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')
    project_id: str | None = Field(None, title='Project Id')
    status: str | None = Field(None, title='Status', min_length=1, max_length=64, description='Lifecycle state (`triage`, `backlog`, `unstarted`, `started`, `completed`, `canceled`). Forwarded raw from Linear so custom workflows resolve to their real names.')
    name_contains: str | None = Field(None, title='Name Contains', min_length=1, max_length=255)
    linear_team_id: str | None = Field(None, title='Linear Team Id', min_length=1, max_length=128)
    portal_instance_id: str | None = Field(None, title='Portal Instance Id', description='Filter to a single portal by its id (from GET /portal/instances). Pass `__main__` for the Main (Root) portal. Omit to return items across all portals.')
    visibility: Literal['visible', 'hidden', 'pending'] | None = Field(None, title='Visibility', description='`visible` items show on their portals, `hidden` items were taken down, `pending` items were never reviewed.')
    sort: Literal['created_at', 'total_score'] | None = Field(None, title='Sort', description='`created_at` (newest first) or `total_score` (highest demand first). Both break ties by id.')
    created_after: AwareDatetime | None = Field(None, title='Created After')
    created_before: AwareDatetime | None = Field(None, title='Created Before')
    updated_after: AwareDatetime | None = Field(None, title='Updated After')
    updated_before: AwareDatetime | None = Field(None, title='Updated Before')


class ListChangelogsConfig(_Input):
    """List changelogs."""
    operation: Literal['list_changelogs'] = Field('list_changelogs', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(50, title='Limit', ge=1, le=200)
    cursor: str | None = Field(None, title='Cursor')
    published: Literal['true', 'false', '1', '0', 'yes', 'no', 'on', 'off'] | None = Field(None, title='Published')
    archived: Literal['true', 'false', '1', '0', 'yes', 'no', 'on', 'off'] | None = Field(None, title='Archived')
    language: str | None = Field(None, title='Language', description='BCP-47 language code. Merges the matching translation onto each row. Requires the Pro plan and the language enabled in workspace settings.')
    title_contains: str | None = Field(None, title='Title Contains', min_length=1, max_length=255)
    tag_id: str | None = Field(None, title='Tag Id', description='Comma-separated tag ids. Matches changelogs with at least one.')
    portal_instance_id: str | None = Field(None, title='Portal Instance Id', description='Filter to a single portal by its id (from GET /portal/instances). Pass `__main__` for the Main (Root) portal. Omit to return items across all portals.')
    created_after: AwareDatetime | None = Field(None, title='Created After')
    created_before: AwareDatetime | None = Field(None, title='Created Before')
    updated_after: AwareDatetime | None = Field(None, title='Updated After')
    updated_before: AwareDatetime | None = Field(None, title='Updated Before')


class GetChangelogConfig(_Input):
    """Get changelog."""
    operation: Literal['get_changelog'] = Field('get_changelog', json_schema_extra={"ui:hidden": True})
    changelog_id: PathId = Field(..., title='Changelog Id', json_schema_extra=_picker('changelog_id'))
    language: str | None = Field(None, title='Language', description='BCP-47 language code. Returns the translation merged onto the response. Requires the Pro plan and the language enabled in workspace settings.')


class CreateChangelogConfig(_Input):
    """Create changelog."""
    operation: Literal['create_changelog'] = Field('create_changelog', json_schema_extra={"ui:hidden": True})
    title: str = Field(..., title='Title', min_length=1)
    content: str = Field(..., title='Content', min_length=1, description='Markdown body. House shape: one `##` per section, a `---` divider above each one that has content above it, `> ` for a callout, and backticks for a navigation path.')
    date: AwareDatetime | None = Field(None, title='Date')
    published: bool | None = Field(None, title='Published')
    tag_ids: list[str] | None = Field(None, title='Tag Ids', json_schema_extra={"ui:widget": "list"})
    portal_instance_ids: list[str] | None = Field(None, title='Portal Instance Ids', description='Every portal the entry is on. Use "__main__" for the Main portal. Takes precedence over portal_instance_id.', json_schema_extra={"ui:widget": "list"})


class UpdateChangelogConfig(_Input):
    """Update changelog."""
    operation: Literal['update_changelog'] = Field('update_changelog', json_schema_extra={"ui:hidden": True})
    changelog_id: PathId = Field(..., title='Changelog Id', json_schema_extra=_picker('changelog_id'))
    title: str | None = Field(None, title='Title', min_length=1)
    content: str | None = Field(None, title='Content', min_length=1, description='Markdown body. Replaces the whole body, so read the changelog first and edit what it returns. House shape: one `##` per section, a `---` divider above each one that has content above it, `> ` for a callout, and backticks for a navigation path.')
    date: AwareDatetime | None = Field(None, title='Date')
    published: bool | None = Field(None, title='Published')
    archived: bool | None = Field(None, title='Archived')
    tag_ids: list[str] | None = Field(None, title='Tag Ids', description='Replaces the full tag set.', json_schema_extra={"ui:widget": "list"})
    portal_instance_ids: list[str] | None = Field(None, title='Portal Instance Ids', description='Every portal the entry is on. Use "__main__" for the Main portal. Takes precedence over portal_instance_id.', json_schema_extra={"ui:widget": "list"})


ProductlaneConfig = Annotated[Union[
    GetMeConfig,
    ListThreadsConfig,
    GetThreadConfig,
    CreateThreadConfig,
    UpdateThreadConfig,
    ListMessagesConfig,
    SendMessageConfig,
    ListCommentsConfig,
    CreateCommentConfig,
    ListContactsConfig,
    GetContactConfig,
    CreateContactConfig,
    UpdateContactConfig,
    ListCompaniesConfig,
    GetCompanyConfig,
    CreateCompanyConfig,
    UpdateCompanyConfig,
    ListTagsConfig,
    ListProjectsConfig,
    ListIssuesConfig,
    ListChangelogsConfig,
    GetChangelogConfig,
    CreateChangelogConfig,
    UpdateChangelogConfig
], Field(discriminator="operation")]


class ProductlaneFullConfig(NodeConfig[ProductlaneConfig, ProductlaneApiKeyCredential]):
    pass


# Method, contract path, path bindings, body allowlist, nullable body fields, query fields.
ROUTES = {'get_me': ('GET', '/me', {}, [], [], []),
 'list_threads': ('GET',
                  '/threads',
                  {},
                  [],
                  [],
                  ['limit',
                   'cursor',
                   'status',
                   'tab',
                   'assignee_id',
                   'contact_id',
                   'company_id',
                   'tag_id',
                   'pain_level',
                   'origin',
                   'issue_id',
                   'project_id',
                   'external_id',
                   'number',
                   'created_after',
                   'created_before',
                   'updated_after',
                   'updated_before']),
 'get_thread': ('GET', '/threads/{id}', {'id': 'thread_id'}, [], [], ['expand']),
 'create_thread': ('POST',
                   '/threads',
                   {},
                   ['text',
                    'title',
                    'pain_level',
                    'contact_email',
                    'contact_external_id',
                    'contact_name',
                    'status',
                    'assignee_id',
                    'company_id',
                    'project_id',
                    'issue_id',
                    'external_ids'],
                   [],
                   []),
 'update_thread': ('PATCH',
                   '/threads/{id}',
                   {'id': 'thread_id'},
                   ['text',
                    'title',
                    'pain_level',
                    'assignee_id',
                    'contact_id',
                    'company_id',
                    'tag_ids',
                    'project_id',
                    'status',
                    'snoozed_until',
                    'closed_loop',
                    'external_ids'],
                   ['title', 'assignee_id', 'company_id', 'project_id'],
                   []),
 'list_messages': ('GET',
                   '/threads/{thread_id}/messages',
                   {'thread_id': 'thread_id'},
                   [],
                   [],
                   ['limit',
                    'cursor',
                    'order',
                    'type',
                    'direction',
                    'user_id',
                    'q',
                    'created_after',
                    'created_before',
                    'updated_after',
                    'updated_before']),
 'send_message': ('POST',
                  '/threads/{thread_id}/messages',
                  {'thread_id': 'thread_id'},
                  ['content', 'channel_id', 'author', 'external_message_id'],
                  [],
                  []),
 'list_comments': ('GET',
                   '/threads/{thread_id}/comments',
                   {'thread_id': 'thread_id'},
                   [],
                   [],
                   ['limit', 'cursor']),
 'create_comment': ('POST', '/threads/{thread_id}/comments', {'thread_id': 'thread_id'}, ['content'], [], []),
 'list_contacts': ('GET',
                   '/contacts',
                   {},
                   [],
                   [],
                   ['limit',
                    'cursor',
                    'email',
                    'name_contains',
                    'company_id',
                    'external_id',
                    'created_after',
                    'created_before',
                    'updated_after',
                    'updated_before']),
 'get_contact': ('GET', '/contacts/{id}', {'id': 'contact_id'}, [], [], []),
 'create_contact': ('POST',
                    '/contacts',
                    {},
                    ['email',
                     'name',
                     'is_subscribed',
                     'external_ids',
                     'company_id',
                     'company_name',
                     'company_external_id'],
                    [],
                    []),
 'update_contact': ('PATCH',
                    '/contacts/{id}',
                    {'id': 'contact_id'},
                    ['name',
                     'email',
                     'is_subscribed',
                     'external_ids',
                     'company_id',
                     'company_name',
                     'company_external_id'],
                    [],
                    []),
 'list_companies': ('GET',
                    '/companies',
                    {},
                    [],
                    [],
                    ['limit',
                     'cursor',
                     'external_id',
                     'domain',
                     'name_contains',
                     'status_id',
                     'tier_id',
                     'size_gte',
                     'size_lte',
                     'revenue_gte',
                     'revenue_lte',
                     'created_after',
                     'created_before',
                     'updated_after',
                     'updated_before']),
 'get_company': ('GET', '/companies/{id}', {'id': 'company_id'}, [], [], []),
 'create_company': ('POST', '/companies', {}, ['name', 'domains', 'size', 'revenue', 'external_ids'], [], []),
 'update_company': ('PATCH',
                    '/companies/{id}',
                    {'id': 'company_id'},
                    ['name', 'domains', 'size', 'revenue', 'external_ids'],
                    ['size', 'revenue'],
                    []),
 'list_tags': ('GET',
               '/tags',
               {},
               [],
               [],
               ['limit',
                'cursor',
                'name_contains',
                'tag_group_id',
                'created_after',
                'created_before',
                'updated_after',
                'updated_before']),
 'list_projects': ('GET',
                   '/projects',
                   {},
                   [],
                   [],
                   ['limit',
                    'cursor',
                    'state',
                    'name_contains',
                    'linear_team_id',
                    'portal_instance_id',
                    'visibility',
                    'sort',
                    'created_after',
                    'created_before',
                    'updated_after',
                    'updated_before']),
 'list_issues': ('GET',
                 '/issues',
                 {},
                 [],
                 [],
                 ['limit',
                  'cursor',
                  'project_id',
                  'status',
                  'name_contains',
                  'linear_team_id',
                  'portal_instance_id',
                  'visibility',
                  'sort',
                  'created_after',
                  'created_before',
                  'updated_after',
                  'updated_before']),
 'list_changelogs': ('GET',
                     '/changelogs',
                     {},
                     [],
                     [],
                     ['limit',
                      'cursor',
                      'published',
                      'archived',
                      'language',
                      'title_contains',
                      'tag_id',
                      'portal_instance_id',
                      'created_after',
                      'created_before',
                      'updated_after',
                      'updated_before']),
 'get_changelog': ('GET', '/changelogs/{id}', {'id': 'changelog_id'}, [], [], ['language']),
 'create_changelog': ('POST',
                      '/changelogs',
                      {},
                      ['title', 'content', 'date', 'published', 'tag_ids', 'portal_instance_ids'],
                      [],
                      []),
 'update_changelog': ('PATCH',
                      '/changelogs/{id}',
                      {'id': 'changelog_id'},
                      ['title', 'content', 'date', 'published', 'archived', 'tag_ids', 'portal_instance_ids'],
                      ['date'],
                      [])}


class ProductlaneNode(WorkflowNode):
    integration_type = "automation-productlane"
    scope_registry = PRODUCTLANE_SCOPES
    connection_evidence = ConnectionEvidence(noun="Productlane workspace", identity_operation="get_me",
        identity_keys=("workspace_id",))

    @classmethod
    def get_config_model(cls):
        return ProductlaneFullConfig

    @staticmethod
    async def _request(credential, config):
        method, path, bindings, body_names, nullable, query_names = ROUTES[config.operation]
        values = config.model_dump(mode="json")
        for key, field in bindings.items():
            path = path.replace("{" + key + "}", quote(values[field], safe=""))
        params = {key: values[key] for key in query_names if values[key] is not None}
        body = {key: values[key] for key in body_names if values[key] is not None
                or (key in config.model_fields_set and key in nullable)}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://productlane.com/api/v2" + path,
                params=params, headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                **({"json": body} if method in {"POST", "PATCH"} else {}))
        if response.status_code != 200:
            message = "Productlane request failed"
            try:
                error = response.json().get("error", {})
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(credential.api_key, "[redacted]")[:1000]
            except (ValueError, AttributeError):
                pass
            return {"status": "error", "status_code": response.status_code, "error": message}
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Expected bounded JSON from Productlane")
        payload = response.json()
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("Productlane returned an unexpected response")
        if config.operation == "get_me":
            if not isinstance(payload.get("workspace_id"), str) or not payload["workspace_id"]:
                raise ValueError("Productlane identity is missing its workspace")
        elif config.operation.startswith("list_"):
            if not isinstance(payload.get("data"), list) or not isinstance(payload.get("page"), dict):
                raise ValueError("Productlane list is missing its data or page")
        elif not isinstance(payload.get("id"), str) or not payload["id"]:
            raise ValueError("Productlane resource is missing its ID")
        # Preserve provider fields (including thread status) under data.
        return {"status": "success", "data": payload}

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Productlane v2 API key")
        return await self._request(self.config.credentials, self.config.config)

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        listings = {"thread_id": ListThreadsConfig, "contact_id": ListContactsConfig,
            "company_id": ListCompaniesConfig, "changelog_id": ListChangelogsConfig}
        if field_name not in listings:
            raise ValueError("Unknown Productlane resource field")
        if search:
            raise ValueError("Productlane choices do not support text search; paste an ID or page through choices")
        credential = ProductlaneApiKeyCredential.model_validate(credential_data)
        result = await cls._request(credential, listings[field_name](cursor=page_token))
        if result["status"] != "success":
            raise ValueError(result["error"])
        payload = result["data"]
        options = []
        for item in payload["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError("Productlane choice is missing its ID")
            options.append({"value": item["id"], "label": item.get("title") or item.get("name") or item.get("email") or item["id"]})
        page = payload["page"]
        if not isinstance(page.get("has_more"), bool) or (page["has_more"] and not isinstance(page.get("cursor"), str)):
            raise ValueError("Productlane returned invalid pagination")
        return {"options": options, "next_page_token": page["cursor"] if page["has_more"] else None}

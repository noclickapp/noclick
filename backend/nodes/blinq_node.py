"""Blinq Public API v1: personal contacts, cards, notes and webhook subscriptions.

Contract: https://docs.blinq.me/api-reference/openapi.json (1.0.0).
Each operation performs one documented request; pagination remains explicit.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class BlinqAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Blinq API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.blinq.me/api-reference/introduction",
            "x-credential-instructions": "In the Blinq web app, open Settings > API keys and create a key. Requires a Pro or Business plan and verified email. Select blinq:identity:read for connection verification, blinq:notes:read for notes, blinq:contacts:read for contacts, blinq:cards:read for cards, and blinq:webhooks:read/write for subscriptions. Creating subscriptions also requires blinq:contacts:read. Paste the key without Bearer. Keys cannot exceed the owner's workspace permissions."
        })
    credential_type: Literal["blinq_api_key"] = Field("blinq_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the Blinq key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if (info.field_name == "id" or info.field_name.endswith("_id")) and isinstance(value, str):
            if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use the resource ID returned by Blinq")
        return value


class BlinqListNotesConfig(_Input):
    """List notes."""
    operation: Literal['list_notes'] = Field('list_notes', json_schema_extra={"ui:hidden": True})
    created_after: str | None = Field(None, pattern='^(?:(?:\\d\\d[2468][048]|\\d\\d[13579][26]|\\d\\d0[48]|[02468][048]00|[13579][26]00)-02-29|\\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\\d|30)|(?:02)-(?:0[1-9]|1\\d|2[0-8])))T(?:(?:[01]\\d|2[0-3]):[0-5]\\d(?::[0-5]\\d(?:\\.\\d+)?)?(?:Z|([+-](?:[01]\\d|2[0-3]):[0-5]\\d)))$', description='Return notes created after this ISO 8601 timestamp with a timezone, such as `2026-10-01T00:00:00Z` (exclusive).')
    created_before: str | None = Field(None, pattern='^(?:(?:\\d\\d[2468][048]|\\d\\d[13579][26]|\\d\\d0[48]|[02468][048]00|[13579][26]00)-02-29|\\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\\d|30)|(?:02)-(?:0[1-9]|1\\d|2[0-8])))T(?:(?:[01]\\d|2[0-3]):[0-5]\\d(?::[0-5]\\d(?:\\.\\d+)?)?(?:Z|([+-](?:[01]\\d|2[0-3]):[0-5]\\d)))$', description='Return notes created before this ISO 8601 timestamp with a timezone, such as `2026-11-01T00:00:00Z` (exclusive).')
    updated_at_gte: str | None = Field(None, pattern='^(?:(?:\\d\\d[2468][048]|\\d\\d[13579][26]|\\d\\d0[48]|[02468][048]00|[13579][26]00)-02-29|\\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\\d|30)|(?:02)-(?:0[1-9]|1\\d|2[0-8])))T(?:(?:[01]\\d|2[0-3]):[0-5]\\d(?::[0-5]\\d(?:\\.\\d+)?)?(?:Z|([+-](?:[01]\\d|2[0-3]):[0-5]\\d)))$', description='Return notes last updated at or after this ISO 8601 timestamp with a timezone, such as `2026-10-01T00:00:00Z` (inclusive). Deleted notes are excluded.')
    order_by: Literal['created_at', 'updated_at'] = Field('created_at', description='The timestamp used to sort notes in descending order. Keep this value unchanged between pages.')
    cursor: str | None = Field(None, min_length=1, description='The `next_cursor` from the previous response. Omit on the first request. Keep filters and `order_by` unchanged between pages.')
    limit: int = Field(25, le=50, gt=0, description='The maximum number of notes to return per page.')


class BlinqSearchNotesConfig(_Input):
    """Search notes."""
    operation: Literal['search_notes'] = Field('search_notes', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, description='Search terms to match against indexed titles and bodies, including recording summaries and saved text.')
    limit: int = Field(10, le=25, gt=0, description='The maximum number of search results to return. Search does not support pagination.')


class BlinqQueryNotesConfig(_Input):
    """Ask a question about notes."""
    operation: Literal['query_notes'] = Field('query_notes', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, description='A natural-language question. Answers draw on note titles and note bodies (the AI summary for a recording or the saved text of a typed note), not transcripts. Each note body is truncated to 8,000 UTF-16 code units.')
    note_ids: list[Annotated[str, Field(min_length=1)]] | None = Field(None, min_length=1, max_length=8, description='Restricts the answer to between 1 and 8 notes you own. Omit to let the API select up to 10 of the most relevant notes automatically. IDs of inaccessible notes are ignored.')


class BlinqGetNoteConfig(_Input):
    """Get note."""
    operation: Literal['get_note'] = Field('get_note', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='The note ID.')


class BlinqGetNoteTranscriptConfig(_Input):
    """Get note transcript."""
    operation: Literal['get_note_transcript'] = Field('get_note_transcript', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='The note ID.')


class BlinqGetCurrentUserConfig(_Input):
    """Get the authenticated user."""
    operation: Literal['get_current_user'] = Field('get_current_user', json_schema_extra={"ui:hidden": True})


class BlinqListWorkspacesConfig(_Input):
    """List workspaces."""
    operation: Literal['list_workspaces'] = Field('list_workspaces', json_schema_extra={"ui:hidden": True})


class BlinqListContactsConfig(_Input):
    """List contacts."""
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, min_length=1, description='The `next_cursor` returned by the previous response. Omit for the first page. Keep filters unchanged between pages.')
    search: str | None = Field(None, min_length=1, description='Filters contacts using a case-insensitive substring match against card names, job titles, company names, and saved text notes.')
    updated_at_gte: str | None = Field(None, pattern='^(?:(?:\\d\\d[2468][048]|\\d\\d[13579][26]|\\d\\d0[48]|[02468][048]00|[13579][26]00)-02-29|\\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\\d|30)|(?:02)-(?:0[1-9]|1\\d|2[0-8])))T(?:(?:[01]\\d|2[0-3]):[0-5]\\d(?::[0-5]\\d(?:\\.\\d+)?)?(?:Z|([+-](?:[01]\\d|2[0-3]):[0-5]\\d)))$', description='Return contact records last updated at or after this ISO 8601 timestamp with a timezone, such as `2026-10-01T00:00:00Z` (inclusive). Deleted contacts are excluded. Changes to linked resources do not necessarily update the contact record.')
    created_at_gte: str | None = Field(None, pattern='^(?:(?:\\d\\d[2468][048]|\\d\\d[13579][26]|\\d\\d0[48]|[02468][048]00|[13579][26]00)-02-29|\\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\\d|30)|(?:02)-(?:0[1-9]|1\\d|2[0-8])))T(?:(?:[01]\\d|2[0-3]):[0-5]\\d(?::[0-5]\\d(?:\\.\\d+)?)?(?:Z|([+-](?:[01]\\d|2[0-3]):[0-5]\\d)))$', description='Include contacts created at or after this ISO 8601 timestamp with a timezone, such as `2026-10-01T00:00:00Z` (inclusive).')
    created_at_lte: str | None = Field(None, pattern='^(?:(?:\\d\\d[2468][048]|\\d\\d[13579][26]|\\d\\d0[48]|[02468][048]00|[13579][26]00)-02-29|\\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\\d|30)|(?:02)-(?:0[1-9]|1\\d|2[0-8])))T(?:(?:[01]\\d|2[0-3]):[0-5]\\d(?::[0-5]\\d(?:\\.\\d+)?)?(?:Z|([+-](?:[01]\\d|2[0-3]):[0-5]\\d)))$', description='Include contacts created at or before this ISO 8601 timestamp with a timezone, such as `2026-10-31T23:59:59Z` (inclusive).')
    limit: int = Field(25, le=50, gt=0, description='The maximum number of contacts to return per page.')
    workspace_id: str = Field(..., min_length=1, description='The workspace ID. Use an `id` returned by the list workspaces endpoint.')


class BlinqGetContactConfig(_Input):
    """Get contact."""
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, description='The ID of the workspace containing the contact. Use the `workspace_id` returned when listing contacts.')
    contact_id: str = Field(..., min_length=1, description='The contact ID.')


class BlinqListCardsConfig(_Input):
    """List cards."""
    operation: Literal['list_cards'] = Field('list_cards', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, min_length=1, description='The `next_cursor` returned by the previous response. Omit for the first page. Keep the workspace unchanged between pages.')
    limit: int = Field(25, le=50, gt=0, description='The maximum number of cards to return per page.')
    workspace_id: str = Field(..., min_length=1, description='The workspace ID. Use an `id` returned by the list workspaces endpoint.')


class BlinqGetCardConfig(_Input):
    """Get card."""
    operation: Literal['get_card'] = Field('get_card', json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, description='The ID of the workspace containing the card. Use an `id` from list workspaces.')
    card_id: str = Field(..., min_length=1, description='The card ID.')


class BlinqCreateWebhookConfig(_Input):
    """Create webhook subscription."""
    operation: Literal['create_webhook'] = Field('create_webhook', json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, description='The workspace ID: your individual workspace, or a business workspace where you are an owner or admin. Use an `id` returned by the list workspaces endpoint.')
    url: str = Field(..., min_length=1, max_length=2048, description='The HTTPS destination URL for deliveries. Credentials and fragments are rejected. The stored URL is the normalized form, preserving query parameters.')
    events: list[Literal['contact.created']] = Field(..., min_length=1, description='The events to receive. At least one is required; duplicates are stored once.')

    @field_validator("url")
    @classmethod
    def https_destination(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment or any(c.isspace() for c in value):
            raise ValueError("Use an absolute HTTPS destination without credentials or a fragment")
        return value


class BlinqListWebhooksConfig(_Input):
    """List webhook subscriptions."""
    operation: Literal['list_webhooks'] = Field('list_webhooks', json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, description='The workspace ID: your individual workspace, or a business workspace where you are an owner or admin. Use an `id` returned by the list workspaces endpoint.')


class BlinqDeleteWebhookConfig(_Input):
    """Delete webhook subscription."""
    operation: Literal['delete_webhook'] = Field('delete_webhook', json_schema_extra={"ui:hidden": True})
    workspace_id: str = Field(..., min_length=1, description='The workspace ID: your individual workspace, or a business workspace where you are an owner or admin. Use an `id` returned by the list workspaces endpoint.')
    subscription_id: str = Field(..., min_length=1, description='The webhook subscription ID to delete.')


BlinqConfig = Annotated[Union[BlinqListNotesConfig, BlinqSearchNotesConfig, BlinqQueryNotesConfig, BlinqGetNoteConfig, BlinqGetNoteTranscriptConfig, BlinqGetCurrentUserConfig, BlinqListWorkspacesConfig, BlinqListContactsConfig, BlinqGetContactConfig, BlinqListCardsConfig, BlinqGetCardConfig, BlinqCreateWebhookConfig, BlinqListWebhooksConfig, BlinqDeleteWebhookConfig], Field(discriminator="operation")]


class BlinqFullConfig(NodeConfig[BlinqConfig, BlinqAPIKeyCredential]):
    pass


ROUTES = {'list_notes': ('GET',
                '/v1/notes',
                (),
                ('created_after', 'created_before', 'updated_at_gte', 'order_by', 'cursor', 'limit'),
                (),
                200,
                ('notes', 'has_more', 'next_cursor', 'total_count')),
 'search_notes': ('GET', '/v1/notes/search', (), ('query', 'limit'), (), 200, ('notes', 'is_truncated')),
 'query_notes': ('POST', '/v1/notes/query', (), (), ('query', 'note_ids'), 200, ('answer', 'citations')),
 'get_note': ('GET',
              '/v1/notes/{id}',
              ('id',),
              (),
              (),
              200,
              ('id',
               'title',
               'created_at',
               'updated_at',
               'deleted_at',
               'status',
               'type',
               'share_url',
               'linked_contacts',
               'content',
               'content_format',
               'source')),
 'get_note_transcript': ('GET',
                         '/v1/notes/{id}/transcript',
                         ('id',),
                         (),
                         (),
                         200,
                         ('status', 'retry_after', 'text')),
 'get_current_user': ('GET', '/v1/me', (), (), (), 200, ('user_id', 'email')),
 'list_workspaces': ('GET', '/v1/workspaces', (), (), (), 200, ('workspaces',)),
 'list_contacts': ('GET',
                   '/v1/workspaces/{workspace_id}/contacts',
                   ('workspace_id',),
                   ('cursor', 'search', 'updated_at_gte', 'created_at_gte', 'created_at_lte', 'limit'),
                   (),
                   200,
                   ('contacts', 'has_more', 'next_cursor', 'total_count')),
 'get_contact': ('GET',
                 '/v1/workspaces/{workspace_id}/contacts/{contact_id}',
                 ('workspace_id', 'contact_id'),
                 (),
                 (),
                 200,
                 ('id',
                  'workspace_id',
                  'type',
                  'first_name',
                  'middle_name',
                  'last_name',
                  'full_name',
                  'preferred_name',
                  'pronouns',
                  'job_title',
                  'company_name',
                  'department',
                  'headline',
                  'avatar_url',
                  'company_logo_url',
                  'emails',
                  'phone_numbers',
                  'urls',
                  'addresses',
                  'tags',
                  'contact_notes',
                  'linked_notes',
                  'capture_context',
                  'created_at',
                  'updated_at')),
 'list_cards': ('GET',
                '/v1/workspaces/{workspace_id}/cards',
                ('workspace_id',),
                ('cursor', 'limit'),
                (),
                200,
                ('cards', 'has_more', 'next_cursor', 'total_count')),
 'get_card': ('GET',
              '/v1/workspaces/{workspace_id}/cards/{card_id}',
              ('workspace_id', 'card_id'),
              (),
              (),
              200,
              ('id',
               'workspace_id',
               'url',
               'card_title',
               'first_name',
               'last_name',
               'job_title',
               'company_name',
               'department',
               'qr_code')),
 'create_webhook': ('POST',
                    '/v1/workspaces/{workspace_id}/webhooks',
                    ('workspace_id',),
                    (),
                    ('url', 'events'),
                    201,
                    ('id', 'signing_secret')),
 'list_webhooks': ('GET',
                   '/v1/workspaces/{workspace_id}/webhooks',
                   ('workspace_id',),
                   (),
                   (),
                   200,
                   ('webhooks',)),
 'delete_webhook': ('DELETE',
                    '/v1/workspaces/{workspace_id}/webhooks/{subscription_id}',
                    ('workspace_id', 'subscription_id'),
                    (),
                    (),
                    204,
                    ())}


class BlinqNode(WorkflowNode):
    integration_type = "automation-blinq"
    connection_evidence = ConnectionEvidence(noun="Blinq account", identity_operation="get_current_user")

    @classmethod
    def get_config_model(cls):
        return BlinqFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Blinq API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, route, paths, queries, fields, expected_status, required = ROUTES[op.operation]
        for name in paths:
            route = route.replace("{" + name + "}", quote(getattr(op, name), safe=""))
        params = {name: getattr(op, name) for name in queries if getattr(op, name) is not None}
        body = {name: getattr(op, name) for name in fields if getattr(op, name) is not None}
        # Never follow a redirect with the personal key, retry a mutation, or
        # fetch a URL returned in a note, card or contact.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.blinq.me" + route,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if fields else {}))
        if response.status_code != expected_status:
            message = "Blinq request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(token, "[redacted]")
            except ValueError:
                pass
            result = {"status": "error", "http_status": response.status_code, "status_code": response.status_code, "message": message}
            if method != "GET" and response.status_code >= 500:
                result["write_outcome"] = "unknown; inspect before retrying"
            return result
        if expected_status == 204:
            return {"status": "success", "http_status": 204, "deleted_id": op.subscription_id,
                    "deletion_acknowledged": True}
        if len(response.content) > 10_000_000:
            raise ValueError("Blinq response exceeds the supported size")
        data = response.json()
        if not isinstance(data, dict) or not set(required).issubset(data):
            raise ValueError("Blinq returned an unexpected response shape")
        if op.operation == "get_current_user" and (not isinstance(data["user_id"], str) or not isinstance(data["email"], str)):
            raise ValueError("Blinq identity response is invalid")
        collection = {"list_notes": "notes", "search_notes": "notes", "list_contacts": "contacts",
                      "list_cards": "cards", "list_workspaces": "workspaces", "list_webhooks": "webhooks"}.get(op.operation)
        if collection and (not isinstance(data[collection], list) or any(not isinstance(row, dict) for row in data[collection])):
            raise ValueError("Blinq returned an invalid collection")
        if "has_more" in data:
            if type(data["has_more"]) is not bool or (data["has_more"] and (not isinstance(data["next_cursor"], str) or not data["next_cursor"])):
                raise ValueError("Blinq returned invalid pagination")
            if data["has_more"] and data["next_cursor"] == getattr(op, "cursor", None):
                raise ValueError("Blinq returned a nonadvancing cursor")
        return {"status": "success", "http_status": response.status_code, "data": data}

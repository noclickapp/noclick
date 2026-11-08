"""Mem Public Client API v2: notes, collections and intelligent capture.

Contract: https://docs.mem.ai/api-reference/openapi.json, version 1.0.0.
Each operation issues one request; pagination tokens remain visible to callers.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MemAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mem API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://mem.ai/settings",
        "x-help-url": "https://docs.mem.ai/api-reference/overview/authentication",
        "x-credential-instructions": "In Mem settings, open the API section and copy your API key. Paste the key alone; NoClick sends it using Bearer authentication to api.mem.ai.",
    })
    credential_type: Literal["mem_api_key"] = Field("mem_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Mem API key")
        value = clean_secret(value, field_name="API key")
        if any(ord(c) <= 32 or ord(c) >= 127 for c in value):
            raise ValueError("Paste the API key alone without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def validate_text(cls, value, info):
        # Mem limits both characters and UTF-8 bytes for these fields.
        bound = {"content": 200000, "title": 1000, "description": 10000}.get(info.field_name)
        if isinstance(value, str) and bound and len(value.encode("utf-8")) > bound:
            raise ValueError("Text exceeds Mem's UTF-8 byte limit")
        if info.field_name == "collection_titles" and value is not None:
            if any(len(title.encode("utf-8")) > 1000 for title in value):
                raise ValueError("Collection titles must fit within 1000 UTF-8 bytes")
        if info.field_name == "query" and isinstance(value, str) and not value.strip():
            raise ValueError("Search query must contain text")
        return value


class MemListNotesConfig(_Input):
    'List notes visible to the authenticated caller with cursor pagination.\nWhen multiple `contains_*` fields are true, a note may match any of them.\nResults are ordered by `order_by` and return `next_page` when additional rows are available.\nFor relevance-ranked retrieval by query, use `POST /v2/notes/search`.'
    operation: Literal['list_notes'] = Field('list_notes', json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=100, strict=True, description='Maximum number of notes in this page.\nUse smaller values for lower latency.\nDefault is 50; valid range is 1 to 100.')
    page: str | None = Field(None, description='Opaque cursor from a previous list response.\nOmit for the first page.\nIMPORTANT: Reuse with the same filters and `order_by` settings.')
    order_by: Literal['created_at', 'updated_at'] = Field('updated_at', description='Sort key for pagination boundaries.\nUse `updated_at` (default) for recency feeds.\nUse `created_at` for creation-order views.')
    collection_id: UUID | None = Field(None, description='Optional collection filter by UUID.\nWhen set, only notes linked to this collection are returned.')
    filter_by_created_after: AwareDatetime | None = Field(None, description='Optional inclusive lower bound for note creation time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_created_before: AwareDatetime | None = Field(None, description='Optional inclusive upper bound for note creation time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_updated_after: AwareDatetime | None = Field(None, description='Optional inclusive lower bound for note update time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_updated_before: AwareDatetime | None = Field(None, description='Optional inclusive upper bound for note update time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    contains_open_tasks: bool = Field(False, description='When true, include notes that contain at least one open task item.\nWhen multiple `contains_*` fields are true, notes matching any selected\nfilter may be returned.')
    contains_tasks: bool = Field(False, description='When true, include notes that contain at least one task item\n(open or closed).\nWhen multiple `contains_*` fields are true, notes matching any selected\nfilter may be returned.')
    contains_images: bool = Field(False, description='When true, include notes that contain image media\n(including image and GIF kinds).\nWhen multiple `contains_*` fields are true, notes matching any selected\nfilter may be returned.')
    contains_files: bool = Field(False, description='When true, include notes that contain file-like attachments\n(including file and PDF kinds).\nWhen multiple `contains_*` fields are true, notes matching any selected\nfilter may be returned.')
    include_note_content: bool = Field(False, description='When true, include full markdown content for each returned note.\nIMPORTANT: This increases payload size and can increase latency.')

class MemCreateNoteConfig(_Input):
    'Create a note with an optional note ID, timestamps, and collection links.\nIf omitted, Mem generates the note ID.\nThe first line of `content` becomes the note title.'
    operation: Literal['create_note'] = Field('create_note', json_schema_extra={"ui:hidden": True})
    collection_ids: list[UUID] | None = Field(None, description='Optional collection IDs to associate with the note.\nIDs that do not map to accessible collections are ignored.')
    collection_titles: list[str] | None = Field(None, description='Optional collection titles to associate with the note.\nMatching is case-insensitive exact match; titles with no match are ignored.\nMaximum per title: 1,000 characters (and no more than 1,000 UTF-8 bytes).')
    content: str = Field(..., max_length=200000, description='Full markdown body for the note.\nSend the full desired note body (partial patch semantics are not supported here).\nIMPORTANT: The first line is interpreted as the note title.\nMaximum: 200,000 characters (and no more than 200,000 UTF-8 bytes on create).')
    created_at: AwareDatetime | None = Field(None, description='Optional creation timestamp (ISO 8601).\nIf provided, it must include a timezone offset and cannot be in the future.\nIf omitted, Mem uses `updated_at` when provided; otherwise current server time.')
    id: UUID | None = Field(None, description='Optional UUID for the note.\nIf omitted, Mem generates a new UUID.')
    updated_at: AwareDatetime | None = Field(None, description='Optional "last updated" timestamp for this write (ISO 8601).\nIf provided, it must include a timezone offset and cannot be in the future.\nIf omitted, Mem uses the current server time for the initial content write.')

class MemGetNoteConfig(_Input):
    'Fetch the full current state of a single note by ID.\nIf the note is in trash, the response still returns the note and includes `trashed_at`.\nFor discovery flows, use `GET /v2/notes` or `POST /v2/notes/search`.'
    operation: Literal['get_note'] = Field('get_note', json_schema_extra={"ui:hidden": True})
    note_id: UUID = Field(..., description='UUID of the note to read. Use an ID returned by create/list/search. The caller must be able to access this note.')

class MemUpdateNoteConfig(_Input):
    'Submit a complete markdown body for a note and the exact `version` being updated.\nSend the full desired body in `content` (not a partial markdown patch).\nThe first line of `content` becomes the updated title.\nTrashed notes must be restored before they can be updated.'
    operation: Literal['update_note'] = Field('update_note', json_schema_extra={"ui:hidden": True})
    note_id: UUID = Field(..., description='UUID of the note to update. Use an ID returned by create/list/search. The caller must be able to edit this note.')
    content: str = Field(..., max_length=200000, description='Complete markdown body to submit for this write.\nSend the full desired note body (partial patch semantics are not supported\nin this request payload).\nThe first line is interpreted as the title.')
    updated_at: AwareDatetime | None = Field(None, description='Optional "last updated" timestamp for this write (ISO 8601).\nIf omitted, the current server time is used.')
    version: int = Field(..., ge=1, strict=True, description='Exact note content document version this update is based on.\nUse the `version` returned by `GET /v2/notes/{note_id}` or by the most\nrecent note write response.')

class MemDeleteNoteConfig(_Input):
    'Permanently delete a note.\nHard-deleted notes cannot be restored.\nFor recoverable removal, use `POST /v2/notes/{note_id}/trash`.'
    operation: Literal['delete_note'] = Field('delete_note', json_schema_extra={"ui:hidden": True})
    note_id: UUID = Field(..., description='UUID of the note to permanently delete. Use an ID returned by create/list/search. The caller must be able to edit this note.')

class MemTrashNoteConfig(_Input):
    'Soft-delete a note by moving it to trash.\nTrashed notes can be restored via `POST /v2/notes/{note_id}/restore`.\nFor irreversible deletion, use `DELETE /v2/notes/{note_id}`.'
    operation: Literal['trash_note'] = Field('trash_note', json_schema_extra={"ui:hidden": True})
    note_id: UUID = Field(..., description='UUID of the note to move to trash. Use an ID returned by create/list/search. The caller must be able to edit this note.')

class MemRestoreNoteConfig(_Input):
    'Restore a previously trashed note to the active note set.\nThis only reverses soft-delete lifecycle state.\nNotes permanently deleted via `DELETE /v2/notes/{note_id}` cannot be restored.'
    operation: Literal['restore_note'] = Field('restore_note', json_schema_extra={"ui:hidden": True})
    note_id: UUID = Field(..., description='UUID of the note to restore from trash. Use an ID returned by create/list/search. The caller must be able to edit this note.')

class MemSetNoteCreatedAtConfig(_Input):
    "Set a note's visible creation timestamp without changing its content.\nThe supplied `created_at` must include a timezone offset and cannot be in the future.\nIt can only backdate the note: the timestamp cannot be later than\nwhen the note was originally created.\nThis operation changes note metadata only.\nTrashed notes must be restored before their creation date can be changed."
    operation: Literal['set_note_created_at'] = Field('set_note_created_at', json_schema_extra={"ui:hidden": True})
    note_id: UUID = Field(..., description='UUID of the note whose visible creation timestamp should change. The caller must own this note.')
    created_at: AwareDatetime = Field(..., description='New visible creation timestamp for the note (ISO 8601).\nIt must include a timezone offset and cannot be in the future.\nIt can only backdate the note: the timestamp cannot be later than\nwhen the note was originally created.\nThis changes note metadata only; it does not update note content.')

class MemFindRelatedNotesConfig(_Input):
    'Find notes semantically related to the current persisted content of a note.\nThe source note is embedded at request time, so newly created or recently\nupdated notes can be used before asynchronous indexing catches up.\nCandidate related notes still come from the note search index.'
    operation: Literal['find_related_notes'] = Field('find_related_notes', json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, ge=1, le=20, strict=True, description='Maximum number of related notes to return.\nDefault is 10; valid range is 1 to 20.')
    note_id: UUID = Field(..., description='UUID of the source note. The caller must be able to access this note.')

class MemSearchNotesConfig(_Input):
    'Search notes using a required free-text query and structured filters.\nWhen multiple `filter_by_contains_*` fields are true, a note may match any of them.\nReturns note results from a bounded search snapshot with deterministic offset pagination.\nQuery-based searches are relevance-ranked within the bounded search snapshot window.\nReuse the returned `snapshot_id` when requesting later pages.\nThe returned `total` reflects the bounded search snapshot, capped by the 100-result search window.\nFor deterministic chronological pagination across all accessible notes, use `GET /v2/notes`.'
    operation: Literal['search_notes'] = Field('search_notes', json_schema_extra={"ui:hidden": True})
    limit: int = Field(20, ge=1, le=50, strict=True, description='Maximum number of notes in this search page.\nUse smaller values for lower latency.\nDefault is 20; valid range is 1 to 50.')
    offset: int = Field(0, ge=0, strict=True, description='Number of matching notes to skip before returning results.\nThis value is zero-based.')
    snapshot_id: UUID | None = Field(None, description='Opaque search snapshot identifier returned by a previous search page.\nRequired when requesting later pages with `offset > 0`.')
    filter_by_collection_ids: list[UUID] | None = Field(None, description='Optional collection UUID filters.\nWhen provided, results are limited to notes in any listed collection.')
    filter_by_contains_files: bool = Field(False, description='When true, include notes that contain file-like attachments\n(including file and PDF kinds).')
    filter_by_contains_images: bool = Field(False, description='When true, include notes that contain image media\n(including image and GIF kinds).')
    filter_by_contains_open_tasks: bool = Field(False, description='When true, include notes that contain at least one open task item.')
    filter_by_contains_tasks: bool = Field(False, description='When true, include notes that contain at least one task item\n(open or closed).')
    filter_by_created_after: AwareDatetime | None = Field(None, description='Optional inclusive lower bound for note creation time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_created_before: AwareDatetime | None = Field(None, description='Optional inclusive upper bound for note creation time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_updated_after: AwareDatetime | None = Field(None, description='Optional inclusive lower bound for note update time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_updated_before: AwareDatetime | None = Field(None, description='Optional inclusive upper bound for note update time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    query: str = Field(..., min_length=1, description='Required text query for relevance matching.\nThe query must contain at least one non-whitespace character.\nThis endpoint does not provide exhaustive chronological pagination; for that, use\n`GET /v2/notes`.')

    @model_validator(mode="after")
    def pagination_snapshot(self):
        if self.offset > 0 and self.snapshot_id is None:
            raise ValueError("Use snapshot_id from the first search page for offset > 0")
        return self

class MemListCollectionsConfig(_Input):
    'List collections visible to the authenticated caller with cursor pagination.\nResults are ordered by `order_by` and return `next_page` when additional rows are available.\nFor relevance-ranked retrieval by query, use `POST /v2/collections/search`.'
    operation: Literal['list_collections'] = Field('list_collections', json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=100, strict=True, description='Maximum number of collections in this page.\nUse smaller values for lower latency.\nDefault is 50; valid range is 1 to 100.')
    page: str | None = Field(None, description='Opaque cursor from a previous list response.\nOmit for the first page.\nIMPORTANT: Reuse with the same filters and `order_by` settings.')
    order_by: Literal['created_at', 'updated_at'] = Field('updated_at', description='Sort key for pagination boundaries.\nUse `updated_at` (default) for recency feeds.\nUse `created_at` for creation-order views.')
    filter_by_created_after: AwareDatetime | None = Field(None, description='Optional inclusive lower bound for collection creation time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_created_before: AwareDatetime | None = Field(None, description='Optional inclusive upper bound for collection creation time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_updated_after: AwareDatetime | None = Field(None, description='Optional inclusive lower bound for collection update time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_updated_before: AwareDatetime | None = Field(None, description='Optional inclusive upper bound for collection update time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')

class MemCreateCollectionConfig(_Input):
    'Create a collection with optional caller-provided ID and timestamps.\nIf `id` already exists, this request returns a conflict.\nUse collection membership endpoints to add, remove, or move notes between collections.'
    operation: Literal['create_collection'] = Field('create_collection', json_schema_extra={"ui:hidden": True})
    created_at: AwareDatetime | None = Field(None, description='Optional creation timestamp (ISO 8601).\nIf provided, it must include a timezone offset and cannot be in the future.\nIf omitted, Mem uses `updated_at` when provided; otherwise current server time.')
    description: str | None = Field(None, max_length=10000, description='Optional longer description of collection scope or intent.\nMaximum: 10,000 characters (and no more than 10,000 UTF-8 bytes).')
    id: UUID | None = Field(None, description='Optional caller-provided UUID for the collection.\nIf omitted, Mem generates a new UUID.\nIf the provided ID already exists, this request returns a conflict.')
    title: str = Field(..., max_length=1000, description='Title for the collection.\nUse a short, stable label suitable for navigation and search.\nMaximum: 1,000 characters (and no more than 1,000 UTF-8 bytes).')
    updated_at: AwareDatetime | None = Field(None, description='Optional "last updated" timestamp for this write (ISO 8601).\nIf provided, it must include a timezone offset and cannot be in the future.\nIf omitted, Mem uses `created_at` for the initial collection write.')

class MemGetCollectionConfig(_Input):
    'Fetch metadata for a single collection by ID.\nThis endpoint returns collection metadata only, not a note list for that collection.\nFor discovery flows, use `GET /v2/collections` or `POST /v2/collections/search`.'
    operation: Literal['get_collection'] = Field('get_collection', json_schema_extra={"ui:hidden": True})
    collection_id: UUID = Field(..., description='UUID of the collection to read. Use an ID returned by create/list/search. The caller must be able to access this collection.')

class MemUpdateCollectionConfig(_Input):
    'Update metadata for a collection by ID.\nUse this endpoint to rename a collection by setting `title`.\nThis endpoint updates only provided fields (`title`, `description`) and leaves omitted fields unchanged.\nFor read-only retrieval, use `GET /v2/collections/{collection_id}`.'
    operation: Literal['update_collection'] = Field('update_collection', json_schema_extra={"ui:hidden": True})
    clear_description: bool = Field(False, description="Clear the collection description. Sends an empty description to Mem.")
    collection_id: UUID = Field(..., description='UUID of the collection to update. Use an ID returned by create/list/search. The caller must be able to edit this collection.')
    description: str | None = Field(None, max_length=10000, description='Optional replacement description for the collection.\nOmit to keep the current description unchanged.\nSet to an empty string to clear the description.\nMaximum: 10,000 characters (and no more than 10,000 UTF-8 bytes).')
    title: str | None = Field(None, max_length=1000, description='Optional replacement title for the collection.\nUse this field to rename a collection.\nOmit to keep the current title unchanged.\nMaximum: 1,000 characters (and no more than 1,000 UTF-8 bytes).')
    updated_at: AwareDatetime | None = Field(None, description='Optional "last updated" timestamp for this write (ISO 8601).\nIf provided, it must include a timezone offset and cannot be in the future.\nIf omitted, the current server time is used.')

    @model_validator(mode="after")
    def require_change(self):
        if self.clear_description and self.description is not None:
            raise ValueError("Choose a replacement description or clear it")
        if self.title is None and self.description is None and not self.clear_description:
            raise ValueError("Supply a title or description to update")
        return self

class MemDeleteCollectionConfig(_Input):
    'Permanently delete a collection.\nHard-deleting removes the collection resource itself.\nFor membership-only changes, use note add, remove, or move collection endpoints.'
    operation: Literal['delete_collection'] = Field('delete_collection', json_schema_extra={"ui:hidden": True})
    collection_id: UUID = Field(..., description='UUID of the collection to permanently delete. Use an ID returned by create/list/search. The caller must be able to access this collection.')

class MemAddNoteToCollectionConfig(_Input):
    'Add an existing note to an existing collection.\nThis operation only creates the membership link and does not modify note or collection content.\nUse create endpoints to create notes or collections.'
    operation: Literal['add_note_to_collection'] = Field('add_note_to_collection', json_schema_extra={"ui:hidden": True})
    collection_id: UUID = Field(..., description='UUID of the collection that will receive the note. Use an ID returned by create/list/search. The caller must be able to contribute to this collection.')
    note_id: UUID = Field(..., description='UUID of the note to add. Use an ID returned by create/list/search. The caller must be able to access this note.')

class MemRemoveNoteFromCollectionConfig(_Input):
    'Remove a note from a collection while keeping both resources.\nThis operation only removes the membership link between IDs.\nUse note/collection deletion endpoints to remove resources.'
    operation: Literal['remove_note_from_collection'] = Field('remove_note_from_collection', json_schema_extra={"ui:hidden": True})
    collection_id: UUID = Field(..., description='UUID of the collection to unlink. Use an ID returned by create/list/search. Caller must be able to edit the note or contribute to the collection.')
    note_id: UUID = Field(..., description='UUID of the note to unlink. Use an ID returned by create/list/search. Caller must be able to edit the note or contribute to the collection.')

class MemMoveNoteConfig(_Input):
    'Move a note from one collection to another collection.\nThis operation adds the note to the target collection, then removes it from the source collection.\nIt does not modify note or collection content.'
    operation: Literal['move_note'] = Field('move_note', json_schema_extra={"ui:hidden": True})
    source_collection_id: UUID = Field(..., description='UUID of the collection that currently contains the note. Caller must be able to remove the note from this collection.')
    note_id: UUID = Field(..., description='UUID of the note to move. Use an ID returned by create/list/search.')
    target_collection_id: UUID = Field(..., description='UUID of the collection that should receive the note.\nThe caller must be able to add the note to this collection.')

class MemSearchCollectionsConfig(_Input):
    'Search collections using free-text relevance matching.\nReturns a bounded relevance-ranked result set and does not return `next_page`.\nFor deterministic chronological pagination, use `GET /v2/collections`.'
    operation: Literal['search_collections'] = Field('search_collections', json_schema_extra={"ui:hidden": True})
    filter_by_created_after: AwareDatetime | None = Field(None, description='Optional inclusive lower bound for collection creation time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_created_before: AwareDatetime | None = Field(None, description='Optional inclusive upper bound for collection creation time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_updated_after: AwareDatetime | None = Field(None, description='Optional inclusive lower bound for collection update time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    filter_by_updated_before: AwareDatetime | None = Field(None, description='Optional inclusive upper bound for collection update time (ISO 8601).\nThe timestamp must include a timezone offset such as `Z` or `+01:00`.')
    query: str | None = Field(None, description='Optional text query for relevance matching across collections.\nIf omitted, search can still return a bounded general set.')

class MemMemItConfig(_Input):
    'Mem It'
    operation: Literal['mem_it'] = Field('mem_it', json_schema_extra={"ui:hidden": True})
    context: str | None = Field(None, max_length=10000, description='Additional background information that helps Mem understand how this input relates to your existing knowledge.\n\nExamples:\n• "This is related to my Project Alpha research"\n• "This is from the quarterly planning meeting"\n• "This is a follow-up to our discussion yesterday"\n\nMaximum of ~10k characters.')
    input: str = Field(..., max_length=1000000, description='Any raw content you want to remember - web pages, emails, transcripts, articles, or simple text.\n\nCommon Use Cases:\n• HTML from a webpage\n• Email text (including headers)\n• Meeting transcript\n• Text from a document\n• Simple notes or thoughts\n\nExamples:\n• "<!DOCTYPE html><html><head><title>AI Trends 2025</title>...</html>"\n• "[08:47:19] Kevin: Hello...[09:15:22] Meeting ended."\n• "Check out Atomic Habits by James Clear - recommended by Sarah"\n\nMaximum of ~1M characters (~1 MB).')
    instructions: str | None = Field(None, max_length=10000, description='Optional guidance on how you want this information processed or remembered.\n\nExamples:\n• "Extract the key findings and save as a research note"\n• "Create a summary with action items and decisions"\n• "Add to my reading list"\n\nMaximum size: approximately 10 KB.')
    timestamp: AwareDatetime | None = Field(None, description='When this information was encountered or created (ISO 8601 datetime string). Defaults to the current date and time.\n\nExample:\n• "2025-04-01T14:30:45Z"\n• "2023-12-15T09:45:30+01:00"\n\nMaximum of ~10k characters.')


MemOperation = Annotated[Union[
    MemListNotesConfig,
    MemCreateNoteConfig,
    MemGetNoteConfig,
    MemUpdateNoteConfig,
    MemDeleteNoteConfig,
    MemTrashNoteConfig,
    MemRestoreNoteConfig,
    MemSetNoteCreatedAtConfig,
    MemFindRelatedNotesConfig,
    MemSearchNotesConfig,
    MemListCollectionsConfig,
    MemCreateCollectionConfig,
    MemGetCollectionConfig,
    MemUpdateCollectionConfig,
    MemDeleteCollectionConfig,
    MemAddNoteToCollectionConfig,
    MemRemoveNoteFromCollectionConfig,
    MemMoveNoteConfig,
    MemSearchCollectionsConfig,
    MemMemItConfig
], Field(discriminator="operation")]


class MemNodeConfig(NodeConfig[MemOperation, MemAPIKeyCredential]):
    pass


# (method, contract path, query fields, JSON body fields)
ROUTES = {'list_notes': ('GET',
                '/v2/notes',
                ['limit',
                 'page',
                 'order_by',
                 'collection_id',
                 'filter_by_created_after',
                 'filter_by_created_before',
                 'filter_by_updated_after',
                 'filter_by_updated_before',
                 'contains_open_tasks',
                 'contains_tasks',
                 'contains_images',
                 'contains_files',
                 'include_note_content'],
                []),
 'create_note': ('POST',
                 '/v2/notes',
                 [],
                 ['collection_ids', 'collection_titles', 'content', 'created_at', 'id', 'updated_at']),
 'get_note': ('GET', '/v2/notes/{note_id}', [], []),
 'update_note': ('PATCH', '/v2/notes/{note_id}', [], ['content', 'updated_at', 'version']),
 'delete_note': ('DELETE', '/v2/notes/{note_id}', [], []),
 'trash_note': ('POST', '/v2/notes/{note_id}/trash', [], []),
 'restore_note': ('POST', '/v2/notes/{note_id}/restore', [], []),
 'set_note_created_at': ('PATCH', '/v2/notes/{note_id}/created-at', [], ['created_at']),
 'find_related_notes': ('GET', '/v2/notes/{note_id}/related-notes', ['limit'], []),
 'search_notes': ('POST',
                  '/v2/notes/search',
                  ['limit', 'offset', 'snapshot_id'],
                  ['config',
                   'filter_by_collection_ids',
                   'filter_by_contains_files',
                   'filter_by_contains_images',
                   'filter_by_contains_open_tasks',
                   'filter_by_contains_tasks',
                   'filter_by_created_after',
                   'filter_by_created_before',
                   'filter_by_updated_after',
                   'filter_by_updated_before',
                   'query']),
 'list_collections': ('GET',
                      '/v2/collections',
                      ['limit',
                       'page',
                       'order_by',
                       'filter_by_created_after',
                       'filter_by_created_before',
                       'filter_by_updated_after',
                       'filter_by_updated_before'],
                      []),
 'create_collection': ('POST',
                       '/v2/collections',
                       [],
                       ['created_at', 'description', 'id', 'title', 'updated_at']),
 'get_collection': ('GET', '/v2/collections/{collection_id}', [], []),
 'update_collection': ('PATCH',
                       '/v2/collections/{collection_id}',
                       [],
                       ['description', 'title', 'updated_at']),
 'delete_collection': ('DELETE', '/v2/collections/{collection_id}', [], []),
 'add_note_to_collection': ('PUT', '/v2/collections/{collection_id}/notes/{note_id}', [], []),
 'remove_note_from_collection': ('DELETE', '/v2/collections/{collection_id}/notes/{note_id}', [], []),
 'move_note': ('POST',
               '/v2/collections/{source_collection_id}/notes/{note_id}/move',
               [],
               ['target_collection_id']),
 'search_collections': ('POST',
                        '/v2/collections/search',
                        [],
                        ['filter_by_created_after',
                         'filter_by_created_before',
                         'filter_by_updated_after',
                         'filter_by_updated_before',
                         'query']),
 'mem_it': ('POST', '/v2/mem-it', [], ['context', 'input', 'instructions', 'timestamp'])}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class MemNode(WorkflowNode):
    integration_type = "automation-mem"
    connection_evidence = ConnectionEvidence(noun="collections", operation="list_collections")
    edit_examples = ["Save meeting notes to Mem", "Search my Mem notes", "Organize notes into a collection"]

    @classmethod
    def get_config_model(cls):
        return MemNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Mem API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True)
        for field in ("note_id", "collection_id", "source_collection_id"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", values[field])
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        if isinstance(op, MemUpdateCollectionConfig) and op.clear_description:
            body["description"] = ""
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.mem.ai" + path,
                    headers=headers, params=params, **({"json": body} if body_fields else {}))
        except httpx.HTTPError:
            raise ValueError("Mem request did not complete; inspect the result before retrying a write") from None
        if response.status_code != 200:
            # Preserve provider rejection text for the manual connection verdict.
            raise ValueError(_redact(f"Mem HTTP {response.status_code}: {response.text[:2000]}", token))
        try:
            result = response.json()
        except ValueError:
            raise ValueError("Mem returned an invalid JSON response") from None
        if not isinstance(result, dict) or "request_id" not in result:
            raise ValueError("Mem response lacks its request identifier")
        if result.get("error") or result.get("errors"):
            raise ValueError(_redact("Mem rejected the request: " + str(result), token))
        if "results" in result and not isinstance(result["results"], list):
            raise ValueError("Mem returned an invalid results page")
        output = _redact({"status": "success", **result}, token)
        await self.emit(output)
        return output

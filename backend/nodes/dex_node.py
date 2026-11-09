"""Dex v2 API: personal and workspace-bound API keys, canonical envelopes.

Contract: https://api.prod.getdex.com/docs/json (1.0.0).
Each action calls one endpoint. Lists expose the provider's opaque pagination.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.prod.getdex.com"

class DexAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Dex API Key", json_schema_extra={
        "x-credential-url": "https://getdex.com/docs/api-reference/authentication",
        "x-credential-instructions": "In Dex Settings > Dex API & MCP, create a key for Personal Dex or your workspace. Paste the key here. Choose Read & write to create or change records; a Read-only key supports reads. Workspace API access must be enabled by its owner or admin.",
    })
    credential_type: Literal["dex_api_key"] = Field("dex_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

class DexInput(BaseModel):
    @field_validator("*", mode="after")
    @classmethod
    def utc_datetimes(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("Include a timezone in the timestamp")
            return value.astimezone(timezone.utc)
        return value

class DexPage(DexInput):
    take: int = Field(100, ge=1, le=100, title="Page size")
    cursor: str | None = Field(None, title="Next cursor", description="Copy pagination.nextCursor from the previous response. Leave blank for the first page.")

class DexWrite(DexInput):
    idempotency_key: str = Field(..., min_length=8, max_length=255, pattern=r"^[\w\-:.]+$", title="Idempotency key", description="A unique key per logical change; reuse exactly this key and body on retries.")

class DexContactFields(DexWrite):
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    description: str | None = None
    job_title: str | None = None
    company: str | None = None
    website: str | None = None
    starred: bool | None = None
    email: str | None = Field(None, max_length=320, description="When supplied, sends contact_emails with this address. On update this replaces the email collection.")

class DexGetUser(DexInput):
    operation: Literal["get_user"] = Field("get_user", title="Get My Account", json_schema_extra={"ui:hidden": True})

class DexListContacts(DexPage):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    updated_since: datetime | None = Field(None, description="Only contacts updated at or after this UTC timestamp.")

class DexGetContact(DexInput):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID

class DexDeleteContact(DexWrite):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID

class DexCreateContact(DexContactFields):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})

class DexUpdateContact(DexContactFields):
    operation: Literal["update_contact"] = Field("update_contact", title="Update Contact", json_schema_extra={"ui:hidden": True})
    contact_id: UUID

class DexUUIDPage(DexPage):
    cursor: UUID | None = Field(None, title="Next cursor", description="Use pagination.nextCursor from the preceding page.")

class DexListGroups(DexUUIDPage):
    operation: Literal["list_groups"] = Field("list_groups", title="List Groups", json_schema_extra={"ui:hidden": True})

class DexCreateGroup(DexWrite):
    operation: Literal["create_group"] = Field("create_group", title="Create Group", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100)

class DexListTags(DexUUIDPage):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})

class DexCreateTag(DexWrite):
    operation: Literal["create_tag"] = Field("create_tag", title="Create Tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=99)

class DexAddContactsToGroup(DexWrite):
    operation: Literal["add_contacts_to_group"] = Field("add_contacts_to_group", title="Add Contacts To Group", json_schema_extra={"ui:hidden": True})
    group_id: UUID
    contact_ids: list[UUID] = Field(..., min_length=1, max_length=500)

class DexRemoveContactsFromGroup(DexWrite):
    operation: Literal["remove_contacts_from_group"] = Field("remove_contacts_from_group", title="Remove Contacts From Group", json_schema_extra={"ui:hidden": True})
    group_id: UUID
    contact_ids: list[UUID] = Field(..., min_length=1, max_length=500)

class DexAddTagsToContacts(DexWrite):
    operation: Literal["add_tags_to_contacts"] = Field("add_tags_to_contacts", title="Add Tags To Contacts", json_schema_extra={"ui:hidden": True})
    contact_ids: list[UUID] = Field(..., min_length=1, max_length=500)
    tag_ids: list[UUID] = Field(..., min_length=1, max_length=100)

class DexListContactNotes(DexUUIDPage):
    operation: Literal["list_contact_notes"] = Field("list_contact_notes", title="List Contact Notes", json_schema_extra={"ui:hidden": True})
    contact_id: UUID

class DexCreateNote(DexWrite):
    operation: Literal["create_note"] = Field("create_note", title="Create Note", json_schema_extra={"ui:hidden": True})
    note: str = Field(..., max_length=50000)
    event_time: datetime
    contact_ids: list[UUID] = Field(default_factory=list)

class DexUpdateNote(DexWrite):
    operation: Literal["update_note"] = Field("update_note", title="Update Note", json_schema_extra={"ui:hidden": True})
    note_id: UUID
    note: str = Field(..., max_length=50000)

class DexDeleteNote(DexWrite):
    operation: Literal["delete_note"] = Field("delete_note", title="Delete Note", json_schema_extra={"ui:hidden": True})
    note_id: UUID

class DexListReminders(DexPage):
    operation: Literal["list_reminders"] = Field("list_reminders", title="List Reminders", json_schema_extra={"ui:hidden": True})

class DexGetReminder(DexInput):
    operation: Literal["get_reminder"] = Field("get_reminder", title="Get Reminder", json_schema_extra={"ui:hidden": True})
    reminder_id: UUID

class DexCreateReminder(DexWrite):
    operation: Literal["create_reminder"] = Field("create_reminder", title="Create Reminder", json_schema_extra={"ui:hidden": True})
    text: str
    due_at_date: datetime
    contact_ids: list[UUID] = Field(default_factory=list)

class DexUpdateReminder(DexWrite):
    operation: Literal["update_reminder"] = Field("update_reminder", title="Update Reminder", json_schema_extra={"ui:hidden": True})
    reminder_id: UUID
    text: str | None = None
    due_at_date: datetime | None = None
    is_complete: bool | None = None

class DexDeleteReminder(DexWrite):
    operation: Literal["delete_reminder"] = Field("delete_reminder", title="Delete Reminder", json_schema_extra={"ui:hidden": True})
    reminder_id: UUID

class DexOnNewContact(PollTriggerConfigBase, DexInput):
    operation: Literal["on_new_contact"] = Field("on_new_contact", title="On New Contact", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    updated_since: datetime | None = Field(None, description="Optional UTC lower bound for contacts to monitor. Existing records form the initial baseline.")

class DexOnUpdatedContact(PollTriggerConfigBase, DexInput):
    operation: Literal["on_updated_contact"] = Field("on_updated_contact", title="On Updated Contact", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    updated_since: datetime | None = Field(None, description="Optional UTC lower bound for contacts to monitor. Existing records form the initial baseline.")

DexConfig = Annotated[Union[DexGetUser, DexListContacts, DexGetContact, DexDeleteContact, DexCreateContact, DexUpdateContact, DexListGroups, DexCreateGroup, DexListTags, DexCreateTag, DexAddContactsToGroup, DexRemoveContactsFromGroup, DexAddTagsToContacts, DexListContactNotes, DexCreateNote, DexUpdateNote, DexDeleteNote, DexListReminders, DexGetReminder, DexCreateReminder, DexUpdateReminder, DexDeleteReminder, DexOnNewContact, DexOnUpdatedContact], Field(discriminator="operation")]

class DexNodeConfig(NodeConfig[DexConfig, DexAPIKeyCredential]):
    pass


class DexNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-dex"
    connection_evidence = ConnectionEvidence(noun="Dex account", identity_operation="get_user", identity_keys=("name", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return DexNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("contacts")) if config.get("operation") in {"on_new_contact", "on_updated_contact"} else True

    @classmethod
    def resolve_agent_event(cls, output):
        if "contact_count" not in output:
            return super().resolve_agent_event(output)
        contacts = output.get("contacts", [])
        if not contacts:
            return None
        lines = [f"- {c.get('full_name') or ' '.join(filter(None, [c.get('first_name'), c.get('last_name')])) or 'Contact'} (contact id {c['id']}): {c.get('description') or ''}" for c in contacts[:20]]
        return {"text": f"Dex: {len(contacts)} {output['event']} contact(s) in the connected Dex account.\n" + "\n".join(lines), "conversation_key": None}

    async def _request(self, method, path, *, params=None, body=None, idempotency_key=None):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Dex API key")
        headers = {"Authorization": f"Bearer {credential.api_key}", "Accept": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, params=params, **({"json": body} if body is not None else {}))
        response.raise_for_status()
        if response.status_code == 204:
            return {"deleted": True}
        result = response.json()
        if not isinstance(result, dict) or "error" in result or not isinstance(result.get("data"), dict):
            raise ValueError("Dex did not return a canonical data envelope")
        return result["data"]

    @staticmethod
    def _contact_query(config):
        params = {"take": 100}
        if config.updated_since:
            params["where[has_updated_at][gte]"] = config.updated_since.isoformat().replace("+00:00", "Z")
        return params

    async def _poll_contacts(self, config):
        params = self._contact_query(config)
        contacts, cursors = [], set()
        for _ in range(100):
            data = await self._request("GET", "/v2/contacts/", params=params)
            rows = data.get("contacts")
            if not isinstance(rows, list) or any(not isinstance(c, dict) or not c.get("id") for c in rows):
                raise ValueError("Dex contact list is incomplete")
            contacts.extend(rows)
            cursor = data.get("pagination", {}).get("nextCursor")
            if not cursor:
                break
            if cursor in cursors:
                raise ValueError("Dex repeated a pagination cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        else:
            raise ValueError("More than 10,000 contacts; narrow updated_since before monitoring")
        updated = config.operation == "on_updated_contact"
        if updated and any(not c.get("updated_at") for c in contacts):
            raise ValueError("Dex omitted updated_at needed for change detection")
        fresh = await self._filter_unseen(contacts, lambda c: str(c["id"]) + (":" + str(c["updated_at"]) if updated else ""))
        return {"contacts": fresh, "contact_count": len(fresh), "event": "updated" if updated else "new"}

    async def execute(self, inputs):
        config = self.config.config
        op = config.operation
        if op in {"on_new_contact", "on_updated_contact"}:
            return await self._poll_contacts(config)
        values = config.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        key = values.pop("idempotency_key", None)
        if op == "get_user":
            return await self._request("GET", "/v2/users/me")
        if op.startswith("list_"):
            path = {"list_contacts": "/v2/contacts/", "list_groups": "/v2/groups/", "list_tags": "/v2/tags/", "list_reminders": "/v2/reminders/", "list_contact_notes": "/v2/timeline/notes"}[op]
            if op == "list_contacts":
                values.pop("updated_since", None)
                values.update(self._contact_query(config))
                values["take"] = config.take
            return await self._request("GET", path, params=values)
        if op in {"add_contacts_to_group", "remove_contacts_from_group"}:
            group = values.pop("group_id")
            path = f"/v2/groups/{quote(group, safe='')}/contacts" + ("/batch-remove" if op.startswith("remove") else "")
            return await self._request("POST", path, body={"contactIds": values["contact_ids"]}, idempotency_key=key)
        if op == "add_tags_to_contacts":
            return await self._request("POST", "/v2/tags/contacts/add", body={"contactIds": values["contact_ids"], "tagIds": values["tag_ids"]}, idempotency_key=key)
        action, entity = op.split("_", 1)
        root = {"contact": "/v2/contacts/", "group": "/v2/groups/", "tag": "/v2/tags/", "note": "/v2/timeline/notes", "reminder": "/v2/reminders/"}[entity]
        resource_id = values.pop(entity + "_id", None)
        path = root.rstrip("/") + "/" + quote(resource_id, safe="") if resource_id else root
        method = {"get": "GET", "create": "POST", "update": "PATCH", "delete": "DELETE"}[action]
        body = None
        if action in {"create", "update"}:
            if entity == "contact":
                email = values.pop("email", None)
                if email is not None:
                    values["contact_emails"] = [{"email": email}]
                body = values
            else:
                ids = values.pop("contact_ids", None)
                if ids is not None:
                    values["timeline_items_contacts" if entity == "note" else "reminders_contacts"] = [{"contact_id": i} for i in ids]
                body = {entity: values}
        return await self._request(method, path, body=body, idempotency_key=key)

"""Zenzap chat and task automation against the published v2 API.

Static key requests sign the exact transmitted URI or body. Scheduled triggers
use the provider's creation-ordered topic and message lists with scoped baselines.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://api.zenzap.co"


class ZenzapAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zenzap API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.zenzap.co/console",
        "x-credential-instructions": "In the Zenzap admin console, create a static API key bot with permissions for your operations. Paste its API key and API secret. Actions run as that bot; add it to the topics you want to automate.",
    })
    credential_type: Literal["zenzap_api_key"] = Field("zenzap_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, title="API secret", json_schema_extra={"ui:widget": "password"})


class ZenzapInput(BaseModel):
    # Saved canvas configs also carry labels and credential attachment metadata.
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def validate_update(self):
        values = self.model_dump(exclude_none=True, exclude={"operation"})
        if values.get("before") is not None and values.get("after") is not None:
            raise ValueError("Choose either before or after")
        if self.operation == "update_topic" and not ({"name", "description"} & values.keys()):
            raise ValueError("Supply a name or description")
        if self.operation == "update_task":
            if "name" in values and "title" in values:
                raise ValueError("Supply either name or title")
            if "status" in values and not values.get("topic_id"):
                raise ValueError("Topic ID is required when changing status")
            if values.get("unassign") and values.get("assignee"):
                raise ValueError("Choose an assignee or unassign the task")
            if not ({"name", "title", "description", "assignee", "due_date", "status"} & values.keys()) and not values.get("unassign"):
                raise ValueError("Supply a task field to update")
        return self


class ZenzapSendMessageConfig(ZenzapInput):
    """Send a message."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True, "x-display-name": 'Send a message', "x-is-trigger": False})
    topic_id: UUID = Field(..., title='Topic ID', description='The ID of the topic to send the message to')
    text: str = Field(..., title='Text', description='The message text content. To mention a member, use `<@profileId>` inside the text. Example: `Hello <@550e8400-e29b-41d4-a716-446655440001>` ', max_length=10000, min_length=1)
    external_id: str | None = Field(None, title='External id', description='Optional external identifier for tracking purposes', max_length=61)

class ZenzapEditMessageConfig(ZenzapInput):
    """Edit a message."""
    operation: Literal["edit_message"] = Field("edit_message", json_schema_extra={"ui:hidden": True, "x-display-name": 'Edit a message', "x-is-trigger": False})
    message_id: UUID = Field(..., title='Message ID', description='The message ID to edit')
    text: str = Field(..., title='Text', description='Updated message text (max 10000 characters)', max_length=10000, min_length=1)

class ZenzapDeleteMessageConfig(ZenzapInput):
    """Delete a message."""
    operation: Literal["delete_message"] = Field("delete_message", json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete a message', "x-is-trigger": False})
    message_id: UUID = Field(..., title='Message ID', description='The message ID to delete')

class ZenzapAddReactionConfig(ZenzapInput):
    """Add a reaction to a message."""
    operation: Literal["add_reaction"] = Field("add_reaction", json_schema_extra={"ui:hidden": True, "x-display-name": 'Add a reaction to a message', "x-is-trigger": False})
    message_id: UUID = Field(..., title='Message ID', description='The message ID to react to')
    reaction: str = Field(..., title='Reaction', description='Emoji reaction to add', min_length=1)

class ZenzapRemoveReactionConfig(ZenzapInput):
    """Remove a reaction from a message."""
    operation: Literal["remove_reaction"] = Field("remove_reaction", json_schema_extra={"ui:hidden": True, "x-display-name": 'Remove a reaction from a message', "x-is-trigger": False})
    message_id: UUID = Field(..., title='Message ID', description='The message ID the reaction belongs to')
    reaction_id: UUID = Field(..., title='Reaction id', description='The reaction ID to remove')

class ZenzapMarkMessageReadConfig(ZenzapInput):
    """Mark a message as read."""
    operation: Literal["mark_message_read"] = Field("mark_message_read", json_schema_extra={"ui:hidden": True, "x-display-name": 'Mark a message as read', "x-is-trigger": False})
    message_id: UUID = Field(..., title='Message ID', description='The message ID to mark as read')

class ZenzapListTopicsConfig(ZenzapInput):
    """List topics."""
    operation: Literal["list_topics"] = Field("list_topics", json_schema_extra={"ui:hidden": True, "x-display-name": 'List topics', "x-is-trigger": False})
    limit: int = Field(50, title='Limit', description='Maximum number of topics to return (default: 50, max: 100)', ge=1, le=100)
    cursor: str | None = Field(None, title='Cursor', description='Opaque cursor from a previous `nextCursor` value.')

class ZenzapCreateTopicConfig(ZenzapInput):
    """Create a topic."""
    operation: Literal["create_topic"] = Field("create_topic", json_schema_extra={"ui:hidden": True, "x-display-name": 'Create a topic', "x-is-trigger": False})
    name: str = Field(..., title='Name', description='The topic name', max_length=64, min_length=1)
    description: str | None = Field(None, title='Description', description='Optional topic description', max_length=10000)
    members: list[UUID] = Field(..., title='Members', description='Array of user IDs to add as topic members (max 100). Your bot will automatically be added as a member.', max_length=100)
    external_id: str | None = Field(None, title='External id', description='Optional external identifier for tracking purposes. Must be unique per bot - you cannot reuse the same external ID for multiple topics.', max_length=100)

class ZenzapGetTopicConfig(ZenzapInput):
    """Get topic details."""
    operation: Literal["get_topic"] = Field("get_topic", json_schema_extra={"ui:hidden": True, "x-display-name": 'Get topic details', "x-is-trigger": False})
    topic_id: UUID = Field(..., title='Topic ID', description='The ID of the topic to retrieve')

class ZenzapGetTopicByExternalIdConfig(ZenzapInput):
    """Get topic by external ID."""
    operation: Literal["get_topic_by_external_id"] = Field("get_topic_by_external_id", json_schema_extra={"ui:hidden": True, "x-display-name": 'Get topic by external ID', "x-is-trigger": False})
    external_id: str = Field(..., title='External id', description='The external ID of the topic to retrieve', max_length=100)

class ZenzapUpdateTopicConfig(ZenzapInput):
    """Update a topic."""
    operation: Literal["update_topic"] = Field("update_topic", json_schema_extra={"ui:hidden": True, "x-display-name": 'Update a topic', "x-is-trigger": False})
    topic_id: UUID = Field(..., title='Topic ID', description='The ID of the topic to update')
    name: str | None = Field(None, title='Name', description='The new topic name', max_length=64, min_length=1)
    description: str | None = Field(None, title='Description', description='The new topic description', max_length=10000)

class ZenzapListMessagesConfig(ZenzapInput):
    """Get topic messages."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True, "x-display-name": 'Get topic messages', "x-is-trigger": False})
    topic_id: UUID = Field(..., title='Topic ID', description='The ID of the topic to get messages from')
    limit: int = Field(50, title='Limit', description='Maximum number of messages to return (default: 50, max: 100)', ge=1, le=100)
    cursor: str | None = Field(None, title='Cursor', description='Opaque cursor for pagination. Use the value from `nextCursor` in the response. Cursors are cryptographically signed and validated server-side to prevent tampering.')
    before: int | None = Field(None, title='Before', description='Return messages created before this timestamp (Unix milliseconds). Mutually exclusive with `after`.')
    after: int | None = Field(None, title='After', description='Return messages created after this timestamp (Unix milliseconds). Mutually exclusive with `before`.')
    sender_id: str | None = Field(None, title='Sender id', description='Filter messages by sender ID')
    order: Literal['asc', 'desc'] = Field('desc', title='Order', description='Sort order for messages (default: desc - newest first)')
    include_system: bool = Field(True, title='Include system', description='Include system messages (default: true)')
    thread_id: UUID | None = Field(None, title='Thread id', description='Filter to messages within a specific thread (replies to a parent message)')
    include_reaction_users: bool = Field(False, title='Include reaction users', description='Include user IDs in reaction data (default: false, heavier payload)')

class ZenzapAddTopicMembersConfig(ZenzapInput):
    """Add members to a topic."""
    operation: Literal["add_topic_members"] = Field("add_topic_members", json_schema_extra={"ui:hidden": True, "x-display-name": 'Add members to a topic', "x-is-trigger": False})
    topic_id: UUID = Field(..., title='Topic ID', description='The ID of the topic to add members to')
    member_ids: list[UUID] = Field(..., title='Member ids', description='Array of member IDs to add to the topic (max 5). All members must be from the same organization as the bot and must not already be members of the topic. Duplicate IDs in the request are automatically removed.', max_length=5, min_length=1)

class ZenzapRemoveTopicMembersConfig(ZenzapInput):
    """Remove members from a topic."""
    operation: Literal["remove_topic_members"] = Field("remove_topic_members", json_schema_extra={"ui:hidden": True, "x-display-name": 'Remove members from a topic', "x-is-trigger": False})
    topic_id: UUID = Field(..., title='Topic ID', description='The ID of the topic to remove members from')
    member_ids: list[UUID] = Field(..., title='Member ids', description='Array of member IDs to remove from the topic (max 5). Members not in the topic are silently ignored. Duplicates are automatically removed.', max_length=5, min_length=1)

class ZenzapListTasksConfig(ZenzapInput):
    """List tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True, "x-display-name": 'List tasks', "x-is-trigger": False})
    topic_id: UUID | None = Field(None, title='Topic ID', description='Filter tasks by topic ID')
    status: Literal['Open', 'Done'] | None = Field(None, title='Status', description='Filter by task status')
    assignee: str | None = Field(None, title='Assignee', description='Filter by assignee profile ID (empty value filters unassigned tasks)')
    limit: int = Field(50, title='Limit', description='Maximum tasks to return (default 50, max 100)', ge=1, le=100)
    cursor: str | None = Field(None, title='Cursor', description='Opaque cursor from a previous `nextCursor` value.')

class ZenzapCreateTaskConfig(ZenzapInput):
    """Create a task."""
    operation: Literal["create_task"] = Field("create_task", json_schema_extra={"ui:hidden": True, "x-display-name": 'Create a task', "x-is-trigger": False})
    topic_id: UUID = Field(..., title='Topic ID', description='The ID of the topic where the task should be created')
    title: str = Field(..., title='Title', description='The task title', max_length=256, min_length=1)
    description: str | None = Field(None, title='Description', description='Optional task description', max_length=10000)
    assignee: UUID | None = Field(None, title='Assignee', description='Optional user ID to assign the task to')
    due_date: int | None = Field(None, title='Due date', description='Optional due date as Unix timestamp in milliseconds')
    external_id: str | None = Field(None, title='External id', description='Optional external identifier for tracking purposes', max_length=100)

class ZenzapGetTaskConfig(ZenzapInput):
    """Get task details."""
    operation: Literal["get_task"] = Field("get_task", json_schema_extra={"ui:hidden": True, "x-display-name": 'Get task details', "x-is-trigger": False})
    task_id: UUID = Field(..., title='Task ID', description='The task ID')

class ZenzapUpdateTaskConfig(ZenzapInput):
    """Update a task."""
    operation: Literal["update_task"] = Field("update_task", json_schema_extra={"ui:hidden": True, "x-display-name": 'Update a task', "x-is-trigger": False})
    unassign: bool = Field(False, title="Remove assignee", description="Send an empty assignee to unassign the task. Leave the assignee field unset.")
    task_id: UUID = Field(..., title='Task ID', description='The task ID to update')
    topic_id: UUID | None = Field(None, title='Topic ID', description='Required when `status` is provided.')
    name: str | None = Field(None, title='Name', description='Task title (alias of `title`). Provide either `name` or `title`.', max_length=256, min_length=1)
    title: str | None = Field(None, title='Title', description='Task title. Provide either `title` or `name`.', max_length=256, min_length=1)
    description: str | None = Field(None, title='Description', description='Task description', max_length=10000)
    assignee: str | None = Field(None, title='Assignee', description='Assignee profile ID. Empty string removes assignee.')
    due_date: int | None = Field(None, title='Due date', description='Due date as Unix timestamp in milliseconds. Set to `0` to clear.')
    status: Literal['Open', 'Done'] | None = Field(None, title='Status', description='Task status')

class ZenzapDeleteTaskConfig(ZenzapInput):
    """Delete a task."""
    operation: Literal["delete_task"] = Field("delete_task", json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete a task', "x-is-trigger": False})
    task_id: UUID = Field(..., title='Task ID', description='The task ID to delete')

class ZenzapListMembersConfig(ZenzapInput):
    """List members."""
    operation: Literal["list_members"] = Field("list_members", json_schema_extra={"ui:hidden": True, "x-display-name": 'List members', "x-is-trigger": False})
    limit: int = Field(50, title='Limit', description='Maximum number of members to return (default: 50, max: 100)', ge=1, le=100)
    cursor: str | None = Field(None, title='Cursor', description='Opaque cursor from a previous `nextCursor` value.')
    emails: str | None = Field(None, title='Emails', description='Comma-separated list of email addresses to filter members (e.g., john@example.com,jane@example.com)')

class ZenzapGetCurrentMemberConfig(ZenzapInput):
    """Get current member."""
    operation: Literal["get_current_member"] = Field("get_current_member", json_schema_extra={"ui:hidden": True, "x-display-name": 'Get current member', "x-is-trigger": False})


class ZenzapOnNewTopicConfig(PollTriggerConfigBase):
    """Watch the newest 100 topics; choose a polling interval that fits traffic."""
    operation: Literal["on_new_topic"] = Field("on_new_topic", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "New topic", "x-category": "Triggers", "description": "Poll the newest 100 topics. Use an interval with fewer than 100 new topics."})


class ZenzapOnNewMessageConfig(PollTriggerConfigBase):
    """Watch the newest 100 messages in a topic on each scheduled poll."""
    operation: Literal["on_new_message"] = Field("on_new_message", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "New message", "x-category": "Triggers", "description": "Poll the newest 100 messages in a topic. Use an interval with fewer than 100 new messages."})
    topic_id: UUID = Field(..., title="Topic ID", description="Watch messages in this topic. The bot must be a member.")

ZenzapConfig = Annotated[Union[ZenzapSendMessageConfig, ZenzapEditMessageConfig, ZenzapDeleteMessageConfig, ZenzapAddReactionConfig, ZenzapRemoveReactionConfig, ZenzapMarkMessageReadConfig, ZenzapListTopicsConfig, ZenzapCreateTopicConfig, ZenzapGetTopicConfig, ZenzapGetTopicByExternalIdConfig, ZenzapUpdateTopicConfig, ZenzapListMessagesConfig, ZenzapAddTopicMembersConfig, ZenzapRemoveTopicMembersConfig, ZenzapListTasksConfig, ZenzapCreateTaskConfig, ZenzapGetTaskConfig, ZenzapUpdateTaskConfig, ZenzapDeleteTaskConfig, ZenzapListMembersConfig, ZenzapGetCurrentMemberConfig, ZenzapOnNewTopicConfig, ZenzapOnNewMessageConfig], Field(discriminator="operation")]


class ZenzapNodeConfig(NodeConfig[ZenzapConfig, ZenzapAPIKeyCredential]):
    pass


OPERATIONS = {'send_message': {'method': 'POST',
                  'path': '/v2/messages',
                  'path_fields': {},
                  'query': {},
                  'body': {'topic_id': 'topicId', 'text': 'text', 'external_id': 'externalId'}},
 'edit_message': {'method': 'PATCH',
                  'path': '/v2/messages/{messageId}',
                  'path_fields': {'message_id': 'messageId'},
                  'query': {},
                  'body': {'text': 'text'}},
 'delete_message': {'method': 'DELETE',
                    'path': '/v2/messages/{messageId}',
                    'path_fields': {'message_id': 'messageId'},
                    'query': {},
                    'body': {}},
 'add_reaction': {'method': 'POST',
                  'path': '/v2/messages/{messageId}/reactions',
                  'path_fields': {'message_id': 'messageId'},
                  'query': {},
                  'body': {'reaction': 'reaction'}},
 'remove_reaction': {'method': 'DELETE',
                     'path': '/v2/messages/{messageId}/reactions/{reactionId}',
                     'path_fields': {'message_id': 'messageId', 'reaction_id': 'reactionId'},
                     'query': {},
                     'body': {}},
 'mark_message_read': {'method': 'POST',
                       'path': '/v2/messages/{messageId}/read',
                       'path_fields': {'message_id': 'messageId'},
                       'query': {},
                       'body': {}},
 'list_topics': {'method': 'GET',
                 'path': '/v2/topics',
                 'path_fields': {},
                 'query': {'limit': 'limit', 'cursor': 'cursor'},
                 'body': {}},
 'create_topic': {'method': 'POST',
                  'path': '/v2/topics',
                  'path_fields': {},
                  'query': {},
                  'body': {'name': 'name',
                           'description': 'description',
                           'members': 'members',
                           'external_id': 'externalId'}},
 'get_topic': {'method': 'GET',
               'path': '/v2/topics/{topicId}',
               'path_fields': {'topic_id': 'topicId'},
               'query': {},
               'body': {}},
 'get_topic_by_external_id': {'method': 'GET',
                              'path': '/v2/topics/external/{externalId}',
                              'path_fields': {'external_id': 'externalId'},
                              'query': {},
                              'body': {}},
 'update_topic': {'method': 'PATCH',
                  'path': '/v2/topics/{topicId}',
                  'path_fields': {'topic_id': 'topicId'},
                  'query': {},
                  'body': {'name': 'name', 'description': 'description'}},
 'list_messages': {'method': 'GET',
                   'path': '/v2/topics/{topicId}/messages',
                   'path_fields': {'topic_id': 'topicId'},
                   'query': {'limit': 'limit',
                             'cursor': 'cursor',
                             'before': 'before',
                             'after': 'after',
                             'sender_id': 'senderId',
                             'order': 'order',
                             'include_system': 'includeSystem',
                             'thread_id': 'threadId',
                             'include_reaction_users': 'includeReactionUsers'},
                   'body': {}},
 'add_topic_members': {'method': 'POST',
                       'path': '/v2/topics/{topicId}/members',
                       'path_fields': {'topic_id': 'topicId'},
                       'query': {},
                       'body': {'member_ids': 'memberIds'}},
 'remove_topic_members': {'method': 'DELETE',
                          'path': '/v2/topics/{topicId}/members',
                          'path_fields': {'topic_id': 'topicId'},
                          'query': {},
                          'body': {'member_ids': 'memberIds'}},
 'list_tasks': {'method': 'GET',
                'path': '/v2/tasks',
                'path_fields': {},
                'query': {'topic_id': 'topicId',
                          'status': 'status',
                          'assignee': 'assignee',
                          'limit': 'limit',
                          'cursor': 'cursor'},
                'body': {}},
 'create_task': {'method': 'POST',
                 'path': '/v2/tasks',
                 'path_fields': {},
                 'query': {},
                 'body': {'topic_id': 'topicId',
                          'title': 'title',
                          'description': 'description',
                          'assignee': 'assignee',
                          'due_date': 'dueDate',
                          'external_id': 'externalId'}},
 'get_task': {'method': 'GET',
              'path': '/v2/tasks/{taskId}',
              'path_fields': {'task_id': 'taskId'},
              'query': {},
              'body': {}},
 'update_task': {'method': 'PATCH',
                 'path': '/v2/tasks/{taskId}',
                 'path_fields': {'task_id': 'taskId'},
                 'query': {},
                 'body': {'topic_id': 'topicId',
                          'name': 'name',
                          'title': 'title',
                          'description': 'description',
                          'assignee': 'assignee',
                          'due_date': 'dueDate',
                          'status': 'status'}},
 'delete_task': {'method': 'DELETE',
                 'path': '/v2/tasks/{taskId}',
                 'path_fields': {'task_id': 'taskId'},
                 'query': {},
                 'body': {}},
 'list_members': {'method': 'GET',
                  'path': '/v2/members',
                  'path_fields': {},
                  'query': {'limit': 'limit', 'cursor': 'cursor', 'emails': 'emails'},
                  'body': {}},
 'get_current_member': {'method': 'GET',
                        'path': '/v2/members/me',
                        'path_fields': {},
                        'query': {},
                        'body': {}}}


class ZenzapNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-zenzap"
    connection_evidence = ConnectionEvidence(
        noun="topics", operation="list_topics", identity_operation="get_current_member",
        identity_keys=("name", "email"),
    )

    @classmethod
    def get_config_model(cls):
        return ZenzapNodeConfig

    @classmethod
    def resolve_agent_event(cls, output):
        messages = output.get("messages", [])
        topics = output.get("topics", [])
        if messages:
            text = "\n\n".join(
                f"New Zenzap message from {row.get('senderName') or row.get('senderId') or 'a member'} "
                f"in topic {row.get('topicId')}: {row.get('text') or '[' + str(row.get('type', 'message')) + ']'}\n"
                f"Message ID: {row['id']}; sender ID: {row.get('senderId')}; topic ID: {row.get('topicId')}"
                for row in messages
            )
            topic_ids = {row.get("topicId") for row in messages}
            conversation = str(messages[0].get("topicId")) if len(topic_ids) == 1 else None
            return {"text": text[:32000], "conversation_key": conversation, "title": "New Zenzap message"}
        if topics:
            text = "\n\n".join(
                f"New Zenzap topic: {row.get('name', 'Unnamed topic')}\n"
                f"{row.get('description', '')}\nTopic ID: {row['id']}" for row in topics
            )
            return {"text": text[:32000], "conversation_key": None, "title": "New Zenzap topic"}
        return None

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Zenzap API key and secret")
        content = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        # Build once: the bytes signed are exactly the bytes httpx transmits,
        # including query escaping and a DELETE body when the endpoint needs it.
        request = httpx.Request(method, BASE_URL + path, params=params, content=content)
        timestamp = str(int(time.time() * 1000))
        payload = request.url.raw_path if method == "GET" else content
        signature = hmac.new(credential.api_secret.encode(), timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
        request.headers.update({
            "Authorization": "Bearer " + credential.api_key,
            "X-Timestamp": timestamp, "X-Signature": signature,
            "Content-Type": "application/json", "Accept": "application/json",
        })
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.send(request)
        if response.status_code >= 300:
            # Keep provider rejection text, but never echo either pasted secret.
            detail = response.text
            for secret in (credential.api_key, credential.api_secret):
                detail = detail.replace(secret, "[redacted]")
            raise ValueError(f"Zenzap HTTP {response.status_code}: {detail[:1500]}")
        return response.json() if response.content else {}

    async def _perform(self, config):
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for field, wire in spec["path_fields"].items():
            path = path.replace("{" + wire + "}", quote(str(values[field]), safe=""))
        params = {wire: values[field] for field, wire in spec["query"].items() if field in values}
        body = {wire: values[field] for field, wire in spec["body"].items() if field in values}
        if config.operation == "update_task" and values.get("unassign"):
            body["assignee"] = ""
        return await self._request(spec["method"], path, params=params or None, body=body if spec["body"] else None)

    async def _poll(self, config):
        messages = config.operation == "on_new_message"
        key = "messages" if messages else "topics"
        path = f"/v2/topics/{config.topic_id}/messages" if messages else "/v2/topics"
        params = {"limit": 100, **({"order": "desc"} if messages else {})}
        # A bounded, creation-ordered window avoids replaying the entire chat
        # history on every scheduled tick. The window and older-page flag are
        # explicit in the result; use an interval with fewer than 100 new items.
        data = await self._request("GET", path, params=params)
        rows = data.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("id") for row in rows):
            raise ValueError(f"Zenzap returned an invalid {key} page")
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
        return {"status": "success", key: fresh, "data": fresh, "new_count": len(fresh),
                "window_limit": 100, "has_older_items": data.get("hasMore", False)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Zenzap API key and secret")
        config = self.config.config
        if isinstance(config, (ZenzapOnNewTopicConfig, ZenzapOnNewMessageConfig)):
            return await self._poll(config)
        data = await self._perform(config)
        return {"status": "success", "operation": config.operation, "data": data}

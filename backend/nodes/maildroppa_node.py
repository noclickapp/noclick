"""Maildroppa API 1.2.0: subscriber, tag, topic and segment automation.

Contract: https://api.maildroppa.com/openapi. Each operation makes one request.
List operations return the provider page intact; pageNumber starts at one.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.maildroppa.com"
SubscriberStatus = Literal["PENDING", "CONFIRMED", "UNSUBSCRIBED", "COLD", "BOUNCED", "SOFT_BOUNCED", "BLOCKED", "DELETED"]


class MaildroppaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Maildroppa API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://api.maildroppa.com/",
            "x-credential-instructions": "Copy your API token from UserProfile in the Maildroppa app. Accept the customer agreements in the app before using API keys. Paste the token below; NoClick sends it as X-API-Key."})
    credential_type: Literal["maildroppa_api_key"] = Field("maildroppa_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListSubscribersConfig(_Input):
    operation: Literal["list_subscribers"] = Field("list_subscribers", json_schema_extra={"ui:hidden": True})
    pageNumber: int = Field(1, ge=1)
    pageSize: int = Field(100, ge=1, le=100)
    query: Optional[str] = None
    status: Optional[SubscriberStatus] = None

class GetSubscriberConfig(_Input):
    operation: Literal["get_subscriber"] = Field("get_subscriber", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID

class CreateSubscriberConfig(_Input):
    operation: Literal["create_subscriber"] = Field("create_subscriber", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3)
    firstName: Optional[str] = None
    tags: Optional[list[UUID]] = None
    subscriberStatus: Optional[SubscriberStatus] = None
    topicIds: Optional[list[UUID]] = None

class DeleteSubscriberConfig(_Input):
    operation: Literal["delete_subscriber"] = Field("delete_subscriber", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID

class CountSubscribersConfig(_Input):
    operation: Literal["count_subscribers"] = Field("count_subscribers", json_schema_extra={"ui:hidden": True})
    status: Optional[SubscriberStatus] = None

class UpdateSubscriberEmailConfig(_Input):
    operation: Literal["update_subscriber_email"] = Field("update_subscriber_email", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID
    email: str = Field(..., min_length=3)

class UpdateSubscriberFirstNameConfig(_Input):
    operation: Literal["update_subscriber_first_name"] = Field("update_subscriber_first_name", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID
    firstName: Optional[str] = Field(..., description="New first name; null clears it")

class UpdateSubscriberStatusConfig(_Input):
    operation: Literal["update_subscriber_status"] = Field("update_subscriber_status", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID
    subscriberStatus: SubscriberStatus

class AssignSubscriberTagConfig(_Input):
    operation: Literal["assign_subscriber_tag"] = Field("assign_subscriber_tag", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID
    tagId: UUID

class RemoveSubscriberTagConfig(_Input):
    operation: Literal["remove_subscriber_tag"] = Field("remove_subscriber_tag", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID
    tagId: UUID

class ListTagsConfig(_Input):
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    includeArchived: bool = False

class CreateTagConfig(_Input):
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)

class RenameTagConfig(_Input):
    operation: Literal["rename_tag"] = Field("rename_tag", json_schema_extra={"ui:hidden": True})
    tagId: UUID
    name: str = Field(..., min_length=1)

class ArchiveTagConfig(_Input):
    operation: Literal["archive_tag"] = Field("archive_tag", json_schema_extra={"ui:hidden": True})
    tagId: UUID

class RestoreTagConfig(_Input):
    operation: Literal["restore_tag"] = Field("restore_tag", json_schema_extra={"ui:hidden": True})
    tagId: UUID

class ListTopicsConfig(_Input):
    operation: Literal["list_topics"] = Field("list_topics", json_schema_extra={"ui:hidden": True})
    includeArchived: bool = False

class CreateTopicConfig(_Input):
    operation: Literal["create_topic"] = Field("create_topic", json_schema_extra={"ui:hidden": True})
    label: str = Field(..., min_length=1)
    description: Optional[str] = None
    enrollExistingSubscribers: bool = False

class UpdateTopicConfig(_Input):
    operation: Literal["update_topic"] = Field("update_topic", json_schema_extra={"ui:hidden": True})
    topicId: UUID
    label: str = Field(..., min_length=1)
    description: Optional[str] = None

class ArchiveTopicConfig(_Input):
    operation: Literal["archive_topic"] = Field("archive_topic", json_schema_extra={"ui:hidden": True})
    topicId: UUID

class GetSubscriberTopicsConfig(_Input):
    operation: Literal["get_subscriber_topics"] = Field("get_subscriber_topics", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID

class ReplaceSubscriberTopicsConfig(_Input):
    operation: Literal["replace_subscriber_topics"] = Field("replace_subscriber_topics", json_schema_extra={"ui:hidden": True})
    subscriberId: UUID
    topicIds: list[UUID]
    overrideOptOuts: bool = False

class ListFieldsConfig(_Input):
    operation: Literal["list_fields"] = Field("list_fields", json_schema_extra={"ui:hidden": True})

class ListSegmentsConfig(_Input):
    operation: Literal["list_segments"] = Field("list_segments", json_schema_extra={"ui:hidden": True})

class GetSegmentConfig(_Input):
    operation: Literal["get_segment"] = Field("get_segment", json_schema_extra={"ui:hidden": True})
    segmentId: UUID

MaildroppaConfig = Annotated[Union[ListSubscribersConfig, GetSubscriberConfig, CreateSubscriberConfig, DeleteSubscriberConfig, CountSubscribersConfig, UpdateSubscriberEmailConfig, UpdateSubscriberFirstNameConfig, UpdateSubscriberStatusConfig, AssignSubscriberTagConfig, RemoveSubscriberTagConfig, ListTagsConfig, CreateTagConfig, RenameTagConfig, ArchiveTagConfig, RestoreTagConfig, ListTopicsConfig, CreateTopicConfig, UpdateTopicConfig, ArchiveTopicConfig, GetSubscriberTopicsConfig, ReplaceSubscriberTopicsConfig, ListFieldsConfig, ListSegmentsConfig, GetSegmentConfig], Field(discriminator="operation")]

ROUTES = {'list_subscribers': {'method': 'GET',
                      'path': '/subscribers',
                      'path_fields': [],
                      'query_fields': ['pageNumber', 'pageSize', 'query', 'status'],
                      'body_fields': []},
 'get_subscriber': {'method': 'GET',
                    'path': '/subscribers/{subscriberId}',
                    'path_fields': ['subscriberId'],
                    'query_fields': [],
                    'body_fields': []},
 'create_subscriber': {'method': 'POST',
                       'path': '/subscribers',
                       'path_fields': [],
                       'query_fields': [],
                       'body_fields': ['email',
                                       'firstName',
                                       'tags',
                                       'subscriberStatus',
                                       'topicIds']},
 'delete_subscriber': {'method': 'DELETE',
                       'path': '/subscribers/{subscriberId}',
                       'path_fields': ['subscriberId'],
                       'query_fields': [],
                       'body_fields': []},
 'count_subscribers': {'method': 'GET',
                       'path': '/subscribers/count',
                       'path_fields': [],
                       'query_fields': ['status'],
                       'body_fields': []},
 'update_subscriber_email': {'method': 'PUT',
                             'path': '/subscribers/{subscriberId}/email',
                             'path_fields': ['subscriberId'],
                             'query_fields': [],
                             'body_fields': ['email']},
 'update_subscriber_first_name': {'method': 'PUT',
                                  'path': '/subscribers/{subscriberId}/first-name',
                                  'path_fields': ['subscriberId'],
                                  'query_fields': [],
                                  'body_fields': ['firstName']},
 'update_subscriber_status': {'method': 'PUT',
                              'path': '/subscribers/{subscriberId}/status',
                              'path_fields': ['subscriberId'],
                              'query_fields': [],
                              'body_fields': ['subscriberStatus']},
 'assign_subscriber_tag': {'method': 'PUT',
                           'path': '/subscribers/{subscriberId}/tags/{tagId}',
                           'path_fields': ['subscriberId', 'tagId'],
                           'query_fields': [],
                           'body_fields': []},
 'remove_subscriber_tag': {'method': 'DELETE',
                           'path': '/subscribers/{subscriberId}/tags/{tagId}',
                           'path_fields': ['subscriberId', 'tagId'],
                           'query_fields': [],
                           'body_fields': []},
 'list_tags': {'method': 'GET',
               'path': '/tags',
               'path_fields': [],
               'query_fields': ['includeArchived'],
               'body_fields': []},
 'create_tag': {'method': 'POST',
                'path': '/tags',
                'path_fields': [],
                'query_fields': [],
                'body_fields': ['name']},
 'rename_tag': {'method': 'PUT',
                'path': '/tags/{tagId}',
                'path_fields': ['tagId'],
                'query_fields': [],
                'body_fields': ['name']},
 'archive_tag': {'method': 'POST',
                 'path': '/tags/{tagId}/archive',
                 'path_fields': ['tagId'],
                 'query_fields': [],
                 'body_fields': []},
 'restore_tag': {'method': 'POST',
                 'path': '/tags/{tagId}/restore',
                 'path_fields': ['tagId'],
                 'query_fields': [],
                 'body_fields': []},
 'list_topics': {'method': 'GET',
                 'path': '/topics',
                 'path_fields': [],
                 'query_fields': ['includeArchived'],
                 'body_fields': []},
 'create_topic': {'method': 'POST',
                  'path': '/topics',
                  'path_fields': [],
                  'query_fields': [],
                  'body_fields': ['label', 'description', 'enrollExistingSubscribers']},
 'update_topic': {'method': 'PUT',
                  'path': '/topics/{topicId}',
                  'path_fields': ['topicId'],
                  'query_fields': [],
                  'body_fields': ['label', 'description']},
 'archive_topic': {'method': 'POST',
                   'path': '/topics/{topicId}/archive',
                   'path_fields': ['topicId'],
                   'query_fields': [],
                   'body_fields': []},
 'get_subscriber_topics': {'method': 'GET',
                           'path': '/subscribers/{subscriberId}/topics',
                           'path_fields': ['subscriberId'],
                           'query_fields': [],
                           'body_fields': []},
 'replace_subscriber_topics': {'method': 'PUT',
                               'path': '/subscribers/{subscriberId}/topics',
                               'path_fields': ['subscriberId'],
                               'query_fields': [],
                               'body_fields': ['topicIds', 'overrideOptOuts']},
 'list_fields': {'method': 'GET',
                 'path': '/fields',
                 'path_fields': [],
                 'query_fields': [],
                 'body_fields': []},
 'list_segments': {'method': 'GET',
                   'path': '/segments',
                   'path_fields': [],
                   'query_fields': [],
                   'body_fields': []},
 'get_segment': {'method': 'GET',
                 'path': '/segments/{segmentId}',
                 'path_fields': ['segmentId'],
                 'query_fields': [],
                 'body_fields': []}}


class MaildroppaFullConfig(NodeConfig[MaildroppaConfig, MaildroppaAPIKeyCredential]):
    pass


class MaildroppaNode(WorkflowNode):
    integration_type = "automation-maildroppa"
    connection_evidence = ConnectionEvidence(noun="tags", operation="list_tags", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return MaildroppaFullConfig

    async def execute(self, input_data):
        if not self.config.credentials:
            raise ValueError("Connect a Maildroppa API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        # The first-name endpoint explicitly accepts null to clear the value.
        if config.operation == "update_subscriber_first_name":
            values["firstName"] = config.firstName
        path = route["path"]
        for name in route["path_fields"]:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {k: str(values[k]).lower() if isinstance(values[k], bool) else values[k]
                  for k in route["query_fields"] if k in values}
        body = {k: values[k] for k in route["body_fields"] if k in values}
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(route["method"], BASE + path,
                    headers={"X-API-Key": key, "Accept": "application/json"}, params=params,
                    **({"json": body} if route["body_fields"] else {}))
            if not 200 <= response.status_code < 300:
                message = response.text[:2000].replace(key, "[redacted]")
                return {"status": "error", "http_status": response.status_code, "message": message}
            if len(response.content) > 10_000_000:
                raise ValueError("Maildroppa response exceeds the size limit")
            data = response.json() if response.content else None
            result = {"status": "success", "data": data, "http_status": response.status_code}
            if config.operation == "list_tags" and isinstance(data, list):
                result["items"] = data
            return result
        except httpx.HTTPError:
            return {"status": "error", "message": "Maildroppa request could not be completed; inspect writes before retrying"}

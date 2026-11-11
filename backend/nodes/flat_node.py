"""Flat music notation API, pinned to Flat OpenAPI 2.26.2.
Personal token setup: https://flat.io/developers/docs/api/authentication
"""
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit, parse_qs
import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://api.flat.io/v2"

class FlatCredential(BaseModel):
    model_config = ConfigDict(title="Flat Personal Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://flat.io/developers/apps",
        "x-credential-instructions": "Create an app, then REST API > Personal tokens. Select account.public_profile, collections, scores and scores.social. Paste the personal token below.",
    })
    credential_type: Literal["flat_token"] = Field("flat_token")
    access_token: str = Field(..., min_length=1, title="Personal access token", json_schema_extra={"ui:widget": "password"})

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ListCollectionsConfig(Input):
    operation: Literal["list_collections"] = Field("list_collections", title='List the collections', json_schema_extra={"ui:hidden": True})
    parent: str = "user"
    sort: Literal["creationDate", "modificationDate", "title"] = "modificationDate"
    direction: Literal["asc", "desc"] = "desc"
    limit: int = Field(25, ge=1, le=100)
    next: Optional[str] = None

class CreateCollectionConfig(Input):
    operation: Literal["createCollection"] = Field("createCollection", title='Create a new collection', json_schema_extra={"ui:hidden": True})
    title: str = Field(..., min_length=1, max_length=300)
    privacy: Literal["private", "privateLink", "public"] = "private"

class GetCollectionConfig(Input):
    operation: Literal["getCollection"] = Field("getCollection", title='Get collection details', json_schema_extra={"ui:hidden": True})
    collection: str = Field(..., min_length=1, max_length=256)

class EditCollectionConfig(Input):
    operation: Literal["editCollection"] = Field("editCollection", title="Update a collection's metadata", json_schema_extra={"ui:hidden": True})
    collection: str = Field(..., min_length=1, max_length=256)
    title: str = Field(..., min_length=1, max_length=300)

class DeleteCollectionConfig(Input):
    operation: Literal["deleteCollection"] = Field("deleteCollection", title='Delete the collection', json_schema_extra={"ui:hidden": True})
    collection: str = Field(..., min_length=1, max_length=256)

class UntrashCollectionConfig(Input):
    operation: Literal["untrashCollection"] = Field("untrashCollection", title='Untrash a collection', json_schema_extra={"ui:hidden": True})
    collection: str = Field(..., min_length=1, max_length=256)

class ListCollectionScoresConfig(Input):
    operation: Literal["listCollectionScores"] = Field("listCollectionScores", title='List the scores contained in a collection', json_schema_extra={"ui:hidden": True})
    collection: str = Field(..., min_length=1, max_length=256)
    sort: Literal["creationDate", "modificationDate", "title"] = "modificationDate"
    direction: Literal["asc", "desc"] = "desc"
    limit: int = Field(25, ge=1, le=100)
    next: Optional[str] = None

class AddScoreToCollectionConfig(Input):
    operation: Literal["addScoreToCollection"] = Field("addScoreToCollection", title='Add a score to the collection', json_schema_extra={"ui:hidden": True})
    collection: str = Field(..., min_length=1, max_length=256)
    score: str = Field(..., min_length=1, max_length=256)

class DeleteScoreFromCollectionConfig(Input):
    operation: Literal["deleteScoreFromCollection"] = Field("deleteScoreFromCollection", title='Delete a score from the collection', json_schema_extra={"ui:hidden": True})
    collection: str = Field(..., min_length=1, max_length=256)
    score: str = Field(..., min_length=1, max_length=256)

class GetAuthenticatedUserConfig(Input):
    operation: Literal["get_authenticated_user"] = Field("get_authenticated_user", title='Get current user account', json_schema_extra={"ui:hidden": True})

class GetScoreConfig(Input):
    operation: Literal["getScore"] = Field("getScore", title="Get a score's metadata", json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)

class EditScoreConfig(Input):
    operation: Literal["editScore"] = Field("editScore", title="Edit a score's metadata", json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)
    title: str = Field(..., min_length=1)
    composer: Optional[str] = None
    description: Optional[str] = Field(None, max_length=2000)

class DeleteScoreConfig(Input):
    operation: Literal["deleteScore"] = Field("deleteScore", title='Delete a score', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)

class UntrashScoreConfig(Input):
    operation: Literal["untrashScore"] = Field("untrashScore", title='Untrash a score', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)

class ForkScoreConfig(Input):
    operation: Literal["forkScore"] = Field("forkScore", title='Fork a score', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)
    collection: Optional[str] = None
    keepOriginalTitle: bool = False

class GetScoreCollaboratorsConfig(Input):
    operation: Literal["getScoreCollaborators"] = Field("getScoreCollaborators", title='List the collaborators', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)

class AddScoreCollaboratorConfig(Input):
    operation: Literal["addScoreCollaborator"] = Field("addScoreCollaborator", title='Add a new collaborator', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)
    user: str = Field(..., min_length=1)
    aclRead: bool = True
    aclWrite: bool = False
    aclAdmin: bool = False

class RemoveScoreCollaboratorConfig(Input):
    operation: Literal["removeScoreCollaborator"] = Field("removeScoreCollaborator", title='Delete a collaborator', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)
    collaborator: str = Field(..., min_length=1, max_length=256)

class GetScoreCommentsConfig(Input):
    operation: Literal["getScoreComments"] = Field("getScoreComments", title='List comments', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)

class PostScoreCommentConfig(Input):
    operation: Literal["postScoreComment"] = Field("postScoreComment", title='Post a new comment', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)
    comment: str = Field(..., min_length=1, description="Plain text without mention markup")

class UpdateScoreCommentConfig(Input):
    operation: Literal["updateScoreComment"] = Field("updateScoreComment", title='Update an existing comment', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)
    comment_id: str = Field(..., min_length=1, max_length=256)
    text: str = Field(..., min_length=1, max_length=10000)

class DeleteScoreCommentConfig(Input):
    operation: Literal["deleteScoreComment"] = Field("deleteScoreComment", title='Delete a comment', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)
    comment_id: str = Field(..., min_length=1, max_length=256)

class GetScoreRevisionsConfig(Input):
    operation: Literal["getScoreRevisions"] = Field("getScoreRevisions", title='List the revisions', json_schema_extra={"ui:hidden": True})
    score: str = Field(..., min_length=1, max_length=256)

class OnUpdatedScoreConfig(PollTriggerConfigBase):
    operation: Literal["on_updated_score"] = Field("on_updated_score", title="New or Updated Score", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    collection: str = Field("allScores", description="Collection ID or allScores for the full account library")

class OnUpdatedCollectionConfig(PollTriggerConfigBase):
    operation: Literal["on_updated_collection"] = Field("on_updated_collection", title="New or Updated Collection", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    parent: str = Field("user")

FlatConfig = Annotated[Union[ListCollectionsConfig, CreateCollectionConfig, GetCollectionConfig, EditCollectionConfig, DeleteCollectionConfig, UntrashCollectionConfig, ListCollectionScoresConfig, AddScoreToCollectionConfig, DeleteScoreFromCollectionConfig, GetAuthenticatedUserConfig, GetScoreConfig, EditScoreConfig, DeleteScoreConfig, UntrashScoreConfig, ForkScoreConfig, GetScoreCollaboratorsConfig, AddScoreCollaboratorConfig, RemoveScoreCollaboratorConfig, GetScoreCommentsConfig, PostScoreCommentConfig, UpdateScoreCommentConfig, DeleteScoreCommentConfig, GetScoreRevisionsConfig, OnUpdatedScoreConfig, OnUpdatedCollectionConfig], Field(discriminator="operation")]

class FlatNodeConfig(NodeConfig[FlatConfig, FlatCredential]):
    pass

ROUTES = {'list_collections': ('GET', '/collections'), 'createCollection': ('POST', '/collections'), 'getCollection': ('GET', '/collections/{collection}'), 'editCollection': ('PUT', '/collections/{collection}'), 'deleteCollection': ('DELETE', '/collections/{collection}'), 'untrashCollection': ('POST', '/collections/{collection}/untrash'), 'listCollectionScores': ('GET', '/collections/{collection}/scores'), 'addScoreToCollection': ('PUT', '/collections/{collection}/scores/{score}'), 'deleteScoreFromCollection': ('DELETE', '/collections/{collection}/scores/{score}'), 'get_authenticated_user': ('GET', '/me'), 'getScore': ('GET', '/scores/{score}'), 'editScore': ('PUT', '/scores/{score}'), 'deleteScore': ('DELETE', '/scores/{score}'), 'untrashScore': ('POST', '/scores/{score}/untrash'), 'forkScore': ('POST', '/scores/{score}/fork'), 'getScoreCollaborators': ('GET', '/scores/{score}/collaborators'), 'addScoreCollaborator': ('POST', '/scores/{score}/collaborators'), 'removeScoreCollaborator': ('DELETE', '/scores/{score}/collaborators/{collaborator}'), 'getScoreComments': ('GET', '/scores/{score}/comments'), 'postScoreComment': ('POST', '/scores/{score}/comments'), 'updateScoreComment': ('PUT', '/scores/{score}/comments/{comment}'), 'deleteScoreComment': ('DELETE', '/scores/{score}/comments/{comment}'), 'getScoreRevisions': ('GET', '/scores/{score}/revisions')}

class FlatNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-flat"
    connection_evidence = ConnectionEvidence(operation="list_collections", noun="collections", label_keys=("title",), identity_operation="get_authenticated_user", identity_keys=("name", "username"))

    @classmethod
    def get_config_model(cls):
        return FlatNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("items")) if config.get("operation", "").startswith("on_") else True

    @classmethod
    def resolve_agent_event(cls, output):
        items = output.get("items", [])
        if not items:
            return None
        lines = ["New or updated Flat music resources:"]
        for item in items:
            lines.append(f"{item.get('title') or item['id']} (id={item['id']}) at {item.get('modificationDate') or item.get('creationDate')}: {item.get('htmlUrl', '')}")
        lines.append("Use getScore or getCollection with the resource id to inspect it before acting.")
        return {"text": "\n".join(lines), "title": "Flat music resources updated"}

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, params=params, **({"json": body} if body is not None else {}))
        if response.is_error:
            try:
                message = response.json().get("message", "Request rejected")
            except (ValueError, AttributeError):
                message = "Request rejected"
            raise ValueError(f"Flat API {response.status_code}: {str(message).replace(token, '[redacted]')}")
        data = response.json() if response.content else {"success": True}
        cursor = None
        for link in response.headers.get("link", "").split(","):
            if 'rel="next"' in link:
                target = urlsplit(link.split("<", 1)[-1].split(">", 1)[0])
                cursor = parse_qs(target.query).get("next", [None])[0]
        return data, cursor

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Flat personal token")
        config = self.config.config
        name = config.operation
        token = credential.access_token
        if name.startswith("on_"):
            if name == "on_updated_score":
                path = "/collections/" + quote(config.collection, safe="") + "/scores"
                params = {"sort": "modificationDate", "direction": "desc", "limit": 100}
            else:
                path = "/collections"
                params = {"parent": config.parent, "sort": "modificationDate", "direction": "desc", "limit": 100}
            items, seen_cursors = [], set()
            for _ in range(100):
                data, cursor = await self._request(token, "GET", path, params=params)
                if not isinstance(data, list):
                    raise ValueError("Flat list response must be an array")
                items.extend(data)
                if not cursor:
                    break
                if cursor in seen_cursors:
                    raise ValueError("Flat repeated a pagination cursor")
                seen_cursors.add(cursor)
                params["next"] = cursor
            else:
                raise ValueError("Flat poll exceeds 100 pages; choose a smaller collection")
            def key(item):
                return str(item["id"]) + ":" + str(item.get("modificationDate") or item["creationDate"])
            fresh = await self._filter_unseen(items, key)
            return {"items": fresh, "count": len(fresh)}
        method, path = ROUTES[name]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for field in re.findall(r"{(.*?)}", path):
            key = "comment_id" if field == "comment" else field
            path = path.replace("{" + field + "}", quote(str(values.pop(key)), safe=""))
        if name == "updateScoreComment":
            values["comment"] = values.pop("text")
        if name in {"postScoreComment", "updateScoreComment"} and "@[" in values["comment"]:
            raise ValueError("Use plain text without mention markup")
        data, cursor = await self._request(token, method, path, params=values if method == "GET" else None, body=values if method in {"POST", "PUT"} and values else None)
        return {"data": data, "next_cursor": cursor}

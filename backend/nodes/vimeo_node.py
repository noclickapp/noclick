"""Vimeo API 3.4: personal access token operations, one request per operation.

Contract: https://github.com/vimeo/openapi/blob/master/api.yaml
Personal tokens: https://developer.vimeo.com/api/authentication
"""
from typing import Annotated, Literal, Union
import re
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class VimeoTokenCredential(BaseModel):
    model_config = ConfigDict(title="Vimeo Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.vimeo.com/apps",
            "x-credential-instructions": "Create an authenticated personal access token for your Vimeo account in your app's Authentication tab. Enable public and private for reads, edit for updates, create for folders, delete for deletions and removing folder members, and interact for adding folder members, posting comments and likes as needed. Paste the token below. Account reads verify identity, not every write permission."})
    credential_type: Literal["vimeo_token"] = Field("vimeo_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Personal access token", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GetAccount(Input):
    """Get a user"""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})

class ListVideos(Input):
    """Get all the videos that a user has uploaded"""
    operation: Literal["list_videos"] = Field("list_videos", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description="Page number; increment to read another page")
    per_page: int = Field(25, ge=1, le=100)
    query: str | None = Field(None, description="Search your videos")

class GetVideo(Input):
    """Get a specific video"""
    operation: Literal["get_video"] = Field("get_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")

class UpdateVideo(Input):
    """Edit a video"""
    operation: Literal["update_video"] = Field("update_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")
    name: str = Field(..., min_length=1, description="New name")
    description: str | None = None

class DeleteVideo(Input):
    """Delete a video"""
    operation: Literal["delete_video"] = Field("delete_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")

class ListComments(Input):
    """Get all the comments on a video"""
    operation: Literal["list_comments"] = Field("list_comments", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")
    page: int = Field(1, ge=1, description="Page number; increment to read another page")
    per_page: int = Field(25, ge=1, le=100)

class CreateComment(Input):
    """Add a comment to a video"""
    operation: Literal["create_comment"] = Field("create_comment", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")
    text: str = Field(..., min_length=1, description="Comment text")

class GetComment(Input):
    """Get a specific video comment"""
    operation: Literal["get_comment"] = Field("get_comment", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")
    comment_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric comment id")

class UpdateComment(Input):
    """Edit a video comment"""
    operation: Literal["update_comment"] = Field("update_comment", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")
    comment_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric comment id")
    text: str = Field(..., min_length=1, description="Comment text")

class DeleteComment(Input):
    """Delete a video comment"""
    operation: Literal["delete_comment"] = Field("delete_comment", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")
    comment_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric comment id")

class ListFolders(Input):
    """Get all the projects that belong to a user"""
    operation: Literal["list_folders"] = Field("list_folders", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, description="Page number; increment to read another page")
    per_page: int = Field(25, ge=1, le=100)

class CreateFolder(Input):
    """Create a project"""
    operation: Literal["create_folder"] = Field("create_folder", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description="New name")

class GetFolder(Input):
    """Get a specific project"""
    operation: Literal["get_folder"] = Field("get_folder", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric project id")

class UpdateFolder(Input):
    """Edit a project"""
    operation: Literal["update_folder"] = Field("update_folder", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric project id")
    name: str = Field(..., min_length=1, description="New name")

class DeleteFolder(Input):
    """Delete a project"""
    operation: Literal["delete_folder"] = Field("delete_folder", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric project id")

class ListFolderVideos(Input):
    """Get all the videos in a project"""
    operation: Literal["list_folder_videos"] = Field("list_folder_videos", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric project id")
    page: int = Field(1, ge=1, description="Page number; increment to read another page")
    per_page: int = Field(25, ge=1, le=100)

class AddVideoToFolder(Input):
    """Add a specific video to a project"""
    operation: Literal["add_video_to_folder"] = Field("add_video_to_folder", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric project id")
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")

class RemoveVideoFromFolder(Input):
    """Remove a specific video from a project"""
    operation: Literal["remove_video_from_folder"] = Field("remove_video_from_folder", json_schema_extra={"ui:hidden": True})
    project_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric project id")
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")

class LikeVideo(Input):
    """Cause a user to like a video"""
    operation: Literal["like_video"] = Field("like_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")

class UnlikeVideo(Input):
    """Cause a user to unlike a video"""
    operation: Literal["unlike_video"] = Field("unlike_video", json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., pattern=r"^[0-9]+$", max_length=32, description="Vimeo numeric video id")

VimeoOperation = Annotated[Union[GetAccount, ListVideos, GetVideo, UpdateVideo, DeleteVideo, ListComments, CreateComment, GetComment, UpdateComment, DeleteComment, ListFolders, CreateFolder, GetFolder, UpdateFolder, DeleteFolder, ListFolderVideos, AddVideoToFolder, RemoveVideoFromFolder, LikeVideo, UnlikeVideo], Field(discriminator="operation")]

class VimeoConfig(NodeConfig[VimeoOperation, VimeoTokenCredential]):
    pass

ROUTES = {'get_account': {'method': 'GET', 'path': '/me', 'body': [], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'get_user_alt1'}, 'list_videos': {'method': 'GET', 'path': '/me/videos', 'body': [], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'get_videos_alt1'}, 'get_video': {'method': 'GET', 'path': '/videos/{video_id}', 'body': [], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'get_video'}, 'update_video': {'method': 'PATCH', 'path': '/videos/{video_id}', 'body': ['name', 'description'], 'content_type': 'application/vnd.vimeo.video+json', 'statuses': [200], 'operation_id': 'edit_video'}, 'delete_video': {'method': 'DELETE', 'path': '/videos/{video_id}', 'body': [], 'content_type': 'application/json', 'statuses': [204], 'operation_id': 'delete_video'}, 'list_comments': {'method': 'GET', 'path': '/videos/{video_id}/comments', 'body': [], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'get_comments'}, 'create_comment': {'method': 'POST', 'path': '/videos/{video_id}/comments', 'body': ['text'], 'content_type': 'application/vnd.vimeo.comment+json', 'statuses': [201], 'operation_id': 'create_comment'}, 'get_comment': {'method': 'GET', 'path': '/videos/{video_id}/comments/{comment_id}', 'body': [], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'get_comment'}, 'update_comment': {'method': 'PATCH', 'path': '/videos/{video_id}/comments/{comment_id}', 'body': ['text'], 'content_type': 'application/vnd.vimeo.comment+json', 'statuses': [200], 'operation_id': 'edit_comment'}, 'delete_comment': {'method': 'DELETE', 'path': '/videos/{video_id}/comments/{comment_id}', 'body': [], 'content_type': 'application/json', 'statuses': [204], 'operation_id': 'delete_comment'}, 'list_folders': {'method': 'GET', 'path': '/me/projects', 'body': [], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'get_projects_alt1'}, 'create_folder': {'method': 'POST', 'path': '/me/projects', 'body': ['name'], 'content_type': 'application/json', 'statuses': [201], 'operation_id': 'create_project_alt1'}, 'get_folder': {'method': 'GET', 'path': '/me/projects/{project_id}', 'body': [], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'get_project_alt1'}, 'update_folder': {'method': 'PATCH', 'path': '/me/projects/{project_id}', 'body': ['name'], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'edit_project_alt1'}, 'delete_folder': {'method': 'DELETE', 'path': '/me/projects/{project_id}', 'body': [], 'content_type': 'application/json', 'statuses': [204], 'operation_id': 'delete_project_alt1'}, 'list_folder_videos': {'method': 'GET', 'path': '/me/projects/{project_id}/videos', 'body': [], 'content_type': 'application/json', 'statuses': [200], 'operation_id': 'get_project_videos_alt1'}, 'add_video_to_folder': {'method': 'PUT', 'path': '/me/projects/{project_id}/videos/{video_id}', 'body': [], 'content_type': 'application/json', 'statuses': [204], 'operation_id': 'add_video_to_project_alt1'}, 'remove_video_from_folder': {'method': 'DELETE', 'path': '/me/projects/{project_id}/videos/{video_id}', 'body': [], 'content_type': 'application/json', 'statuses': [204], 'operation_id': 'remove_video_from_project_alt1'}, 'like_video': {'method': 'PUT', 'path': '/me/likes/{video_id}', 'body': [], 'content_type': 'application/json', 'statuses': [204], 'operation_id': 'like_video_alt1'}, 'unlike_video': {'method': 'DELETE', 'path': '/me/likes/{video_id}', 'body': [], 'content_type': 'application/json', 'statuses': [204], 'operation_id': 'unlike_video_alt1'}}

class VimeoNode(WorkflowNode):
    integration_type = "automation-vimeo"
    connection_evidence = ConnectionEvidence(noun="videos", operation="list_videos", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return VimeoConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Vimeo personal access token")
        op = self.config.config
        token = self.config.credentials.access_token
        route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = route["path"]
        for key in re.findall(r"{(.*?)}", path):
            path = path.replace("{" + key + "}", values.pop(key))
        body = {key: values.pop(key) for key in route["body"] if key in values}
        headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.vimeo.*+json;version=3.4"}
        if route["body"]:
            headers["Content-Type"] = route["content_type"]
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(route["method"], "https://api.vimeo.com" + path,
                    headers=headers, params=values, **({"json": body} if route["body"] else {}))
        except httpx.HTTPError:
            raise ValueError("Vimeo request did not complete; inspect writes before retrying") from None
        if response.status_code not in route["statuses"]:
            message = "Vimeo rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("error"), str):
                    message = error["error"].replace(token, "[redacted]")
            except ValueError:
                pass
            result = {"status": "error", "http_status": response.status_code, "error": message}
        elif response.status_code == 204:
            result = {"status": "success", "http_status": 204, "acknowledged": True}
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Vimeo returned invalid JSON; inspect writes before retrying") from None
            if not isinstance(data, (dict, list)) or (isinstance(data, dict) and "error" in data):
                raise ValueError("Vimeo returned an unexpected response")
            result = {"status": "success", "http_status": response.status_code, "data": data}
        await self.emit(result)
        return result

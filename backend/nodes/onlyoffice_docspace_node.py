"""ONLYOFFICE DocSpace backend API 3.6: token-authenticated document automation.

Each action issues one fixed contract operation. Listing returns one page;
no mutation retries or follow-up requests are made.
"""
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-onlyoffice-docspace"


class OnlyofficeDocspaceTokenCredential(BaseModel):
    model_config = ConfigDict(title="ONLYOFFICE DocSpace Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.onlyoffice.com/docspace/",
            "x-credential-instructions": "Enter your DocSpace portal HTTPS URL and paste an existing personal access token. In the linked documentation, open Backend, Get started, Authentication, then Personal access tokens for token instructions. NoClick sends it as a Bearer token to this portal; it does not collect your password or create or renew tokens. The account must have permission for the selected operation."})
    credential_type: Literal["onlyoffice_docspace_token"] = Field("onlyoffice_docspace_token", json_schema_extra={"ui:hidden": True})
    base_url: str = Field(..., title="DocSpace portal URL", description="Your portal HTTPS origin, for example https://yourportal.onlyoffice.com, without an API path.")
    access_token: str = Field(..., min_length=1, max_length=8192, title="Personal access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("base_url")
    @classmethod
    def portal(cls, value):
        value = value.strip()
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or "\\" in value):
            raise ValueError("Enter an HTTPS portal origin without a path, query or user information")
        return value.rstrip("/")

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token", key=True)
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the token alone, without Bearer or whitespace")
        return value


def operation(name, category):
    return Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": name.replace("_", " ").title(),
        "x-category": category, "x-is-trigger": False})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    count: int = Field(50, ge=1, le=100, description="Maximum items on this page.")
    start_index: int = Field(0, ge=0, le=2147483647, description="Zero-based page offset; advance by the number of returned items.")


class _Folder(_Input):
    folder_id: int = Field(..., ge=1, le=2147483647, title="Folder ID")


class _File(_Input):
    file_id: int = Field(..., ge=1, le=2147483647, title="File ID")


class _Room(_Input):
    room_id: int = Field(..., ge=1, le=2147483647, title="Room ID")


class GetProfileConfig(_Input):
    """Read the currently authenticated user profile."""
    operation: Literal["get_profile"] = operation("get_profile", "People")


class ListUsersConfig(_Page):
    """Read one page of portal user profiles."""
    operation: Literal["list_users"] = operation("list_users", "People")


class ListMyDocumentsConfig(_Page):
    """Read one page of files and folders in My documents."""
    operation: Literal["list_my_documents"] = operation("list_my_documents", "Documents")


class ListRoomsConfig(_Page):
    """Read one page of rooms visible to the connected account."""
    operation: Literal["list_rooms"] = operation("list_rooms", "Rooms")


class GetRoomConfig(_Room):
    """Read room metadata by ID."""
    operation: Literal["get_room"] = operation("get_room", "Rooms")


class CreateRoomConfig(_Input):
    """Create a room with a title and room type."""
    operation: Literal["create_room"] = operation("create_room", "Rooms")
    title: str = Field(..., min_length=1, max_length=170)
    room_type: Literal["FillingFormsRoom", "EditingRoom", "CustomRoom", "PublicRoom", "VirtualDataRoom", "AiRoom"] = Field("EditingRoom", description="Room type. EditingRoom is a collaboration room.", json_schema_extra={"enumNames": ["Form filling", "Collaboration", "Custom", "Public", "Virtual data", "AI"]})


class RenameRoomConfig(_Room):
    """Change a room title."""
    operation: Literal["rename_room"] = operation("rename_room", "Rooms")
    title: str = Field(..., min_length=1, max_length=170)


class GetFolderConfig(_Folder):
    """Read folder metadata by ID."""
    operation: Literal["get_folder"] = operation("get_folder", "Folders")


class ListFolderContentsConfig(_Folder, _Page):
    """Read one page of files and subfolders in a folder."""
    operation: Literal["list_folder_contents"] = operation("list_folder_contents", "Folders")


class CreateFolderConfig(_Folder):
    """Create a subfolder in the selected parent folder."""
    operation: Literal["create_folder"] = operation("create_folder", "Folders")
    title: str = Field(..., min_length=1, max_length=165)


class RenameFolderConfig(_Folder):
    """Change a folder title."""
    operation: Literal["rename_folder"] = operation("rename_folder", "Folders")
    title: str = Field(..., min_length=1, max_length=165)


class GetFolderPathConfig(_Folder):
    """Read the parent path of a folder."""
    operation: Literal["get_folder_path"] = operation("get_folder_path", "Folders")


class GetFileConfig(_File):
    """Read file metadata by ID."""
    operation: Literal["get_file"] = operation("get_file", "Files")


class RenameFileConfig(_File):
    """Change a file title."""
    operation: Literal["rename_file"] = operation("rename_file", "Files")
    title: str = Field(..., min_length=1, max_length=165)


class ListFileVersionsConfig(_File):
    """Read the versions of a file."""
    operation: Literal["list_file_versions"] = operation("list_file_versions", "Files")


class ListFileHistoryConfig(_File, _Page):
    """Read one page of actions performed on a file."""
    operation: Literal["list_file_history"] = operation("list_file_history", "Files")


class CreateTextFileConfig(_Input):
    """Create a text file in My documents."""
    operation: Literal["create_text_file"] = operation("create_text_file", "Files")
    title: str = Field(..., min_length=1, max_length=165)
    content: str = Field(..., max_length=1000000, json_schema_extra={"ui:widget": "textarea"})
    create_new_if_exist: bool = Field(True, description="Create another file when its title already exists.")


class ListRoomAccessConfig(_Room, _Page):
    """Read one page of room access rights."""
    operation: Literal["list_room_access"] = operation("list_room_access", "Sharing")


class ListFileAccessConfig(_File, _Page):
    """Read one page of file access rights."""
    operation: Literal["list_file_access"] = operation("list_file_access", "Sharing")


class ListFolderAccessConfig(_Folder, _Page):
    """Read one page of folder access rights."""
    operation: Literal["list_folder_access"] = operation("list_folder_access", "Sharing")


DocspaceOperation = Annotated[Union[GetProfileConfig, ListUsersConfig, ListMyDocumentsConfig, ListRoomsConfig, GetRoomConfig, CreateRoomConfig, RenameRoomConfig, GetFolderConfig, ListFolderContentsConfig, CreateFolderConfig, RenameFolderConfig, GetFolderPathConfig, GetFileConfig, RenameFileConfig, ListFileVersionsConfig, ListFileHistoryConfig, CreateTextFileConfig, ListRoomAccessConfig, ListFileAccessConfig, ListFolderAccessConfig], Field(discriminator="operation")]


class OnlyofficeDocspaceConfig(NodeConfig[DocspaceOperation, OnlyofficeDocspaceTokenCredential]):
    pass


ROUTES = {
    'get_profile': ('GET', '/people/@self', {}, {}),
    'list_users': ('GET', '/people', {'count': 'count', 'start_index': 'startIndex'}, {}),
    'list_my_documents': ('GET', '/files/@my', {'count': 'count', 'start_index': 'startIndex'}, {}),
    'list_rooms': ('GET', '/files/rooms', {'count': 'count', 'start_index': 'startIndex'}, {}),
    'get_room': ('GET', '/files/rooms/{room_id}', {}, {}),
    'create_room': ('POST', '/files/rooms', {}, {'title': 'title', 'room_type': 'roomType'}),
    'rename_room': ('PUT', '/files/rooms/{room_id}', {}, {'title': 'title'}),
    'get_folder': ('GET', '/files/folder/{folder_id}', {}, {}),
    'list_folder_contents': ('GET', '/files/{folder_id}', {'count': 'count', 'start_index': 'startIndex'}, {}),
    'create_folder': ('POST', '/files/folder/{folder_id}', {}, {'title': 'title'}),
    'rename_folder': ('PUT', '/files/folder/{folder_id}', {}, {'title': 'title'}),
    'get_folder_path': ('GET', '/files/folder/{folder_id}/path', {}, {}),
    'get_file': ('GET', '/files/file/{file_id}', {}, {}),
    'rename_file': ('PUT', '/files/file/{file_id}', {}, {'title': 'title'}),
    'list_file_versions': ('GET', '/files/file/{file_id}/history', {}, {}),
    'list_file_history': ('GET', '/files/file/{file_id}/log', {'count': 'count', 'start_index': 'startIndex'}, {}),
    'create_text_file': ('POST', '/files/@my/text', {}, {'title': 'title', 'content': 'content', 'create_new_if_exist': 'createNewIfExist'}),
    'list_room_access': ('GET', '/files/rooms/{room_id}/share', {'count': 'count', 'start_index': 'startIndex'}, {}),
    'list_file_access': ('GET', '/files/file/{file_id}/share', {'count': 'count', 'start_index': 'startIndex'}, {}),
    'list_folder_access': ('GET', '/files/folder/{folder_id}/share', {'count': 'count', 'start_index': 'startIndex'}, {}),
}


class OnlyofficeDocspaceNode(WorkflowNode):
    integration_type = "automation-onlyoffice-docspace"
    connection_evidence = ConnectionEvidence(noun="DocSpace rooms", operation="list_rooms", identity_operation="get_profile",
        identity_keys=("displayName", "email"))

    @classmethod
    def get_config_model(cls):
        return OnlyofficeDocspaceConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a DocSpace portal and personal access token")
        credential = self.config.credentials
        config = self.config.config
        method, template, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump()
        path = "/api/2.0" + template.format(**values)
        params = {target: values[source] for source, target in query_fields.items()}
        body = {target: values[source] for source, target in body_fields.items()}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.base_url + path,
                params=params, **({"json": body} if body_fields else {}),
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            # Never echo a response or request header that could contain a token.
            raise ValueError(f"DocSpace rejected the request (HTTP {response.status_code})")
        if len(response.content) > 10000000:
            raise ValueError("DocSpace response exceeds the JSON size limit")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error") or "response" not in payload:
            raise ValueError("DocSpace returned an invalid or error response envelope")
        if payload.get("statusCode", 200) >= 400 or payload.get("status", 0) != 0:
            raise ValueError("DocSpace returned an error status")
        data = payload["response"]
        result = {"status": "success", "data": data}
        if isinstance(data, list):
            result["items"] = data
        elif config.operation in {"list_rooms", "list_my_documents", "list_folder_contents"}:
            if not isinstance(data, dict):
                raise ValueError("DocSpace folder content must be an object")
            result["items"] = (data.get("folders") or []) + (data.get("files") or [])
        if query_fields:
            # A page is never presented as the complete collection.
            result["start_index"] = config.start_index
            result["page_size"] = config.count
        return result

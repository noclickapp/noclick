"""Langflow management API: project, flow and user-file metadata, without execution.

Primary contract: https://docs.langflow.org/api
Only an owned public HTTPS server and issued x-api-key are supported.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import unicodedata
from contextvars import ContextVar
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client, normalize_https_origin

KIND = "langflow_api_key"
MAX_RESPONSE = 2 * 1024 * 1024
MAX_ITEMS = 1000
_private_request = ContextVar("langflow_private_request", default=False)


class _PrivateLogFilter(logging.Filter):
    def filter(self, record):
        return not _private_request.get()


# File names and project search are documented query parameters. Filter this
# request's diagnostics only; never expose an API key or raw HTTP error body.
for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool",
        "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_name).addFilter(_PrivateLogFilter())


def text(value, maximum=500, *, empty=False, multiline=False):
    controls = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]" if multiline else r"[\x00-\x1f\x7f]"
    if not isinstance(value, str) or (not value and not empty) or len(value) > maximum or re.search(controls, value):
        raise ValueError("Langflow text metadata is invalid.")
    return value


def identifier(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Langflow requires a UUID resource ID.") from None


def filename(value):
    value = text(value, 255)
    if (len(value.encode()) > 255 or ".." in value or any(c in value for c in "/\\")
            or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value)
            or value.casefold().startswith("_mcp_servers")
            or value.casefold().startswith("mcp_servers")):
        raise ValueError("Langflow file name must be a bounded ordinary basename.")
    return value


class LangflowAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", title="Langflow API Key", json_schema_extra={
        "x-credential-url": "https://docs.langflow.org/configuration-api-keys",
        "x-credential-instructions": "Supply an issued Langflow API key and the exact origin of your owned public HTTPS server. Localhost, private networks, login passwords and session tokens are not supported.",
    })
    credential_type: Literal["langflow_api_key"] = Field(KIND, json_schema_extra={"ui:hidden": True})
    server_url: StrictStr = Field(..., title="Public HTTPS Server Origin", max_length=2048,
        description="An owned server origin only, with no path, query, user information or fragment.")
    api_key: StrictStr = Field(..., title="API Key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url")
    @classmethod
    def origin(cls, value):
        if re.search(r"[\x00-\x20\x7f\\]", value):
            raise ValueError("Invalid Langflow server origin.")
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Server origins cannot carry user information.")
        result = normalize_https_origin(value, field_name="Langflow server")
        host = urlsplit(result).hostname
        if host is None or host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("Langflow requires a public HTTPS server.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError("Langflow requires a public hostname.") from None
        else:
            if not address.is_global:
                raise ValueError("Langflow requires a public address.")
        return result

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        if not value.isascii():
            raise ValueError("Langflow API keys must be valid ASCII header values.")
        return text(value, 4096)


def credential(data):
    if isinstance(data, LangflowAPIKeyCredential):
        data = data.model_dump()
    if not isinstance(data, dict) or ("credential_type" in data and data["credential_type"] != KIND):
        raise ValueError("Langflow requires its own API key credential.")
    try:
        return LangflowAPIKeyCredential.model_validate(data)
    except Exception:
        raise ValueError("Langflow credential shape or public server origin is invalid.") from None


def raw_tag(data):
    if isinstance(data, dict):
        value = data.get("credentials")
        if isinstance(value, dict) and "credential_type" in value and value["credential_type"] != KIND:
            raise ConfigValidationError("Credential type is not supported by Langflow.")


def operation(name, label, resource=None):
    extra = {"const": name, "ui:hidden": True, "x-display-name": label}
    if resource:
        extra.update({"x-creates-resource": True, "x-resource-type": resource, "x-resource-id-path": "data.id"})
    return Field(name, title=label, json_schema_extra=extra)


def resource_field(kind, name, *, parent=None, required=True):
    options = {"field_name": name, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return Field(... if required else None, title=kind.replace("langflow_", "").title(),
        json_schema_extra={"x-resource-type": kind, "x-dynamic-options": options})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("project_id", "flow_id", "file_id", check_fields=False)
    @classmethod
    def ids(cls, value):
        return identifier(value) if value is not None else None

    @field_validator("name", "description", check_fields=False)
    @classmethod
    def strings(cls, value, info):
        return text(value, 4000, empty=True, multiline=info.field_name == "description") if value is not None else None


class LangflowCheckConnection(Input):
    operation: Literal["check_connection"] = operation("check_connection", "Check Management API Access")


class LangflowListProjects(Input):
    operation: Literal["list_projects"] = operation("list_projects", "List Project Metadata")


class ProjectInput(Input):
    project_id: StrictStr = resource_field("langflow_project", "project_id")


class PageInput(Input):
    page_size: StrictInt = Field(50, ge=1, le=100)
    page_token: Optional[StrictStr] = Field(None, description="Opaque next-page token bound to the server, API key and filters.")


class LangflowGetProject(ProjectInput, PageInput):
    operation: Literal["get_project"] = operation("get_project", "Get Project and Flow Metadata")
    search: StrictStr = Field("", max_length=200)

    @field_validator("search")
    @classmethod
    def safe_search(cls, value):
        return text(value, 200, empty=True)


class LangflowCreateProject(Input):
    operation: Literal["create_project"] = operation("create_project", "Create Empty Project", "langflow_project")
    name: StrictStr = Field(..., min_length=1, max_length=200)
    description: Optional[StrictStr] = Field(None, max_length=4000)


class MetadataUpdate(Input):
    name: Optional[StrictStr] = Field(None, min_length=1, max_length=200)
    description: Optional[StrictStr] = Field(None, max_length=4000)

    @model_validator(mode="after")
    def supplied(self):
        if self.name is None and "description" not in self.model_fields_set:
            raise ValueError("Supply a name or description metadata field.")
        return self


class LangflowUpdateProject(ProjectInput, MetadataUpdate):
    operation: Literal["update_project"] = operation("update_project", "Update Project Metadata")


class DeleteConfirmation(Input):
    confirm_delete: StrictBool = Field(..., description="Explicitly confirm permanent deletion of this resource.")

    @model_validator(mode="after")
    def confirm(self):
        if self.confirm_delete is not True:
            raise ValueError("Deletion requires explicit confirmation.")
        return self


class LangflowDeleteProject(ProjectInput, DeleteConfirmation):
    operation: Literal["delete_project"] = operation("delete_project", "Delete Project",
        # Project deletion can cascade to contained flows; no cleanup is inferred.
    )


class LangflowListFlows(PageInput):
    operation: Literal["list_flows"] = operation("list_flows", "List Flow Metadata")
    project_id: Optional[StrictStr] = resource_field("langflow_project", "project_id", required=False)
    remove_example_flows: StrictBool = True
    components_only: StrictBool = False


class FlowInput(ProjectInput):
    flow_id: StrictStr = resource_field("langflow_flow", "flow_id", parent="project_id")


class LangflowGetFlow(FlowInput):
    operation: Literal["get_flow"] = operation("get_flow", "Get Flow Metadata")


class LangflowCreateEmptyFlow(ProjectInput):
    operation: Literal["create_empty_flow"] = operation("create_empty_flow", "Create Private Empty Flow", "langflow_flow")
    name: StrictStr = Field(..., min_length=1, max_length=200)
    description: Optional[StrictStr] = Field(None, max_length=4000)


class LangflowUpdateFlow(FlowInput, MetadataUpdate):
    operation: Literal["update_flow_metadata"] = operation("update_flow_metadata", "Update Flow Metadata")
    # Explicitly expose no graph, webhook, endpoint, sharing or execution setting.


class LangflowDeleteFlow(FlowInput, DeleteConfirmation):
    operation: Literal["delete_flow"] = operation("delete_flow", "Delete Flow")


class LangflowListFiles(Input):
    operation: Literal["list_files"] = operation("list_files", "List User File Metadata")


class FileInput(Input):
    file_id: StrictStr = resource_field("langflow_file", "file_id")


class LangflowUploadFile(Input):
    operation: Literal["upload_file"] = operation("upload_file", "Upload Explicit File Bytes", "langflow_file")
    name: StrictStr = Field(..., min_length=1, max_length=255)
    content_base64: StrictStr = Field(..., max_length=1400000,
        description="Explicit workflow-owned bytes only, at most 1 MiB. No URLs or remote fetch.",
        json_schema_extra={"ui:widget": "textarea"})
    content_type: Literal["text/plain", "application/json", "application/pdf", "text/csv"] = "text/plain"

    @field_validator("name")
    @classmethod
    def basename(cls, value):
        return filename(value)

    @field_validator("content_base64")
    @classmethod
    def bounded_bytes(cls, value):
        try:
            decoded = base64.b64decode(value, validate=True)
        except Exception:
            raise ValueError("Supply canonical base64 file bytes.") from None
        if not decoded or len(decoded) > 1024 * 1024:
            raise ValueError("File bytes must be between 1 byte and 1 MiB.")
        return value


class LangflowRenameFile(FileInput):
    operation: Literal["rename_file"] = operation("rename_file", "Rename User File")
    name: StrictStr = Field(..., min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def basename(cls, value):
        return filename(value)


class LangflowDeleteFile(FileInput, DeleteConfirmation):
    operation: Literal["delete_file"] = operation("delete_file", "Delete User File")


LangflowOperations = Annotated[Union[
    LangflowCheckConnection, LangflowListProjects, LangflowGetProject, LangflowCreateProject,
    LangflowUpdateProject, LangflowDeleteProject, LangflowListFlows, LangflowGetFlow,
    LangflowCreateEmptyFlow, LangflowUpdateFlow, LangflowDeleteFlow, LangflowListFiles,
    LangflowUploadFile, LangflowRenameFile, LangflowDeleteFile,
], Field(discriminator="operation")]


class LangflowConfiguration(NodeConfig[LangflowOperations, LangflowAPIKeyCredential]):
    pass


def rows(value):
    if not isinstance(value, list) or len(value) > MAX_ITEMS or any(not isinstance(item, dict) for item in value):
        raise ValueError("Langflow returned an invalid or oversized metadata list.")
    return value


def summary(value, kind):
    if not isinstance(value, dict):
        raise ValueError("Langflow returned malformed resource metadata.")
    result = {"id": identifier(value.get("id")), "name": text(value.get("name"))}
    if kind in {"project", "flow"}:
        if value.get("description") is not None:
            result["description"] = text(value["description"], 4000, empty=True, multiline=True)
    for key in ("parent_id", "folder_id"):
        if kind != "file" and key in value:
            result[key] = identifier(value[key]) if value[key] is not None else None
    if kind == "flow":
        for key in ("is_component", "locked", "webhook", "mcp_enabled", "a2a_enabled"):
            if key in value and value[key] is not None:
                if type(value[key]) is not bool:
                    raise ValueError("Langflow returned invalid flow flags.")
                result[key] = value[key]
        if value.get("updated_at") is not None:
            result["updated_at"] = text(value["updated_at"], 100)
        if value.get("tags") is not None:
            tags = value["tags"]
            if not isinstance(tags, list) or len(tags) > 100:
                raise ValueError("Langflow returned invalid tags.")
            result["tags"] = [text(tag, 200) for tag in tags]
    if kind == "file":
        if type(value.get("size")) is not int or value["size"] < 0:
            raise ValueError("Langflow returned invalid file size.")
        result["size"] = value["size"]
    # data, credentials, fs/storage paths, URLs, auth_settings and owners are not output.
    return result


def page_count(value, *, minimum=0):
    if type(value) is not int or not minimum <= value <= 999999:
        raise ValueError("Langflow returned invalid pagination metadata.")
    return value


def binding(creds):
    return (creds.server_url, creds.api_key)


def page_token(page, config, creds):
    message = json.dumps([creds.server_url, config.model_dump(exclude={"page_token"}), page], sort_keys=True, separators=(",", ":"))
    return str(page) + "." + hmac.new(creds.api_key.encode(), message.encode(), hashlib.sha256).hexdigest()


def decode_page(token, config, creds):
    if token is None:
        return 1
    if not re.fullmatch(r"[1-9][0-9]{0,5}\.[a-f0-9]{64}", token) or not hmac.compare_digest(token, page_token(int(token.split(".")[0]), config, creds)):
        raise ValueError("Langflow page token does not match this server, key and filters.")
    return int(token.split(".")[0])


def paginated(value, config, creds, requested_page):
    if not isinstance(value, dict):
        raise ValueError("Langflow returned a malformed paginated response.")
    page = page_count(value.get("page"), minimum=1)
    size = page_count(value.get("size"), minimum=1)
    pages = page_count(value.get("pages"))
    total = page_count(value.get("total"))
    items = rows(value.get("items"))
    if page != requested_page or size != config.page_size or len(items) > size or len(items) > total or (total > 0 and pages < page):
        raise ValueError("Langflow pagination did not match the requested page.")
    return {"items": [summary(item, "flow") for item in items], "page": page, "size": size,
        "pages": pages, "total": total,
        "next_page_token": page_token(page + 1, config, creds) if page < pages else None}


class LangflowNode(WorkflowNode):
    integration_type = "automation-langflow"
    agent_tool_provider = True
    workflow_credential_refresh = True
    # The API can use deployment-specific auth/auto-login settings. Own project
    # metadata is useful evidence, but an empty collection is not user identity.
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return LangflowConfiguration

    @classmethod
    def parse_config(cls, config_data):
        raw_tag(config_data)
        try:
            return LangflowConfiguration.model_validate(config_data)
        except Exception:
            raise ConfigValidationError("Invalid Langflow configuration or credential shape.") from None

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls.parse_config(config_data)
            return {"valid": True, "errors": [], "satisfied_set": "default"}
        except Exception:
            return {"valid": False, "errors": ["Invalid Langflow configuration or credential shape."], "satisfied_set": None}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._load_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _load_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, organization_id=None, workflow_id=None):
        creds = credential(credential_data)
        if not credential_id:
            return creds.model_dump()
        if not user_id:
            raise ValueError("Langflow saved credentials require the current authenticated caller.")
        # Use staging's shared access/owner-fallback policy for saved API keys.
        from nodes.core.run_op import resolve_operation_credential
        current = await resolve_operation_credential(
            credential_id, user_id, pool,
            organization_id=organization_id,
            workflow_id=workflow_id,
        )
        return credential(current).model_dump()

    async def _current(self):
        raw_tag(self.node_data)
        if not isinstance(self.config, LangflowConfiguration) or self.config.credentials is None:
            raise ValueError("Langflow API key credentials are required.")
        creds = credential(self.config.credentials)
        saved = self.node_data.get("credential_id") or (self.node_data.get("credentialIds") or {}).get(KIND)
        if saved:
            creds = credential(await self._load_credential(creds.model_dump(), user_id=self.user_id,
                pool=self.node_data.get("_approval_pool"), credential_id=saved,
                organization_id=self.organization_id, workflow_id=self.workflow_id))
            self.config.credentials = creds
        return creds

    async def _request(self, method, path, *, params=None, body=None, files=None, statuses=(200,), expected_binding=None):
        if body is not None and len(json.dumps(body, allow_nan=False).encode()) > MAX_RESPONSE:
            raise ValueError("Langflow request body exceeds the 2 MiB client bound.")
        creds = await self._current()
        if expected_binding is not None and binding(creds) != expected_binding:
            raise ValueError("Langflow current credential changed between scoped read and write.")
        marker = _private_request.set(True)
        try:
            async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=30) as client:
                async with client.stream(method, creds.server_url + path, params=params, json=body, files=files,
                        headers={"x-api-key": creds.api_key, "Accept": "application/json"}) as response:
                    if response.status_code not in statuses:
                        safe_request = httpx.Request(method, "https://langflow.invalid/api/")
                        raise httpx.HTTPStatusError(
                            f"Langflow HTTP {response.status_code}; saved credential validity is unverified.",
                            request=safe_request, response=httpx.Response(response.status_code, request=safe_request))
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_RESPONSE:
                            raise ValueError("Langflow response exceeds the 2 MiB client bound.")
                    if response.status_code == 204:
                        if content:
                            raise ValueError("Langflow returned a body for a no-content acknowledgement.")
                        return None, 204, creds
                    try:
                        value = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except Exception:
                        raise ValueError("Langflow returned malformed JSON.") from None
                    if isinstance(value, dict) and any(value.get(key) for key in ("error", "errors")):
                        raise ValueError("Langflow returned an error envelope; saved credential validity is unverified.")
                    return value, response.status_code, creds
        except httpx.HTTPStatusError:
            raise
        except (httpx.RequestError, SSRFError):
            raise ValueError("Langflow request failed; saved credential validity is unverified.") from None
        finally:
            _private_request.reset(marker)

    async def _scoped_flow(self, config):
        value, _, creds = await self._request("GET", "/api/v1/flows/" + config.flow_id)
        data = summary(value, "flow")
        if data["id"] != config.flow_id or data.get("folder_id") != config.project_id:
            raise ValueError("Langflow returned a flow outside the selected project.")
        return data, binding(creds)

    async def _ordinary_file(self, file_id):
        value, _, creds = await self._request("GET", "/api/v2/files")
        matches = [item for item in rows(value) if item.get("id") == file_id]
        if len(matches) != 1:
            raise ValueError("Langflow file is unavailable in the current user's catalog.")
        data = summary(matches[0], "file")
        filename(data["name"])
        return binding(creds)

    async def execute(self, inputs):
        await self._current()
        config = self.config.config
        op = config.operation
        code = 200
        if op in {"check_connection", "list_projects"}:
            value, code, _ = await self._request("GET", "/api/v1/projects/")
            projects = [summary(item, "project") for item in rows(value)]
            data = {"management_api_reachable": True, "project_count": len(projects)} if op == "check_connection" else {"projects": projects}
        elif op == "get_project":
            creds = await self._current()
            page = decode_page(config.page_token, config, creds)
            query = {"page": page, "size": config.page_size}
            if config.search:
                query["search"] = config.search
            value, code, current = await self._request("GET", "/api/v1/projects/" + config.project_id,
                params=query, expected_binding=binding(creds))
            if not isinstance(value, dict):
                raise ValueError("Langflow returned malformed project pagination.")
            data = summary(value.get("folder"), "project")
            if data["id"] != config.project_id:
                raise ValueError("Langflow returned an unexpected project.")
            data["flows"] = paginated(value.get("flows"), config, current, page)
            if any(item.get("folder_id") != config.project_id for item in data["flows"]["items"]):
                raise ValueError("Langflow returned flows outside the selected project.")
        elif op == "create_project":
            body = config.model_dump(exclude={"operation"}, exclude_none=True)
            value, code, _ = await self._request("POST", "/api/v1/projects/", body=body, statuses=(201,))
            data = summary(value, "project")
        elif op == "update_project":
            body = config.model_dump(include={"name", "description"}, exclude_unset=True)
            value, code, _ = await self._request("PATCH", "/api/v1/projects/" + config.project_id, body=body)
            data = summary(value, "project")
            if data["id"] != config.project_id:
                raise ValueError("Langflow returned an unexpected project.")
        elif op == "delete_project":
            _, code, _ = await self._request("DELETE", "/api/v1/projects/" + config.project_id, statuses=(204,))
            data = {"id": config.project_id, "deleted": True}
        elif op == "list_flows":
            creds = await self._current()
            page = decode_page(config.page_token, config, creds)
            query = {"get_all": "false", "header_flows": "false", "page": page, "size": config.page_size,
                "remove_example_flows": str(config.remove_example_flows).lower(), "components_only": str(config.components_only).lower()}
            if config.project_id:
                query["folder_id"] = config.project_id
            value, code, current = await self._request("GET", "/api/v1/flows/", params=query, expected_binding=binding(creds))
            data = paginated(value, config, current, page)
            if config.project_id and any(item.get("folder_id") != config.project_id for item in data["items"]):
                raise ValueError("Langflow returned flows outside the selected project.")
        elif op in {"get_flow", "update_flow_metadata", "delete_flow"}:
            data, anchor = await self._scoped_flow(config)
            if op == "update_flow_metadata":
                body = config.model_dump(include={"name", "description"}, exclude_unset=True)
                value, code, _ = await self._request("PATCH", "/api/v1/flows/" + config.flow_id, body=body, expected_binding=anchor)
                data = summary(value, "flow")
                if data["id"] != config.flow_id or data.get("folder_id") != config.project_id:
                    raise ValueError("Langflow returned a flow outside the selected project.")
            elif op == "delete_flow":
                value, code, _ = await self._request("DELETE", "/api/v1/flows/" + config.flow_id, expected_binding=anchor)
                if not isinstance(value, dict) or value.get("message") != "Flow deleted successfully":
                    raise ValueError("Langflow did not acknowledge flow deletion.")
                data = {"id": config.flow_id, "project_id": config.project_id, "deleted": True}
        elif op == "create_empty_flow":
            body = {"name": config.name, "data": {"nodes": [], "edges": []}, "folder_id": config.project_id,
                "webhook": False, "is_component": False, "mcp_enabled": False, "a2a_enabled": False,
                "access_type": "PRIVATE", "flow_type": "workflow"}
            if config.description is not None:
                body["description"] = config.description
            value, code, _ = await self._request("POST", "/api/v1/flows/", body=body, statuses=(201,))
            data = summary(value, "flow")
            if data.get("folder_id") != config.project_id:
                raise ValueError("Langflow created a flow outside the selected project.")
            graph = value.get("data")
            if (any(value.get(flag) is not False for flag in ("webhook", "mcp_enabled", "a2a_enabled", "is_component"))
                    or value.get("access_type") != "PRIVATE" or value.get("flow_type") != "workflow"
                    or not isinstance(graph, dict) or graph.get("nodes") != [] or graph.get("edges") != []):
                raise ValueError("Langflow did not acknowledge private empty-flow creation.")
        elif op == "list_files":
            value, code, _ = await self._request("GET", "/api/v2/files")
            data = {"files": [summary(item, "file") for item in rows(value) if not str(item.get("name", "")).casefold().startswith(("_mcp_servers", "mcp_servers"))]}
        elif op == "upload_file":
            content = base64.b64decode(config.content_base64, validate=True)
            value, code, _ = await self._request("POST", "/api/v2/files",
                params={"append": "false", "ephemeral": "false"},
                files={"file": (config.name, content, config.content_type)}, statuses=(201,))
            data = summary(value, "file")
        elif op == "rename_file":
            anchor = await self._ordinary_file(config.file_id)
            value, code, _ = await self._request("PUT", "/api/v2/files/" + config.file_id,
                params={"name": config.name}, expected_binding=anchor)
            data = summary(value, "file")
            if data["id"] != config.file_id:
                raise ValueError("Langflow returned an unexpected file.")
        elif op == "delete_file":
            anchor = await self._ordinary_file(config.file_id)
            value, code, _ = await self._request("DELETE", "/api/v2/files/" + config.file_id, expected_binding=anchor)
            # The public v2 docs use message. Retain the existing detail
            # acknowledgement with a file name, requiring explicit success.
            documented = isinstance(value, dict) and value.get("message") == "File deleted successfully"
            detail = value.get("detail") if isinstance(value, dict) else None
            legacy = isinstance(detail, str) and detail.startswith("File ") and detail.endswith(" deleted successfully")
            if not (documented or legacy):
                raise ValueError("Langflow did not acknowledge file deletion.")
            data = {"id": config.file_id, "deleted": True}
        else:
            raise ValueError("Unsupported Langflow operation.")
        return {"operation": op, "http_status": code, "data": data}

    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        if validation_context is None:
            return {"valid": None, "message": "Langflow access is unverified; retry with authenticated validation context."}
        try:
            result = await validation_context.run_operation("check_connection", {})
            if not isinstance(result, dict) or result.get("executed") is False or result.get("_halt_downstream"):
                return {"valid": None, "message": "Langflow access probe did not execute."}
            if result["data"].get("management_api_reachable") is True:
                return {"valid": True, "message": "Langflow management API responded. This does not identify an account or verify execution permissions."}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                return {"valid": False, "message": f"Langflow rejected management API access (HTTP {exc.response.status_code})."}
        except Exception:
            pass
        return {"valid": None, "message": "Langflow access is unverified; retry validation."}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search_query=None, page_token=None, **kwargs):
        context = context or {}
        if field_name not in {"project_id", "flow_id", "file_id"}:
            return {"options": [], "has_more": False}
        config = {"operation": "list_projects"}
        collection = "projects"
        if field_name == "flow_id":
            config = {"operation": "list_flows", "project_id": identifier(context.get("project_id")),
                "page_size": 100, "page_token": page_token}
            collection = "items"
        elif field_name == "file_id":
            config = {"operation": "list_files"}
            collection = "files"
        if field_name != "flow_id" and page_token is not None:
            raise ValueError("Langflow project/file catalogs do not document pagination.")
        creds = credential(credential_data)
        node = cls("langflow-picker", "automation-langflow", {"credentials": creds.model_dump()},
            cls.parse_config({"config": config, "credentials": creds.model_dump()}))
        data = (await node.execute({}))["data"]
        search = (search_query or kwargs.get("search") or "").casefold()
        options = [{"value": item["id"], "label": item["name"]} for item in data[collection]
            if not search or search in item["name"].casefold() or search in item["id"].casefold()]
        token = data.get("next_page_token")
        return {"options": options, "has_more": token is not None, "next_page_token": token}

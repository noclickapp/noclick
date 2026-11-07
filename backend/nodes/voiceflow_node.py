"""Native Voiceflow project/environment metadata and knowledge-base management."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


"""Fixed current Voiceflow service API and bounded selected metadata contracts."""
import base64
import hashlib
import json
import math
import re
from datetime import datetime
from urllib.parse import quote

import httpx
from utils.ssrf import guarded_async_client

ORIGIN = "https://realtime-api.voiceflow.com"
MAX_BODY = 512 * 1024
ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
PATHS = {
    "GET": re.compile(r"/v1/stable/(?:workspace(?:/" + ID + r")?|project(?:/" + ID + r")?|environment(?:/" + ID + r")?|agent|document(?:/" + ID + r")?)"),
    "PATCH": re.compile(r"/v1/stable/document/" + ID),
    "DELETE": re.compile(r"/v1/stable/document/" + ID),
    "POST": re.compile(r"/v1/stable/knowledge-base/query"),
}


class VoiceflowAPIError(RuntimeError):
    def __init__(self, message, *, status=None, provider_status=None, uncertain=False):
        super().__init__(message)
        self.http_status = status
        self.provider_status = provider_status
        self.uncertain = uncertain


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(ID, value):
        raise ValueError("Use a bounded URL-safe Voiceflow ID or environment alias, without a URL or path.")
    return value


def path_id(value):
    return quote(identifier(value), safe="")


def text(value, maximum=4096, *, nonempty=False):
    if not isinstance(value, str) or len(value) > maximum or (nonempty and not value.strip()) or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError("Voiceflow returned invalid bounded selected text.")
    return value


def timestamp(value):
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return value
    except Exception:
        raise ValueError("Voiceflow returned an invalid timezone-aware timestamp.") from None


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate Voiceflow JSON field.")
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError("Non-finite Voiceflow JSON number.")


def _bounded(value, depth=0):
    if depth > 14 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Voiceflow returned an unbounded JSON value.")
    if isinstance(value, (dict, list)):
        if len(value) > 2000:
            raise ValueError("Voiceflow returned an oversized JSON container.")
        for child in value.values() if isinstance(value, dict) else value:
            _bounded(child, depth + 1)


def parse_json(payload):
    try:
        if not payload or len(payload) > MAX_BODY:
            raise ValueError()
        result = json.loads(payload, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        if not isinstance(result, dict):
            raise ValueError()
        _bounded(result)
        return result
    except Exception:
        raise ValueError("Voiceflow returned invalid bounded JSON.") from None


def safe_selected(result, data):
    token = data["personal_access_token"]
    def walk(value):
        if isinstance(value, str) and (token in value or json.dumps(token)[1:-1] in value):
            raise ValueError("Voiceflow selected output contains credential material.")
        if isinstance(value, dict):
            for key, child in value.items():
                walk(key)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(result)
    return result


async def request(data, method, path, *, params=None, body=None, mutation=False):
    if method not in PATHS or not PATHS[method].fullmatch(path):
        raise ValueError("Unsupported native Voiceflow service operation.")
    encoded = json.dumps(body, allow_nan=False, separators=(",", ":")).encode() if body is not None else None
    if encoded is not None and len(encoded) > 16384:
        raise ValueError("The Voiceflow metadata request exceeds its local size limit.")
    headers = {"Authorization": "Bearer " + data["personal_access_token"], "Accept": "application/json"}
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    try:
        async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, ORIGIN + path, params=params, content=encoded, headers=headers) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise VoiceflowAPIError("Voiceflow response exceeds the local bound.", status=response.status_code, uncertain=mutation)
                    chunks.append(chunk)
                payload = b"".join(chunks)
                result = None
                if "application/json" in response.headers.get("content-type", "").lower():
                    try:
                        result = parse_json(payload)
                    except ValueError:
                        pass
                native = result.get("statusCode") if isinstance(result, dict) else None
                native = native if type(native) is int and 400 <= native <= 599 else None
                if response.status_code != 200 or native is not None:
                    status = response.status_code
                    raise VoiceflowAPIError("Voiceflow rejected the request or returned an unexpected status.", status=status, provider_status=native,
                        uncertain=mutation and (status in {200, 201, 202, 204, 429} or status >= 500))
                if result is None:
                    raise VoiceflowAPIError("Voiceflow returned an invalid bounded JSON acknowledgement.", status=200, uncertain=mutation)
                return result
    except httpx.HTTPError:
        raise VoiceflowAPIError("The Voiceflow result could not be verified; read back a document before retrying a write.", uncertain=mutation) from None


def object_metadata(row, kind, *, data, target=None):
    if not isinstance(row, dict):
        raise ValueError("Voiceflow omitted its selected object envelope.")
    key = "alias" if kind == "environment" else "id"
    selected_id = identifier(row.get(key))
    if target is not None and selected_id != target:
        raise ValueError("Voiceflow returned a different object than the selected target.")
    result = {key: selected_id, "name": text(row.get("name"), 256, nonempty=True)}
    if kind == "project":
        if identifier(row.get("workspaceID")) != data["workspace_id"]:
            raise ValueError("Voiceflow returned a project from a different workspace.")
        result["workspaceID"] = data["workspace_id"]
        result["description"] = text(row.get("description"), 4096)
    elif kind == "workspace":
        result["organizationID"] = identifier(row.get("organizationID"))
    else:
        if type(row.get("isMain")) is not bool or not isinstance(row.get("releases"), list):
            raise ValueError("Voiceflow returned invalid environment metadata.")
        traffic = row.get("trafficPercentage")
        if type(traffic) not in (int, float) or not math.isfinite(traffic) or not 0 <= traffic <= 100:
            raise ValueError("Voiceflow returned an invalid environment traffic percentage.")
        result.update(isMain=row["isMain"], trafficPercentage=traffic, release_count=len(row["releases"]))
    for key in ("createdAt", "updatedAt"):
        if key in row:
            result[key] = timestamp(row[key])
    return safe_selected(result, data)


def metadata_tags(value):
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Use at most 20 document metadata fields.")
    result = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"key", "values"} or not isinstance(row["values"], list) or len(row["values"]) > 20:
            raise ValueError("Use document metadata objects with key and bounded string values only.")
        result.append({"key": text(row["key"], 128, nonempty=True), "values": [text(v, 256) for v in row["values"]]})
    if len({row["key"] for row in result}) != len(result):
        raise ValueError("Use unique document metadata keys.")
    return result


def document_metadata(row, *, data, target=None, full=False):
    if not isinstance(row, dict):
        raise ValueError("Voiceflow omitted the document envelope.")
    document_id = identifier(row.get("id"))
    if target is not None and document_id != target:
        raise ValueError("Voiceflow returned a different document ID.")
    source, status, chunking = row.get("data"), row.get("status"), row.get("smartChunking")
    if not isinstance(source, dict) or source.get("type") not in {"url", "docx", "pdf", "text", "md", "csv", "xlsx", "table"} or not isinstance(status, dict) or status.get("type") not in {"ERROR", "PENDING", "SUCCESS", "INITIALIZED"} or not isinstance(chunking, dict):
        raise ValueError("Voiceflow returned invalid document source/status metadata.")
    result = {"id": document_id, "name": text(source.get("name"), 256, nonempty=True), "source_type": source["type"], "status": status["type"]}
    if full:
        chunks = row.get("chunks")
        if not isinstance(chunks, list):
            raise ValueError("Voiceflow omitted the document chunk collection.")
        result.update(chunk_count=len(chunks), metadata=metadata_tags(row.get("metadata")))
    return safe_selected(result, data)


def selected_collection(body, key, select):
    rows = body.get(key)
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("Voiceflow returned an invalid bounded whole collection.")
    if any(key in body for key in ("nextPageToken", "next", "cursor")):
        raise ValueError("Provider paging is not documented for this Voiceflow collection.")
    result = [select(row) for row in rows]
    ids = [row.get("id", row.get("alias")) for row in result]
    if len(set(ids)) != len(ids):
        raise ValueError("Voiceflow returned duplicate object identifiers.")
    return result


def local_page(rows, *, data, purpose, limit, token=None, search=""):
    search = text(search, 100)
    rows = sorted((row for row in rows if not search or search.casefold() in row["name"].casefold()), key=lambda row: row.get("id", row.get("alias")))
    context = {
        "token_hash": hashlib.sha256(data["personal_access_token"].encode()).hexdigest(), "workspace": data["workspace_id"],
        "project": data["project_id"], "environment": data["environment_alias"], "purpose": purpose, "limit": limit, "search": search}
    binding = hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    offset = 0
    if token is not None:
        try:
            if not isinstance(token, str) or not 1 <= len(token) <= 512 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
                raise ValueError()
            record = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True), object_pairs_hook=_pairs)
            if set(record) != {"v", "binding", "snapshot", "offset"} or type(record["v"]) is not int or record["v"] != 1 or record["binding"] != binding or record["snapshot"] != snapshot or type(record["offset"]) is not int or not 0 < record["offset"] < len(rows) or record["offset"] % limit:
                raise ValueError()
            offset = record["offset"]
        except Exception:
            raise ValueError("The local Voiceflow continuation belongs to different authority, filters or a changed collection; start again.") from None
    end = offset + limit
    next_token = None
    if end < len(rows):
        record = {"v": 1, "binding": binding, "snapshot": snapshot, "offset": end}
        next_token = base64.urlsafe_b64encode(json.dumps(record, separators=(",", ":")).encode()).decode().rstrip("=")
    return {"items": rows[offset:end], "next_page_token": next_token, "has_more": next_token is not None,
        "total": len(rows), "pagination_mode": "local slice of re-fetched whole collection; no provider paging"}


class VoiceflowPATCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Voiceflow Personal Access Token", json_schema_extra={
        "x-credential-url": "https://www.voiceflow.com/docs/api-reference/authentication",
        "x-credential-instructions": "Create a personal access token under Voiceflow Settings > Access tokens. Supply its existing workspace/project IDs and environment alias. Current vfp_ tokens act with your account's access across its workspaces and expire; rotate manually before expiry. This node binds knowledge operations to the supplied project/environment and verifies current returned metadata. A returned project name identifies that project, not a human principal or universal write entitlement.",
    })
    credential_type: Literal["voiceflow_pat"] = Field("voiceflow_pat", json_schema_extra={"ui:hidden": True})
    personal_access_token: str = Field(..., min_length=12, max_length=4096, title="Personal Access Token", json_schema_extra={"ui:widget": "password"})
    workspace_id: str = Field(..., title="Workspace ID")
    project_id: str = Field(..., title="Project ID", description="Find the existing project ID under Settings > General > Metadata.")
    environment_alias: str = Field(..., title="Knowledge Environment Alias", description="An existing environment alias such as main. No environment is created or published.")

    @field_validator("personal_access_token")
    @classmethod
    def token(cls, value):
        if not value.startswith("vfp_") or any(ord(c) < 33 or ord(c) > 126 for c in value) or "://" in value:
            raise ValueError("Supply the current issued vfp_ personal access token without a Bearer prefix or URL.")
        return value

    @field_validator("workspace_id", "project_id", "environment_alias")
    @classmethod
    def identifier(cls, value):
        return identifier(value)


def credential_shape(data):
    try:
        return VoiceflowPATCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("The current Voiceflow personal token credential is invalid.") from None


def op(value, label, category):
    return Field(value, json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def dynamic(name):
    return {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True}}


class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LocalPagination(OperationConfig):
    limit: int = Field(25, ge=1, le=100, strict=True, title="Local Page Size", description="The provider returns its whole collection; this is a local output slice.")
    page_token: str | None = Field(None, max_length=512, title="Local Continuation", description="Use this operation's next_page_token with the same credential, query and unchanged collection.")
    search: str = Field("", max_length=100, title="Name Contains", description="Local name filter over the bounded full collection.")


class ListWorkspaces(LocalPagination):
    operation: Literal["list_workspaces"] = op("list_workspaces", "List Accessible Workspace Metadata", "Workspaces")


class GetWorkspace(OperationConfig):
    operation: Literal["get_workspace"] = op("get_workspace", "Get Connected Workspace Metadata", "Workspaces")


class ListProjects(LocalPagination):
    operation: Literal["list_projects"] = op("list_projects", "List Workspace Project Metadata", "Projects")


class GetProject(OperationConfig):
    operation: Literal["get_project"] = op("get_project", "Get Project Metadata", "Projects")
    project_id: str | None = Field(None, title="Project", description="Default: credential's project. Other selections must belong to its workspace; knowledge operations always retain the credential's project.", json_schema_extra=dynamic("project_id"))

    @field_validator("project_id")
    @classmethod
    def identifier(cls, value):
        return identifier(value) if value is not None else None


class ListEnvironments(LocalPagination):
    operation: Literal["list_environments"] = op("list_environments", "List Project Environment Metadata", "Environments")


class GetEnvironment(OperationConfig):
    operation: Literal["get_environment"] = op("get_environment", "Get Environment Metadata", "Environments")
    environment_alias: str | None = Field(None, title="Environment", description="Metadata target only. Knowledge operations retain the credential's environment.", json_schema_extra=dynamic("environment_alias"))

    @field_validator("environment_alias")
    @classmethod
    def identifier(cls, value):
        return identifier(value) if value is not None else None


class GetAgent(OperationConfig):
    operation: Literal["get_agent_metadata"] = op("get_agent_metadata", "Get Agent Workflow Metadata", "Agent")


class ListDocuments(LocalPagination):
    operation: Literal["list_documents"] = op("list_documents", "List Knowledge Document Metadata", "Knowledge Base")


class DocumentTarget(OperationConfig):
    document_id: str = Field(..., title="Document", json_schema_extra=dynamic("document_id"))

    @field_validator("document_id")
    @classmethod
    def identifier(cls, value):
        return identifier(value)


class GetDocument(DocumentTarget):
    operation: Literal["get_document"] = op("get_document", "Get Document Metadata and Status", "Knowledge Base")


class UpdateDocumentMetadata(DocumentTarget):
    operation: Literal["update_document_metadata"] = op("update_document_metadata", "Update Document Metadata Tags", "Knowledge Base")
    metadata_json: str = Field(..., max_length=12000, title="Metadata Tags", description='JSON array of {"key":"topic","values":["owned-fixture"]}. Replaces document metadata; no text-replacement contract is assumed.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("metadata_json")
    @classmethod
    def metadata(cls, value):
        parse_metadata(value)
        return value


class DeleteDocument(DocumentTarget):
    operation: Literal["delete_document"] = op("delete_document", "Delete Selected Knowledge Document", "Knowledge Base")
    confirm_delete: Literal["DELETE_SELECTED_DOCUMENT"] = Field(..., title="Confirm Delete", description="Select only an owned disposable document. Deletion removes a retrieval source and cannot be undone by this node.")


class QueryKnowledgeBase(OperationConfig):
    operation: Literal["query_knowledge_base"] = op("query_knowledge_base", "Retrieve Knowledge Chunks", "Knowledge Base")
    question: str = Field(..., min_length=1, max_length=2048, title="Retrieval Question", json_schema_extra={"ui:widget": "textarea"})
    version: Literal["draft", "published"] = Field("draft", title="Knowledge Version")
    chunk_limit: int = Field(5, ge=1, le=20, strict=True, title="Maximum Chunks", description="Local bound. Sends synthesis:false; no model settings or answer generation.")

    @field_validator("question")
    @classmethod
    def bounded(cls, value):
        return text(value, 2048, nonempty=True)


VoiceflowConfig = Annotated[Union[ListWorkspaces, GetWorkspace, ListProjects, GetProject, ListEnvironments, GetEnvironment,
    GetAgent, ListDocuments, GetDocument, UpdateDocumentMetadata, DeleteDocument, QueryKnowledgeBase], Field(discriminator="operation")]


class VoiceflowFullConfig(NodeConfig):
    model_config = ConfigDict(hide_input_in_errors=True)
    credentials: VoiceflowPATCredential | None = None
    config: VoiceflowConfig


def parse_metadata(value):
    try:
        # Reuse the native bounded duplicate/non-finite JSON parser via an envelope.
        envelope = parse_json(("{\"metadata\":" + value + "}").encode())
        if set(envelope) != {"metadata"}:
            raise ValueError()
        return metadata_tags(envelope["metadata"])
    except Exception:
        raise ValueError("Use a bounded JSON array of metadata key/string-values objects.") from None


def knowledge_params(data):
    return {"projectID": data["project_id"], "environmentAlias": data["environment_alias"]}


async def project(data, target=None):
    target = target or data["project_id"]
    body = await request(data, "GET", "/v1/stable/project/" + path_id(target))
    return object_metadata(body.get("project"), "project", data=data, target=target)


async def environment(data, alias=None):
    alias = alias or data["environment_alias"]
    body = await request(data, "GET", "/v1/stable/environment/" + path_id(alias), params={"projectID": data["project_id"]})
    return object_metadata(body.get("environment"), "environment", data=data, target=alias)


async def witness(data):
    # An environment has no project ID in its published envelope. Its witnessed
    # project and exact request scope are retained; no fabricated parent field.
    return {"project": await project(data), "environment": await environment(data)}


async def documents(data):
    body = await request(data, "GET", "/v1/stable/document", params=knowledge_params(data))
    return selected_collection(body, "documents", lambda row: document_metadata(row, data=data))


async def document(data, target):
    body = await request(data, "GET", "/v1/stable/document/" + path_id(target), params=knowledge_params(data))
    return document_metadata(body.get("document"), data=data, target=target, full=True)


async def metadata_collection(data, kind):
    params = {"workspaceID": data["workspace_id"]} if kind == "project" else {"projectID": data["project_id"]} if kind == "environment" else None
    body = await request(data, "GET", "/v1/stable/" + kind, params=params)
    return selected_collection(body, kind + "s", lambda row: object_metadata(row, kind, data=data))


class VoiceflowNode(WorkflowNode):
    integration_type = "automation-voiceflow"
    connection_evidence = ConnectionEvidence(identity_operation="get_project", noun="project", proves="account", identity_keys=("name",))

    @classmethod
    def get_config_model(cls):
        return VoiceflowFullConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None):
        if field_name not in {"project_id", "environment_alias", "document_id"}:
            return {"options": [], "next_page_token": None}
        credential_data = credential_shape(credential_data)
        context = context or {}
        await witness(credential_data)
        rows = await documents(credential_data) if field_name == "document_id" else await metadata_collection(credential_data, "project" if field_name == "project_id" else "environment")
        result = local_page(rows, data=credential_data, purpose="picker-" + field_name, limit=50,
            token=context.get("page_token"), search=context.get("search") or "")
        return {"options": [{"value": row.get("id", row.get("alias")), "label": row["name"]} for row in result["items"]],
            "next_page_token": result["next_page_token"], "pagination_mode": result["pagination_mode"]}

    async def execute(self, inputs):
        acknowledged = False
        target = None
        try:
            if not isinstance(self.config, VoiceflowFullConfig) or self.config.credentials is None:
                raise ValueError("Select the Voiceflow personal token and native operation.")
            config = self.config.config
            data = credential_shape(self.config.credentials.model_dump())
            context = await witness(data)
            if isinstance(config, GetProject):
                result = {**context, "project": await project(data, config.project_id) if config.project_id and config.project_id != data["project_id"] else context["project"]}
            elif isinstance(config, GetEnvironment):
                result = {"environment": await environment(data, config.environment_alias) if config.environment_alias and config.environment_alias != data["environment_alias"] else context["environment"]}
            elif isinstance(config, GetWorkspace):
                body = await request(data, "GET", "/v1/stable/workspace/" + path_id(data["workspace_id"]))
                result = {"workspace": object_metadata(body.get("workspace"), "workspace", data=data, target=data["workspace_id"])}
            elif isinstance(config, (ListWorkspaces, ListProjects, ListEnvironments, ListDocuments)):
                kind = "workspace" if isinstance(config, ListWorkspaces) else "project" if isinstance(config, ListProjects) else "environment"
                rows = await documents(data) if isinstance(config, ListDocuments) else await metadata_collection(data, kind)
                result = local_page(rows, data=data, purpose=config.operation, limit=config.limit, token=config.page_token, search=config.search)
            elif isinstance(config, GetAgent):
                body = await request(data, "GET", "/v1/stable/agent", params={**knowledge_params(data), "includeInstructions": "false", "includePrompt": "false"})
                agent = body.get("agent")
                if not isinstance(agent, dict) or type(agent.get("includeGuidelines")) is not bool:
                    raise ValueError("Voiceflow returned invalid agent metadata.")
                result = {"project_id": data["project_id"], "environment_alias": data["environment_alias"], "includeGuidelines": agent["includeGuidelines"]}
                for field in ("promptLineCount", "instructionsLineCount"):
                    if type(agent.get(field)) is not int or agent[field] < 0:
                        raise ValueError("Voiceflow returned invalid agent metadata counters.")
                    result[field] = agent[field]
                for collection, id_key in (("workflows", "workflowID"), ("playbooks", "playbookID")):
                    rows = agent.get(collection)
                    if not isinstance(rows, list) or len(rows) > 200:
                        raise ValueError("Voiceflow returned invalid bounded agent workflow references.")
                    result[collection + "_ids"] = [identifier(row.get(id_key)) for row in rows if isinstance(row, dict)]
                    if len(result[collection + "_ids"]) != len(rows):
                        raise ValueError("Voiceflow returned invalid agent workflow references.")
            elif isinstance(config, QueryKnowledgeBase):
                body = await request(data, "POST", "/v1/stable/knowledge-base/query", params=knowledge_params(data),
                    body={"version": config.version, "question": config.question, "synthesis": False, "chunkLimit": config.chunk_limit})
                answer = body.get("answer")
                if not isinstance(answer, dict) or answer.get("output") is not None or answer.get("answerTokens", 0) != 0:
                    raise ValueError("Voiceflow returned a synthesized answer for retrieval-only mode; the result is refused.")
                chunks = answer.get("chunks")
                if not isinstance(chunks, list) or len(chunks) > config.chunk_limit:
                    raise ValueError("Voiceflow returned invalid bounded retrieval chunks.")
                selected = []
                for row in chunks:
                    if not isinstance(row, dict) or type(row.get("score")) not in (int, float) or not isinstance(row.get("source"), dict) or not isinstance(row.get("metadata"), dict):
                        raise ValueError("Voiceflow returned an invalid retrieval chunk.")
                    selected.append({"chunk_id": identifier(row.get("chunkID")), "document_id": identifier(row.get("documentID")),
                        "score": row["score"], "content": text(row.get("content"), 4096), "source_name": text(row["source"].get("name"), 256), "source_type": text(row["source"].get("type"), 32)})
                result = {"chunks": selected, "synthesis": False, "version": config.version, "project_id": data["project_id"], "environment_alias": data["environment_alias"]}
            else:
                target = config.document_id
                before = await document(data, target)
                if isinstance(config, GetDocument):
                    result = {"document": before}
                else:
                    method = "PATCH" if isinstance(config, UpdateDocumentMetadata) else "DELETE"
                    updates = parse_metadata(config.metadata_json) if method == "PATCH" else None
                    body = await request(data, method, "/v1/stable/document/" + path_id(target), params=knowledge_params(data),
                        body={"metadata": updates} if updates is not None else None, mutation=True)
                    acknowledged = True
                    text(body.get("message"), 512, nonempty=True)
                    if method == "PATCH":
                        after = await document(data, target)
                        if after["metadata"] != updates:
                            raise ValueError("Voiceflow document metadata readback differs from the requested update.")
                        result = {"document": after, "readback_verified": True}
                    else:
                        remaining = await documents(data)
                        if any(row["id"] == target for row in remaining):
                            raise ValueError("Voiceflow still returned the acknowledged deleted document.")
                        result = {"deleted_document_id": target, "readback_verified": True}
            return {"status": "success", "operation": config.operation, "data": safe_selected(result, data)}
        except Exception as exc:
            message = "The document write was acknowledged but its readback is unverified; inspect the selected document before retrying." if acknowledged else (
                str(exc) if isinstance(exc, (ValueError, VoiceflowAPIError)) else "The native Voiceflow result could not be verified.")
            return {"status": "error", "error": message, "status_code": getattr(exc, "http_status", None), "provider_status": getattr(exc, "provider_status", None),
                "write_outcome_uncertain": acknowledged or bool(getattr(exc, "uncertain", False)), "acknowledged_document_id": target if acknowledged else None}

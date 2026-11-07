"""Rossum v1 tenant document workflows with supplied-token credentials.

The pinned publisher OpenAPI is the contract: cursor URLs remain opaque, uploads
are asynchronous, and extracted values require an explicit selected-field read.
No login, export, document download, confirmation, or token mint is exposed.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import parse_qsl, urlsplit

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_serializer, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import guarded_async_client, normalize_https_origin

TYPE = "rossum_token"
AUTH_KEY = "_rossum_authority"
CURRENT_ORGANIZATION = object()
UNAVAILABLE = "Rossum credential is unavailable or its authority changed"
UNVERIFIED = "Rossum response could not be verified"
ID = Annotated[StrictInt, Field(ge=1, le=9007199254740991)]
Name = Annotated[StrictStr, Field(min_length=1, max_length=255)]
Status = Literal["confirmed", "created", "deleted", "exported", "exporting", "failed_export", "failed_import", "importing", "in_workflow", "postponed", "purged", "rejected", "reviewing", "split", "to_review"]


def tenant(value):
    if not isinstance(value, str): raise ValueError("Supply the exact Rossum HTTPS tenant origin")
    normalized = normalize_https_origin(value, field_name="Rossum tenant")
    # Both spellings are in the current publisher contract. Legacy Elis,
    # arbitrary dedicated hosts and custom ports are deliberately unsupported.
    if not re.fullmatch(r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:rossum\.app|app\.rossum\.ai)", normalized):
        raise ValueError("Use your tenant.rossum.app or tenant.app.rossum.ai HTTPS origin")
    return normalized


def token(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 8192 or any(c.isspace() or ord(c) < 33 for c in value) or "://" in value:
        raise ValueError("Supply an already-issued Rossum token without a URL or whitespace")
    return value


def form_id(value):
    return int(value) if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,15}", value) else value


class RossumTokenCredential(BaseModel):
    model_config = ConfigDict(title="Rossum API Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://example.app.rossum.ai/api/docs/openapi/guides/overview/",
        "x-credential-instructions": "Paste an already-issued Rossum Bearer token and exact tenant origin. Bind your organization ID from Rossum. This connection does not log in, exchange one-time tokens, refresh, or log out. The documented default token lifetime is 162 hours, but a token can expire sooner or be revoked. Organization reachability proves this resource binding, not user identity or every queue permission.",
    })
    credential_type: Literal["rossum_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    tenant_url: Annotated[StrictStr, BeforeValidator(tenant)] = Field(..., title="Rossum Tenant Origin", description="Exact HTTPS origin, without /api, a path, port, query or fragment.")
    organization_id: Annotated[ID, BeforeValidator(form_id)] = Field(..., title="Rossum Organization ID", description="Positive ID of the organization this connection may use.")
    api_token: Annotated[StrictStr, BeforeValidator(token)] = Field(..., title="Issued Rossum API Token", repr=False, json_schema_extra={"ui:widget": "password"})

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("Rossum requires its original supplied-token credential type")
    try: return RossumTokenCredential.model_validate(raw)
    except Exception: raise ValueError("Rossum credential fields are invalid") from None


def raw_guard(data):
    if not isinstance(data, dict): return
    raw = data.get("credentials")
    if raw is not None and (not isinstance(raw, dict) or raw.get("credential_type") != TYPE):
        raise ValueError("Rossum credential type is not supported")


def op(name, title, description, **extra):
    return Field(name, title=title, description=description, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": title, "x-category": "Document Workflows", "x-is-trigger": False, **extra})


def picker(resource, *parents):
    return {"x-resource-type": "rossum_" + resource.removesuffix("_id"), "x-dynamic-options": {"field_name": resource, "allow_custom": True, "searchable": False, "custom_placeholder": "Exact Rossum ID", **({"depends_on": parents[0]} if parents else {})}}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(Config):
    operation: Literal["check_connection"] = op("check_connection", "Check Organization Access", "Read the bound organization; this is resource reachability, not a human identity or full permission proof.")


class GetOrganization(Config):
    operation: Literal["get_organization"] = op("get_organization", "Get Organization", "Read closed organization metadata without users, security settings or billing.")


class Page(Config):
    page_size: Annotated[StrictInt, Field(ge=1, le=100)] = Field(20, title="Page Size")
    continuation_url: Optional[Annotated[StrictStr, Field(max_length=8192)]] = Field(None, title="Next Page URL", description="Use the complete next_page_url returned by this same operation and parent scope. The signed cursor is never constructed or changed.")


class ListWorkspaces(Page):
    operation: Literal["list_workspaces"] = op("list_workspaces", "List Workspaces", "One organization-scoped cursor page, at most 100 workspaces.")


class Workspace(Config):
    workspace_id: ID = Field(..., title="Workspace ID", json_schema_extra=picker("workspace_id"))


class GetWorkspace(Workspace):
    operation: Literal["get_workspace"] = op("get_workspace", "Get Workspace", "Verify that the workspace belongs to the bound organization.")


class Metadata(Config):
    metadata: dict[str, Any] = Field(..., title="Replacement Metadata", description="Complete replacement JSON metadata object, at most 4 kB. Preserve existing keys you need; avoid secrets and personal data.", json_schema_extra={"ui:widget": "json"})

    @model_validator(mode="after")
    def bounded_metadata(self):
        try:
            encoded = json.dumps(self.metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            if len(encoded) > 4096: raise ValueError()
        except (ValueError, TypeError, RecursionError): raise ValueError("Rossum metadata must be finite JSON of at most 4 kB") from None
        return self


class CreateWorkspace(Metadata):
    operation: Literal["create_workspace"] = op("create_workspace", "Create Workspace", "Create a workspace in the bound organization and verify it with a separate GET. Does not create a queue or enable automation.", **{"x-creates-resource": True, "x-resource-type": "workspace", "x-resource-id-path": "data.workspace.id"})
    name: Name = Field(..., title="Workspace Name")


class UpdateWorkspace(Workspace, Metadata):
    operation: Literal["update_workspace"] = op("update_workspace", "Update Workspace Metadata", "Change only the selected workspace name and replacement metadata; verify with a separate GET.")
    name: Optional[Name] = Field(None, title="New Workspace Name")


class DeleteEmptyWorkspace(Workspace):
    operation: Literal["delete_empty_workspace"] = op("delete_empty_workspace", "Delete Empty Workspace", "Destructive: require an empty bound workspace, DELETE 204, then authenticated GET 404. A provider 409 is a refusal, not successful cleanup.")
    expected_name: Name = Field(..., title="Expected Workspace Name", description="Exact name read back before deletion. Use only a disposable owned workspace.")


class ListQueues(Workspace, Page):
    operation: Literal["list_queues"] = op("list_queues", "List Queues", "Read one cursor page for an exact organization-bound workspace.")


class Queue(Workspace):
    queue_id: ID = Field(..., title="Queue ID", json_schema_extra=picker("queue_id", "workspace_id"))


class GetQueue(Queue):
    operation: Literal["get_queue"] = op("get_queue", "Get Queue", "Read queue identity, status and counts without inbox addresses, hooks, users, connectors or engine settings.")


class UpdateQueueMetadata(Queue, Metadata):
    operation: Literal["update_queue_metadata"] = op("update_queue_metadata", "Update Queue Metadata", "PATCH only metadata and optional name. Preserve queue automation, extraction, retention, hooks and settings.")
    name: Optional[Name] = Field(None, title="New Queue Name")


class ListAnnotations(Queue, Page):
    operation: Literal["list_annotations"] = op("list_annotations", "List Annotations", "Read private workflow status for one exact queue cursor page; no extracted values, emails or document URLs.")
    status: Optional[Status] = Field(None, title="Status Filter")


class Annotation(Queue):
    annotation_id: ID = Field(..., title="Annotation ID", description="Exact annotation ID from this queue; validated before content or metadata access. Enter a custom ID.")


class GetAnnotation(Annotation):
    operation: Literal["get_annotation"] = op("get_annotation", "Get Annotation Status", "Read exact queue-bound annotation status and timestamps without content or customer metadata.")


class GetAnnotationStructure(Annotation):
    operation: Literal["get_annotation_structure"] = op("get_annotation_structure", "Get Annotation Field Structure", "Project field IDs and schema IDs from private structured content. Discard OCR, values, positions and model predictions.")


class GetSelectedValues(Annotation):
    operation: Literal["get_selected_values"] = op("get_selected_values", "Read Selected Private Values", "Explicit private document data read. Return only requested schema IDs and their validated values. Treat downstream workflow data as confidential; no raw content, binary exports or public links.")
    schema_ids: Annotated[list[Annotated[StrictStr, Field(min_length=1, max_length=255)]], Field(min_length=1, max_length=50)] = Field(..., title="Selected Schema IDs", description="Exact extracted datapoint schema IDs; repeated table fields return multiple values.")

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.schema_ids)) != len(self.schema_ids): raise ValueError("Select each schema ID once")
        return self


class UpdateAnnotationMetadata(Annotation, Metadata):
    operation: Literal["update_annotation_metadata"] = op("update_annotation_metadata", "Update Annotation Metadata", "Change only replacement metadata; do not change workflow status, extraction values or assignees. Existing tenant extensions may observe the update.")


class GetDocument(Annotation):
    operation: Literal["get_document"] = op("get_document", "Get Annotation Document Metadata", "Read the document referenced by this queue-bound annotation. Return MIME type, IDs and timestamps without filename, storage keys or content URL.")


class UpdateDocumentMetadata(Annotation, Metadata):
    operation: Literal["update_document_metadata"] = op("update_document_metadata", "Update Annotation Document Metadata", "PATCH only replacement metadata on the exact document referenced by this annotation; verify via independent readback.")


class ImportDocument(Queue):
    operation: Literal["import_document"] = op("import_document", "Import Document Asynchronously", "Upload one supplied document. Starts extraction and may trigger configured tenant automation, extensions, or priced processing. Returns an accepted task ID, never a completed import. No URL download or automatic retry.")
    file_name: Annotated[StrictStr, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]*\.(?:pdf|png|jpg|jpeg|tif|tiff|xlsx|xls|docx|doc)$")] = Field(..., title="File Name", description="Simple filename only, no filesystem path.")
    content_base64: Annotated[StrictStr, Field(min_length=4, max_length=6990508)] = Field(..., title="Private File Content (Base64)", repr=False, description="Raw standard base64 supplied by the workflow, at most 5 MiB decoded; no data URL or arbitrary remote resource.", json_schema_extra={"ui:widget": "password"})
    reject_identical: StrictBool = Field(True, title="Reject Identical Document", description="Rossum checks identical filename and bytes in the organization; 409 remains a refusal.")

    @model_validator(mode="after")
    def validate_file(self):
        decode_file(self.content_base64)
        return self


class GetImportTask(Queue):
    operation: Literal["get_import_task"] = op("get_import_task", "Get Import Task Status", "GET task with no_redirect=true. Require upload_created and validate its upload's queue and organization. Discard provider detail and arbitrary result URLs.")
    task_id: ID = Field(..., title="Import Task ID")


class GetUpload(Queue):
    operation: Literal["get_upload"] = op("get_upload", "Get Upload Result", "Read exact bound upload metadata and created document/annotation IDs without content, filenames or user information.")
    upload_id: ID = Field(..., title="Upload ID")


OPERATIONS = (CheckConnection, GetOrganization, ListWorkspaces, GetWorkspace, CreateWorkspace, UpdateWorkspace, DeleteEmptyWorkspace, ListQueues, GetQueue, UpdateQueueMetadata, ListAnnotations, GetAnnotation, GetAnnotationStructure, GetSelectedValues, UpdateAnnotationMetadata, GetDocument, UpdateDocumentMetadata, ImportDocument, GetImportTask, GetUpload)
RossumConfig = Annotated[Union[CheckConnection, GetOrganization, ListWorkspaces, GetWorkspace, CreateWorkspace, UpdateWorkspace, DeleteEmptyWorkspace, ListQueues, GetQueue, UpdateQueueMetadata, ListAnnotations, GetAnnotation, GetAnnotationStructure, GetSelectedValues, UpdateAnnotationMetadata, GetDocument, UpdateDocumentMetadata, ImportDocument, GetImportTask, GetUpload], Field(discriminator="operation")]


class RossumNodeConfig(NodeConfig[RossumConfig, RossumTokenCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-rossum"] = "automation-rossum"


@dataclass(eq=False)
class Authority:
    credential: RossumTokenCredential
    pool: Any = None
    user_id: Any = None
    credential_id: Any = None
    organization_id: Any = None
    workflow_id: Any = None

    @classmethod
    async def create(cls, raw, *, pool=None, user_id=None, credential_id=None, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        shaped = credential(raw)
        if credential_id and not user_id: raise ValueError(UNAVAILABLE)
        current = cls(shaped, pool, user_id, credential_id, organization_id, workflow_id)
        if credential_id:
            if pool is None:
                from utils.database_pool import get_native_pool
                current.pool = get_native_pool()
            if organization_id is CURRENT_ORGANIZATION:
                from wss.handlers.workflow_handler import get_user_org_context
                async with current.pool.acquire() as conn:
                    current.organization_id = await get_user_org_context(conn, user_id)
            latest = await current.load()
            if latest != shaped: raise ValueError(UNAVAILABLE)
        return current

    async def load(self):
        # Staging owns access, revocation and workflow-owner fallback checks.
        raw = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id,
        )
        if not raw: raise ValueError(UNAVAILABLE)
        return credential(raw)

    async def require_current(self):
        if self.credential_id and await self.load() != self.credential:
            raise ValueError(UNAVAILABLE)


class ApiError(ValueError):
    def __init__(self, status, retry_after=None):
        self.status_code = status
        self.retry_after = retry_after
        super().__init__(f"Rossum API returned HTTP {status}" + (f"; retry after {retry_after} seconds" if retry_after is not None else ""))


class OutcomeUnverified(RuntimeError): pass


def decode_file(value):
    try:
        content = base64.b64decode(value, validate=True)
        if not content or len(content) > 5242880 or base64.b64encode(content).decode() != value: raise ValueError()
        return content
    except (ValueError, binascii.Error): raise ValueError("Supply canonical base64 for one document of at most 5 MiB") from None


def resource_url(auth, resource, identifier):
    return f"{auth.credential.tenant_url}/api/v1/{resource}/{identifier}"


def reference_id(auth, value, resource, expected=None):
    prefix = auth.credential.tenant_url + "/api/v1/" + resource + "/"
    if not isinstance(value, str) or not value.startswith(prefix) or not re.fullmatch(r"[1-9][0-9]{0,15}", value[len(prefix):]): raise OutcomeUnverified(UNVERIFIED)
    identifier = int(value[len(prefix):])
    if identifier > 9007199254740991 or expected is not None and identifier != expected: raise OutcomeUnverified(UNVERIFIED)
    return identifier


def entity(auth, raw, resource, expected=None):
    if not isinstance(raw, dict) or type(raw.get("id")) is not int or not 1 <= raw["id"] <= 9007199254740991: raise OutcomeUnverified(UNVERIFIED)
    reference_id(auth, raw.get("url"), resource, raw["id"])
    if expected is not None and raw["id"] != expected: raise OutcomeUnverified(UNVERIFIED)
    return raw


def short_text(raw, key, maximum=255, nullable=False):
    value = raw.get(key)
    if nullable and value is None: return None
    if not isinstance(value, str) or not len(value) <= maximum: raise OutcomeUnverified(UNVERIFIED)
    return value


def base_projection(raw, *keys):
    return {"id": raw["id"], **{key: short_text(raw, key, 100, nullable=True) for key in keys}}


def next_page(auth, value, resource, params):
    if value is None: return None
    if not isinstance(value, str) or len(value) > 8192: raise OutcomeUnverified(UNVERIFIED)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc != urlsplit(auth.credential.tenant_url).netloc or parsed.path != "/api/v1/" + resource or parsed.fragment or parsed.username or parsed.password: raise OutcomeUnverified(UNVERIFIED)
    try: pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError: raise OutcomeUnverified(UNVERIFIED) from None
    query = dict(pairs)
    if len(query) != len(pairs) or set(query) != set(params) | {"cursor"} or not query.get("cursor") or len(query["cursor"]) > 4096 or any(query.get(key) != str(value) for key, value in params.items()): raise OutcomeUnverified("Rossum cursor URL does not retain the exact operation and parent filters")
    # The complete publisher URL is preserved; no cursor decoding/re-encoding.
    return value


async def request(auth, method, path, *, params=None, body=None, files=None, success=(200,), absolute=False):
    await auth.require_current()
    url = path if absolute else auth.credential.tenant_url + "/api/v1/" + path
    try:
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, url, params=params, json=body, files=files, headers={"Authorization": "Bearer " + auth.credential.api_token, "Accept": "application/json", "User-Agent": "NoClick-Rossum/1.0"}) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 4194304: raise OutcomeUnverified(UNVERIFIED)
                    raw.extend(chunk)
                    await auth.require_current()
                await auth.require_current()
                if response.status_code not in success:
                    delay = response.headers.get("retry-after", "")
                    raise ApiError(response.status_code, int(delay) if re.fullmatch(r"[0-9]{1,6}", delay) else None)
                if response.status_code in (204, 404):
                    if response.status_code == 204 and raw: raise OutcomeUnverified(UNVERIFIED)
                    return response.status_code, None
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise OutcomeUnverified(UNVERIFIED)
                try: data = json.loads(raw)
                except (ValueError, UnicodeError): raise OutcomeUnverified(UNVERIFIED) from None
                return response.status_code, data
    except httpx.RequestError:
        raise OutcomeUnverified("Rossum transport outcome is unverified; a write may already have been accepted") from None


async def get(auth, resource, identifier):
    _, raw = await request(auth, "GET", f"{resource}/{identifier}")
    return entity(auth, raw, resource, identifier)


def workspace_projection(auth, raw):
    return {"id": raw["id"], "name": short_text(raw, "name"), "organization_id": reference_id(auth, raw.get("organization"), "organizations", auth.credential.organization_id), "queue_ids": references(auth, raw.get("queues"), "queues"), **{key: short_text(raw, key, 100, True) for key in ("created_at", "modified_at")}}


def references(auth, values, resource, nullable=False):
    if nullable and values is None: return []
    if not isinstance(values, list) or len(values) > 10000: raise OutcomeUnverified(UNVERIFIED)
    ids = [reference_id(auth, value, resource) for value in values]
    if len(set(ids)) != len(ids): raise OutcomeUnverified(UNVERIFIED)
    return ids


def queue_projection(auth, raw, workspace_id):
    parent = reference_id(auth, raw.get("workspace"), "workspaces", workspace_id)
    counts = raw.get("counts")
    if not isinstance(counts, dict) or any(type(v) is not int or v < 0 for v in counts.values()): raise OutcomeUnverified(UNVERIFIED)
    return {"id": raw["id"], "name": short_text(raw, "name"), "workspace_id": parent, "status": short_text(raw, "status"), "counts": {k: v for k, v in counts.items() if k in Status.__args__}, "modified_at": short_text(raw, "modified_at", 100, True)}


def annotation_projection(auth, raw, queue_id):
    return {"id": raw["id"], "queue_id": reference_id(auth, raw.get("queue"), "queues", queue_id), "organization_id": reference_id(auth, raw.get("organization"), "organizations", auth.credential.organization_id), "document_id": reference_id(auth, raw.get("document"), "documents"), "status": short_text(raw, "status"), **{key: short_text(raw, key, 100, True) for key in ("created_at", "modified_at", "exported_at", "confirmed_at")}}


async def page(auth, resource, params, continuation, projection):
    url = next_page(auth, continuation, resource, params) if continuation else None
    _, raw = await request(auth, "GET", url or resource, params=None if url else params, absolute=bool(url))
    if not isinstance(raw, dict) or not isinstance(raw.get("results"), list) or len(raw["results"]) > params["page_size"] or not isinstance(raw.get("pagination"), dict): raise OutcomeUnverified(UNVERIFIED)
    items = [projection(entity(auth, row, resource)) for row in raw["results"]]
    if len({row["id"] for row in items}) != len(items): raise OutcomeUnverified(UNVERIFIED)
    nxt = next_page(auth, raw["pagination"].get("next"), resource, params)
    if nxt is not None and nxt == url: raise OutcomeUnverified("Rossum cursor did not advance")
    return {"items": items, "next_page_url": nxt, "has_more": nxt is not None}


def structured_content(auth, raw, annotation_id, selected=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("content"), list): raise OutcomeUnverified(UNVERIFIED)
    rows, seen = [], set()
    def walk(node, depth=0):
        if depth > 8 or not isinstance(node, dict) or type(node.get("id")) is not int or node["id"] < 1 or node["id"] in seen or len(seen) >= 5000: raise OutcomeUnverified(UNVERIFIED)
        seen.add(node["id"])
        expected = f"{auth.credential.tenant_url}/api/v1/annotations/{annotation_id}/content/{node['id']}"
        if node.get("url") != expected or node.get("category") not in ("section", "multivalue", "tuple", "datapoint"): raise OutcomeUnverified(UNVERIFIED)
        schema_id = short_text(node, "schema_id")
        if node["category"] == "datapoint":
            row = {"id": node["id"], "schema_id": schema_id, "category": "datapoint"}
            if selected is not None and schema_id in selected:
                content = node.get("content")
                if content is not None and (not isinstance(content, dict) or not isinstance(content.get("value"), str) or len(content["value"]) > 1500): raise OutcomeUnverified(UNVERIFIED)
                row["value"] = content["value"] if content is not None else None
                rows.append(row)
            elif selected is None: rows.append(row)
        else:
            children = node.get("children")
            if not isinstance(children, list): raise OutcomeUnverified(UNVERIFIED)
            if selected is None: rows.append({"id": node["id"], "schema_id": schema_id, "category": node["category"]})
            for child in children: walk(child, depth + 1)
    for section in raw["content"]:
        if not isinstance(section, dict) or section.get("category") != "section": raise OutcomeUnverified(UNVERIFIED)
        walk(section)
    return {"annotation_id": annotation_id, "fields": rows, **({"missing_schema_ids": sorted(set(selected) - {row["schema_id"] for row in rows}), "private_values": True} if selected is not None else {})}


async def operate(auth, cfg):
    organization = await get(auth, "organizations", auth.credential.organization_id)
    org = {"id": organization["id"], "name": short_text(organization, "name"), "binding": "organization_resource_access"}
    if isinstance(cfg, (CheckConnection, GetOrganization)): return org
    if isinstance(cfg, ListWorkspaces):
        return await page(auth, "workspaces", {"organization": auth.credential.organization_id, "page_size": cfg.page_size}, cfg.continuation_url, lambda raw: workspace_projection(auth, raw))
    if isinstance(cfg, CreateWorkspace):
        _, raw = await request(auth, "POST", "workspaces", body={"name": cfg.name, "organization": resource_url(auth, "organizations", auth.credential.organization_id), "metadata": cfg.metadata}, success=(201,))
        ack = entity(auth, raw, "workspaces")
        workspace_projection(auth, ack)
        current = await get(auth, "workspaces", ack["id"])
        projection = workspace_projection(auth, current)
        if current.get("metadata") != cfg.metadata or current.get("name") != cfg.name: raise OutcomeUnverified("Rossum workspace creation was acknowledged but readback differs")
        return {"workspace": projection, "write_acknowledged": True, "readback_verified": True}
    workspace = await get(auth, "workspaces", cfg.workspace_id)
    projected_workspace = workspace_projection(auth, workspace)
    if isinstance(cfg, GetWorkspace): return projected_workspace
    if isinstance(cfg, UpdateWorkspace):
        body = {"metadata": cfg.metadata, **({"name": cfg.name} if cfg.name is not None else {})}
        _, ack = await request(auth, "PATCH", f"workspaces/{cfg.workspace_id}", body=body)
        workspace_projection(auth, entity(auth, ack, "workspaces", cfg.workspace_id))
        current = await get(auth, "workspaces", cfg.workspace_id)
        projection = workspace_projection(auth, current)
        if current.get("metadata") != cfg.metadata or cfg.name is not None and current.get("name") != cfg.name: raise OutcomeUnverified("Rossum workspace update was acknowledged but readback differs")
        return {"workspace": projection, "write_acknowledged": True, "readback_verified": True}
    if isinstance(cfg, DeleteEmptyWorkspace):
        if projected_workspace["name"] != cfg.expected_name or projected_workspace["queue_ids"]: raise ValueError("Only the exact named empty workspace may be deleted")
        await request(auth, "DELETE", f"workspaces/{cfg.workspace_id}", success=(204,))
        status, _ = await request(auth, "GET", f"workspaces/{cfg.workspace_id}", success=(200, 404))
        if status != 404: raise OutcomeUnverified("Rossum deletion was acknowledged but absence is not confirmed")
        return {"workspace_id": cfg.workspace_id, "deleted": True, "readback_verified": True}
    if isinstance(cfg, ListQueues):
        return await page(auth, "queues", {"workspace": cfg.workspace_id, "page_size": cfg.page_size}, cfg.continuation_url, lambda raw: queue_projection(auth, raw, cfg.workspace_id))
    queue = await get(auth, "queues", cfg.queue_id)
    projected_queue = queue_projection(auth, queue, cfg.workspace_id)
    if cfg.queue_id not in projected_workspace["queue_ids"]: raise OutcomeUnverified("Rossum queue is not referenced by the selected workspace")
    if isinstance(cfg, GetQueue): return projected_queue
    if isinstance(cfg, UpdateQueueMetadata):
        body = {"metadata": cfg.metadata, **({"name": cfg.name} if cfg.name is not None else {})}
        _, ack = await request(auth, "PATCH", f"queues/{cfg.queue_id}", body=body)
        queue_projection(auth, entity(auth, ack, "queues", cfg.queue_id), cfg.workspace_id)
        current = await get(auth, "queues", cfg.queue_id)
        projection = queue_projection(auth, current, cfg.workspace_id)
        if current.get("metadata") != cfg.metadata or cfg.name is not None and current.get("name") != cfg.name: raise OutcomeUnverified("Rossum queue update was acknowledged but readback differs")
        return {"queue": projection, "write_acknowledged": True, "readback_verified": True}
    if isinstance(cfg, ListAnnotations):
        params = {"queue": cfg.queue_id, "page_size": cfg.page_size, **({"status": cfg.status} if cfg.status is not None else {})}
        return await page(auth, "annotations", params, cfg.continuation_url, lambda raw: annotation_projection(auth, raw, cfg.queue_id))
    if isinstance(cfg, ImportDocument):
        if projected_queue["status"] != "active": raise ValueError("Rossum imports require an active queue")
        content = decode_file(cfg.content_base64)
        _, ack = await request(auth, "POST", "uploads", params={"queue": cfg.queue_id, "reject_identical": "true" if cfg.reject_identical else "false"}, files={"content": (cfg.file_name, content, "application/octet-stream")}, success=(202,))
        if not isinstance(ack, dict): raise OutcomeUnverified(UNVERIFIED)
        task_id = reference_id(auth, ack.get("url"), "tasks")
        return {"task_id": task_id, "queue_id": cfg.queue_id, "accepted": True, "import_complete": False, "provider_status": 202}
    async def upload(identifier):
        raw = await get(auth, "uploads", identifier)
        reference_id(auth, raw.get("organization"), "organizations", auth.credential.organization_id)
        reference_id(auth, raw.get("queue"), "queues", cfg.queue_id)
        return {"id": raw["id"], "queue_id": cfg.queue_id, "document_ids": references(auth, raw.get("documents"), "documents"), "annotation_ids": references(auth, raw.get("annotations"), "annotations", True), "created_at": short_text(raw, "created_at", 100, True)}
    if isinstance(cfg, GetUpload): return await upload(cfg.upload_id)
    if isinstance(cfg, GetImportTask):
        _, data = await request(auth, "GET", f"tasks/{cfg.task_id}", params={"no_redirect": "true"})
        raw = entity(auth, data, "tasks", cfg.task_id)
        if raw.get("type") != "upload_created" or raw.get("status") not in ("running", "succeeded", "failed") or not isinstance(raw.get("content"), dict): raise OutcomeUnverified(UNVERIFIED)
        upload_id = reference_id(auth, raw["content"].get("upload"), "uploads")
        bound = await upload(upload_id)
        return {"id": cfg.task_id, "type": "upload_created", "status": raw["status"], "expires_at": short_text(raw, "expires_at", 100), "upload": bound, "upload_task_complete": raw["status"] == "succeeded", "extraction_status_verified": False}
    annotation = await get(auth, "annotations", cfg.annotation_id)
    projected_annotation = annotation_projection(auth, annotation, cfg.queue_id)
    if isinstance(cfg, GetAnnotation): return projected_annotation
    if isinstance(cfg, (GetAnnotationStructure, GetSelectedValues)):
        _, raw = await request(auth, "GET", f"annotations/{cfg.annotation_id}/content")
        return structured_content(auth, raw, cfg.annotation_id, cfg.schema_ids if isinstance(cfg, GetSelectedValues) else None)
    if isinstance(cfg, UpdateAnnotationMetadata):
        _, ack = await request(auth, "PATCH", f"annotations/{cfg.annotation_id}", body={"metadata": cfg.metadata})
        annotation_projection(auth, entity(auth, ack, "annotations", cfg.annotation_id), cfg.queue_id)
        current = await get(auth, "annotations", cfg.annotation_id)
        projection = annotation_projection(auth, current, cfg.queue_id)
        if current.get("metadata") != cfg.metadata: raise OutcomeUnverified("Rossum annotation metadata was acknowledged but readback differs")
        return {"annotation": projection, "write_acknowledged": True, "readback_verified": True}
    document_id = projected_annotation["document_id"]
    def document_projection(raw):
        if cfg.annotation_id not in references(auth, raw.get("annotations"), "annotations"): raise OutcomeUnverified("Rossum document does not refer to the selected annotation")
        return {"id": document_id, "annotation_id": cfg.annotation_id, "mime_type": short_text(raw, "mime_type"), "arrived_at": short_text(raw, "arrived_at", 100, True)}
    document = await get(auth, "documents", document_id)
    projected_document = document_projection(document)
    if isinstance(cfg, GetDocument): return projected_document
    if isinstance(cfg, UpdateDocumentMetadata):
        _, ack = await request(auth, "PATCH", f"documents/{document_id}", body={"metadata": cfg.metadata})
        document_projection(entity(auth, ack, "documents", document_id))
        current = await get(auth, "documents", document_id)
        projection = document_projection(current)
        if current.get("metadata") != cfg.metadata: raise OutcomeUnverified("Rossum document metadata was acknowledged but readback differs")
        return {"document": projection, "write_acknowledged": True, "readback_verified": True}
    raise ValueError("Unsupported Rossum operation")


class RossumNode(WorkflowNode):
    integration_type = "automation-rossum"
    connection_evidence = ConnectionEvidence(identity_operation="check_connection", identity_keys=("name",), noun="Rossum organization")

    @classmethod
    def get_config_model(cls): return RossumNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        raw_guard(config_data)
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Supplied tokens do not refresh; staging resolves saved access first.
        return credential(credential_data).model_dump()

    @classmethod
    async def validate_credential_access(cls, raw):
        try:
            auth = await Authority.create(raw)
            await operate(auth, CheckConnection())
            return {"valid": True, "error": None}
        except ApiError as error:
            return {"valid": False if error.status_code == 401 else None, "error": str(error)}
        except Exception:
            return {"valid": None, "error": "Rossum organization access is unverified"}

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if self.config.credentials is None: raise ValueError("Rossum credentials are required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        data = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "data": data}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in ("workspace_id", "queue_id") or search or context is not None and not isinstance(context, dict): raise ValueError("Use the documented Rossum picker or enter an exact custom ID")
        auth = credential_data.get(AUTH_KEY) if isinstance(credential_data, dict) else None
        if auth is not None and (not isinstance(auth, Authority) or auth.credential != credential(credential_data)): raise ValueError(UNAVAILABLE)
        if auth is None: auth = await Authority.create(credential_data)
        try:
            cfg = ListWorkspaces(page_size=100, continuation_url=page_token) if field_name == "workspace_id" else ListQueues(workspace_id=(context or {}).get("workspace_id"), page_size=100, continuation_url=page_token)
        except Exception: raise ValueError("Select a typed parent workspace before loading Rossum queues") from None
        data = await operate(auth, cfg)
        await auth.require_current()
        return {"options": [{"value": row["id"], "label": row["name"]} for row in data["items"]], "next_page_token": data["next_page_url"]}

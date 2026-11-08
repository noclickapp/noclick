"""Native Veryfi receipts/invoices processing and document organization.

Client-scoped keys use fixed production/development origins and optional documented
HMAC signing. Private results are projected; raw OCR, media, bank and card fields are discarded.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import time
import unicodedata
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import SSRFError, allow_private_hosts, guarded_async_client

TYPES = ("veryfi_bearer_api_key", "veryfi_standard_api_key")
ROOTS = {"production": "https://api.veryfi.com", "development": "https://devapi.veryfi.com"}
DOCUMENTS = "/api/v8/partner/documents"
MAX_BYTES = 2 * 1024 * 1024
MAX_ID = 9223372036854775807


def text_value(value):
    if not isinstance(value, str) or not value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Use nonempty text without control characters")
    return unicodedata.normalize("NFC", value.strip())


def id_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > MAX_ID:
        raise ValueError("Use the decimal Veryfi ID, without a URL or path")
    return value


def provider_id(value):
    if type(value) is not int or not 1 <= value <= MAX_ID:
        raise ValueError("Veryfi returned an invalid integer ID")
    return str(value)


def utc_value(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", value):
        raise ValueError("Use UTC YYYY-MM-DD HH:MM:SS")
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError("Use a valid UTC date and time") from None
    return value


Text = Annotated[str, BeforeValidator(text_value)]
RecordID = Annotated[str, BeforeValidator(id_value)]
UTCTime = Annotated[str, BeforeValidator(utc_value)]


def confirmation_value(value):
    if type(value) is not bool or value is not True:
        raise ValueError("Explicitly confirm this operation")
    return value


Confirmation = Annotated[Literal[True], BeforeValidator(confirmation_value)]


class ClientCredential(BaseModel):
    environment: Literal["production", "development"] = Field("production", title="Veryfi Environment", description="Development uses the vendor staging model endpoint; it does not guarantee free or isolated processing. Confirm the environment shown with your issued key.")
    client_id: str = Field(..., min_length=1, max_length=256, title="Client ID", description="The CLIENT-ID belonging to the account that issued the API key.")
    client_secret: str | None = Field(None, min_length=1, max_length=6000, repr=False, title="Client Secret for Request Signing", description="Optional in the public contract; supply it when your account requires signatures. Never retried without signing.", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    @field_validator("client_id", mode="before")
    @classmethod
    def client_value(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
            raise ValueError("Supply the issued Veryfi Client ID")
        return value

    @field_validator("client_secret", mode="before")
    @classmethod
    def secret_value(cls, value):
        return key_value(value) if value is not None else None


def key_value(value):
    if not isinstance(value, str):
        raise ValueError("Supply an issued opaque Veryfi key")
    value = clean_secret(value)
    if not value or not value.isascii() or re.search(r"[\x00-\x20\x7f:]", value):
        raise ValueError("Supply only the key without a header prefix or whitespace")
    return value


class VeryfiBearerAPIKeyCredential(ClientCredential):
    credential_type: Literal["veryfi_bearer_api_key"] = Field(TYPES[0], json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=6000, repr=False, title="Bearer API Key", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Veryfi Bearer API Key", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.veryfi.com/api/getting-started/authentication/bearer-keys/",
        "x-credential-instructions": "Recommended client-scoped Bearer key, full-access or explicitly route-scoped. Supply its matching CLIENT-ID, environment and signing secret if required. Route grants and expiry are enforced by Veryfi; no OAuth exchange, key administration or automatic refresh is performed.",
    })

    @model_validator(mode="before")
    @classmethod
    def manual_family(cls, value):
        return {"credential_type": TYPES[0], **value} if isinstance(value, dict) else value

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        return key_value(value)


class VeryfiStandardAPIKeyCredential(ClientCredential):
    credential_type: Literal["veryfi_standard_api_key"] = Field(TYPES[1], json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=256, repr=False, title="Veryfi Username")
    api_key: str = Field(..., min_length=1, max_length=6000, repr=False, title="Standard API Key", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Veryfi Standard API Key", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.veryfi.com/api/getting-started/authentication/standard-keys/",
        "x-credential-instructions": "Legacy, still supported per-user key. Supply the username paired with the key, account CLIENT-ID, correct environment and signing secret where required. This family sends Authorization: apikey username:key; it is distinct from a client-scoped Bearer key.",
    })

    @model_validator(mode="before")
    @classmethod
    def manual_family(cls, value):
        return {"credential_type": TYPES[1], **value} if isinstance(value, dict) else value

    @field_validator("api_key", mode="before")
    @classmethod
    def valid_key(cls, value):
        return key_value(value)

    @field_validator("username", mode="before")
    @classmethod
    def valid_username(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.@+\-]{1,256}", value):
            raise ValueError("Supply the username paired with this standard key")
        return value


def credential_value(raw, *, manual=False):
    if isinstance(raw, (VeryfiBearerAPIKeyCredential, VeryfiStandardAPIKeyCredential)):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        raise ValueError("Connect a typed Veryfi credential")
    family = raw.get("credential_type")
    if manual and family is None:
        family = TYPES[1] if "username" in raw else TYPES[0]
        raw = {**raw, "credential_type": family}
    if family not in TYPES:
        raise ValueError("Connect a typed Veryfi Bearer or standard API key")
    try:
        model = VeryfiBearerAPIKeyCredential if family == TYPES[0] else VeryfiStandardAPIKeyCredential
        return model.model_validate(raw)
    except ValueError:
        raise ValueError("Supply valid Veryfi client, environment and key fields") from None


def picker(field, depends=None):
    dynamic = {"field_name": field, "searchable": True, "allow_custom": True, "custom_placeholder": "Paste a decimal Veryfi ID"}
    if depends:
        dynamic["depends_on"] = depends
    return {"x-resource-type": "veryfi_" + field, "x-dynamic-options": dynamic}


def operation_field(value, name, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": name, "x-category": category})


def operation_meta(name, category, effect=None):
    extra = {"x-display-name": name, "x-category": category, "x-is-trigger": False}
    if effect:
        extra["x-operation-effect"] = effect
    return ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra=extra)


class ListDocuments(BaseModel):
    operation: Literal["list_documents"] = operation_field("list_documents", "List or search documents", "Documents")
    page_size: int = Field(10, strict=True, ge=1, le=50, title="Page Size", description="Exactly one bounded page; Veryfi maximum 50.")
    page_token: str | None = Field(None, max_length=128, title="Next Page Token", description="Use this node's returned continuation with unchanged key, environment and filters.")
    q: Text | None = Field(None, max_length=200, title="Search Text", description="Case sensitive OCR/extracted-field/notes/external-ID search. * is the documented partial-match wildcard; returned data remains metadata only.")
    external_id: Text | None = Field(None, max_length=256, title="External ID")
    tag: Text | None = Field(None, max_length=100, title="Tag Name")
    status: Text | None = Field(None, max_length=64, title="Document Status", description="A status returned by Veryfi, for example in_progress; no invented lifecycle values.")
    created_after: UTCTime | None = Field(None, title="Created After (UTC)")
    created_before: UTCTime | None = Field(None, title="Created Before (UTC)")
    model_config = operation_meta("List or search documents", "Documents")

    @model_validator(mode="after")
    def date_range(self):
        if self.created_after and self.created_before and self.created_after >= self.created_before:
            raise ValueError("Use an increasing UTC creation range")
        return self


class DocumentParent(BaseModel):
    document_id: RecordID = Field(..., title="Document ID", json_schema_extra=picker("document_id"))


class GetDocument(DocumentParent):
    operation: Literal["get_document"] = operation_field("get_document", "Get structured document summary", "Documents")
    model_config = operation_meta("Get structured document summary", "Documents")


class GetStatus(DocumentParent):
    operation: Literal["get_document_status"] = operation_field("get_document_status", "Get document status and timestamps", "Documents")
    model_config = operation_meta("Get document status and timestamps", "Documents")


class Upload(BaseModel):
    file_name: Text = Field(..., max_length=128, title="Document Filename", description="A basename ending .pdf, .png, .jpg or .jpeg, matching the supplied bytes.")
    file_data: str = Field(..., min_length=1, max_length=2796204, repr=False, title="Base64 Document", description="Canonical raw Base64 only, 250 bytes–2 MiB decoded. No data URI, URL, S3 path, local file or ZIP; uploaded content is private workflow input.", json_schema_extra={"ui:widget": "textarea"})
    external_id: Text | None = Field(None, max_length=256, title="External ID")
    max_pages_to_process: int = Field(1, strict=True, ge=1, le=15, title="Maximum Pages", description="Process at most this many starting pages; additional pages are intentionally omitted.")
    idempotency_key: Text = Field(..., max_length=255, title="Upload Idempotency Key", description="A unique opaque ASCII key for this upload. Reuse it only for a deliberate retry of the same upload, client and mode. No automatic retry.")
    confirm_processing: Confirmation = Field(..., title="I Authorize Document Processing", description="Exports supplied content to Veryfi; may incur charges, retention and configured webhooks even on timeout.")

    @field_validator("idempotency_key")
    @classmethod
    def header_key(cls, value):
        if not value.isascii() or re.search(r"[\x00-\x20\x7f]", value):
            raise ValueError("Use an opaque ASCII idempotency key without whitespace")
        return value

    @model_validator(mode="after")
    def file_contract(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,120}\.(?:pdf|png|jpg|jpeg)", self.file_name, re.IGNORECASE):
            raise ValueError("Use a PDF, PNG or JPEG basename without paths")
        try:
            decoded = base64.b64decode(self.file_data, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Supply canonical raw Base64 document bytes") from None
        if not 250 <= len(decoded) <= MAX_BYTES or base64.b64encode(decoded).decode() != self.file_data:
            raise ValueError("Supply 250 bytes–2 MiB of canonical Base64")
        extension = self.file_name.rsplit(".", 1)[1].lower()
        magic = decoded.startswith(b"%PDF-") if extension == "pdf" else decoded.startswith(b"\x89PNG\r\n\x1a\n") if extension == "png" else decoded.startswith(b"\xff\xd8\xff")
        if not magic:
            raise ValueError("Filename does not match PDF, PNG or JPEG document bytes")
        return self


class ProcessDocument(Upload):
    operation: Literal["process_document"] = operation_field("process_document", "Process a receipt or invoice", "Processing")
    model_config = operation_meta("Process a receipt or invoice", "Processing", "Uploads private content for billed extraction, retention and configured webhook delivery; timeout does not mean failure.")


class ProcessDocumentAsync(Upload):
    operation: Literal["process_document_async"] = operation_field("process_document_async", "Submit asynchronous document processing", "Processing")
    model_config = operation_meta("Submit asynchronous document processing", "Processing", "Uploads content and returns a document ID before extraction finishes; may be billed and deliver configured webhooks. No webhook is created.")


class UpdateMetadata(DocumentParent):
    operation: Literal["update_document_metadata"] = operation_field("update_document_metadata", "Update document notes or external ID", "Documents")
    external_id: Text | None = Field(None, max_length=256, title="External ID", description="Omit to keep unchanged; explicitly set null to clear.")
    notes: str | None = Field(None, max_length=2000, title="Notes", description="Private document notes. Omit to keep unchanged; explicitly set null to clear.", json_schema_extra={"ui:widget": "textarea"})
    confirm_update: Confirmation = Field(..., title="I Authorize Updating Document Metadata")
    model_config = operation_meta("Update document notes or external ID", "Documents", "Changes the selected document's notes/external ID; no extracted financial fields are writable here.")

    @field_validator("notes", mode="before")
    @classmethod
    def notes_value(cls, value):
        if value is not None and (not isinstance(value, str) or re.search(r"[\x00-\x08\x0b-\x1f\x7f]", value)):
            raise ValueError("Use notes without control characters")
        return unicodedata.normalize("NFC", value) if value is not None else None

    @model_validator(mode="after")
    def supplied_patch(self):
        if not {"notes", "external_id"}.intersection(self.model_fields_set):
            raise ValueError("Supply notes or an external ID, including explicit null to clear")
        return self


class DeleteDocument(DocumentParent):
    operation: Literal["delete_document"] = operation_field("delete_document", "Delete a document", "Documents")
    confirm_delete: Confirmation = Field(..., title="I Authorize Deleting This Document", description="Removes the selected stored document. One protected GET readback must return 404 before absence is confirmed.")
    model_config = operation_meta("Delete a document", "Documents", "Deletes the selected stored document; no automatic retry or restoration.")


class ListTags(DocumentParent):
    operation: Literal["list_document_tags"] = operation_field("list_document_tags", "List document tags", "Tags")
    model_config = operation_meta("List document tags", "Tags")


class AddTag(DocumentParent):
    operation: Literal["add_document_tag"] = operation_field("add_document_tag", "Add a document tag", "Tags")
    name: Text = Field(..., max_length=100, title="Tag Name")
    confirm_update: Confirmation = Field(..., title="I Authorize Adding This Tag", description="Adds an existing tag or creates a new account tag and attaches it.")
    model_config = operation_meta("Add a document tag", "Tags", "May create a new account tag and attach it to this document.")


class UnlinkTag(DocumentParent):
    operation: Literal["unlink_document_tag"] = operation_field("unlink_document_tag", "Unlink a document tag", "Tags")
    tag_id: RecordID = Field(..., title="Tag ID", json_schema_extra=picker("tag_id", "document_id"))
    confirm_update: Confirmation = Field(..., title="I Authorize Unlinking This Tag", description="Removes the document association; does not delete the account tag.")
    model_config = operation_meta("Unlink a document tag", "Tags", "Unlinks one selected tag from this document.")


Operations = Annotated[Union[ListDocuments, GetDocument, GetStatus, ProcessDocument, ProcessDocumentAsync, UpdateMetadata, DeleteDocument, ListTags, AddTag, UnlinkTag], Discriminator("operation")]


class VeryfiNodeConfig(NodeConfig):
    config: Operations = Field(default_factory=ListDocuments)
    credentials: Union[VeryfiBearerAPIKeyCredential, VeryfiStandardAPIKeyCredential, None] = None


VERYFI_SCOPES = ScopeRegistry("veryfi", {name: ScopeRequirement(credential_types=TYPES, note="Veryfi enforces the supplied key's actual route grants and expiry") for name in (
    "list_documents", "get_document", "get_document_status", "process_document", "process_document_async", "update_document_metadata", "delete_document", "list_document_tags", "add_document_tag", "unlink_document_tag",
)})


def finite_json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def decimal(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
        return number
    try:
        return json.loads(content, object_pairs_hook=pairs, parse_float=decimal, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Veryfi returned malformed or nonfinite JSON") from None


class VeryfiAPIError(ValueError):
    def __init__(self, status, retry_after=None):
        self.http_status, self.retry_after = status, retry_after
        super().__init__(f"Veryfi HTTP {status}: request not confirmed; no automatic retry" + (f"; retry after {retry_after} seconds" if retry_after is not None else "") + (". Upload may already have completed and been billed; retain the original idempotency key" if status == 504 else ""))


def auth_header(credential):
    return "Bearer " + credential.api_key if credential.credential_type == TYPES[0] else "apikey " + credential.username + ":" + credential.api_key


def signature(secret, payload, timestamp):
    # The public Python SDK and authentication sample use insertion-order Python
    # value serialization, including True/False. No secret or signing string is logged.
    message = f"timestamp:{timestamp}" + "".join(f",{key}:{value}" for key, value in payload.items())
    return base64.b64encode(hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()).decode()


def reject_secret_input(value, credential):
    text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if any(secret and secret in text for secret in (credential.api_key, credential.client_secret, auth_header(credential))):
        raise ValueError("Do not place credential bytes in document content, metadata or filters")


async def fetch(credential, operation, method, path, *, params=None, body=None, idempotency_key=None, absence=False):
    credential = credential_value(credential)
    VERYFI_SCOPES.enforce_credential_type(operation, credential.credential_type)
    single = bool(re.fullmatch(re.escape(DOCUMENTS) + r"/[1-9][0-9]{0,18}", path))
    tags = bool(re.fullmatch(re.escape(DOCUMENTS) + r"/[1-9][0-9]{0,18}/tags", path))
    unlink = bool(re.fullmatch(re.escape(DOCUMENTS) + r"/[1-9][0-9]{0,18}/tags/[1-9][0-9]{0,18}", path))
    allowed_read = method == "GET" and body is None and (path == DOCUMENTS and operation == "list_documents" or single and operation in {"get_document", "get_document_status", "update_document_metadata", "delete_document", "list_document_tags", "add_document_tag", "unlink_document_tag"} or tags and operation in {"list_document_tags", "add_document_tag", "unlink_document_tag"})
    allowed_write = method == "POST" and path == DOCUMENTS and operation in {"process_document", "process_document_async"} and isinstance(body, dict) and set(body) <= {"file_name", "file_data", "async", "max_pages_to_process", "external_id", "allowed_async_enrichments"} or single and operation == "update_document_metadata" and method == "PUT" and isinstance(body, dict) and bool(body) and set(body) <= {"external_id", "notes"} or single and operation == "delete_document" and method == "DELETE" and body is None or tags and operation == "add_document_tag" and method == "PUT" and isinstance(body, dict) and set(body) == {"name"} or unlink and operation == "unlink_document_tag" and method == "DELETE" and body is None
    query_fields = {"page", "page_size", "q", "external_id", "tag", "status", "created__gt", "created__lt", "track_total_results", "order_by"}
    if not (allowed_read or allowed_write) or params and (path != DOCUMENTS or method != "GET" or set(params) - query_fields) or absence and not (operation == "delete_document" and method == "GET" and single) or allow_private_hosts():
        raise ValueError("Use native public Veryfi document routes without arbitrary requests or private overrides")
    if idempotency_key is not None and not (method == "POST" and operation in {"process_document", "process_document_async"}):
        raise ValueError("Idempotency keys apply only to native document uploads")
    reject_secret_input({"body": body, "params": params, "idempotency_key": idempotency_key}, credential)
    headers = {"Authorization": auth_header(credential), "CLIENT-ID": credential.client_id, "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "NoClick Veryfi native integration"}
    if credential.client_secret:
        timestamp = int(time.time() * 1000)
        headers.update({"X-Veryfi-Request-Timestamp": str(timestamp), "X-Veryfi-Request-Signature": signature(credential.client_secret, body or {}, timestamp)})
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    expected = 201 if method == "POST" else 200
    try:
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, ROOTS[credential.environment] + path, headers=headers, params=params, **({"json": body} if body is not None else {})) as response:
                if absence and response.status_code == 404:
                    return None
                if response.status_code != expected:
                    retry = response.headers.get("retry-after", "")
                    raise VeryfiAPIError(response.status_code, int(retry) if re.fullmatch(r"[0-9]{1,6}", retry) else None)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("Veryfi response exceeds 2 MiB; no partial result accepted")
                    content.extend(chunk)
                # Tag unlink documents an empty HTTP 200. Document delete has an
                # underspecified 200 body: only a subsequent protected 404 proves absence.
                if method == "DELETE" and not content:
                    return {}
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Veryfi returned a non-JSON success response")
                raw = finite_json(bytes(content))
                if not isinstance(raw, dict) or raw.get("error") is not None or raw.get("status") == "fail" or "errors" in raw:
                    raise ValueError("Veryfi returned a failure or invalid document envelope")
                return raw
    except SSRFError:
        raise ValueError("Veryfi destination is not publicly reachable") from None
    except httpx.RequestError:
        raise ValueError("Veryfi request could not be completed; no automatic retry. Upload may have been processed and billed; retain its idempotency key") from None


def safe_text(value, credential, *, notes=False):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2000 or re.search(r"[\x00-\x08\x0b-\x1f\x7f]" if notes else r"[\x00-\x1f\x7f]", value):
        raise ValueError("Veryfi returned invalid metadata text")
    for secret in (credential.api_key, credential.client_secret, auth_header(credential), getattr(credential, "username", None)):
        if secret:
            value = value.replace(secret, "[redacted]").replace(quote(secret, safe=""), "[redacted]")
    return re.sub(r"(?i)(?:api[_-]?key|client[_-]?secret|authorization|password|access_token)\s*[=:]\s*[^\s&]+", "[redacted]", value)


def document(raw, credential, expected_id=None, *, summary=False, metadata=False):
    if not isinstance(raw, dict):
        raise ValueError("Veryfi returned invalid document metadata")
    identity = provider_id(raw.get("id"))
    if expected_id is not None and identity != expected_id:
        raise ValueError("Veryfi returned a different document")
    data = {"id": identity}
    fields = ["status", "created_date", "updated_date"]
    if summary:
        fields += ["date", "currency_code", "document_type"]
    if metadata:
        fields += ["external_id", "notes"]
    for field in fields:
        if field in raw:
            data[field] = safe_text(raw[field], credential, notes=field == "notes")
    if summary:
        for field in ("subtotal", "tax", "total", "discount"):
            if field in raw:
                value = raw[field]
                if value is not None and (type(value) not in {int, float} or abs(value) > 1e15 or not math.isfinite(value)):
                    raise ValueError("Veryfi returned an invalid extracted amount")
                data[field] = value
    return data


def tags_value(raw, credential):
    tags = raw.get("tags") if isinstance(raw, dict) else None
    if not isinstance(tags, list) or len(tags) > 100:
        raise ValueError("Veryfi returned invalid or oversized document tags; no partial list accepted")
    result = []
    for tag in tags:
        if not isinstance(tag, dict):
            raise ValueError("Veryfi returned invalid tag metadata")
        result.append({"id": provider_id(tag.get("id")), "name": safe_text(tag.get("name"), credential)})
        if not result[-1]["name"]:
            raise ValueError("Veryfi omitted a tag name")
    if len({tag["id"] for tag in result}) != len(result):
        raise ValueError("Veryfi returned duplicate tag IDs")
    return result


def page_binding(credential, config):
    return hashlib.sha256(json.dumps([credential.model_dump(), config.model_dump(exclude={"page_token"})], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:32] + ":"


async def list_documents(credential, config):
    prefix = page_binding(credential, config)
    page = 1
    if config.page_token is not None:
        if not config.page_token.startswith(prefix) or not re.fullmatch(r"[1-9][0-9]{0,6}", config.page_token[len(prefix):]):
            raise ValueError("Continuation changed credential, client, environment, page size or filters")
        page = int(config.page_token[len(prefix):])
        if not 2 <= page <= 1000000:
            raise ValueError("Veryfi paging exceeds the native page bound")
    params = {"page": page, "page_size": config.page_size, "track_total_results": "true", "order_by": "-created"}
    for field in ("q", "external_id", "tag", "status"):
        if getattr(config, field) is not None:
            params[field] = getattr(config, field)
    for field, wire in (("created_after", "created__gt"), ("created_before", "created__lt")):
        if getattr(config, field) is not None:
            params[wire] = getattr(config, field)
    raw = await fetch(credential, config.operation, "GET", DOCUMENTS, params=params)
    rows = raw.get("documents")
    if not isinstance(rows, list) or len(rows) > config.page_size:
        raise ValueError("Veryfi returned an invalid or oversized document page")
    meta = raw.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("Veryfi omitted document pagination metadata")
    for field in ("documents_per_page", "page_number", "total_pages", "total_results"):
        if type(meta.get(field)) is not int or not 0 <= meta[field] <= MAX_ID:
            raise ValueError("Veryfi omitted accurate document pagination")
    if meta["page_number"] != page or meta["documents_per_page"] != config.page_size or meta["total_pages"] > 1000000 or meta["total_results"] < len(rows) or meta["total_pages"] == 0 and rows or meta["total_pages"] > 0 and page > meta["total_pages"]:
        raise ValueError("Veryfi returned inconsistent pagination")
    data = [document(row, credential) for row in rows]
    if len({row["id"] for row in data}) != len(data) or not rows and page < meta["total_pages"]:
        raise ValueError("Veryfi returned duplicate IDs or an empty continuing page")
    return {"items": data, "page_number": page, "total_pages": meta["total_pages"], "total_results": meta["total_results"], "page_size": config.page_size, "next_page_token": prefix + str(page + 1) if page < meta["total_pages"] else None}


async def request_operation(credential_data, config):
    credential = credential_value(credential_data)
    operation = config.operation
    if isinstance(config, ListDocuments):
        return {"data": await list_documents(credential, config)}
    if isinstance(config, (ProcessDocument, ProcessDocumentAsync)):
        async_mode = isinstance(config, ProcessDocumentAsync)
        body = {"file_name": config.file_name, "file_data": config.file_data, "async": async_mode, "max_pages_to_process": config.max_pages_to_process, "allowed_async_enrichments": []}
        if config.external_id is not None:
            body["external_id"] = config.external_id
        raw = await fetch(credential, operation, "POST", DOCUMENTS, body=body, idempotency_key=config.idempotency_key)
        data = document(raw, credential, summary=not async_mode)
        return {"data": data, "http_status": 201, "submission_accepted": True, "processing_mode": "asynchronous" if async_mode else "synchronous", "processing_completion_verified": False, "webhook_delivery_verified": False}
    path = DOCUMENTS + "/" + config.document_id
    raw = await fetch(credential, operation, "GET", path)
    before = document(raw, credential, config.document_id, metadata=isinstance(config, UpdateMetadata))
    if isinstance(config, (GetDocument, GetStatus)):
        return {"data": document(raw, credential, config.document_id, summary=isinstance(config, GetDocument)), "processing_completion_verified": False}
    if isinstance(config, UpdateMetadata):
        body = config.model_dump(include={"notes", "external_id"}, exclude_unset=True)
        raw = await fetch(credential, operation, "PUT", path, body=body)
        document(raw, credential, config.document_id, metadata=True)
        if any(key not in raw or raw[key] != value for key, value in body.items()):
            raise ValueError("Veryfi did not confirm requested metadata; no retry")
        raw = await fetch(credential, operation, "GET", path)
        data = document(raw, credential, config.document_id, metadata=True)
        if any(key not in raw or raw[key] != value for key, value in body.items()):
            raise ValueError("Veryfi metadata readback is unconfirmed; no retry")
        return {"data": data, "readback_verified": True}
    if isinstance(config, DeleteDocument):
        await fetch(credential, operation, "DELETE", path)
        absent = await fetch(credential, operation, "GET", path, absence=True)
        if absent is not None:
            document(absent, credential, config.document_id)
            raise ValueError("Veryfi still returns this document; deletion is unconfirmed; no retry")
        return {"data": {"id": before["id"], "deleted": True, "absence_readback_verified": True}, "http_status": 200}
    tag_path = path + "/tags"
    tags = tags_value(await fetch(credential, operation, "GET", tag_path), credential)
    if isinstance(config, ListTags):
        return {"data": {"document_id": config.document_id, "tags": tags}}
    if isinstance(config, AddTag):
        raw = await fetch(credential, operation, "PUT", tag_path, body={"name": config.name})
        tag = {"id": provider_id(raw.get("id")), "name": safe_text(raw.get("name"), credential)}
        if raw.get("name") != config.name:
            raise ValueError("Veryfi did not confirm the requested tag name; no retry")
        after = tags_value(await fetch(credential, operation, "GET", tag_path), credential)
        if tag not in after:
            raise ValueError("Veryfi tag association readback is unconfirmed; no retry")
        return {"data": {"document_id": config.document_id, "tag": tag}, "readback_verified": True}
    if isinstance(config, UnlinkTag):
        if not any(tag["id"] == config.tag_id for tag in tags):
            raise ValueError("Selected tag is not linked to this document")
        await fetch(credential, operation, "DELETE", tag_path + "/" + config.tag_id)
        after = tags_value(await fetch(credential, operation, "GET", tag_path), credential)
        if any(tag["id"] == config.tag_id for tag in after):
            raise ValueError("Veryfi tag remains linked; no retry")
        return {"data": {"document_id": config.document_id, "tag_id": config.tag_id, "unlinked": True}, "readback_verified": True}
    raise ValueError("Use a native Veryfi document operation")


class VeryfiNode(WorkflowNode):
    integration_type = "automation-veryfi"
    credential_provider_labels = {"veryfi": "Veryfi Account"}
    scope_registry = VERYFI_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_documents", operation_arguments={"page_size": 5}, noun="Veryfi document IDs", proves="reachability", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return VeryfiNodeConfig

    @classmethod
    def _require_raw(cls, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("config"), dict):
            raise ValueError("Use native Veryfi configuration")
        credential_value(raw.get("credentials"))
        for key in ("document_id", "tag_id"):
            if key in raw["config"]:
                id_value(raw["config"][key])
        for key in ("confirm_processing", "confirm_update", "confirm_delete"):
            if key in raw["config"]:
                confirmation_value(raw["config"][key])
        controls = {"url", "base_url", "endpoint", "headers", "method", "body", "params", "api_key", "client_id", "client_secret", "environment", "username", "file_url", "file_urls", "file_path", "package_path", "bucket", "webhook", "account_id", "bank", "card", "customer"}
        if controls.intersection(raw) or controls.intersection(raw["config"]):
            raise ValueError("Use typed document fields without arbitrary requests, URLs or credential overrides")

    @classmethod
    def parse_config(cls, config_data):
        cls._require_raw(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._require_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Use native Veryfi fields and a typed credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # API keys do not expire or refresh here. Staging's credential loaders
        # resolve stored credentials and enforce access before invoking this hook.
        return credential_value(credential_data, manual=not credential_id).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        try:
            credential = credential_value(credential_data, manual=True)
            await list_documents(credential, ListDocuments(page_size=1))
        except ValueError as exc:
            return {"valid": False, "error": str(exc)}
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"document_id", "tag_id"}:
            return {"options": [], "next_page_token": None}
        credential = credential_value(credential_data, manual=True)
        if search is not None and (not isinstance(search, str) or len(search) > 200 or re.search(r"[\x00-\x1f\x7f]", search)):
            raise ValueError("Use bounded picker search text")
        if context is not None and not isinstance(context, dict):
            raise ValueError("Use native Veryfi picker context")
        context = context or {}
        if any(key in context for key in ("client_id", "environment", "credential_type", "credentials", "api_key", "client_secret", "username", "_client_id", "_environment", "_credential_type")):
            raise ValueError("Use the saved Veryfi client and environment")
        query = normalize_search(search)
        if field_name == "document_id":
            filters = {key: context[key] for key in ("external_id", "tag", "status", "created_after", "created_before") if context.get(key) is not None}
            config = ListDocuments(page_size=50, page_token=page_token, q=context.get("q"), **filters)
            # Search uses Veryfi's documented OCR/metadata query. The returned
            # labels stay private IDs, so do not discard results by ID text.
            if query:
                config = ListDocuments.model_validate({**config.model_dump(), "q": query})
            data = await list_documents(credential, config)
            options = [{"value": row["id"], "label": "Document " + row["id"], "metadata": {"id": row["id"]}} for row in data["items"]]
            return {"options": options, "next_page_token": data["next_page_token"]}
        if page_token is not None:
            raise ValueError("Veryfi document tags have no pagination")
        parent = id_value(context.get("document_id"))
        document(await fetch(credential, "list_document_tags", "GET", DOCUMENTS + "/" + parent), credential, parent)
        tags = tags_value(await fetch(credential, "list_document_tags", "GET", DOCUMENTS + "/" + parent + "/tags"), credential)
        options = [{"value": row["id"], "label": row["name"], "metadata": {"document_id": parent}} for row in tags]
        return {"options": filter_options_by_search(options, query), "next_page_token": None}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, VeryfiNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a typed Veryfi credential")
        credential = credential_value(self.config.credentials).model_dump()
        return {"status": "success", "action": self.config.config.operation, **await request_operation(credential, self.config.config)}

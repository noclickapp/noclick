"""Native Vervoe assessment metadata and internal folder management."""
from __future__ import annotations

import base64
import re
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client

API = "https://api.vervoe.com/api"
KEY_FAMILY = "vervoe_api_key"
TOKEN_FAMILY = "vervoe_bearer_token"
FAMILIES = {KEY_FAMILY, TOKEN_FAMILY}
GRANT_FIELDS = ("api_key", "secret_key", "access_token")
MAX_BYTES = 2_000_000
MAX_PAGE = 1000  # Local safety bound; Vervoe does not document a page size.


class VervoeError(ValueError):
    def __init__(self, message, status_code=None, retry_after=None):
        super().__init__(message)
        self.status_code, self.retry_after = status_code, retry_after


def text(value, maximum=255):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter a nonempty value without edge whitespace or control characters")
    return value


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value):
        raise ValueError("Enter the exact assessment slug without a URL or path")
    return value


def uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower():
            raise ValueError()
        return value.lower()
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Enter the exact Vervoe UUID without a URL") from None


def guard(data, stored=False):
    if not isinstance(data, dict):
        raise ValueError("Select a native Vervoe credential")
    family = data.get("credential_type")
    if stored or "credential_type" in data:
        if not isinstance(family, str) or family not in FAMILIES:
            raise ValueError("Select a native Vervoe API pair or issued Bearer token")
    else:
        family = TOKEN_FAMILY if "access_token" in data and not ({"api_key", "secret_key"} & data.keys()) else KEY_FAMILY
    if (family == KEY_FAMILY and "access_token" in data) or (family == TOKEN_FAMILY and {"api_key", "secret_key"} & data.keys()):
        raise ValueError("Use one native Vervoe authentication method")
    return family


class VervoeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Vervoe API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://vervoe.stoplight.io/docs/api-docs/ZG9jOjQ4ODIx-introduction", "x-credential-instructions": "Use an existing Enterprise or Partner API key and secret key. The node obtains a short-lived token for each invocation, without storing it or changing the account."})
    credential_type: Literal["vervoe_api_key"] = Field(KEY_FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., title="Secret Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "secret_key", mode="before")
    @classmethod
    def keys(cls, value):
        value = text(value, 4096)
        if not value.isascii() or ":" in value or "://" in value:
            raise ValueError("Enter the issued ASCII key without a URL or Basic header")
        return value


class VervoeBearerTokenCredential(BaseModel):
    model_config = ConfigDict(title="Vervoe Bearer Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://vervoe.stoplight.io/docs/api-docs/ZG9jOjQ4ODIx-introduction", "x-credential-instructions": "Paste an already issued Vervoe token without the Bearer prefix. Tokens expire after 10 minutes. This method does not mint or renew a token; use the API pair for ongoing workflows."})
    credential_type: Literal["vervoe_bearer_token"] = Field(TOKEN_FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Issued Bearer Token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = text(value, 16384)
        if not value.isascii() or any(c.isspace() for c in value) or "://" in value:
            raise ValueError("Paste the issued token without a Bearer prefix or URL")
        return value


def credential(data):
    family = guard(data)
    try:
        return (VervoeAPIKeyCredential if family == KEY_FAMILY else VervoeBearerTokenCredential).model_validate(data).model_dump(mode="json")
    except Exception:
        raise ValueError("Check the native Vervoe API pair or issued token") from None


def picker(field, parent=None):
    options = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return {"x-dynamic-options": options}


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("assessment_slug", mode="before", check_fields=False)
    @classmethod
    def assessment(cls, value):
        return slug(value)

    @field_validator("folder_uuid", "candidate_assessment_uuid", mode="before", check_fields=False)
    @classmethod
    def ids(cls, value):
        return uuid(value)

    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def validate_name(cls, value):
        return text(value)


class ListAssessments(Config):
    operation: Literal["list_assessments"] = Field("list_assessments")


class ListAssessmentFolders(Config):
    operation: Literal["list_assessment_folders"] = Field("list_assessment_folders")


class ListApplications(Config):
    operation: Literal["list_applications"] = Field("list_applications")
    page: int = Field(1, ge=1, le=100000, strict=True)
    sort: Literal["updated", "created", "completed"] = "updated"
    order: Literal["asc", "desc"] = "asc"
    status: Literal["complete", "expired", "in_progress", "hired", "rejected", "screeningInProgress", "screeningFailed", "screeningPassed"] | None = None

    @model_validator(mode="after")
    def completed_sort(self):
        if self.sort == "completed" and self.status != "complete":
            raise ValueError("Completed sorting requires the complete status filter")
        return self


class Application(Config):
    operation: Literal["get_application"] = Field("get_application")
    assessment_slug: str = Field(..., json_schema_extra=picker("assessment_slug"))
    candidate_assessment_uuid: str = Field(..., json_schema_extra=picker("candidate_assessment_uuid", "assessment_slug"))


class ListAssessmentCandidates(Config):
    operation: Literal["list_assessment_candidates"] = Field("list_assessment_candidates")
    assessment_slug: str = Field(..., json_schema_extra=picker("assessment_slug"))
    page: int = Field(1, ge=1, le=100000, strict=True)


class ListBrands(Config):
    operation: Literal["list_brands"] = Field("list_brands")


class Write(Config):
    confirm_folder_change: Literal[True] = Field(..., title="Confirm Folder Change", description="Changes internal assessment organization. No invitation, hiring or scoring action is performed.")


class CreateFolder(Write):
    operation: Literal["create_folder"] = Field("create_folder")
    name: str


class RenameFolder(CreateFolder):
    operation: Literal["rename_folder"] = Field("rename_folder")
    folder_uuid: str = Field(..., json_schema_extra=picker("folder_uuid"))


class MoveAssessment(Write):
    operation: Literal["move_assessment_to_folder"] = Field("move_assessment_to_folder")
    assessment_slug: str = Field(..., json_schema_extra=picker("assessment_slug"))
    folder_uuid: str = Field(..., json_schema_extra=picker("folder_uuid"))


class DeleteFolder(Write):
    operation: Literal["delete_folder"] = Field("delete_folder")
    folder_uuid: str = Field(..., json_schema_extra=picker("folder_uuid"))


class RemoveAssessment(Write):
    operation: Literal["remove_assessment_from_folder"] = Field("remove_assessment_from_folder")
    assessment_slug: str = Field(..., json_schema_extra=picker("assessment_slug"))


VervoeConfig = Annotated[Union[ListAssessments, ListAssessmentFolders, ListApplications, Application, ListAssessmentCandidates, ListBrands, CreateFolder, RenameFolder, MoveAssessment, DeleteFolder, RemoveAssessment], Field(discriminator="operation")]


class VervoeNodeConfig(NodeConfig[VervoeConfig, Union[VervoeAPIKeyCredential, VervoeBearerTokenCredential]]):
    pass


class CurrentCredential(dict):
    def __init__(self, data):
        super().__init__(data)
        self.bearer = data.get("access_token")


async def freshen(data, **kwargs):
    # Staging resolves saved credentials through its shared access policy before
    # execute/lookup. These native keys need no persisted OAuth refresh.
    return CurrentCredential(credential(data))


async def http(data, method, route, authorization, *, query=None, body=None, expected=200, empty=False):
    try:
        async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=30) as client:
            response = await client.request(method, API + "/" + route, headers={"Authorization": authorization, "Accept": "application/json"}, params=query, json=body)
    except (SSRFError, httpx.RequestError):
        raise VervoeError("Vervoe could not be reached; the request is unverified") from None
    if response.status_code != expected:
        words = {400: "request was invalid", 401: "authentication was refused or token expired", 403: "permission was denied", 404: "resource was not found", 429: "request rate limit reached"}
        delay = response.headers.get("Retry-After")
        retry = int(delay) if delay and delay.isascii() and delay.isdecimal() and len(delay) <= 8 else None
        raise VervoeError(f"Vervoe HTTP {response.status_code}: {words.get(response.status_code, 'response was not accepted')}", response.status_code, retry)
    if empty:
        if response.content:
            raise VervoeError("Vervoe returned content for a documented empty response")
        return None
    if len(response.content) > MAX_BYTES:
        raise VervoeError("Vervoe response exceeds the supported size")
    try:
        payload = response.json()
    except ValueError:
        raise VervoeError("Vervoe returned unreadable JSON") from None
    if not isinstance(payload, dict) or payload.get("success", True) is not True or any(k in payload for k in ("error", "errors")):
        raise VervoeError("Vervoe returned an unsuccessful or unreadable response")
    return payload


async def request(data, method, route, **kwargs):
    if data.bearer is None:
        encoded = base64.b64encode((data["api_key"] + ":" + data["secret_key"]).encode("ascii")).decode("ascii")
        payload = await http(data, "GET", "public/ats-api/token", "Basic " + encoded)
        if payload.get("success") is not True or not isinstance(payload.get("data"), dict):
            raise VervoeError("Vervoe token response was unreadable")
        try:
            data.bearer = VervoeBearerTokenCredential.token(payload["data"].get("token"))
        except (ValueError, TypeError):
            raise VervoeError("Vervoe token response was unreadable") from None
    # The ephemeral token never enters a returned credential, row or output.
    return await http(data, method, route, "Bearer " + data.bearer, **kwargs)


def safe_text(value, data):
    secrets = [data.get(k) for k in GRANT_FIELDS] + [data.bearer]
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value) or any(s and s in value for s in secrets):
        raise VervoeError("Vervoe returned unreadable or protected metadata")
    return value


def folder(raw, data):
    if not isinstance(raw, dict):
        raise VervoeError("Vervoe returned unreadable folder metadata")
    return {"uuid": uuid(raw.get("uuid")), "name": safe_text(raw.get("name"), data)}


def assessment(raw, data):
    if not isinstance(raw, dict):
        raise VervoeError("Vervoe returned unreadable assessment metadata")
    out = {"slug": slug(raw.get("slug")), "name": safe_text(raw.get("name"), data)}
    if raw.get("skills") is not None:
        if not isinstance(raw["skills"], list) or len(raw["skills"]) > 200:
            raise VervoeError("Vervoe returned unreadable assessment skills")
        out["skills"] = [safe_text(x, data) for x in raw["skills"]]
    value = raw.get("auditionFolder")
    if value not in (None, "null"):
        out["auditionFolder"] = folder(value, data)
    else:
        out["auditionFolder"] = None
    return out


def application(raw, data):
    if not isinstance(raw, dict):
        raise VervoeError("Vervoe returned unreadable application metadata")
    out = {"candidateAssessmentUuid": uuid(raw.get("candidateAssessmentUuid")), "status": safe_text(raw.get("status"), data)}
    if raw.get("assessmentSlug") is not None:
        out["assessmentSlug"] = slug(raw["assessmentSlug"])
    for key in ("startedAt", "completedAt"):
        if raw.get(key) is not None:
            out[key] = safe_text(raw[key], data)
    return out


def candidate(raw, data):
    if not isinstance(raw, dict):
        raise VervoeError("Vervoe returned unreadable candidate metadata")
    out = {"fullName": safe_text(raw.get("fullName"), data), "status": safe_text(raw.get("status"), data)}
    for key in ("statusChangedAt", "startedAt"):
        if raw.get(key) is not None:
            out[key] = safe_text(raw[key], data)
    # This endpoint documents no candidate UUID. Do not invent one or expose
    # email/phone/answers/rank/scores/proctoring/media to manufacture identity.
    return out


def data_envelope(payload):
    if payload.get("success") is not True or "data" not in payload:
        raise VervoeError("Vervoe returned an unreadable success envelope")
    return payload["data"]


def page(payload, project, data, requested=None):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or len(payload["items"]) > MAX_PAGE:
        raise VervoeError("Vervoe returned an unreadable or oversized page")
    for key in ("count", "total", "currentPage"):
        value = payload.get(key)
        if type(value) not in (int, float) or not 0 <= value < 10**9 or int(value) != value:
            raise VervoeError("Vervoe returned unreadable page metadata")
    if payload["currentPage"] < 1 or (requested is not None and payload["currentPage"] != requested) or payload["count"] != len(payload["items"]) or payload["total"] < payload["count"] or type(payload.get("hasMorePages")) is not bool:
        raise VervoeError("Vervoe returned inconsistent page metadata")
    rows = [project(x, data) for x in payload["items"]]
    ids = [x.get("slug") or x.get("candidateAssessmentUuid") for x in rows]
    if ids and all(ids) and len(set(ids)) != len(ids):
        raise VervoeError("Vervoe returned duplicate resource identifiers")
    return {"items": rows, "count": int(payload["count"]), "total": int(payload["total"]), "current_page": int(payload["currentPage"]), "has_more": payload["hasMorePages"], "next_page_token": None}


async def assessments(data):
    # The spec exposes paginated metadata, but documents no page parameter for
    # this endpoint. Read the default page; never invent a continuation query.
    return page(await request(data, "GET", "integration/assessments"), assessment, data)


async def applications(data, requested=1, query=None):
    return page(data_envelope(await request(data, "GET", "integration/user-assessments", query={"page": requested, **(query or {})})), application, data, requested)


class VervoeNode(WorkflowNode):
    integration_type = "automation-vervoe"
    credential_provider_labels = {"vervoe": "Vervoe Connection"}
    connection_evidence = ConnectionEvidence(operation="list_assessments", noun="assessments", label_keys=("name",), proves="account")
    edit_examples = ["List my Vervoe assessments", "Check an application completion status", "Create an assessment folder", "Move an assessment into a folder"]

    @classmethod
    def get_config_model(cls):
        return VervoeNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            raise ConfigValidationError("Select a native Vervoe credential") from None
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data, dict) and config_data.get("credentials") is not None:
                guard(config_data["credentials"])
        except ValueError:
            return {"valid": False, "errors": ["Select a native Vervoe credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    def _extract_actionable_validation_error(cls, error, config_data):
        return "Check the native Vervoe credentials and operation fields"

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen(credential_data)

    @classmethod
    async def validate_credential(cls, data, *, validation_context=None):
        if validation_context is not None:
            result = await validation_context.run_operation("list_assessments", {})
            await validation_context.accept(result)
            return {"valid": True}
        try:
            await assessments(await freshen(data))
            return {"valid": True}
        except VervoeError as exc:
            return {"valid": False if exc.status_code in {401, 403} else None, "error": str(exc)}
        except (ValueError, TypeError, KeyError):
            return {"valid": False, "error": "Check the native Vervoe credentials"}

    @classmethod
    async def validate_credential_access(cls, data, *, validation_context=None):
        return await cls.validate_credential(data, validation_context=validation_context)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if page_token:
            raise ValueError("Vervoe pickers show one bounded page; use numbered application lists or exact identifiers")
        data = credential_data if isinstance(credential_data, CurrentCredential) else await freshen(credential_data)
        if field_name in {"assessment_slug", "folder_uuid"}:
            rows = (await assessments(data))["items"]
            if field_name == "assessment_slug":
                options = [{"value": r["slug"], "label": r["name"]} for r in rows]
            else:
                seen = {}
                for row in rows:
                    if row["auditionFolder"]:
                        f = row["auditionFolder"]
                        if f["uuid"] in seen and seen[f["uuid"]] != f["name"]:
                            raise VervoeError("Vervoe returned inconsistent folder labels")
                        seen[f["uuid"]] = f["name"]
                options = [{"value": k, "label": v} for k, v in seen.items()]
        elif field_name == "candidate_assessment_uuid":
            parent = slug((context or {}).get("assessment_slug"))
            rows = (await applications(data))["items"]
            options = [{"value": r["candidateAssessmentUuid"], "label": r["candidateAssessmentUuid"] + " · " + r["status"]} for r in rows if r.get("assessmentSlug") == parent]
        else:
            raise ValueError("Unknown native Vervoe picker")
        if search:
            needle = text(search).casefold()
            options = [x for x in options if needle in x["label"].casefold()]
        return {"options": options, "next_page_token": None}

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a native Vervoe credential")
        config = self.config.config
        try:
            data = await freshen(self.config.credentials.model_dump(mode="json"))
            return {"status": "success", "action": config.operation, "data": await self._operation(data, config)}
        except VervoeError as exc:
            return {"status": "error", "action": config.operation, "error": str(exc), "status_code": exc.status_code, "retry_after": exc.retry_after}
        except (ValueError, TypeError, KeyError):
            return {"status": "error", "action": config.operation, "error": "Vervoe credential or response could not be validated"}

    async def _operation(self, data, config):
        op = config.operation
        if op in {"list_assessments", "list_assessment_folders"}:
            result = await assessments(data)
            if op == "list_assessment_folders":
                folders = {}
                for row in result["items"]:
                    if row["auditionFolder"]:
                        f = row["auditionFolder"]
                        if f["uuid"] in folders and folders[f["uuid"]] != f:
                            raise VervoeError("Vervoe returned inconsistent folder metadata")
                        folders[f["uuid"]] = f
                return {"items": list(folders.values()), "observed_assessment_page": result["current_page"], "complete_folder_inventory": False}
            return result
        if op == "list_applications":
            return await applications(data, config.page, {k: getattr(config, k) for k in ("sort", "order", "status") if getattr(config, k) is not None})
        if op == "get_application":
            result = application(data_envelope(await request(data, "GET", "integration/user-assessments/" + config.candidate_assessment_uuid)), data)
            if result["candidateAssessmentUuid"] != config.candidate_assessment_uuid or result.get("assessmentSlug") != config.assessment_slug:
                raise VervoeError("Vervoe returned a different application or assessment binding")
            return result
        if op == "list_assessment_candidates":
            result = page(data_envelope(await request(data, "GET", "integration/assessments/" + config.assessment_slug + "/candidates", query={"page": config.page})), candidate, data, config.page)
            return {**result, "requested_assessment_slug": config.assessment_slug}
        if op == "list_brands":
            rows = data_envelope(await request(data, "GET", "integration/brands"))
            if not isinstance(rows, list) or len(rows) > MAX_PAGE:
                raise VervoeError("Vervoe returned an unreadable brand list")
            result = [{"uuid": uuid(r.get("uuid")), "title": safe_text(r.get("title"), data), "color": safe_text(r.get("color"), data)} for r in rows if isinstance(r, dict)]
            if len(result) != len(rows) or len({r["uuid"] for r in result}) != len(result):
                raise VervoeError("Vervoe returned malformed or duplicate brands")
            return {"items": result}
        if op == "delete_folder":
            await request(data, "DELETE", "integration/assessments/folders/" + config.folder_uuid, expected=204, empty=True)
            return {"uuid": config.folder_uuid, "deletion_request_completed": True, "previously_existed": None, "verified_readback": None}
        if op in {"create_folder", "rename_folder"}:
            route = "integration/assessments/folders" + ("/" + config.folder_uuid if op == "rename_folder" else "")
            result = folder(data_envelope(await request(data, "POST" if op == "create_folder" else "PATCH", route, body={"name": config.name}, expected=201 if op == "create_folder" else 200)), data)
            if op == "rename_folder" and result["uuid"] != config.folder_uuid:
                raise VervoeError("Vervoe returned a different renamed folder")
        else:
            route = "integration/assessments/" + config.assessment_slug + "/folders"
            if op == "move_assessment_to_folder":
                route += "/" + config.folder_uuid + "/move"
            result = assessment(data_envelope(await request(data, "PATCH" if op == "move_assessment_to_folder" else "DELETE", route)), data)
            if result["slug"] != config.assessment_slug or (op == "move_assessment_to_folder" and (result["auditionFolder"] or {}).get("uuid") != config.folder_uuid) or (op == "remove_assessment_from_folder" and result["auditionFolder"] is not None):
                raise VervoeError("Vervoe returned a different assessment or folder binding")
        return {"resource": result, "write_acknowledged": True, "verified_readback": None}

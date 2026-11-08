"""Aha! API v1: fixed account, roadmap and idea operations using a personal API key.

Contract: https://www.aha.io/openapi.json, version 1.0.0.
Lists return one page; writes are sent once and never retried automatically.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client


class AhaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Aha! API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://secure.aha.io/settings/api_keys",
            "x-credential-instructions": "Create a personal API key in Aha! under Settings → Personal → Developer → API keys. Paste the key and your account subdomain. The key uses your Aha! permissions; connect reads your workspaces and current user."})
    credential_type: Literal["aha_api_key"] = Field("aha_api_key", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., title="Account subdomain", min_length=1, max_length=63,
        description="The company part of https://company.aha.io.", pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain", mode="before")
    @classmethod
    def tenant(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter your Aha! account subdomain")
        return value.strip().lower()

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value)):
            raise ValueError("Use a numeric Aha! ID or reference key such as PRJ1-1")
        if info.field_name == "name" and isinstance(value, str) and not value.strip():
            raise ValueError("Enter a nonempty name")
        return value


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, strict=True, description="Page number to read. Use next_page from the previous result.")
    per_page: int = Field(30, ge=1, le=200, strict=True, title="Results per page")


class _Named(_Input):
    name: str = Field(..., min_length=1, max_length=1000)
    description: str | None = Field(None, max_length=100000, description="Text or HTML description.")


class AhaGetMeConfig(_Input):
    operation: Literal["get_me"] = Field("get_me", title="Get Me", json_schema_extra={"ui:hidden": True})


class AhaListProductsConfig(_Page):
    operation: Literal["list_products"] = Field("list_products", title="List Products", json_schema_extra={"ui:hidden": True})


class AhaGetProductConfig(_Input):
    operation: Literal["get_product"] = Field("get_product", title="Get Product", json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaListReleasesConfig(_Page):
    operation: Literal["list_releases"] = Field("list_releases", title="List Releases", json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaGetReleaseConfig(_Input):
    operation: Literal["get_release"] = Field("get_release", title="Get Release", json_schema_extra={"ui:hidden": True})
    release_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaListFeaturesConfig(_Page):
    operation: Literal["list_features"] = Field("list_features", title="List Features", json_schema_extra={"ui:hidden": True})


class AhaGetFeatureConfig(_Input):
    operation: Literal["get_feature"] = Field("get_feature", title="Get Feature", json_schema_extra={"ui:hidden": True})
    feature_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaListEpicsConfig(_Page):
    operation: Literal["list_epics"] = Field("list_epics", title="List Epics", json_schema_extra={"ui:hidden": True})


class AhaGetEpicConfig(_Input):
    operation: Literal["get_epic"] = Field("get_epic", title="Get Epic", json_schema_extra={"ui:hidden": True})
    epic_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaListIdeasConfig(_Page):
    operation: Literal["list_ideas"] = Field("list_ideas", title="List Ideas", json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, min_length=1, max_length=1000, description="Search ideas.")


class AhaGetIdeaConfig(_Input):
    operation: Literal["get_idea"] = Field("get_idea", title="Get Idea", json_schema_extra={"ui:hidden": True})
    idea_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaListRequirementsConfig(_Page):
    operation: Literal["list_requirements"] = Field("list_requirements", title="List Requirements", json_schema_extra={"ui:hidden": True})
    feature_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaGetRequirementConfig(_Input):
    operation: Literal["get_requirement"] = Field("get_requirement", title="Get Requirement", json_schema_extra={"ui:hidden": True})
    requirement_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaListNotesConfig(_Page):
    operation: Literal["list_notes"] = Field("list_notes", title="List Notes", json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaGetNoteConfig(_Input):
    operation: Literal["get_note"] = Field("get_note", title="Get Note", json_schema_extra={"ui:hidden": True})
    note_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaCreateFeatureConfig(_Named):
    operation: Literal["create_feature"] = Field("create_feature", title="Create Feature", json_schema_extra={"ui:hidden": True})
    release_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")
    workflow_status: str | None = Field(None, min_length=1, max_length=200, description="Status name configured in this workspace.")
    assigned_to_email: str | None = Field(None, min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title="Assignee email")
    workflow_kind: str | None = Field(None, min_length=1, max_length=100, description="Feature type configured in Aha!, for example new.")


class AhaCreateEpicConfig(_Named):
    operation: Literal["create_epic"] = Field("create_epic", title="Create Epic", json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaCreateIdeaConfig(_Named):
    operation: Literal["create_idea"] = Field("create_idea", title="Create Idea", json_schema_extra={"ui:hidden": True})
    created_by_email: str = Field(..., min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title="Created by email", description="Email of the idea creator, required by the Aha! create-idea documentation.")
    product_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaCreateRequirementConfig(_Named):
    operation: Literal["create_requirement"] = Field("create_requirement", title="Create Requirement", json_schema_extra={"ui:hidden": True})
    feature_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")
    workflow_status: str | None = Field(None, min_length=1, max_length=200, description="Status name configured in this workspace.")
    assigned_to_email: str | None = Field(None, min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", title="Assignee email")


class AhaCreateNoteConfig(_Named):
    operation: Literal["create_note"] = Field("create_note", title="Create Note", json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaUpdateEpicConfig(_Named):
    operation: Literal["update_epic"] = Field("update_epic", title="Update Epic", json_schema_extra={"ui:hidden": True})
    epic_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaUpdateNoteConfig(_Named):
    operation: Literal["update_note"] = Field("update_note", title="Update Note", json_schema_extra={"ui:hidden": True})
    note_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaDeleteFeatureConfig(_Input):
    operation: Literal["delete_feature"] = Field("delete_feature", title="Delete Feature", json_schema_extra={"ui:hidden": True})
    feature_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaDeleteIdeaConfig(_Input):
    operation: Literal["delete_idea"] = Field("delete_idea", title="Delete Idea", json_schema_extra={"ui:hidden": True})
    idea_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


class AhaDeleteRequirementConfig(_Input):
    operation: Literal["delete_requirement"] = Field("delete_requirement", title="Delete Requirement", json_schema_extra={"ui:hidden": True})
    requirement_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$", description="Aha! numeric ID or reference key.")


AhaOperation = Annotated[Union[
    AhaGetMeConfig,
    AhaListProductsConfig,
    AhaGetProductConfig,
    AhaListReleasesConfig,
    AhaGetReleaseConfig,
    AhaListFeaturesConfig,
    AhaGetFeatureConfig,
    AhaListEpicsConfig,
    AhaGetEpicConfig,
    AhaListIdeasConfig,
    AhaGetIdeaConfig,
    AhaListRequirementsConfig,
    AhaGetRequirementConfig,
    AhaListNotesConfig,
    AhaGetNoteConfig,
    AhaCreateFeatureConfig,
    AhaCreateEpicConfig,
    AhaCreateIdeaConfig,
    AhaCreateRequirementConfig,
    AhaCreateNoteConfig,
    AhaUpdateEpicConfig,
    AhaUpdateNoteConfig,
    AhaDeleteFeatureConfig,
    AhaDeleteIdeaConfig,
    AhaDeleteRequirementConfig
], Field(discriminator="operation")]


class AhaNodeConfig(NodeConfig[AhaOperation, AhaAPIKeyCredential]):
    pass


OPERATIONS = {
    "get_me": ('GET', '/me', 'user', False),
    "list_products": ('GET', '/products', 'products', True),
    "get_product": ('GET', '/products/{product_id}', 'product', False),
    "list_releases": ('GET', '/products/{product_id}/releases', 'releases', True),
    "get_release": ('GET', '/releases/{release_id}', 'release', False),
    "list_features": ('GET', '/features', 'features', True),
    "get_feature": ('GET', '/features/{feature_id}', 'feature', False),
    "list_epics": ('GET', '/epics', 'epics', True),
    "get_epic": ('GET', '/epics/{epic_id}', 'epic', False),
    "list_ideas": ('GET', '/ideas', 'ideas', True),
    "get_idea": ('GET', '/ideas/{idea_id}', 'idea', False),
    "list_requirements": ('GET', '/features/{feature_id}/requirements', 'requirements', True),
    "get_requirement": ('GET', '/requirements/{requirement_id}', 'requirement', False),
    "list_notes": ('GET', '/products/{product_id}/pages', 'pages', True),
    "get_note": ('GET', '/pages/{note_id}', 'page', False),
    "create_feature": ('POST', '/releases/{release_id}/features', 'feature', False),
    "create_epic": ('POST', '/products/{product_id}/epics', 'epic', False),
    "create_idea": ('POST', '/products/{product_id}/ideas', 'idea', False),
    "create_requirement": ('POST', '/features/{feature_id}/requirements', 'requirement', False),
    "create_note": ('POST', '/products/{product_id}/pages', 'page', False),
    "update_epic": ('PUT', '/epics/{epic_id}', 'epic', False),
    "update_note": ('PUT', '/pages/{note_id}', 'page', False),
    "delete_feature": ('DELETE', '/features/{feature_id}', None, False),
    "delete_idea": ('DELETE', '/ideas/{idea_id}', None, False),
    "delete_requirement": ('DELETE', '/requirements/{requirement_id}', None, False),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class AhaNode(WorkflowNode):
    integration_type = "automation-aha"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_products", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return AhaNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw = config_data.get("credentials")
        if isinstance(raw, dict) and raw.get("credential_type", "aha_api_key") != "aha_api_key":
            raise ValueError("Attach an Aha! API key credential")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Aha! API key")
        credential = self.config.credentials
        op = self.config.config
        method, template, envelope, many = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        route = template.format(**values)
        params = {k: str(values[k]) for k in ("page", "per_page", "q") if k in values} if many else None
        body = None
        if method in {"POST", "PUT"}:
            fields = {"name": op.name}
            if op.description is not None:
                if envelope == "page":
                    fields["description_attributes"] = {"body": op.description}
                else:
                    fields["description"] = op.description
            for key in ("workflow_kind", "workflow_status", "assigned_to_email"):
                if key not in values:
                    continue
                if key == "workflow_status":
                    fields[key] = {"name": values[key]}
                elif key == "assigned_to_email":
                    fields["assigned_to_user"] = {"email": values[key]}
                else:
                    fields[key] = values[key]
            if op.operation == "create_idea":
                fields["created_by"] = op.created_by_email
            body = {envelope: fields}
        url = f"https://{credential.subdomain}.aha.io/api/v1{route}"
        try:
            async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False, timeout=30.0) as client:
                async with client.stream(method, url, headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                                         params=params, **({"json": body} if body is not None else {})) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 8 * 1024 * 1024:
                            raise ValueError("Aha! response exceeds 8 MiB; request a smaller page")
                    status = response.status_code
                    if status != (204 if method == "DELETE" else 200):
                        message = "Aha! returned HTTP " + str(status)
                        if "json" in response.headers.get("content-type", "").lower():
                            try:
                                payload = json.loads(raw)
                                detail = payload.get("error") or payload.get("errors") or payload.get("message") if isinstance(payload, dict) else None
                                if detail:
                                    message = detail if isinstance(detail, str) else json.dumps(detail)
                            except (ValueError, TypeError):
                                pass
                        result = {"status": "error", "success": False, "status_code": status, "error": message[:2000]}
                    elif method == "DELETE":
                        result = {"status": "success", "success": True, "deleted_id": next(v for k, v in values.items() if k.endswith("_id")), "deletion_acknowledged": True}
                    else:
                        if "json" not in response.headers.get("content-type", "").lower():
                            raise ValueError("Aha! returned a non-JSON response; check the account subdomain")
                        payload = json.loads(raw)
                        if not isinstance(payload, dict) or "error" in payload or "errors" in payload:
                            raise ValueError("Aha! returned an unexpected response envelope")
                        entity = payload.get(envelope)
                        if many:
                            if not isinstance(entity, list) or any(not isinstance(row, dict) for row in entity):
                                raise ValueError("Aha! returned an invalid list")
                            pagination = payload.get("pagination")
                            # The overview documents a singleton array; resource examples use an object.
                            if isinstance(pagination, list) and len(pagination) == 1:
                                pagination = pagination[0]
                            if not isinstance(pagination, dict):
                                raise ValueError("Aha! pagination is missing")
                            current, total = pagination.get("current_page"), pagination.get("total_pages")
                            if type(current) is not int or type(total) is not int or current < 1 or total < 0:
                                raise ValueError("Aha! returned invalid pagination")
                            result = {"status": "success", "success": True, "data": entity, envelope: entity,
                                      "pagination": pagination, "next_page": current + 1 if current < total else None,
                                      "has_more": current < total}
                        else:
                            if not isinstance(entity, dict) or not entity.get("id"):
                                raise ValueError("Aha! returned an invalid resource")
                            result = {"status": "success", "success": True, "data": entity, envelope: entity}
        except (httpx.HTTPError, SSRFError, OSError):
            result = {"status": "error", "success": False, "error": "Aha! request did not complete; inspect the record before retrying a write"}
        except (ValueError, TypeError):
            result = {"status": "error", "success": False, "error": "Aha! response could not be read; check the subdomain and inspect the record before retrying a write"}
        result = _redact(result, credential.api_key)
        await self.emit(result)
        return result

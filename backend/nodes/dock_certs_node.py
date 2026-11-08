"""Dock Certs (now Truvera) v1 API: one provider request per operation.

Contract: https://swagger-api.truvera.io/openapi.yaml . Jobs are returned as
accepted work; callers use get_job to observe completion. Lists return one
explicit offset/limit page and never follow provider-supplied URLs.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, Json, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class DockCertsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Dock Certs API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://truvera.io/",
            "x-credential-instructions": "In Truvera Workspace (formerly Dock Certs), create an API key and paste it here without Bearer. Choose the same environment in which you created the key. Sandbox uses test data; production uses live data.",
        })
    credential_type: Literal["dock_certs_api_key"] = Field("dock_certs_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_identifier(cls, value, info):
        if isinstance(value, str) and info.field_name in {"did", "credential_id", "template_id", "schema_id", "proof_request_id", "job_id"} and value is not None:
            if value in {".", ".."} or any(ord(c) < 33 or ord(c) == 127 for c in value):
                raise ValueError("Use a single provider resource identifier")
        return value


class _Page(_Input):
    offset: int = Field(0, ge=0, strict=True, description="Number of items to skip. This operation returns one page.")
    limit: int = Field(64, ge=1, le=64, strict=True, description="Items per page. Increase offset by limit to request the next page.")


class DockCertsListProfiles(_Page):
    """List profiles."""
    operation: Literal["list_profiles"] = Field("list_profiles", title="List Profiles", json_schema_extra={"ui:hidden": True})


class DockCertsGetProfile(_Input):
    """Get profile."""
    operation: Literal["get_profile"] = Field("get_profile", title="Get Profile", json_schema_extra={"ui:hidden": True})
    did: str = Field(..., min_length=1, max_length=512, title="Did")


class DockCertsListDids(_Page):
    """List dids."""
    operation: Literal["list_dids"] = Field("list_dids", title="List Dids", json_schema_extra={"ui:hidden": True})
    did_type: str | None = Field(None, max_length=512, description="Filter by DID type.")


class DockCertsGetDid(_Input):
    """Get did."""
    operation: Literal["get_did"] = Field("get_did", title="Get Did", json_schema_extra={"ui:hidden": True})
    did: str = Field(..., min_length=1, max_length=512, title="Did")


class DockCertsListTemplates(_Page):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", title="List Templates", json_schema_extra={"ui:hidden": True})


class DockCertsGetTemplate(_Input):
    """Get template."""
    operation: Literal["get_template"] = Field("get_template", title="Get Template", json_schema_extra={"ui:hidden": True})
    template_id: UUID = Field(..., title="Template ID")


class DockCertsDeleteTemplate(_Input):
    """Permanently delete this template."""
    operation: Literal["delete_template"] = Field("delete_template", title="Delete Template", json_schema_extra={"ui:hidden": True})
    template_id: UUID = Field(..., title="Template ID")


class DockCertsListCredentials(_Page):
    """List credentials."""
    operation: Literal["list_credentials"] = Field("list_credentials", title="List Credentials", json_schema_extra={"ui:hidden": True})
    limit: int = Field(64, ge=1, le=100, strict=True)
    filter: str | None = Field(None, max_length=512, description="Credential ID, subject reference, issuer, type or date filter.")
    subject_id: str | None = Field(None, max_length=512, description="Exact holder DID filter.")


class DockCertsGetCredential(_Input):
    """Get credential."""
    operation: Literal["get_credential"] = Field("get_credential", title="Get Credential", json_schema_extra={"ui:hidden": True})
    credential_id: str = Field(..., min_length=1, max_length=2048, title="Credential URI", json_schema_extra={"format": "uri"})


class DockCertsDeleteCredential(_Input):
    """Permanently delete this credential."""
    operation: Literal["delete_credential"] = Field("delete_credential", title="Delete Credential", json_schema_extra={"ui:hidden": True})
    credential_id: str = Field(..., min_length=1, max_length=2048, title="Credential URI", json_schema_extra={"format": "uri"})


class DockCertsListSchemas(_Page):
    """List schemas."""
    operation: Literal["list_schemas"] = Field("list_schemas", title="List Schemas", json_schema_extra={"ui:hidden": True})
    include_ecosystems: bool = Field(True, strict=True)


class DockCertsGetSchema(_Input):
    """Get schema."""
    operation: Literal["get_schema"] = Field("get_schema", title="Get Schema", json_schema_extra={"ui:hidden": True})
    schema_id: str = Field(..., min_length=1, max_length=2048, title="Schema Id")


class DockCertsDeleteSchema(_Input):
    """Permanently delete this schema."""
    operation: Literal["delete_schema"] = Field("delete_schema", title="Delete Schema", json_schema_extra={"ui:hidden": True})
    schema_id: str = Field(..., min_length=1, max_length=2048, title="Schema Id")


class DockCertsListProofRequests(_Page):
    """List proof requests."""
    operation: Literal["list_proof_requests"] = Field("list_proof_requests", title="List Proof Requests", json_schema_extra={"ui:hidden": True})


class DockCertsGetProofRequest(_Input):
    """Get proof request."""
    operation: Literal["get_proof_request"] = Field("get_proof_request", title="Get Proof Request", json_schema_extra={"ui:hidden": True})
    proof_request_id: UUID = Field(..., title="Proof Request ID")


class DockCertsDeleteProofRequest(_Input):
    """Permanently delete this proof request."""
    operation: Literal["delete_proof_request"] = Field("delete_proof_request", title="Delete Proof Request", json_schema_extra={"ui:hidden": True})
    proof_request_id: UUID = Field(..., title="Proof Request ID")


class DockCertsCreateDid(_Input):
    """Submit DID creation; the returned job is not proof of blockchain completion."""
    operation: Literal["create_did"] = Field("create_did", title="Create Did", json_schema_extra={"ui:hidden": True})
    did_type: Literal["cheqd", "dock", "key"] = Field("cheqd", title="DID Type")
    key_type: Literal["ed25519", "bjj", "secp256r1", "secp256k1", "sr25519"] = Field("ed25519")
    include_didcomm_service: bool = Field(True, strict=True)


class DockCertsCreateTemplate(_Input):
    """Create template."""
    operation: Literal["create_template"] = Field("create_template", title="Create Template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=256)
    html: str = Field(..., max_length=10000000, json_schema_extra={"ui:widget": "textarea"})
    css: str = Field(..., max_length=10000000, json_schema_extra={"ui:widget": "textarea"})


class DockCertsIssueCredential(_Input):
    """Issue a verifiable credential without persisting encrypted contents."""
    operation: Literal["issue_credential"] = Field("issue_credential", title="Issue Credential", json_schema_extra={"ui:hidden": True})
    credential: Union[dict[str, Any], Json[dict[str, Any]]] = Field(..., description="Truvera credential input: issuer DID, subject, optional context, schema, name, type and dates.")
    revocable: bool = Field(False, strict=True)
    distribute: bool = Field(False, strict=True, description="Ask Truvera to deliver to the subject; may send email or DID messages.")
    format: Literal["jsonld", "jwt", "sdjwt"] = Field("jsonld")


class DockCertsRevokeCredential(_Input):
    """Revoke credential."""
    operation: Literal["revoke_credential"] = Field("revoke_credential", title="Revoke Credential", json_schema_extra={"ui:hidden": True})
    credential_id: str = Field(..., min_length=1, max_length=2048, title="Credential URI", json_schema_extra={"format": "uri"})


class DockCertsUnrevokeCredential(_Input):
    """Unrevoke credential."""
    operation: Literal["unrevoke_credential"] = Field("unrevoke_credential", title="Unrevoke Credential", json_schema_extra={"ui:hidden": True})
    credential_id: str = Field(..., min_length=1, max_length=2048, title="Credential URI", json_schema_extra={"format": "uri"})


class DockCertsVerifyCredential(_Input):
    """Verify credential."""
    operation: Literal["verify_credential"] = Field("verify_credential", title="Verify Credential", json_schema_extra={"ui:hidden": True})
    presentation: Union[dict[str, Any], Json[dict[str, Any]]] = Field(..., description="Signed verifiable credential or presentation JSON, sent unchanged to /verify.")


class DockCertsCreateSchema(_Input):
    """Submit schema creation; use get_job to observe completion."""
    operation: Literal["create_schema"] = Field("create_schema", title="Create Schema", json_schema_extra={"ui:hidden": True})
    schema_document: Union[dict[str, Any], Json[dict[str, Any]]] = Field(..., description="JSON Schema document, including name, properties, required, and optional $metadata.")


class DockCertsCreateProofRequest(_Input):
    """Create proof request."""
    operation: Literal["create_proof_request"] = Field("create_proof_request", title="Create Proof Request", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=256)
    nonce: str | None = Field(None, max_length=256)
    did: str | None = Field(None, min_length=1, max_length=512)
    template: UUID | None = Field(None, description="Proof template UUID")
    request: Union[dict[str, Any], Json[dict[str, Any]]] | None = Field(None, description="PEX request with name, purpose and input_descriptors.")


class DockCertsGetJob(_Input):
    """Get job."""
    operation: Literal["get_job"] = Field("get_job", title="Get Job", json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, max_length=512, title="Job Id")


Operation = Annotated[Union[DockCertsListProfiles, DockCertsGetProfile, DockCertsListDids, DockCertsGetDid, DockCertsListTemplates, DockCertsGetTemplate, DockCertsDeleteTemplate, DockCertsListCredentials, DockCertsGetCredential, DockCertsDeleteCredential, DockCertsListSchemas, DockCertsGetSchema, DockCertsDeleteSchema, DockCertsListProofRequests, DockCertsGetProofRequest, DockCertsDeleteProofRequest, DockCertsCreateDid, DockCertsCreateTemplate, DockCertsIssueCredential, DockCertsRevokeCredential, DockCertsUnrevokeCredential, DockCertsVerifyCredential, DockCertsCreateSchema, DockCertsCreateProofRequest, DockCertsGetJob], Field(discriminator="operation")]


class DockCertsFullConfig(NodeConfig[Operation, DockCertsAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Fixed route templates are intentionally independent of user-provided URLs.
ROUTES = {
    "list_profiles": ('GET', '/profiles'),
    "get_profile": ('GET', '/profiles/{did}'),
    "list_dids": ('GET', '/dids'),
    "get_did": ('GET', '/dids/{did}'),
    "list_templates": ('GET', '/templates'),
    "get_template": ('GET', '/templates/{template_id}'),
    "delete_template": ('DELETE', '/templates/{template_id}'),
    "list_credentials": ('GET', '/credentials'),
    "get_credential": ('GET', '/credentials/{credential_id}'),
    "delete_credential": ('DELETE', '/credentials/{credential_id}'),
    "list_schemas": ('GET', '/schemas'),
    "get_schema": ('GET', '/schemas/{schema_id}'),
    "delete_schema": ('DELETE', '/schemas/{schema_id}'),
    "list_proof_requests": ('GET', '/proof-requests'),
    "get_proof_request": ('GET', '/proof-requests/{proof_request_id}'),
    "delete_proof_request": ('DELETE', '/proof-requests/{proof_request_id}'),
    "create_did": ('POST', '/dids'),
    "create_template": ('POST', '/templates'),
    "issue_credential": ('POST', '/credentials'),
    "revoke_credential": ('POST', '/credentials/{credential_id}/revoke'),
    "unrevoke_credential": ('POST', '/credentials/{credential_id}/unrevoke'),
    "verify_credential": ('POST', '/verify'),
    "create_schema": ('POST', '/schemas'),
    "create_proof_request": ('POST', '/proof-requests'),
    "get_job": ('GET', '/jobs/{job_id}'),
}


class DockCertsNode(WorkflowNode):
    integration_type = "automation-dock-certs"
    connection_evidence = ConnectionEvidence(operation="list_profiles", noun="issuer profiles")

    @classmethod
    def get_config_model(cls):
        return DockCertsFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Dock Certs API key")
        credential = self.config.credentials
        cfg = self.config.config
        values = cfg.model_dump(exclude_none=True, mode="json")
        method, path = ROUTES[cfg.operation]
        path = path.format(**{k: quote(str(v), safe="") for k, v in values.items()})
        params = {}
        if cfg.operation.startswith("list_"):
            params = {k: v for k, v in values.items() if k != "operation"}
            for old, new in (("did_type", "type"), ("subject_id", "subjectId"), ("include_ecosystems", "includeEcosystems")):
                if old in params:
                    params[new] = params.pop(old)
        body = None
        if cfg.operation == "create_did":
            body = {"type": cfg.did_type, "keyType": cfg.key_type, "includeDidcommService": cfg.include_didcomm_service}
        elif cfg.operation == "create_template":
            body = {"name": cfg.name, "html": cfg.html, "css": cfg.css}
        elif cfg.operation == "issue_credential":
            body = {"credential": cfg.credential, "revocable": cfg.revocable, "distribute": cfg.distribute, "format": cfg.format, "persist": False}
        elif cfg.operation == "verify_credential":
            body = cfg.presentation
        elif cfg.operation == "create_schema":
            body = cfg.schema_document
        elif cfg.operation == "create_proof_request":
            body = {k: v for k, v in values.items() if k != "operation"}
        base = "https://api-testnet.truvera.io" if credential.environment == "sandbox" else "https://api.truvera.io"
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, base + path, params=params,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for the connect seam; redact the key.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            output = {"status": "error", "http_status": response.status_code, "error": message or "Dock Certs request rejected"}
        else:
            if not response.content:
                if method != "DELETE":
                    raise ValueError("Dock Certs returned an empty response")
                data = None
            else:
                data = response.json()
                if not isinstance(data, (dict, list)):
                    raise ValueError("Expected a Dock Certs JSON object or array")
            output = {"status": "success", "data": data}
            if cfg.operation.startswith("list_"):
                if not isinstance(data, list):
                    raise ValueError("Expected a Dock Certs list response")
                output.update(items=data, offset=cfg.offset, limit=cfg.limit,
                    next_offset=cfg.offset + cfg.limit if len(data) == cfg.limit else None)
            if cfg.operation in {"create_did", "create_schema"}:
                output["job_submitted"] = True
        await self.emit(output)
        return output

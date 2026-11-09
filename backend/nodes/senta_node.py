"""Senta Client API 1.6: fixed client, job and note operations.

Contract: https://api.swaggerhub.com/apis/senta/Senta/1.6
Client fields are practice-defined; doc_json is the doc object, not its wrapper.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


DOCS = "https://api.swaggerhub.com/apis/senta/Senta/1.6"


class SentaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Senta API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://support.senta.co/support/solutions/articles/12000068808-setting-up-integration-users",
        "x-credential-instructions": "Enter your Senta workspace subdomain and paste its API key. In Senta Settings > Users, choose Add integration, name it NoClick, and generate an API key. Regenerating a key revokes its predecessor. NoClick sends it in the x-auth header to your workspace only.",
    })
    credential_type: Literal["senta_api_key"] = Field("senta_api_key", json_schema_extra={"ui:hidden": True})
    practice: str = Field(..., title="Workspace subdomain", pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", description="For acme.senta.co, enter acme.")
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("practice", mode="before")
    @classmethod
    def workspace(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter the workspace subdomain")
        return value.strip().lower()

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Client(_Input):
    client_id: str = Field(..., min_length=1, max_length=128, pattern=r"^c[a-zA-Z0-9]+$", description="Client ID, for example c260af21ede8f.")


class ListClients(_Input):
    """Read a practice-created client list with its configured filters and columns."""
    operation: Literal["list_clients"] = Field("list_clients", json_schema_extra={"ui:hidden": True})
    client_view_id: str = Field(..., pattern=r"^v[a-zA-Z0-9]+$", max_length=128, description="View ID from a publicly browsable client list URL /c/l/v…; columns use display names.")


class GetClient(_Client):
    """Get the documented subset of one client's data."""
    operation: Literal["get_client"] = Field("get_client", json_schema_extra={"ui:hidden": True})


class _ClientDocument(_Input):
    doc_json: str = Field(..., min_length=2, max_length=100000, title="Client fields (JSON)", description='The client fields object, e.g. {"title":"Mostly Harmless PLC","clientstate":"Client"}. Do not add a doc wrapper. Fields depend on Settings > Forms. Writes can start jobs automatically.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("doc_json")
    @classmethod
    def document(cls, value):
        try:
            doc = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, TypeError):
            raise ValueError("Enter a JSON object of client fields") from None
        if not isinstance(doc, dict) or not doc or any(k in doc for k in ("doc", "_id")):
            raise ValueError("Enter client fields without doc or _id")
        return value


class CreateClient(_ClientDocument):
    """Create a client using your practice's configured fields."""
    operation: Literal["create_client"] = Field("create_client", json_schema_extra={"ui:hidden": True})


class UpdateClient(_ClientDocument, _Client):
    """Update submitted fields; state/service changes may launch Senta jobs."""
    operation: Literal["update_client"] = Field("update_client", json_schema_extra={"ui:hidden": True})


class DeleteClient(_Client):
    """Delete the selected client."""
    operation: Literal["delete_client"] = Field("delete_client", json_schema_extra={"ui:hidden": True})


class SearchClients(_Input):
    """Search clients by keywords."""
    operation: Literal["search_clients"] = Field("search_clients", json_schema_extra={"ui:hidden": True})
    keywords: str = Field(..., min_length=1, max_length=1000)


class _Jobs(_Input):
    status: Optional[Literal["pending", "ready", "overdue", "completed", "cancelled"]] = None


class ListJobs(_Jobs):
    """List jobs, optionally filtered by client, template and status."""
    operation: Literal["list_jobs"] = Field("list_jobs", json_schema_extra={"ui:hidden": True})
    client_id: Optional[str] = Field(None, pattern=r"^c[a-zA-Z0-9]+$", max_length=128)
    template_id: Optional[str] = Field(None, pattern=r"^w[a-zA-Z0-9]+$", max_length=128)


class ListClientJobs(_Jobs, _Client):
    """List jobs belonging to one client, optionally filtered by status."""
    operation: Literal["list_client_jobs"] = Field("list_client_jobs", json_schema_extra={"ui:hidden": True})


class ListTemplateJobs(_Jobs):
    """List jobs using one job template, optionally filtered by status."""
    operation: Literal["list_template_jobs"] = Field("list_template_jobs", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., pattern=r"^w[a-zA-Z0-9]+$", max_length=128)


class _Note(_Client):
    text: str = Field(..., min_length=1, max_length=100000, description="Note text; Senta permits HTML.", json_schema_extra={"ui:widget": "textarea"})
    note_type: Optional[str] = Field(None, max_length=200, description='Omit to use Senta\'s default "Note".')
    date: Optional[str] = Field(None, description="ISO 8601 date/time; omit to use the time of posting.")

    @field_validator("date")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Enter an ISO 8601 date/time") from None
        return value


class CreateClientNote(_Note):
    """Add a note attached to a client."""
    operation: Literal["create_client_note"] = Field("create_client_note", json_schema_extra={"ui:hidden": True})


class CreateJobNote(_Note):
    """Add a note attached to a client and a job."""
    operation: Literal["create_job_note"] = Field("create_job_note", json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., pattern=r"^j[a-zA-Z0-9]+$", max_length=128)


SentaConfig = Annotated[Union[ListClients, GetClient, CreateClient, UpdateClient, DeleteClient, SearchClients,
    ListJobs, ListClientJobs, ListTemplateJobs, CreateClientNote, CreateJobNote], Field(discriminator="operation")]


class SentaFullConfig(NodeConfig[SentaConfig, SentaAPIKeyCredential]):
    pass


class SentaNode(WorkflowNode):
    integration_type = "automation-senta"
    connection_evidence = ConnectionEvidence(noun="Senta jobs", operation="list_jobs")

    @classmethod
    def get_config_model(cls):
        return SentaFullConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.config or not self.config.credentials:
            return {"status": "error", "error": "Connect a Senta API key"}
        credential = self.config.credentials
        op = self.config.config
        method, path, params, body = self._request_parts(op)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, f"https://{credential.practice}.senta.co{path}",
                    headers={"x-auth": credential.api_key, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
            if response.status_code != 200:
                # Preserve the provider's rejection text for manual connect, redact the key.
                message = response.text[:2000].replace(credential.api_key, "[redacted]")
                return {"status": "error", "http_status": response.status_code,
                    "error": message or f"Senta returned HTTP {response.status_code}"}
            if method == "DELETE":
                return {"status": "success", "deleted_client_id": op.client_id}
            if len(response.content) > 10_000_000:
                raise ValueError("Senta returned too much data")
            data = response.json()
            if not isinstance(data, dict) or any(data.get(k) for k in ("error", "errors")):
                raise ValueError("Senta returned an unexpected response")
            if isinstance(op, (ListClients, SearchClients, ListJobs, ListClientJobs, ListTemplateJobs)):
                rows = data.get("docs")
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("Senta did not return a docs array")
                return {"status": "success", "items": rows, "data": data}
            if isinstance(op, (GetClient, CreateClient, UpdateClient)):
                if not isinstance(data.get("doc"), dict):
                    raise ValueError("Senta did not return a client doc")
            return {"status": "success", "data": data}
        except (httpx.HTTPError, ValueError):
            # Never return a transport exception containing the key or request headers.
            return {"status": "error", "error": "Senta request could not be confirmed; inspect Senta before retrying a write"}

    @staticmethod
    def _request_parts(op):
        params, body = {}, None
        if isinstance(op, ListClients):
            return "GET", "/api/clients/" + op.client_view_id, params, body
        if isinstance(op, SearchClients):
            return "GET", "/api/clients/search", {"keywords": op.keywords}, body
        if isinstance(op, (ListJobs, ListClientJobs, ListTemplateJobs)):
            for field, wire in (("client_id", "cid"), ("template_id", "wid"), ("status", "status")):
                value = getattr(op, field, None)
                if value is not None:
                    params[wire] = value
            return "GET", "/api/jobs", params, body
        if isinstance(op, (CreateClientNote, CreateJobNote)):
            body = {"cid": op.client_id, "text": op.text}
            for field, wire in (("job_id", "jid"), ("note_type", "notetype"), ("date", "date")):
                value = getattr(op, field, None)
                if value is not None:
                    body[wire] = value
            return "POST", "/api/notes", params, body
        if isinstance(op, CreateClient):
            return "POST", "/api/clients", params, {"doc": json.loads(op.doc_json)}
        path = "/api/clients/" + op.client_id
        if isinstance(op, UpdateClient):
            return "PUT", path, params, {"doc": json.loads(op.doc_json)}
        return ("DELETE" if isinstance(op, DeleteClient) else "GET"), path, params, body

"""Conveyor Trust Center portal operations using a manually supplied API key.

Each action maps to one published Portal API operation. Requests stay on the
fixed provider origin; list results preserve the provider response and expose items.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.conveyor.com/api"
_JSON = {"ui:widget": "code_editor", "x-code-language": "json"}


class ConveyorAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Conveyor API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.conveyor.com/reference/api-token",
        "x-credential-instructions": "In Conveyor, open Settings > Integrations > Add Integration > Conveyor API. Name the key and grant the portal permissions your workflow needs, including reading folders for the connection check. Paste the API key here. NoClick sends it in X-API-KEY only to api.conveyor.com. Creating an authorization grants Trust Center access and may invite its recipient; nda_bypass skips signing the NDA when enabled.",
    })
    credential_type: Literal["conveyor_api_key"] = Field("conveyor_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def editor_values(cls, value):
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for name, field in cls.model_fields.items():
            if (field.json_schema_extra or {}).get("ui:widget") == "code_editor" and isinstance(value.get(name), list):
                value[name] = json.dumps(value[name])
        return value

    @field_validator("*", mode="after")
    @classmethod
    def bounded_values(cls, value, info):
        if isinstance(value, str) and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use text without control characters")
        if info.field_name.endswith("_id") and value is not None:
            if value in {".", ".."} or any(c in value for c in "/\\?#"):
                raise ValueError("Use a single Conveyor resource ID")
        return value


class ConveyorListAuthorizationRequestQueueConfig(_Input):
    """Gets all the open authorization requests for a program.

WARNING: this endpoint can be replicated by hitting the GET Authorization Requests endpoint (https://docs.conveyor.com/reference/get-authorization-requests) with the status parameter 'requested'. As such, we are looking to deprecate this endpoint in the near future. Prefer list_authorization_requests with status requested for new workflows."""
    operation: Literal['list_authorization_request_queue'] = Field('list_authorization_request_queue', json_schema_extra={"ui:hidden": True})


class ConveyorGetAuthorizationRequestConfig(_Input):
    """Gets the authorization request with the ID from the path"""
    operation: Literal['get_authorization_request'] = Field('get_authorization_request', json_schema_extra={"ui:hidden": True})
    authorization_request_id: str = Field(..., max_length=1000, min_length=1, description='The ID of the authorization request')


class ConveyorIgnoreAuthorizationRequestConfig(_Input):
    """Update the status of an authorization request to be ignored"""
    operation: Literal['ignore_authorization_request'] = Field('ignore_authorization_request', json_schema_extra={"ui:hidden": True})
    authorization_request_id: str = Field(..., max_length=1000, min_length=1, description='The ID of the authorization request')
    status: Literal['ignored'] = Field('ignored', description="Can only be 'ignored'")
    reviewer_email: str = Field(..., max_length=1000, min_length=1, description='Email address of the reviewer')


class ConveyorCreateAuthorizationConfig(_Input):
    """Creates an authorization based on an email or an existing authorization_request"""
    operation: Literal['create_authorization'] = Field('create_authorization', json_schema_extra={"ui:hidden": True})
    request_id: str | None = Field(None, max_length=1000, min_length=1, description='The ID of the authorization request. This OR the "email" field must be provided.')
    email: str | None = Field(None, max_length=1000, min_length=1, description='Email address of the person getting access. This OR the "request_id" field must be provided.')
    access_group_ids: Json[list[str]] | None = Field(None, json_schema_extra=_JSON, min_length=1, max_length=100, description='Optional: IDs of access groups that will be granted to the requestor. Leaving this empty will grant the requestor only basic access to your Room. Supply a nonempty JSON array of IDs; clearing all groups is not supported by this action.')
    nda_bypass: StrictBool | None = Field(None, description="Optional: Whether to bypass the NDA step or not. Defaults to 'false' (i.e. the reviewer will need to sign the NDA).")
    expires_at: date | None = Field(None, description='Optional: Date of when the authorization will be revoked')

    @model_validator(mode="after")
    def recipient(self):
        if not self.request_id and not self.email:
            raise ValueError("Provide an authorization request ID or recipient email")
        return self


class ConveyorListAuthorizationsConfig(_Input):
    """Gets authorizations with an optional status filter"""
    operation: Literal['list_authorizations'] = Field('list_authorizations', json_schema_extra={"ui:hidden": True})
    status: Literal['gated', 'authorized', 'revoked'] | None = Field(None, description="Optional: If provided, it needs to be one of: 'gated' | 'authorized' | 'revoked'")
    email: str | None = Field(None, max_length=1000, min_length=1, description='Optional')


class ConveyorListAccessGroupsConfig(_Input):
    """Gets all the access groups for a program"""
    operation: Literal['list_access_groups'] = Field('list_access_groups', json_schema_extra={"ui:hidden": True})


class ConveyorListAuthorizationRequestsConfig(_Input):
    """Gets authorization requests with an optional status filter"""
    operation: Literal['list_authorization_requests'] = Field('list_authorization_requests', json_schema_extra={"ui:hidden": True})
    status: Literal['initial', 'requested', 'approved', 'ignored'] | None = Field(None, description="Optional: If provided, it needs to be one of: 'initial' | 'requested' | 'approved' | 'ignored'")
    email: str | None = Field(None, max_length=1000, min_length=1, description='Optional')


class ConveyorUpdateAuthorizationConfig(_Input):
    """Revoke an authorization or update it with new access groups"""
    operation: Literal['update_authorization'] = Field('update_authorization', json_schema_extra={"ui:hidden": True})
    authorization_id: str = Field(..., max_length=1000, min_length=1, description='The ID of the authorization')
    access_group_ids: Json[list[str]] | None = Field(None, json_schema_extra=_JSON, min_length=1, max_length=100, description='An array of Access Group IDs. Remove an Access Group by specifying the Access Groups that should remain. Remove all Access Groups by passing an empty array. Supply a nonempty JSON array of IDs; clearing all groups is not supported by this action.')
    status: Literal['revoked'] | None = Field(None, description='Used to update the status to "revoked". Cannot update the status to anything else.')


class ConveyorListDocumentsConfig(_Input):
    """Gets all documents"""
    operation: Literal['list_documents'] = Field('list_documents', json_schema_extra={"ui:hidden": True})


class ConveyorUpdateDocumentConfig(_Input):
    """Updates a document"""
    operation: Literal['update_document'] = Field('update_document', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, max_length=1000, min_length=1, description='Name of the document')
    description: str | None = Field(None, max_length=10000, min_length=1, description='Description of the document')
    certification: Literal['soc1-type-1', 'soc1-type-2', 'soc2-type-1', 'soc2-type-2', 'soc3', 'iso-9001', 'iso-22301-2019', 'iso-27001', 'iso-27001-2013', 'iso-27001-2022', 'iso-27017', 'iso-27018', 'iso-27018-2014', 'iso-27701', 'iso-14001', 'csa', 'pci', 'gdpr', 'sig', 'hipaa', 'hipaa-ce', 'hitrust', 'fedramp', 'fedramp-high', 'fedramp-li-saas', 'fedramp-moderate', 'cyber-essentials', 'cyber-essentials-plus', 'nist', 'nist-800-171', 'ccpa', '21-cfr-11', 'fisma', 'eu-cloud-coc', 'microsoft-365-certified-app', 'ico-registered', 'iatf-16949', 'ens', 'tpn', 'tpn-blue', 'tpn-gold', 'cfpb', 'eu-us-data-privacy', 'pipeda', 'tisax', 'vpat', 'swiss-us-dpf', 'uk-extension-to-eu-us-dpf', 'tx-ramp', 'us-dol-cybersecurity', 'casa', 'irap soc1-type-1', 'irap'] | None = Field(None, description='Certification type (badge) of the document')
    featured: StrictBool | None = Field(None, description="When set to true, this document will be 'featured' on a public profile")
    folder_id: str | None = Field(None, max_length=1000, min_length=1, description='UUID of the folder to place the document in')
    access_level: Literal['public', 'protected', 'need_to_know', 'internal'] | None = Field(None, description='Access level of the document')
    product_line_ids: str | None = Field(None, max_length=1000, min_length=1, description='Comma-separated Product Line UUIDs. These are the applicable product lines for the document. Leave blank if applicable to all product lines.')
    access_group_ids: str | None = Field(None, max_length=1000, min_length=1, description='Comma-separated Access Group UUIDs')
    disable_downloads: StrictBool | None = Field(None, description='Disable downloads for this document')
    use_for_question_answering: StrictBool | None = Field(None, description='Use this document for question answering. If not provided, it will be automatically determined based on whether the document can be used for question answering.')
    document_id: str = Field(..., max_length=1000, min_length=1, description='UUID of the document')


class ConveyorDeleteDocumentConfig(_Input):
    """Deletes a document"""
    operation: Literal['delete_document'] = Field('delete_document', json_schema_extra={"ui:hidden": True})
    document_id: str = Field(..., max_length=1000, min_length=1, description='UUID of the document')


class ConveyorListFoldersConfig(_Input):
    """Gets all folders"""
    operation: Literal['list_folders'] = Field('list_folders', json_schema_extra={"ui:hidden": True})


class ConveyorCreateFolderConfig(_Input):
    """Creates a folder"""
    operation: Literal['create_folder'] = Field('create_folder', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., max_length=1000, min_length=1, description='Name of folder')


class ConveyorDeleteFolderConfig(_Input):
    """Deletes a folder"""
    operation: Literal['delete_folder'] = Field('delete_folder', json_schema_extra={"ui:hidden": True})
    folder_id: str = Field(..., max_length=1000, min_length=1, description='UUID of the folder')


ConveyorConfig = Annotated[Union[
    ConveyorListAuthorizationRequestQueueConfig,
    ConveyorGetAuthorizationRequestConfig,
    ConveyorIgnoreAuthorizationRequestConfig,
    ConveyorCreateAuthorizationConfig,
    ConveyorListAuthorizationsConfig,
    ConveyorListAccessGroupsConfig,
    ConveyorListAuthorizationRequestsConfig,
    ConveyorUpdateAuthorizationConfig,
    ConveyorListDocumentsConfig,
    ConveyorUpdateDocumentConfig,
    ConveyorDeleteDocumentConfig,
    ConveyorListFoldersConfig,
    ConveyorCreateFolderConfig,
    ConveyorDeleteFolderConfig
], Field(discriminator="operation")]


class ConveyorFullConfig(NodeConfig[ConveyorConfig, ConveyorAPIKeyCredential]):
    pass


ROUTES = {
    "list_authorization_request_queue": {
        "method": "GET",
        "path": "/v2/exchange/authorization_request_queue",
        "path_fields": [],
        "query_fields": []
    },
    "get_authorization_request": {
        "method": "GET",
        "path": "/v2/exchange/authorization_requests/{authorization_request_id}",
        "path_fields": [
            "authorization_request_id"
        ],
        "query_fields": []
    },
    "ignore_authorization_request": {
        "method": "PATCH",
        "path": "/v2/exchange/authorization_requests/{authorization_request_id}",
        "path_fields": [
            "authorization_request_id"
        ],
        "query_fields": [
            "status",
            "reviewer_email"
        ]
    },
    "create_authorization": {
        "method": "POST",
        "path": "/v2/exchange/authorizations",
        "path_fields": [],
        "query_fields": [
            "request_id",
            "email",
            "access_group_ids",
            "nda_bypass",
            "expires_at"
        ]
    },
    "list_authorizations": {
        "method": "GET",
        "path": "/v2/exchange/authorizations",
        "path_fields": [],
        "query_fields": [
            "status",
            "email"
        ]
    },
    "list_access_groups": {
        "method": "GET",
        "path": "/v2/exchange/access_groups",
        "path_fields": [],
        "query_fields": []
    },
    "list_authorization_requests": {
        "method": "GET",
        "path": "/v2/exchange/authorization_requests",
        "path_fields": [],
        "query_fields": [
            "status",
            "email"
        ]
    },
    "update_authorization": {
        "method": "PATCH",
        "path": "/v2/exchange/authorizations/{authorization_id}",
        "path_fields": [
            "authorization_id"
        ],
        "query_fields": [
            "access_group_ids",
            "status"
        ]
    },
    "list_documents": {
        "method": "GET",
        "path": "/v2/exchange/documents",
        "path_fields": [],
        "query_fields": []
    },
    "update_document": {
        "method": "PATCH",
        "path": "/v2/exchange/documents/{document_id}",
        "path_fields": [
            "document_id"
        ],
        "query_fields": [
            "name",
            "description",
            "certification",
            "featured",
            "folder_id",
            "access_level",
            "product_line_ids",
            "access_group_ids",
            "disable_downloads",
            "use_for_question_answering"
        ]
    },
    "delete_document": {
        "method": "DELETE",
        "path": "/v2/exchange/documents/{document_id}",
        "path_fields": [
            "document_id"
        ],
        "query_fields": []
    },
    "list_folders": {
        "method": "GET",
        "path": "/v2/exchange/folders",
        "path_fields": [],
        "query_fields": []
    },
    "create_folder": {
        "method": "POST",
        "path": "/v2/exchange/folders",
        "path_fields": [],
        "query_fields": [
            "name"
        ]
    },
    "delete_folder": {
        "method": "DELETE",
        "path": "/v2/exchange/folders/{folder_id}",
        "path_fields": [
            "folder_id"
        ],
        "query_fields": []
    }
}

LIST_KEYS = {
    "list_authorization_request_queue": "authorization_requests",
    "list_authorizations": "authorizations",
    "list_access_groups": "access_groups",
    "list_authorization_requests": "authorization_requests",
    "list_documents": "documents",
    "list_folders": "folders",
}


class ConveyorNode(WorkflowNode):
    integration_type = "automation-conveyor"
    connection_evidence = ConnectionEvidence(noun="folders", operation="list_folders")

    @classmethod
    def get_config_model(cls):
        return ConveyorFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Attach a Conveyor API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for name in route["path_fields"]:
            path = path.replace("{" + name + "}", quote(values[name], safe=""))
        params = {name: values[name] for name in route["query_fields"] if name in values}
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(route["method"], BASE + path, params=params,
                    headers={"X-API-KEY": key, "Accept": "application/json"})
            if not 200 <= response.status_code < 300:
                message = "Conveyor rejected the request"
                # Surface provider errors for connection evidence without echoing secrets.
                if response.content and len(response.content) < 10000:
                    try:
                        error = response.json()
                        detail = error.get("message") or error.get("error") if isinstance(error, dict) else error
                        if isinstance(detail, str):
                            message = detail.replace(key, "[redacted]")[:1000]
                    except ValueError:
                        pass
                return {"status": "error", "http_status": response.status_code, "error": message}
            if response.status_code == 204:
                return {"status": "success", "http_status": 204, "data": None}
            if len(response.content) > 10_000_000:
                raise ValueError("Conveyor response exceeded the JSON size limit")
            body = response.json()
            if not isinstance(body, (dict, list)):
                raise ValueError("Expected a Conveyor JSON object or list")
            if isinstance(body, dict) and (body.get("error") or body.get("errors")):
                raise ValueError("Conveyor returned an error envelope")
            result = {"status": "success", "http_status": response.status_code, "data": body}
            if config.operation in LIST_KEYS:
                if isinstance(body, list):
                    items = body
                else:
                    embedded = body.get("_embedded", body)
                    items = embedded.get(LIST_KEYS[config.operation]) if isinstance(embedded, dict) else None
                if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                    raise ValueError("Conveyor did not return the expected list")
                result["items"] = items
            return result
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "Conveyor request or response could not be confirmed"}

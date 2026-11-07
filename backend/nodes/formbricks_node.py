"""Formbricks Management API v1 workflow actions.

The authenticated Management API covers surveys, responses, contacts, action
classes, webhooks, and public upload URL preparation. The separate unauthenticated
Client API is intentionally not used by this credentialed automation node.

API reference: https://formbricks.com/docs/api-reference/rest-api
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Dict, Literal, Optional, Type, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client, normalize_https_origin


FORMBRICKS_CLOUD = "https://app.formbricks.com"
_JSON_FIELD = {"ui:widget": "code_editor", "x-code-language": "json"}
_SURVEY_OPTIONS = {
    "x-dynamic-options": {
        "field_name": "survey_id",
        "placeholder": "Select a survey",
        "searchable": True,
        "allow_custom": True,
        "custom_placeholder": "Or paste a survey ID",
    }
}


class FormbricksApiKeyCredential(BaseModel):
    """Personal API key with access to the intended Formbricks workspace."""

    credential_type: Literal["formbricks_api_key"] = Field(
        "formbricks_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    base_url: str = Field(
        FORMBRICKS_CLOUD,
        title="Formbricks Site URL",
        description="Use https://app.formbricks.com or the HTTPS origin of your self-hosted site.",
    )

    model_config = ConfigDict(title="Formbricks API Key", json_schema_extra={
        "x-credential-url": "https://formbricks.com/docs/api-reference/generate-key",
        "x-credential-instructions": (
            "Create a personal API key with Workspace Read access for reads, Write for "
            "creation and updates, or Manage for deletes. Add each workspace the key needs."
        ),
    })

    @field_validator("api_key")
    @classmethod
    def nonempty_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("API key is required")
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def valid_site(cls, value: str) -> str:
        return normalize_https_origin(value, field_name="Formbricks Site URL")


@dataclass(frozen=True)
class _Operation:
    name: str
    label: str
    category: str
    method: str
    path: str
    fields: tuple[str, ...] = ()
    body: Optional[str] = None


# Paths and methods come only from the official v1 reference. User values can
# fill path parameters, query parameters, and JSON bodies, never an API path.
_OPERATIONS = (
    _Operation("get_me", "Get Connected Workspace", "Account", "GET", "/api/v1/management/me"),
    _Operation("list_surveys", "List Surveys", "Surveys", "GET", "/api/v1/management/surveys"),
    _Operation("create_survey", "Create Survey", "Surveys", "POST", "/api/v1/management/surveys", ("workspace_id", "payload_json"), "survey"),
    _Operation("get_survey", "Get Survey", "Surveys", "GET", "/api/v1/management/surveys/{survey_id}", ("survey_id",)),
    _Operation("update_survey", "Update Survey", "Surveys", "PUT", "/api/v1/management/surveys/{survey_id}", ("survey_id", "payload_json"), "payload"),
    _Operation("delete_survey", "Delete Survey", "Surveys", "DELETE", "/api/v1/management/surveys/{survey_id}", ("survey_id",)),
    _Operation("get_single_use_links", "Get Single-Use Links", "Surveys", "GET", "/api/v1/management/surveys/{survey_id}/singleUseIds", ("survey_id",)),
    _Operation("list_responses", "List Responses", "Responses", "GET", "/api/v1/management/responses", ("optional_survey_id", "limit", "skip")),
    _Operation("create_response", "Create Response", "Responses", "POST", "/api/v1/management/responses", ("survey_id", "payload_json"), "response"),
    _Operation("get_response", "Get Response", "Responses", "GET", "/api/v1/management/responses/{response_id}", ("response_id",)),
    _Operation("update_response", "Update Response", "Responses", "PUT", "/api/v1/management/responses/{response_id}", ("response_id", "payload_json"), "payload"),
    _Operation("delete_response", "Delete Response", "Responses", "DELETE", "/api/v1/management/responses/{response_id}", ("response_id",)),
    _Operation("list_contacts", "List Contacts", "Contacts", "GET", "/api/v1/management/contacts"),
    _Operation("get_contact", "Get Contact", "Contacts", "GET", "/api/v1/management/contacts/{contact_id}", ("contact_id",)),
    _Operation("list_contact_attribute_keys", "List Contact Attribute Keys", "Contacts", "GET", "/api/v1/management/contact-attribute-keys"),
    _Operation("get_contact_attribute_key", "Get Contact Attribute Key", "Contacts", "GET", "/api/v1/management/contact-attribute-keys/{attribute_key_id}", ("attribute_key_id",)),
    _Operation("list_contact_attributes", "List Contact Attributes", "Contacts", "GET", "/api/v1/management/contact-attributes"),
    _Operation("list_action_classes", "List Action Classes", "Actions", "GET", "/api/v1/management/action-classes"),
    _Operation("create_action_class", "Create Action Class", "Actions", "POST", "/api/v1/management/action-classes", ("workspace_id", "name", "key", "description"), "action_class"),
    _Operation("get_action_class", "Get Action Class", "Actions", "GET", "/api/v1/management/action-classes/{action_class_id}", ("action_class_id",)),
    _Operation("delete_action_class", "Delete Action Class", "Actions", "DELETE", "/api/v1/management/action-classes/{action_class_id}", ("action_class_id",)),
    _Operation("list_webhooks", "List Webhooks", "Webhooks", "GET", "/api/v1/webhooks"),
    _Operation("create_webhook", "Create Webhook", "Webhooks", "POST", "/api/v1/webhooks", ("webhook_url", "triggers"), "webhook"),
    _Operation("get_webhook", "Get Webhook", "Webhooks", "GET", "/api/v1/webhooks/{webhook_id}", ("webhook_id",)),
    _Operation("delete_webhook", "Delete Webhook", "Webhooks", "DELETE", "/api/v1/webhooks/{webhook_id}", ("webhook_id",)),
    _Operation("prepare_public_upload", "Get Public Upload URL", "Files", "POST", "/api/v1/management/storage", ("workspace_id", "file_name", "file_type", "allowed_extensions_json"), "upload"),
)
_OPERATION_BY_NAME = {operation.name: operation for operation in _OPERATIONS}


def _field(name: str):
    if name == "survey_id":
        return (str, Field(..., title="Survey", json_schema_extra=_SURVEY_OPTIONS))
    if name == "optional_survey_id":
        return (Optional[str], Field(None, title="Survey (Optional)", description="Leave blank to list responses across accessible surveys.", json_schema_extra=_SURVEY_OPTIONS))
    if name == "workspace_id":
        return (str, Field(..., title="Workspace ID", description="Shown by Get Connected Workspace."))
    if name == "payload_json":
        return (str, Field(..., title="Request Body (JSON Object)", description="Paste the documented Formbricks request body. Create Survey and Create Response add the selected workspace or survey ID.", json_schema_extra=_JSON_FIELD))
    if name == "limit":
        return (int, Field(100, ge=1, le=500, title="Limit"))
    if name == "skip":
        return (int, Field(0, ge=0, title="Skip"))
    if name == "description":
        return (Optional[str], Field(None, title="Description"))
    if name == "triggers":
        return (list[Literal["responseCreated", "responseUpdated", "responseFinished"]], Field(..., min_length=1, title="Webhook Events"))
    if name == "webhook_url":
        return (str, Field(..., title="Webhook Destination URL", description="An HTTPS URL that will receive Formbricks events."))
    if name == "allowed_extensions_json":
        return (Optional[str], Field(None, title="Allowed Extensions (JSON Array)", description='For example ["png","jpg"].', json_schema_extra=_JSON_FIELD))
    labels = {
        "response_id": "Response ID", "contact_id": "Contact ID",
        "attribute_key_id": "Attribute Key ID", "action_class_id": "Action Class ID",
        "webhook_id": "Webhook ID", "name": "Name", "key": "Action Key",
        "file_name": "File Name", "file_type": "MIME Type",
    }
    return (str, Field(..., title=labels[name]))


def _operation_model(operation: _Operation) -> Type[BaseModel]:
    title = "".join(part.capitalize() for part in operation.name.split("_"))
    fields: Dict[str, Any] = {
        "operation": (Literal[operation.name], Field(
            operation.name,
            title=operation.label,
            json_schema_extra={
                "const": operation.name,
                "ui:hidden": True,
                "x-display-name": operation.label,
                "x-category": operation.category,
            },
        ))
    }
    for name in operation.fields:
        model_name = "survey_id" if name == "optional_survey_id" else name
        fields[model_name] = _field(name)
    return create_model(f"Formbricks{title}Config", **fields)


_CONFIG_MODELS = tuple(_operation_model(operation) for operation in _OPERATIONS)
FormbricksOperation = Annotated[Union[_CONFIG_MODELS], Discriminator("operation")]


class FormbricksNodeConfig(NodeConfig[FormbricksOperation, FormbricksApiKeyCredential]):
    pass


def _path_part(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 512:
        raise ValueError(f"{label} must be a nonempty ID of at most 512 characters")
    return quote(text, safe="")


def _json_object(raw: str, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


async def _request(
    credential: FormbricksApiKeyCredential,
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call only code-owned v1 paths with SSRF and redirect protection."""
    if not (
        path.startswith("/api/v1/management/")
        or path == "/api/v1/webhooks"
        or path.startswith("/api/v1/webhooks/")
    ):
        raise ValueError("Unsupported Formbricks API path")
    async with guarded_async_client(timeout=30, follow_redirects=False) as client:
        response = await client.request(
            method,
            f"{credential.base_url}{path}",
            headers={"x-api-key": credential.api_key, "Accept": "application/json"},
            params=params,
            json=body,
        )
    if response.is_redirect:
        raise ValueError("Formbricks redirected the request; use the site's final HTTPS origin")
    if response.is_error:
        hint = {
            401: "Check the API key.",
            403: "Check this key's workspace access and permission level.",
            404: "The requested item was not found.",
            429: "Rate limit reached; retry later.",
        }.get(response.status_code, "Check the request and Formbricks API status.")
        raise ValueError(f"Formbricks HTTP {response.status_code}. {hint}")
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"Formbricks returned non-JSON HTTP {response.status_code}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Formbricks returned an unexpected JSON response")
    return payload


def _request_parts(config: BaseModel, operation: _Operation):
    values = config.model_dump(exclude_none=True)
    path = operation.path
    for name in ("survey_id", "response_id", "contact_id", "attribute_key_id", "action_class_id", "webhook_id"):
        if "{" + name + "}" in path:
            path = path.replace("{" + name + "}", _path_part(values[name], name.replace("_", " ").title()))

    params: Optional[Dict[str, Any]] = None
    if operation.name == "list_responses":
        params = {"limit": values["limit"], "skip": values["skip"]}
        if values.get("survey_id"):
            params["surveyId"] = values["survey_id"]

    body: Optional[Dict[str, Any]] = None
    if operation.body in ("payload", "survey", "response"):
        body = _json_object(values["payload_json"], "Request body")
        if operation.body == "survey":
            body["workspaceId"] = values["workspace_id"]
        elif operation.body == "response":
            body["surveyId"] = values["survey_id"]
    elif operation.body == "action_class":
        body = {"workspaceId": values["workspace_id"], "name": values["name"],
                "key": values["key"], "type": "code"}
        if values.get("description"):
            body["description"] = values["description"]
    elif operation.body == "webhook":
        url = values["webhook_url"].strip()
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Webhook destination must be an HTTPS URL without credentials or fragment")
        body = {"url": url, "triggers": values["triggers"]}
    elif operation.body == "upload":
        body = {"workspaceId": values["workspace_id"], "fileName": values["file_name"],
                "fileType": values["file_type"]}
        if values.get("allowed_extensions_json"):
            try:
                extensions = json.loads(values["allowed_extensions_json"])
            except ValueError as exc:
                raise ValueError("Allowed extensions must be a JSON array") from exc
            if not isinstance(extensions, list) or not all(isinstance(item, str) for item in extensions):
                raise ValueError("Allowed extensions must be a JSON array of strings")
            body["allowedFileExtensions"] = extensions
    return path, params, body


class FormbricksNode(WorkflowNode):
    integration_type = "automation-formbricks"

    connection_evidence = ConnectionEvidence(
        field="survey_id", noun="surveys", identity_operation="get_me"
    )

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return FormbricksNodeConfig

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        if field_name != "survey_id":
            return {"options": [], "next_page_token": None}
        credential = FormbricksApiKeyCredential(**credential_data)
        try:
            offset = int(page_token or "0")
        except ValueError as exc:
            raise ValueError("Invalid survey picker page token") from exc
        if offset < 0:
            raise ValueError("Invalid survey picker page token")
        payload = await _request(credential, "GET", "/api/v1/management/surveys")
        surveys = payload.get("data", [])
        if not isinstance(surveys, list):
            raise ValueError("Formbricks returned an invalid survey list")
        items = [item for item in surveys if isinstance(item, dict) and item.get("id")]
        if search:
            needle = search.casefold()
            items = [item for item in items if needle in str(item.get("name", "")).casefold()]
        page = items[offset:offset + 100]
        return {
            "options": [{"value": item["id"], "label": item.get("name") or item["id"]} for item in page],
            "next_page_token": str(offset + len(page)) if offset + len(page) < len(items) else None,
        }

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, FormbricksNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Formbricks API key before running this node")
        config = self.config.config
        operation = _OPERATION_BY_NAME[config.operation]
        path, params, body = _request_parts(config, operation)
        payload = await _request(self.config.credentials, operation.method, path, params=params, body=body)
        value = payload.get("data", payload)
        result: Dict[str, Any] = {"status": "success", "action": operation.name, "data": value}
        if isinstance(value, list):
            result["count"] = len(value)
        return result

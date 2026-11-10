"""Karbon v3 practice-management operations using pasted API credentials.
Each operation maps to one published API endpoint and preserves its JSON data.
"""
from __future__ import annotations
import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.karbonhq.com"

class KarbonCredential(BaseModel):
    model_config = ConfigDict(title="Karbon API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.karbonhq.com/guides/authentication/",
            "x-credential-instructions": "In Karbon, open Settings → Connected Apps → API Applications → your API application. Paste its Authorization token and tenant AccessKey. Omit the Bearer prefix. Both values are required.",
        })
    credential_type: Literal["karbon_api_key"] = Field("karbon_api_key", json_schema_extra={"ui:hidden": True})
    authorization_token: str = Field(..., min_length=1, title="Authorization Token", repr=False, json_schema_extra={"ui:widget": "password"})
    access_key: str = Field(..., min_length=1, title="AccessKey", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("authorization_token", "access_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Karbon credential")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the credential without a Bearer prefix or whitespace")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _Page(_Input):
    top: int = Field(100, ge=1, le=100, description="Page size; subsequent pages are not fetched automatically.")
    skip: int = Field(0, ge=0, le=100, description="Documented $skip offset (0–100).")
    filter: str | None = Field(None, description="OData $filter supported by this endpoint.")

class _Key(_Input):
    key: str = Field(..., min_length=1, description="Karbon-generated record key.")

    @field_validator("key")
    @classmethod
    def valid_key(cls, value):
        if value in {".", ".."} or any(c in value for c in "/?#") or any(ord(c) < 33 for c in value):
            raise ValueError("Use one Karbon record key, without path or query components")
        return value

class _ContactFields(_Input):
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    preferred_name: str | None = None
    salutation: str | None = None
    suffix: str | None = None

class _NonemptyPatch(_Input):
    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude={"operation", "key"}, exclude_none=True):
            raise ValueError("Supply at least one field to update")
        return self

class KarbonCreateContact(_ContactFields):
    operation: Literal["create_contact"] = "create_contact"
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    contact_type: str | None = None
    client_owner: str | None = None
    client_manager: str | None = None
    user_defined_identifier: str | None = None

class KarbonUpdateContact(_ContactFields, _Key, _NonemptyPatch):
    operation: Literal["update_contact"] = "update_contact"

class KarbonCreateOrganization(_Input):
    operation: Literal["create_organization"] = "create_organization"
    full_name: str = Field(..., min_length=1)
    contact_type: str | None = None
    client_owner: str | None = None
    client_manager: str | None = None
    user_defined_identifier: str | None = None

class KarbonUpdateOrganization(_Key):
    operation: Literal["update_organization"] = "update_organization"
    full_name: str = Field(..., min_length=1)

class _WorkFields(_Input):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    assignee_email_address: str | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    deadline_date: datetime | None = None
    work_type: str | None = None
    primary_status: Literal["Planned", "ReadyToStart", "InProgress", "Waiting", "Completed"] | None = Field(None,
        description="PrimaryStatus without SecondaryStatus clears the existing secondary status.")
    secondary_status: str | None = None

    @model_validator(mode="after")
    def secondary_needs_primary(self):
        if self.secondary_status is not None and self.primary_status is None:
            raise ValueError("Secondary status requires primary status in the same request")
        return self

class KarbonCreateWorkItem(_WorkFields):
    operation: Literal["create_work_item"] = "create_work_item"
    title: str = Field(..., min_length=1, max_length=200)
    assignee_email_address: str = Field(..., min_length=1)
    client_key: str = Field(..., min_length=1)
    client_type: Literal["Contact", "Organization", "ClientGroup"]
    start_date: datetime
    work_template_key: str | None = None

class KarbonUpdateWorkItem(_WorkFields, _Key, _NonemptyPatch):
    operation: Literal["update_work_item"] = "update_work_item"

class KarbonNoteTimeline(_Input):
    entity_type: Literal["WorkItem", "Contact", "Organization", "ClientGroup"]
    entity_key: str = Field(..., min_length=1)

class KarbonCreateNote(_Input):
    operation: Literal["create_note"] = "create_note"
    subject: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1, description="Note body; accepts HTML.")
    author_email_address: str = Field(..., min_length=1)
    assignee_email_address: str | None = None
    due_date: datetime | None = None
    todo_date: datetime | None = None
    timelines: list[KarbonNoteTimeline] = Field(default_factory=list)

class KarbonListContacts(_Page):
    operation: Literal["list_contacts"] = "list_contacts"

class KarbonGetContact(_Key):
    operation: Literal["get_contact"] = "get_contact"

class KarbonListOrganizations(_Page):
    operation: Literal["list_organizations"] = "list_organizations"

class KarbonGetOrganization(_Key):
    operation: Literal["get_organization"] = "get_organization"

class KarbonListWorkItems(_Page):
    operation: Literal["list_work_items"] = "list_work_items"

class KarbonGetWorkItem(_Key):
    operation: Literal["get_work_item"] = "get_work_item"

class KarbonListUsers(_Page):
    operation: Literal["list_users"] = "list_users"

class KarbonGetUser(_Key):
    operation: Literal["get_user"] = "get_user"

class KarbonListWorkTemplates(_Page):
    operation: Literal["list_work_templates"] = "list_work_templates"

class KarbonGetWorkTemplate(_Key):
    operation: Literal["get_work_template"] = "get_work_template"

class KarbonListClientGroups(_Page):
    operation: Literal["list_client_groups"] = "list_client_groups"

class KarbonGetClientGroup(_Key):
    operation: Literal["get_client_group"] = "get_client_group"

class KarbonGetNote(_Key):
    operation: Literal["get_note"] = "get_note"

class KarbonGetTenantSettings(_Input):
    operation: Literal["get_tenant_settings"] = "get_tenant_settings"

class _KarbonWebhook(WebhookTriggerConfigBase):
    webhook_url: str | None = Field(None, title="Webhook URL",
        description="Registered automatically. Karbon allows one workflow per webhook type per API application.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

class KarbonOnContactChanged(_KarbonWebhook):
    operation: Literal["on_contact_changed"] = Field("on_contact_changed", title="On Contact Changed",
        json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On Contact Changed"})

class KarbonOnWorkItemChanged(_KarbonWebhook):
    operation: Literal["on_work_item_changed"] = Field("on_work_item_changed", title="On Work Item Changed",
        json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On Work Item Changed"})

class KarbonOnNoteChanged(_KarbonWebhook):
    operation: Literal["on_note_changed"] = Field("on_note_changed", title="On Note Changed",
        json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On Note Changed"})

KarbonOperation = Annotated[Union[
    KarbonOnContactChanged,
    KarbonOnWorkItemChanged,
    KarbonOnNoteChanged,
    KarbonCreateContact,
    KarbonUpdateContact,
    KarbonCreateOrganization,
    KarbonUpdateOrganization,
    KarbonCreateWorkItem,
    KarbonUpdateWorkItem,
    KarbonCreateNote,
    KarbonListContacts,
    KarbonGetContact,
    KarbonListOrganizations,
    KarbonGetOrganization,
    KarbonListWorkItems,
    KarbonGetWorkItem,
    KarbonListUsers,
    KarbonGetUser,
    KarbonListWorkTemplates,
    KarbonGetWorkTemplate,
    KarbonListClientGroups,
    KarbonGetClientGroup,
    KarbonGetNote,
    KarbonGetTenantSettings
], Field(discriminator="operation")]

class KarbonConfig(NodeConfig[KarbonOperation, KarbonCredential]):
    @model_validator(mode="before")
    @classmethod
    def editor_metadata(cls, value):
        if isinstance(value, dict) and isinstance(value.get("config"), dict):
            value = {**value, "config": {k: v for k, v in value["config"].items()
                if k not in {"credentialIds", "key__label"}}}
        return value

OPERATIONS = {'create_contact': ('POST', '/v3/Contacts'), 'update_contact': ('PATCH', '/v3/Contacts/{key}'), 'create_organization': ('POST', '/v3/Organizations'), 'update_organization': ('PATCH', '/v3/Organizations/{key}'), 'create_work_item': ('POST', '/v3/WorkItems'), 'update_work_item': ('PATCH', '/v3/WorkItems/{key}'), 'create_note': ('POST', '/v3/Notes'), 'list_contacts': ('GET', '/v3/Contacts'), 'get_contact': ('GET', '/v3/Contacts/{key}'), 'list_organizations': ('GET', '/v3/Organizations'), 'get_organization': ('GET', '/v3/Organizations/{key}'), 'list_work_items': ('GET', '/v3/WorkItems'), 'get_work_item': ('GET', '/v3/WorkItems/{key}'), 'list_users': ('GET', '/v3/Users'), 'get_user': ('GET', '/v3/Users/{key}'), 'list_work_templates': ('GET', '/v3/WorkTemplates'), 'get_work_template': ('GET', '/v3/WorkTemplates/{key}'), 'list_client_groups': ('GET', '/v3/ClientGroups'), 'get_client_group': ('GET', '/v3/ClientGroups/{key}'), 'get_note': ('GET', '/v3/Notes/{key}'), 'get_tenant_settings': ('GET', '/v3/TenantSettings')}


def _wire_name(name):
    return "".join(part.title() for part in name.split("_"))


def _body(config):
    values = config.model_dump(mode="json", exclude={"key", "operation"}, exclude_none=True)
    result = {_wire_name(k): v for k, v in values.items()}
    if "timelines" in values:
        result["Timelines"] = [{_wire_name(k): v for k, v in row.items()} for row in values["timelines"]]
    return result


# Single-event subscriptions deliberately omit preview batching. The provider's
# payloads and registration contract are pinned in the webhook fixture manifest.
TRIGGER_TYPES = {
    "on_contact_changed": ("Contact", {"Contact", "Organization", "ClientGroup"}),
    "on_work_item_changed": ("Work", {"Work"}),
    "on_note_changed": ("Note", {"Note", "NoteComment"}),
}


class KarbonNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-karbon"
    connection_evidence = ConnectionEvidence(operation="list_users", noun="Karbon users",
        label_keys=("Name", "EmailAddress", "UserKey"))

    @classmethod
    def get_config_model(cls):
        return KarbonConfig

    @classmethod
    async def _webhook_request(cls, credential, method, path, *, body=None):
        credential = KarbonCredential.model_validate(credential)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.authorization_token,
                    "AccessKey": credential.access_key, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if response.status_code == 404 and method in {"GET", "DELETE"}:
            return None
        if not 200 <= response.status_code < 300:
            message = response.text
            for secret in (credential.authorization_token, credential.access_key, (body or {}).get("SigningKey")):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise ValueError(f"Karbon HTTP {response.status_code}: {message[:2000]}")
        if response.status_code == 204:
            return None
        data = response.json()
        if not isinstance(data, dict) or "error" in data:
            raise ValueError("Expected a Karbon webhook subscription")
        return data

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        subscription_type, _ = TRIGGER_TYPES[config["operation"]]
        secret = secrets.token_hex(32)
        # POST is only called by the lifecycle on activation, never per delivery.
        # Karbon rejects a second subscription of the same type; don't delete it.
        await cls._webhook_request(credential, "POST", "/v3/WebhookSubscriptions", body={
            "TargetUrl": webhook_url, "WebhookType": subscription_type, "SigningKey": secret})
        return {"external_webhook_id": subscription_type, "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        subscription_type = config.get("external_webhook_id")
        if not credential or subscription_type not in {v[0] for v in TRIGGER_TYPES.values()}:
            return
        path = "/v3/WebhookSubscriptions/" + subscription_type
        subscription = await cls._webhook_request(credential, "GET", path)
        # The provider has no subscription id: the type is its address. Do not
        # remove a subscription somebody has since moved to another endpoint.
        if subscription and config.get("webhook_url") and subscription.get("TargetUrl") == config["webhook_url"]:
            await cls._webhook_request(credential, "DELETE", path)

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://developers.karbonhq.com/guides/webhooks/#signature-verification
        secret = config.get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "signature"), "")
        if not secret or not isinstance(signature, str) or not signature.isascii() or len(signature) != 64:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        types = TRIGGER_TYPES.get(config.get("operation"))
        return bool(types and isinstance(payload, dict)
            and payload.get("ResourceType") in types[1]
            and payload.get("ActionType") in {"Inserted", "Updated", "Deleted"}
            and payload.get("ResourcePermaKey"))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        resource_type = output.get("ResourceType")
        key = output.get("ResourcePermaKey")
        action = output.get("ActionType")
        if not key or not resource_type or not action:
            return None
        noun = {"Work": "work item", "ClientGroup": "client group", "NoteComment": "note comment"}.get(
            resource_type, resource_type.lower())
        verb = {"Inserted": "created", "Updated": "updated", "Deleted": "deleted"}.get(action, action)
        title = f"Karbon {noun} {verb}: {key}"
        lines = [title, f"Resource type: {resource_type}; ResourcePermaKey: {key}"]
        if output.get("TimeStamp"):
            lines.append(f"Changed at: {output['TimeStamp']}")
        if resource_type == "NoteComment" and output.get("ParentEntityKey"):
            lines.append(f"Parent note key: {output['ParentEntityKey']}")
        if action != "Deleted":
            operation = {"Contact": "get_contact", "Organization": "get_organization",
                "ClientGroup": "get_client_group", "Work": "get_work_item", "Note": "get_note"}.get(resource_type)
            if operation:
                lines.append(f"Read the record with {operation} key={key} for its content and people.")
        return {"text": "\n".join(lines), "title": title, "conversation_key": f"{resource_type}:{key}"}

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, _KarbonWebhook):
            return self.no_event_output(config.operation)
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect Karbon API credentials")
        method, path = OPERATIONS[config.operation]
        if isinstance(config, _Key):
            path = path.replace("{key}", quote(config.key, safe=""))
        params = {}
        if isinstance(config, _Page):
            params = {"$top": config.top, "$skip": config.skip}
            if config.filter is not None:
                params["$filter"] = config.filter
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.authorization_token,
                    "AccessKey": credential.access_key, "Accept": "application/json"},
                params=params, **({"json": _body(config)} if method != "GET" else {}))
        if response.is_error:
            message = response.text
            for secret in (credential.authorization_token, credential.access_key):
                message = message.replace(secret, "[redacted]")
            raise ValueError(f"Karbon HTTP {response.status_code}: {message[:2000]}")
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Unexpected Karbon HTTP {response.status_code}")
        if response.status_code == 204:
            return {"status": "success", "operation": config.operation, "data": None}
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a Karbon JSON object")
        if "error" in body:
            raise ValueError("Karbon returned an API error")
        result = {"status": "success", "operation": config.operation, "data": body}
        if isinstance(config, _Page):
            rows = body.get("value")
            if not isinstance(rows, list):
                raise ValueError("Expected an OData value array")
            result.update(items=rows, next_page_url=body.get("@odata.nextLink"), total=body.get("@odata.count"))
        return result

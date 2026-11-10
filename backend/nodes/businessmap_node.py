"""Businessmap API v2 cards and board events.

Contract: https://demo.kanbanize.com/openapi/json (1.0.0).
Deliveries: https://knowledgebase.businessmap.io/hc/en-us/articles/360015393251-Businessmap-Webhooks
Board webhooks send a shared secret in x-kanbanize-secret, not a body HMAC.
"""
from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from utils.ssrf import guarded_async_client, normalize_provider_https_origin

DOCS = "https://demo.kanbanize.com/openapi"
WEBHOOK_DOCS = "https://knowledgebase.businessmap.io/hc/en-us/articles/360015393251-Businessmap-Webhooks"


class BusinessmapAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Businessmap API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "Enter your Businessmap account URL and paste your existing API key from My Account → API → Show API key. Creating a new key revokes the old key. Your key has your user's permissions."})
    credential_type: Literal["businessmap_api_key"] = Field("businessmap_api_key", json_schema_extra={"ui:hidden": True})
    account_url: str = Field(..., title="Account URL", description="Your account origin, such as https://mycompany.kanbanize.com")
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("account_url")
    @classmethod
    def origin(cls, value):
        host = urlsplit(value if "://" in value else "https://" + value).hostname or ""
        domain = "businessmap.io" if host.endswith(".businessmap.io") else "kanbanize.com"
        return normalize_provider_https_origin(value, domain)

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class Input(BaseModel):
    # Canvas labels and old-operation registration mirrors accompany saved
    # config. Only declared fields are ever serialized into API requests.
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


def number(*, required=False, default=None, maximum=2147483647, minimum=1, description=""):
    return (int if required or default is not None else int | None,
            Field(... if required else default, ge=minimum, le=maximum, description=description))


def text(*, required=False, description="", multiline=False):
    return (str if required else str | None, Field(... if required else None, min_length=1,
            description=description, json_schema_extra={"ui:widget": "textarea"} if multiline else None))


def picker(name):
    return (int, Field(..., ge=1, json_schema_extra={"x-dynamic-options": {
        "field_name": name, "allow_custom": True, "searchable": True, "placeholder": "Choose board"}}))


CARD = {"card_id": number(required=True)}
SUBTASK = {**CARD, "subtask_id": number(required=True)}
CARD_FIELDS = {
    "title": text(), "description": text(multiline=True),
    "column_id": number(), "lane_id": number(), "owner_user_id": number(),
    "priority": number(maximum=250), "size": (float | None, Field(None, ge=0, le=1e15)),
    "deadline": (AwareDatetime | None, None), "custom_id": text(),
    "tag_ids_to_add": (list[int] | None, None), "tag_ids_to_remove": (list[int] | None, None),
    "is_archived": (Literal[0, 1] | None, None),
}
SUBTASK_FIELDS = {"description": text(multiline=True), "owner_user_id": number(),
    "is_finished": (Literal[0, 1] | None, None), "deadline": (AwareDatetime | None, None),
    "position": number(minimum=0)}
PAGE = {"page": number(default=1), "per_page": number(default=100, maximum=1000)}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: dict
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()


OPERATIONS = {
    "get_current_user": Operation("GET", "/me", {}),
    "list_boards": Operation("GET", "/boards", {}),
    "get_board": Operation("GET", "/boards/{board_id}", {"board_id": picker("board_id")}),
    "list_workspaces": Operation("GET", "/workspaces", {}),
    "list_users": Operation("GET", "/users", {}),
    "list_workflows": Operation("GET", "/boards/{board_id}/workflows", {"board_id": picker("board_id")}),
    "get_board_structure": Operation("GET", "/boards/{board_id}/currentStructure", {"board_id": picker("board_id")}),
    "list_cards": Operation("GET", "/cards", {**PAGE,
        "board_ids": (str | None, Field(None, pattern=r"^[1-9][0-9]*(,[1-9][0-9]*)*$", description="Comma-separated board IDs")),
        "state": (Literal["active", "archived", "discarded"] | None, None),
        "created_from": (AwareDatetime | None, None), "last_modified_from": (AwareDatetime | None, None)},
        query=("page", "per_page", "board_ids", "state", "created_from", "last_modified_from")),
    "get_card": Operation("GET", "/cards/{card_id}", CARD),
    "create_card": Operation("POST", "/cards", {**CARD_FIELDS, "title": text(required=True),
        "column_id": number(required=True), "lane_id": number(required=True)}, body=tuple(CARD_FIELDS)),
    "update_card": Operation("PATCH", "/cards/{card_id}", {**CARD, **CARD_FIELDS}, body=tuple(CARD_FIELDS)),
    "delete_card": Operation("DELETE", "/cards/{card_id}", CARD),
    "list_comments": Operation("GET", "/cards/{card_id}/comments", CARD),
    "add_comment": Operation("POST", "/cards/{card_id}/comments", {**CARD, "text": text(required=True, multiline=True)}, body=("text",)),
    "list_subtasks": Operation("GET", "/cards/{card_id}/subtasks", CARD),
    "create_subtask": Operation("POST", "/cards/{card_id}/subtasks", {**CARD, **SUBTASK_FIELDS,
        "description": text(required=True, multiline=True)}, body=tuple(SUBTASK_FIELDS)),
    "update_subtask": Operation("PATCH", "/cards/{card_id}/subtasks/{subtask_id}", {**SUBTASK, **SUBTASK_FIELDS}, body=tuple(SUBTASK_FIELDS)),
    "delete_subtask": Operation("DELETE", "/cards/{card_id}/subtasks/{subtask_id}", SUBTASK),
    "list_tags": Operation("GET", "/tags", {}),
    "log_time": Operation("POST", "/loggedTime", {**CARD, "time": number(required=True, maximum=6000000,
        description="Time to log, in seconds"), "date": (date | None, None), "comment": text(multiline=True),
        "subtask_id": number(), "user_id": number(), "category_id": number()},
        body=("card_id", "time", "date", "comment", "subtask_id", "user_id", "category_id")),
}


class WriteInput(Input):
    @model_validator(mode="after")
    def nonempty_update(self):
        if self.operation.startswith("update_"):
            fields = OPERATIONS[self.operation].body
            if not any(getattr(self, key) is not None for key in fields):
                raise ValueError("Choose at least one field to update")
        for key in ("tag_ids_to_add", "tag_ids_to_remove"):
            if any(type(v) is not int or v <= 0 for v in (getattr(self, key, None) or [])):
                raise ValueError("Tag IDs must be positive integers")
        return self


CONFIG_MODELS = {}
for name, op in OPERATIONS.items():
    model = create_model("Businessmap" + "".join(p.title() for p in name.split("_")) + "Config",
        __base__=WriteInput, __module__=__name__,
        operation=(Literal[name], Field(name, title=name.replace("_", " ").title(),
            json_schema_extra={"ui:hidden": True, "x-is-trigger": False,
                "x-display-name": name.replace("_", " ").title()})), **op.fields)
    CONFIG_MODELS[name] = model
    globals()[model.__name__] = model


TRIGGER_EVENTS = {"on_card_created": "Card created", "on_card_updated": "Card details changed",
                  "on_comment_created": "Comment created", "on_subtask_created": "Subtask created"}


class BoardTrigger(WebhookTriggerConfigBase):
    board_id: int = picker("board_id")[1]
    webhook_url: str | None = Field(None, title="Webhook URL", description="Registered automatically on this board",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


for name in TRIGGER_EVENTS:
    model = create_model("Businessmap" + "".join(p.title() for p in name.split("_")) + "Config",
        __base__=BoardTrigger, __module__=__name__,
        operation=(Literal[name], Field(name, title=name.replace("_", " ").title(),
            json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
                "x-display-name": name.replace("_", " ").title()})))
    CONFIG_MODELS[name] = model
    globals()[model.__name__] = model

BusinessmapConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class BusinessmapNodeConfig(NodeConfig[BusinessmapConfig, BusinessmapAPIKeyCredential]):
    pass


class BusinessmapNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-businessmap"
    connection_evidence = ConnectionEvidence(field="board_id", noun="boards", identity_operation="get_current_user",
        identity_keys=("username", "email", "realname"))
    edit_examples = ["Create a Businessmap card", "Move a card to another column", "Watch for new Businessmap comments"]

    @classmethod
    def get_config_model(cls):
        return BusinessmapNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        credential = BusinessmapAPIKeyCredential.model_validate(credential)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.account_url + "/api/v2" + path,
                params=params, json=body, headers={"apikey": credential.api_key, "Accept": "application/json"})
        if response.is_error:
            # Keep the provider's rejection words so manual connection can show them.
            try:
                detail = response.json().get("error", {}).get("message", "Request rejected")
            except (ValueError, AttributeError):
                detail = "Request rejected"
            raise ValueError(f"Businessmap HTTP {response.status_code}: {str(detail).replace(credential.api_key, '[redacted]')}")
        if response.status_code == 204:
            return {"deleted": True}
        data = response.json()
        if not isinstance(data, dict) or "data" not in data or "error" in data:
            raise ValueError("Businessmap returned an unexpected response envelope")
        return data

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "board_id":
            raise ValueError("Unknown Businessmap lookup field")
        data = await cls._request(credential_data, "GET", "/boards")
        return {"options": [{"value": str(row["board_id"]), "label": row["name"]}
            for row in data["data"] if not search or search.casefold() in row["name"].casefold()],
            "next_page_token": None}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"board_id": (config or {}).get("board_id")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        board_id = BoardTrigger.model_validate(config).board_id
        result = await cls._request(credential, "POST", "/webhooks",
            body={"url": webhook_url, "board_id": board_id, "is_enabled": 1})
        endpoint = result["data"]
        if not endpoint.get("webhook_id") or not endpoint.get("secret"):
            raise ValueError("Businessmap did not return the webhook ID and secret")
        return {"external_webhook_id": str(endpoint["webhook_id"]), "signing_secret": endpoint["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        endpoint = (config or {}).get("external_webhook_id")
        if endpoint is None:
            return
        if not re.fullmatch(r"[1-9][0-9]*", str(endpoint)):
            raise ValueError("Invalid Businessmap webhook ID")
        await cls._request(credential, "DELETE", f"/webhooks/{endpoint}")

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        secret = (config or {}).get("signing_secret")
        supplied = next((v for k, v in headers.items() if k.lower() == "x-kanbanize-secret"), None)
        return bool(isinstance(secret, str) and secret and isinstance(supplied, str)
                    and hmac.compare_digest(secret.encode(), supplied.encode()))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return (payload.get("event") == TRIGGER_EVENTS.get(config.get("operation"))
                and str(payload.get("board_id")) == str(config.get("board_id")))

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if not cls.filter_trigger_payload(payload, config):
            return None
        # Only documented event fields; secret headers and internal transport metadata stay out of outputs.
        fields = ["company", "event", "board_id", "card_id", "user_id"]
        if config.get("operation") == "on_comment_created":
            fields.append("comment_id")
        if config.get("operation") == "on_subtask_created":
            fields.append("subtask_id")
        return {key: payload[key] for key in fields}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event") not in TRIGGER_EVENTS.values():
            return None
        text = (f"Businessmap {output['company']}: {output['event']} by user {output['user_id']} "
                f"on board {output['board_id']}, card {output['card_id']}.")
        for field in ("comment_id", "subtask_id"):
            if field in output:
                text += f" {field}={output[field]}."
        text += f" Read get_card or list_comments/list_subtasks with card_id={output['card_id']} for the content."
        return {"text": text, "conversation_key": f"{output['company']}:{output['board_id']}:{output['card_id']}"}

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Businessmap account")
        config = self.config.config
        if config.operation in TRIGGER_EVENTS:
            payload = (self.node_data.get("config") or {}).get("_triggerPayload") or inputs
            return self.resolve_trigger_payload(payload, config.model_dump()) or {"status": "no_event"}
        op = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = op.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", str(value))
        return await self._request(self.config.credentials, op.method, path,
            params={key: values[key] for key in op.query if key in values} or None,
            body={key: values[key] for key in op.body if key in values} if op.body else None)

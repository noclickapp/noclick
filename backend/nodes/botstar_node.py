"""BotStar public API: bots, audience attributes, CMS items and messages.

Contract: https://apis.botstar.com/docs/public-api.yaml (1.0.0).
The official Swagger page replaces its stale staging server with its own
origin + /v1: https://apis.botstar.com/docs/ (updateJsonSpec).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://apis.botstar.com/v1"


class BotstarAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Botstar API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.botstar.com/account/profile",
            "x-credential-instructions": "In BotStar, open Account > Profile and copy your API Token. Paste only the token. NoClick checks it by reading your bots. See https://apis.botstar.com/docs/."})
    credential_type: Literal["botstar_api_token"] = Field("botstar_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, title="API Token", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            if value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
                raise ValueError("Paste a single BotStar resource ID")
        return value


class _Bot(_Input):
    bot_id: str = Field(..., min_length=1, title="Bot ID", description="Copy the ID from Bot Builder or List Bots.")


class _ReadEnvironment(_Bot):
    env: Literal["draft", "live"] | None = Field(None, title="Bot Environment", description="Omit to use BotStar's default.")


class _WriteEnvironment(_Bot):
    env: Literal["draft", "draft,live"] | None = Field(None, title="Bot Environment", description="Omit to use BotStar's default; draft,live applies to both environments.")


class BotstarListBotsConfig(_Input):
    """List the bots accessible to the connected account."""
    operation: Literal["list_bots"] = Field("list_bots", json_schema_extra={"ui:hidden": True})


class BotstarCreateBotConfig(_Input):
    """Create a new bot with a name."""
    operation: Literal["create_bot"] = Field("create_bot", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=250)


class BotstarGetBotConfig(_Bot):
    """Get a bot by ID."""
    operation: Literal["get_bot"] = Field("get_bot", json_schema_extra={"ui:hidden": True})


class BotstarPublishBotConfig(_Bot):
    """Publish the selected bot's changes to live production."""
    operation: Literal["publish_bot"] = Field("publish_bot", json_schema_extra={"ui:hidden": True})


class BotstarListBotAttributesConfig(_ReadEnvironment):
    """List the selected bot's attributes."""
    operation: Literal["list_bot_attributes"] = Field("list_bot_attributes", json_schema_extra={"ui:hidden": True})


class BotstarDeleteBotAttributeConfig(_WriteEnvironment):
    """Delete an attribute from the selected bot environment."""
    operation: Literal["delete_bot_attribute"] = Field("delete_bot_attribute", json_schema_extra={"ui:hidden": True})
    attribute_id: str = Field(..., min_length=1)


class _User(_Bot):
    user_id: str = Field(..., min_length=1, description="Audience user ID shown in Report & Insight > Audience.")


class BotstarGetUserConfig(_User):
    """Get an audience user's profile and attributes."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})


class BotstarUpdateUserConfig(_User):
    """Update the supplied audience profile fields, leaving omitted fields unchanged."""
    operation: Literal["update_user"] = Field("update_user", json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None, min_length=1)
    last_name: str | None = Field(None, min_length=1)
    email: str | None = Field(None, json_schema_extra={"format": "email"})
    gender: Literal["male", "female", ""] | None = None
    birthday: str | None = Field(None, description="YYYY-MM-DD", json_schema_extra={"format": "date"})

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, key) is None for key in ("first_name", "last_name", "email", "gender", "birthday")):
            raise ValueError("Supply at least one profile field to update")
        return self


class BotstarCreateUserAttributeConfig(_Bot):
    """Create a custom audience attribute definition."""
    operation: Literal["create_user_attribute"] = Field("create_user_attribute", json_schema_extra={"ui:hidden": True})
    field_name: str = Field(..., min_length=1)
    field_type: Literal["string", "number", "date", "boolean"] = "string"


class BotstarListEntitiesConfig(_ReadEnvironment):
    """List the selected bot's CMS entities."""
    operation: Literal["list_entities"] = Field("list_entities", json_schema_extra={"ui:hidden": True})


class BotstarGetEntityConfig(_ReadEnvironment):
    """Get a CMS entity and its field definitions."""
    operation: Literal["get_entity"] = Field("get_entity", json_schema_extra={"ui:hidden": True})
    entity_id: str = Field(..., min_length=1)


class _EntityWrite(_WriteEnvironment):
    entity_id: str = Field(..., min_length=1)


class BotstarUpdateEntityConfig(_EntityWrite):
    """Rename a CMS entity."""
    operation: Literal["update_entity"] = Field("update_entity", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)


class BotstarDeleteEntityConfig(_EntityWrite):
    """Delete the selected CMS entity."""
    operation: Literal["delete_entity"] = Field("delete_entity", json_schema_extra={"ui:hidden": True})


class BotstarListEntityItemsConfig(_ReadEnvironment):
    """Read one page of CMS items, optionally filtered by name and status."""
    operation: Literal["list_entity_items"] = Field("list_entity_items", json_schema_extra={"ui:hidden": True})
    entity_id: str = Field(..., min_length=1)
    page: int = Field(1, ge=1)
    limit: int = Field(100, ge=1)
    name: str | None = Field(None, min_length=1)
    status: Literal["enabled", "disabled"] | None = None


class BotstarGetEntityItemConfig(_ReadEnvironment):
    """Get a single CMS item."""
    operation: Literal["get_entity_item"] = Field("get_entity_item", json_schema_extra={"ui:hidden": True})
    entity_id: str = Field(..., min_length=1)
    entity_item_id: str = Field(..., min_length=1)


class _ItemFields(_EntityWrite):
    custom_fields: dict[str, str | list[str]] = Field(default_factory=dict,
        description="CMS values keyed by each field's unique_name, for example color: [red, yellow] and price: $10.")

    @field_validator("custom_fields")
    @classmethod
    def no_reserved(cls, value):
        if set(value) & {"name", "status", "id", "entity_id"}:
            raise ValueError("Use the named fields for item name and status; IDs cannot be overwritten")
        return value


class BotstarCreateEntityItemConfig(_ItemFields):
    """Create a CMS item with values for the entity's custom fields."""
    operation: Literal["create_entity_item"] = Field("create_entity_item", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    status: Literal["enabled", "disabled"] | None = None


class BotstarUpdateEntityItemConfig(_ItemFields):
    """Update the supplied CMS item fields."""
    operation: Literal["update_entity_item"] = Field("update_entity_item", json_schema_extra={"ui:hidden": True})
    entity_item_id: str = Field(..., min_length=1)
    name: str | None = Field(None, min_length=1)
    status: Literal["enabled", "disabled"] | None = None

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.status is None and not self.custom_fields:
            raise ValueError("Supply at least one item field to update")
        return self


class BotstarDeleteEntityItemConfig(_EntityWrite):
    """Delete the selected CMS item."""
    operation: Literal["delete_entity_item"] = Field("delete_entity_item", json_schema_extra={"ui:hidden": True})
    entity_item_id: str = Field(..., min_length=1)


class BotstarSendMessageConfig(_Input):
    """Send a text message to a Facebook audience recipient, subject to Meta's messaging rules."""
    operation: Literal["send_message"] = Field("send_message", json_schema_extra={"ui:hidden": True})
    recipient_id: str = Field(..., min_length=1, description="Facebook audience recipient ID.")
    text: str = Field(..., min_length=1, title="Message Text")
    message_tag: Literal["CONFIRMED_EVENT_UPDATE", "POST_PURCHASE_UPDATE", "ACCOUNT_UPDATE"] | None = None


BotstarConfig = Annotated[Union[
    BotstarListBotsConfig, BotstarCreateBotConfig, BotstarGetBotConfig, BotstarPublishBotConfig,
    BotstarListBotAttributesConfig, BotstarDeleteBotAttributeConfig, BotstarGetUserConfig,
    BotstarUpdateUserConfig, BotstarCreateUserAttributeConfig, BotstarListEntitiesConfig,
    BotstarGetEntityConfig, BotstarUpdateEntityConfig, BotstarDeleteEntityConfig,
    BotstarListEntityItemsConfig, BotstarGetEntityItemConfig, BotstarCreateEntityItemConfig,
    BotstarUpdateEntityItemConfig, BotstarDeleteEntityItemConfig, BotstarSendMessageConfig,
], Field(discriminator="operation")]


class BotstarFullConfig(NodeConfig[BotstarConfig, BotstarAPITokenCredential]):
    pass


# Each public operation makes exactly one request to one published endpoint.
ROUTES = {
    "list_bots": ("GET", "/bots/"),
    "create_bot": ("POST", "/bots/"),
    "get_bot": ("GET", "/bots/{bot_id}"),
    "publish_bot": ("POST", "/bots/{bot_id}/publish"),
    "list_bot_attributes": ("GET", "/bots/{bot_id}/attributes"),
    "delete_bot_attribute": ("DELETE", "/bots/{bot_id}/attributes/{attribute_id}"),
    "get_user": ("GET", "/bots/{bot_id}/users/{user_id}"),
    "update_user": ("PATCH", "/bots/{bot_id}/users/{user_id}"),
    "create_user_attribute": ("POST", "/bots/{bot_id}/users/attributes"),
    "list_entities": ("GET", "/bots/{bot_id}/cms_entities"),
    "get_entity": ("GET", "/bots/{bot_id}/cms_entities/{entity_id}"),
    "update_entity": ("PATCH", "/bots/{bot_id}/cms_entities/{entity_id}"),
    "delete_entity": ("DELETE", "/bots/{bot_id}/cms_entities/{entity_id}"),
    "list_entity_items": ("GET", "/bots/{bot_id}/cms_entities/{entity_id}/items"),
    "get_entity_item": ("GET", "/bots/{bot_id}/cms_entities/{entity_id}/items/{entity_item_id}"),
    "create_entity_item": ("POST", "/bots/{bot_id}/cms_entities/{entity_id}/items"),
    "update_entity_item": ("PATCH", "/bots/{bot_id}/cms_entities/{entity_id}/items/{entity_item_id}"),
    "delete_entity_item": ("DELETE", "/bots/{bot_id}/cms_entities/{entity_id}/items/{entity_item_id}"),
    "send_message": ("POST", "/messages"),
}


class BotstarNode(WorkflowNode):
    integration_type = "automation-botstar"
    connection_evidence = ConnectionEvidence(noun="bots", operation="list_bots")

    @classmethod
    def get_config_model(cls):
        return BotstarFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a BotStar API token")
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        operation = values.pop("operation")
        method, template = ROUTES[operation]
        path = template.format(**{k: quote(v, safe="") for k, v in values.items() if k.endswith("_id")})
        params = {k: values[k] for k in ("env", "page", "limit") if k in values}
        if operation == "list_entity_items":
            params.update({k: values[k] for k in ("name", "status") if k in values})
        body = None
        if operation == "send_message":
            body = {"recipient": {"id": config.recipient_id}, "message": {"text": config.text}}
            if config.message_tag is not None:
                body["options"] = {"message_tag": config.message_tag}
        elif method in {"POST", "PATCH"} and operation != "publish_bot":
            body = {k: v for k, v in values.items() if not k.endswith("_id") and k != "env" and k != "custom_fields"}
            body.update(values.get("custom_fields", {}))
        kwargs = {"params": params, "headers": {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}}
        if body is not None:
            kwargs["json"] = body
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, **kwargs)
        expected = 201 if operation in {"create_user_attribute", "create_entity_item"} else 200
        if response.status_code != expected:
            # Preserve provider rejection text for manual connection evidence,
            # while refusing to reflect the supplied token back into the result.
            message = "BotStar request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("error") or message)
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                "error": message.replace(credential.api_token, "[redacted]")[:2000]}
        if operation == "delete_bot_attribute" and not response.content:
            return {"status": "success", "http_status": response.status_code, "data": None}
        if len(response.content) > 10_000_000:
            raise ValueError("BotStar response exceeds the supported size")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("BotStar returned an invalid JSON response") from None
        if isinstance(data, dict) and (data.get("error") or data.get("status") in {"error", "failed"}):
            return {"status": "error", "error": str(data.get("message") or data.get("error") or "BotStar returned an error").replace(credential.api_token, "[redacted]")[:2000]}
        list_operation = operation in {"list_bots", "list_bot_attributes", "list_entities", "list_entity_items"}
        if not isinstance(data, list if list_operation else dict):
            raise ValueError("BotStar returned an unexpected response shape")
        result = {"status": "success", "data": data, "http_status": response.status_code}
        if operation == "list_entity_items":
            result.update(page=config.page, limit=config.limit,
                next_page=config.page + 1 if len(data) == config.limit else None)
        return result

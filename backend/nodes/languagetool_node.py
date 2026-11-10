"""LanguageTool's five published v2 operations (OpenAPI 1.1.2).

Uses the authenticated API host, not the public proofreading service, whose
terms prohibit automated requests. No undocumented editor APIs are used.
"""
from typing import Annotated, Literal, Union
import json

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

BASE_URL = "https://api.languagetoolplus.com/v2"


class LanguageToolAPIKey(BaseModel):
    model_config = ConfigDict(
        title="LanguageTool API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://languagetool.org/editor/settings/access-tokens",
            "x-credential-instructions": "Enter your LanguageTool username (email) and API key from Settings → Access tokens. Use an API plan that permits automation. NoClick reads your personal dictionary to verify the connection.",
        },
    )
    credential_type: Literal["languagetool_api_key"] = Field("languagetool_api_key", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, title="Username / Email")
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckTextConfig(_Config):
    """Find grammar, spelling and style issues, including markup-aware text."""
    operation: Literal["check_text"] = Field("check_text", json_schema_extra={"ui:hidden": True})
    text: str | None = Field(None, description="Text to check. Supply either text or annotated data.", json_schema_extra={"ui:widget": "textarea"})
    data: str | None = Field(None, description='Annotated JSON string, e.g. {"annotation":[{"text":"A "},{"markup":"<b>"},{"text":"test"},{"markup":"</b>"}]}. Markup is ignored.')
    language: str = Field("auto", description="Language code, e.g. en-US, de-DE, fr, or auto. Specify a variant for spell checking.")
    dicts: str | None = Field(None, description="Comma-separated dictionary names; omit for the default dictionary.")
    mother_tongue: str | None = Field(None, description="Native language code for false-friend checks.")
    preferred_variants: str | None = Field(None, description="Comma-separated variants for auto detection, e.g. en-GB,de-AT.")
    enabled_rules: str | None = Field(None, description="Comma-separated rule IDs to enable.")
    disabled_rules: str | None = Field(None, description="Comma-separated rule IDs to disable.")
    enabled_categories: str | None = Field(None, description="Comma-separated category IDs to enable.")
    disabled_categories: str | None = Field(None, description="Comma-separated category IDs to disable.")
    enabled_only: bool | None = Field(None, description="Run only the explicitly enabled rules/categories.")
    level: Literal["default", "picky"] | None = Field(None, description="Picky activates additional formal-writing checks.")

    @model_validator(mode="after")
    def text_or_data(self):
        if bool(self.text) == bool(self.data):
            raise ValueError("Supply either text or annotated data")
        if self.data:
            try:
                value = json.loads(self.data)
            except (ValueError, TypeError):
                raise ValueError("Annotated data must be a JSON document") from None
            if not isinstance(value, dict) or not isinstance(value.get("annotation"), list):
                raise ValueError("Annotated data must contain an annotation array")
        return self


class ListLanguagesConfig(_Config):
    """List supported languages and regional language codes."""
    operation: Literal["list_languages"] = Field("list_languages", json_schema_extra={"ui:hidden": True})


class ListWordsConfig(_Config):
    """Read one page of words from your personal dictionaries."""
    operation: Literal["list_words"] = Field("list_words", json_schema_extra={"ui:hidden": True})
    offset: int = Field(0, ge=0, description="Zero-based offset; increment by the returned word count for the next page.")
    limit: int = Field(10, ge=1, description="Maximum words to return in this page.")
    dicts: str | None = Field(None, description="Comma-separated dictionaries; omit for the default dictionary.")


class _WordConfig(_Config):
    word: str = Field(..., min_length=1, description="One word in your personal dictionary, not a phrase.")
    dictionary: str | None = Field(None, description="Dictionary name; omit to use the default dictionary.")

    @field_validator("word")
    @classmethod
    def single_word(cls, value):
        if any(c.isspace() for c in value):
            raise ValueError("Use one word without whitespace")
        return value


class AddWordConfig(_WordConfig):
    """Add a word; named dictionaries are created if needed (500-word limit)."""
    operation: Literal["add_word"] = Field("add_word", json_schema_extra={"ui:hidden": True})


class DeleteWordConfig(_WordConfig):
    """Remove a word; an emptied named dictionary is deleted by LanguageTool."""
    operation: Literal["delete_word"] = Field("delete_word", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[CheckTextConfig, ListLanguagesConfig, ListWordsConfig, AddWordConfig, DeleteWordConfig], Field(discriminator="operation")]


class LanguageToolNodeConfig(NodeConfig[Operation, LanguageToolAPIKey]):
    model_config = ConfigDict(title="LanguageTool Node Configuration")


class LanguageToolNode(WorkflowNode):
    integration_type = "automation-languagetool"
    connection_evidence = ConnectionEvidence(operation="list_words", noun="personal dictionary words")

    @classmethod
    def get_config_model(cls):
        return LanguageToolNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a LanguageTool API key")
        config = self.config.config
        credential = self.config.credentials
        operation = config.operation
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        if operation == "list_languages":
            method, path = "GET", "/languages"
        else:
            values.update(username=credential.username, apiKey=credential.api_key)
            if operation == "list_words":
                method, path = "GET", "/words"
            elif operation == "check_text":
                method, path = "POST", "/check"
                names = {
                    "mother_tongue": "motherTongue", "preferred_variants": "preferredVariants",
                    "enabled_rules": "enabledRules", "disabled_rules": "disabledRules",
                    "enabled_categories": "enabledCategories", "disabled_categories": "disabledCategories",
                    "enabled_only": "enabledOnly",
                }
                values = {names.get(k, k): v for k, v in values.items()}
                if "enabledOnly" in values:
                    values["enabledOnly"] = str(values["enabledOnly"]).lower()
            else:
                method, path = "POST", "/words/add" if operation == "add_word" else "/words/delete"
                if "dictionary" in values:
                    values["dict"] = values.pop("dictionary")
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, headers={"Accept": "application/json"},
                                                **({"params": values} if method == "GET" else {"data": values}))
        except httpx.HTTPError:
            raise ValueError("LanguageTool request could not be completed") from None
        if not response.is_success:
            # Keep the provider's rejection useful to connect without exposing its
            # echoed query credentials or httpx's URL-bearing exception text.
            message = response.text.replace(credential.api_key, "[redacted]").replace(credential.username, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": message[:2000] or "LanguageTool rejected the request"}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("LanguageTool returned an invalid JSON response") from None
        if operation == "list_languages":
            if not isinstance(body, list) or any(not isinstance(x, dict) or not all(isinstance(x.get(k), str) for k in ("name", "code", "longCode")) for x in body):
                raise ValueError("LanguageTool returned an invalid language list")
            return {"languages": body}
        if not isinstance(body, dict):
            raise ValueError("LanguageTool returned an invalid response")
        if operation == "list_words" and (not isinstance(body.get("words"), list) or any(not isinstance(x, str) for x in body["words"])):
            raise ValueError("LanguageTool returned an invalid word list")
        if operation == "check_text" and not isinstance(body.get("matches"), list):
            raise ValueError("LanguageTool returned an invalid text check")
        key = {"add_word": "added", "delete_word": "deleted"}.get(operation)
        if key and not isinstance(body.get(key), bool):
            raise ValueError("LanguageTool did not confirm the dictionary change")
        return body

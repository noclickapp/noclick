"""Registry API: manage API descriptions in the published Google-hosted registry.

Contract: https://github.com/apigee/registry/blob/main/openapi.yaml (0.0.1).
Authentication: https://github.com/apigee/registry/blob/main/auth/HOSTED.sh
Bearer header: https://docs.cloud.google.com/docs/authentication/rest
Paste a Google access token; tokens expire and must be replaced by the person.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.apigee_operations import OPERATIONS
from utils.ssrf import guarded_async_client

BASE_URL = "https://apigeeregistry.googleapis.com"
Segment = Annotated[str, Field(max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.~-]*$")]
ResourceId = Annotated[str, Field(min_length=4, max_length=63, pattern=r"^[a-z][a-z0-9-]{3,62}$")]


class ApigeeTokenCredential(BaseModel):
    model_config = ConfigDict(title="Registry API Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-instructions": "Paste a Google Cloud access token with cloud-platform scope and Registry permissions on your project. Enter the project ID and location (usually global). Access tokens expire; replace an expired token here. NoClick reads your project's APIs to check the connection.",
            "x-credential-url": "https://cloud.google.com/docs/authentication/rest"})
    credential_type: Literal["apigee_access_token"] = Field("apigee_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, json_schema_extra={"ui:widget": "password"})
    project: Segment = Field(..., title="Google Cloud project ID")
    location: Segment = Field("global", title="Location")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _snake(value):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _make_config(name, spec):
    fields = {"operation": (Literal[name], Field(name, title=name.replace('_', ' ').title(),
        json_schema_extra={"ui:hidden": True, "x-method-kind": "read" if spec["method"] == "GET" else "write"}))}
    for param in re.findall(r"\{(\w+)\}", spec["path"]):
        if param not in {"project", "location"}:
            fields[param + "_id"] = (Segment, Field(..., title=param.title() + " ID"))
    for key, description in spec["query"]:
        field = _snake(key)
        if key.endswith("Id"):
            fields[field] = (ResourceId, Field(..., description=description))
        elif key == "pageSize":
            fields[field] = (int, Field(100, ge=1, le=1000, description=description))
        elif key in {"force", "allowMissing"}:
            fields[field] = (bool, Field(False, description=description))
        elif key == "updateMask":
            # Derive the mask from explicitly supplied mutable fields.
            continue
        else:
            fields[field] = (Optional[str], Field(None, description=description))
    for key, wire in spec["body"].items():
        if wire in {"labels", "annotations"}:
            fields[key] = (Optional[dict[str, str]], Field(None))
        else:
            fields[key] = (Optional[str], Field(None, description="Base64 encoded specification contents" if wire == "contents" else wire))
    return create_model("Apigee" + ''.join(x.title() for x in name.split('_')) + "Config", __base__=_Operation, **fields)


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class ApigeeOnApiUpdatedConfig(PollTriggerConfigBase):
    operation: Literal["on_api_updated"] = Field("on_api_updated", title="On New or Updated API",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated API"})
    filter: Optional[str] = Field(None, description="CEL filter on API fields, including createTime and updateTime. Polls all matching pages; baseline does not emit existing APIs.")


ApigeeConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ApigeeOnApiUpdatedConfig,)], Field(discriminator="operation")]


class ApigeeNodeConfig(NodeConfig[ApigeeConfig, ApigeeTokenCredential]):
    pass


class ApigeeNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-apigee"
    connection_evidence = ConnectionEvidence(operation="list_apis", noun="APIs", label_keys=("displayName", "name"))

    @classmethod
    def get_config_model(cls):
        return ApigeeNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_api_count")) if config.get("operation") == "on_api_updated" else True

    @classmethod
    def resolve_agent_event(cls, output):
        apis = output.get("apis", []) if isinstance(output, dict) else []
        if not apis:
            return None
        lines = ["Registry API: new or updated API descriptions"]
        for api in apis[:50]:
            name = api.get("name", "")
            lines.append(f"API: {api.get('displayName') or name}\nResource: {name}\nUpdated: {api.get('updateTime', '')}")
            if api.get("description"):
                lines.append(str(api["description"])[:1500])
            if name:
                lines.append(f"To act: get_api api_id={name.rsplit('/', 1)[-1]}; use the resource's project and location connection.")
        return {"text": "\n\n".join(lines), "title": "Registry API updates"}

    @classmethod
    async def _request(cls, credential, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=30.0) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.is_error:
            try:
                message = response.json().get("error", {}).get("message", "Registry request failed")
            except (ValueError, AttributeError):
                message = "Registry request failed"
            raise ValueError(f"Registry API {response.status_code}: {str(message).replace(credential.access_token, '[redacted]')}")
        return response.json() if response.content else {}

    @classmethod
    async def _perform(cls, credential, config):
        spec = OPERATIONS[config.operation]
        path = spec["path"]
        for name in re.findall(r"\{(\w+)\}", path):
            value = getattr(credential, name) if name in {"project", "location"} else getattr(config, name + "_id")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        params = {}
        for wire, _ in spec["query"]:
            if wire == "updateMask":
                continue
            value = getattr(config, _snake(wire))
            if value is not None:
                params[wire] = str(value).lower() if isinstance(value, bool) else value
        body = {wire: getattr(config, key) for key, wire in spec["body"].items() if getattr(config, key) is not None}
        if spec["method"] == "PATCH":
            if not body:
                raise ValueError("Provide at least one field to update")
            params["updateMask"] = ",".join(body)
            body["name"] = path.removeprefix("/v1/")
        return await cls._request(credential, spec["method"], path, params=params,
            body=body if spec["body"] else None)

    async def execute(self, inputs):
        if not isinstance(self.config, ApigeeNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Registry API access token")
        credential, config = self.config.credentials, self.config.config
        if isinstance(config, ApigeeOnApiUpdatedConfig):
            items, page_token, seen_tokens = [], None, set()
            for _ in range(100):
                page = await self._perform(credential, CONFIG_MODELS["list_apis"](filter=config.filter, page_token=page_token))
                rows = page.get("apis", [])
                if not isinstance(rows, list):
                    raise ValueError("Registry API list response must contain an APIs array")
                items.extend(rows)
                page_token = page.get("nextPageToken")
                if not page_token:
                    break
                if page_token in seen_tokens:
                    raise ValueError("Registry API returned a repeated page token")
                seen_tokens.add(page_token)
            else:
                raise ValueError("Registry API poll exceeds 100 pages; narrow the filter")
            # Api.name and Api.updateTime are both in the published response schema.
            fresh = await self._filter_unseen(items, lambda api: json.dumps([api["name"], api["updateTime"]]) if api.get("name") and api.get("updateTime") else None)
            return {"apis": fresh, "new_api_count": len(fresh)}
        data = await self._perform(credential, config)
        # Keep the provider's JSON envelope, including nextPageToken, unchanged.
        await self.emit(data)
        return data

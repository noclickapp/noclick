"""Bonsai account records through the provider's public v1 API."""
from typing import Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.bonsai_operations import BonsaiOperation, ROUTES
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://app.hellobonsai.com"


class BonsaiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bonsai API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-instructions": "Create an API key in your Bonsai settings, then paste it here. The key acts with your Bonsai member's permissions.",
        "x-credential-url": "https://app.hellobonsai.com/settings",
    })
    credential_type: Literal["bonsai_api_key"] = "bonsai_api_key"
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value)
        if len(value) > 4096 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the Bonsai API key without the Bearer prefix")
        return value


# Bonsai's own MCP server: agents get its tools through a person's Bonsai sign-in.
BonsaiMcpCredential = mcp_credential("bonsai", "https://mcp.hellobonsai.com/mcp", app="Bonsai")
BonsaiCredential = Union[BonsaiAPIKeyCredential, BonsaiMcpCredential]


class BonsaiFullConfig(NodeConfig[BonsaiOperation, BonsaiCredential]):
    pass


class BonsaiNode(WorkflowNode):
    integration_type = "automation-bonsai"
    credential_provider_labels = {"bonsai": "Bonsai Account"}
    connection_evidence = ConnectionEvidence(noun="companies", operation="list_companies", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return BonsaiFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Bonsai API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json")
        path = route["path"]
        for name, parameter in route["path_fields"].items():
            path = path.replace("{" + parameter + "}", quote(str(values[name]), safe=""))
        params = {target: values[name] for name, target in route["params"].items() if values[name] is not None}
        kwargs = {"params": params}
        if route["wrapper"]:
            # Unset fields stay absent. Only nullable provider fields can send null.
            attributes = {name: values[name] for name in route["body_fields"]
                          if name in config.model_fields_set and (values[name] is not None or name in route["nullable"])}
            if route["method"] == "PATCH" and not attributes:
                raise ValueError("Supply at least one field to update")
            kwargs["json"] = {route["wrapper"]: attributes}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], BASE + path,
                    headers={"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"}, **kwargs)
            if response.status_code not in {200, 201}:
                error = "Bonsai request failed"
                try:
                    message = response.json().get("error", {}).get("message")
                    if isinstance(message, str):
                        error = message.replace(self.config.credentials.api_key, "[redacted]")[:1000]
                except (ValueError, AttributeError):
                    pass
                return {"status": "error", "http_status": response.status_code, "error": error}
            body = response.json()
            if not isinstance(body, dict) or "error" in body or "data" not in body or not isinstance(body.get("meta"), dict):
                raise ValueError("Bonsai returned an incomplete response envelope")
            if not isinstance(body["meta"].get("request_id"), str):
                raise ValueError("Bonsai response is missing its request identifier")
            result = {"status": "success", "data": body["data"], "meta": body["meta"]}
            if config.operation.startswith("list_"):
                if not isinstance(body["data"], list) or any(not isinstance(row, dict) for row in body["data"]):
                    raise ValueError("Bonsai list response must contain records")
                page = body["meta"].get("pagination")
                if not isinstance(page, dict) or type(page.get("page")) is not int or type(page.get("page_size")) is not int or type(page.get("has_more")) is not bool:
                    raise ValueError("Bonsai pagination is incomplete")
                if page["page"] != values["page"] or not 1 <= page["page_size"] <= 100:
                    raise ValueError("Bonsai pagination does not match the requested page")
                result.update(has_more=page["has_more"], next_page=page["page"] + 1 if page["has_more"] else None)
            elif not isinstance(body["data"], dict):
                raise ValueError("Bonsai response must contain a record")
            return result
        except (httpx.HTTPError, ValueError, SSRFError):
            return {"status": "error", "error": "Bonsai did not return a valid response; inspect the record before retrying a write"}

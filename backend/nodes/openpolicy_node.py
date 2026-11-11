"""Open Policy Agent REST API, pinned to the provider's OpenAPI 0.28.0.

Bearer authentication: https://www.openpolicyagent.org/docs/security
Routes and semantics: https://www.openpolicyagent.org/docs/rest-api
The v0 webhook route is a synchronous decision API, not an event subscription.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_https_origin


class OpenPolicyTokenCredential(BaseModel):
    model_config = ConfigDict(title="Open Policy Agent Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.openpolicyagent.org/docs/security#authentication-and-authorization",
            "x-credential-instructions": "Enter your OPA instance's HTTPS origin and paste a bearer token accepted by its authorization policy. The instance must enable --authentication=token and authorize the APIs you use. NoClick lists loaded policies to check the connection; OPA has no user profile API.",
        })
    credential_type: Literal["openpolicy_token"] = Field("openpolicy_token", json_schema_extra={"ui:hidden": True})
    base_url: str = Field(..., title="Instance URL", description="Exact HTTPS origin, including the port if needed; for example https://opa.example.com:8181.")
    api_token: str = Field(..., title="Bearer token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("base_url")
    @classmethod
    def origin(cls, value):
        return normalize_https_origin(value, field_name="Instance URL")

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Bearer token")
        if any(c.isspace() for c in value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the bearer token without a header or whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Policy(_Operation):
    policy_id: str = Field(..., min_length=1, max_length=1024, description="Policy module identifier, for example authz.rego.")

    @field_validator("policy_id")
    @classmethod
    def identifier(cls, value):
        return _path(value)


def _path(value):
    if any(p in {"", ".", ".."} for p in value.split("/")) or any(ord(c) < 32 for c in value) or "\\" in value:
        raise ValueError("Use nonempty slash-separated document segments without dot segments or control characters")
    return value


class _Document(_Operation):
    path: str = Field(..., min_length=1, max_length=2048, description="Slash-separated document path without a leading slash, for example opa/examples/allow_request.")
    _validate_path = field_validator("path")(_path)


class _Metrics(_Operation):
    metrics: bool = Field(False, description="Include evaluation performance metrics.")


class ListPolicies(_Operation):
    """List all loaded policy modules (also the connection proof)."""
    operation: Literal["list_policies"] = "list_policies"


class GetPolicy(_Policy):
    """Read a policy module and its AST."""
    operation: Literal["get_policy"] = "get_policy"


class PutPolicy(_Policy, _Metrics):
    """Create or replace a Rego policy module."""
    operation: Literal["put_policy"] = "put_policy"
    policy: str = Field(..., min_length=1, description="Complete Rego source supported by your OPA instance.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "rego"})


class DeletePolicy(_Policy):
    """Delete a loaded policy module."""
    operation: Literal["delete_policy"] = "delete_policy"


class GetDocument(_Document, _Metrics):
    """Read a base or virtual document without input."""
    operation: Literal["get_document"] = "get_document"
    provenance: bool = False


class EvaluateDocument(_Document, _Metrics):
    """Evaluate a decision with input wrapped in the v1 input envelope."""
    operation: Literal["evaluate_document"] = "evaluate_document"
    input: dict[str, Any] = Field(..., description="Decision input; NoClick wraps this as {input: ...}.")
    provenance: bool = False


class EvaluateWebhookDocument(_Document):
    """Evaluate the v0 decision endpoint with an unwrapped input document."""
    operation: Literal["evaluate_webhook_document"] = "evaluate_webhook_document"
    input: dict[str, Any] = Field(..., description="Raw input document sent directly to the v0 decision endpoint.")


class PutDocument(_Document):
    """Create or replace base data at a document path."""
    operation: Literal["put_document"] = "put_document"
    document: Any = Field(..., description="JSON document to store, including objects, arrays and scalar values.")
    create_only: bool = Field(False, description="Send If-None-Match: * to prevent overwriting existing data.")


class JSONPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    op: Literal["add", "remove", "replace", "move", "copy", "test"]
    path: str = Field(..., min_length=1, description="JSON pointer relative to the API document path.")
    value: Any = None
    from_path: str | None = Field(None, alias="from", description="Source JSON pointer for move or copy.")

    @model_validator(mode="after")
    def required_members(self):
        if self.op in {"add", "replace", "test"} and "value" not in self.model_fields_set:
            raise ValueError("This patch operation requires value (JSON null is allowed)")
        if self.op in {"move", "copy"} and not self.from_path:
            raise ValueError("This patch operation requires from")
        return self


class PatchDocument(_Document):
    """Apply an atomic JSON Patch to base data."""
    operation: Literal["patch_document"] = "patch_document"
    patches: list[JSONPatch] = Field(..., min_length=1)


class DeleteDocument(_Document):
    """Delete base data at a document path."""
    operation: Literal["delete_document"] = "delete_document"


class SimpleQuery(_Operation):
    """Evaluate the instance's default decision using a raw input object."""
    operation: Literal["simple_query"] = "simple_query"
    input: dict[str, Any] = Field(..., description="Input object for the configured default decision.")


class GetQuery(_Metrics):
    """Execute an ad hoc Rego query using GET."""
    operation: Literal["get_query"] = "get_query"
    query: str = Field(..., min_length=1, description="Rego query, for example data.servers[i].name = name.")


class PostQuery(_Metrics):
    """Execute a complex ad hoc Rego query using POST."""
    operation: Literal["post_query"] = "post_query"
    query: str = Field(..., min_length=1)


class CompileQuery(_Metrics):
    """Partially evaluate a query with specified unknowns."""
    operation: Literal["compile_query"] = "compile_query"
    query: str = Field(..., min_length=1)
    input: dict[str, Any] | None = None
    unknowns: list[str] | None = Field(None, description="Unknown references, for example [data.reports].")


class GetHealth(_Operation):
    """Read OPA health, optionally checking bundles and plugins."""
    operation: Literal["get_health"] = "get_health"
    bundles: bool = False
    plugins: bool = False


class GetConfig(_Operation):
    """Read the active instance configuration (OPA masks private keys)."""
    operation: Literal["get_config"] = "get_config"


OpenPolicyOperation = Annotated[Union[
    ListPolicies, GetPolicy, PutPolicy, DeletePolicy, GetDocument, EvaluateDocument,
    EvaluateWebhookDocument, PutDocument, PatchDocument, DeleteDocument, SimpleQuery,
    GetQuery, PostQuery, CompileQuery, GetHealth, GetConfig,
], Field(discriminator="operation")]


class OpenPolicyConfig(NodeConfig[OpenPolicyOperation, OpenPolicyTokenCredential]):
    pass


# Each action maps to exactly one pinned OpenAPI operation.
ROUTES = {
    "list_policies": ("GET", "/v1/policies"),
    "get_policy": ("GET", "/v1/policies/{id}"),
    "put_policy": ("PUT", "/v1/policies/{id}"),
    "delete_policy": ("DELETE", "/v1/policies/{id}"),
    "get_document": ("GET", "/v1/data/{path}"),
    "evaluate_document": ("POST", "/v1/data/{path}"),
    "evaluate_webhook_document": ("POST", "/v0/data/{path}"),
    "put_document": ("PUT", "/v1/data/{path}"),
    "patch_document": ("PATCH", "/v1/data/{path}"),
    "delete_document": ("DELETE", "/v1/data/{path}"),
    "simple_query": ("POST", "/"),
    "get_query": ("GET", "/v1/query"),
    "post_query": ("POST", "/v1/query"),
    "compile_query": ("POST", "/v1/compile"),
    "get_health": ("GET", "/health"),
    "get_config": ("GET", "/v1/config"),
}


class OpenPolicyNode(WorkflowNode):
    integration_type = "automation-openpolicy"
    connection_evidence = ConnectionEvidence(noun="loaded OPA policies", operation="list_policies")

    @classmethod
    def get_config_model(cls):
        return OpenPolicyConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Open Policy Agent token")
        credential, op = self.config.credentials, self.config.config
        method, route = ROUTES[op.operation]
        if isinstance(op, _Policy):
            route = route.replace("{id}", quote(op.policy_id, safe=""))
        if isinstance(op, _Document):
            route = route.replace("{path}", "/".join(quote(p, safe="") for p in op.path.split("/")))
        headers = {"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}
        params = {}
        for name in ("metrics", "provenance", "bundles", "plugins"):
            if getattr(op, name, False):
                params[name] = "true"
        kwargs = {}
        if isinstance(op, PutPolicy):
            headers["Content-Type"] = "text/plain"
            kwargs["content"] = op.policy.encode("utf-8")
        else:
            body = None
            has_body = False
            if isinstance(op, (EvaluateDocument, EvaluateWebhookDocument, SimpleQuery)):
                body = {"input": op.input} if isinstance(op, EvaluateDocument) else op.input
                has_body = True
            elif isinstance(op, PutDocument):
                body, has_body = op.document, True
                if op.create_only:
                    headers["If-None-Match"] = "*"
            elif isinstance(op, PatchDocument):
                body, has_body = [p.model_dump(by_alias=True, exclude_unset=True) for p in op.patches], True
            elif isinstance(op, (PostQuery, CompileQuery)):
                body, has_body = {"query": op.query}, True
                if isinstance(op, CompileQuery):
                    for name in ("input", "unknowns"):
                        if getattr(op, name) is not None:
                            body[name] = getattr(op, name)
            elif isinstance(op, GetQuery):
                params["q"] = op.query
            if has_body:
                # Official REST docs support JSON for all decision/query bodies.
                # The 0.28.0 OpenAPI pin incorrectly lists YAML only for three POSTs.
                headers["Content-Type"] = "application/json-patch+json" if isinstance(op, PatchDocument) else "application/json"
                kwargs["content"] = json.dumps(body, allow_nan=False).encode("utf-8")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.base_url + route, headers=headers, params=params, **kwargs)
        if response.status_code == 304 and isinstance(op, PutDocument) and op.create_only:
            return {"status": "success", "http_status": 304, "written": False, "data": None}
        expected = 204 if isinstance(op, (PutDocument, PatchDocument, DeleteDocument)) else 200
        if response.status_code != expected:
            detail = response.text[:2000].replace(credential.api_token, "[redacted]")
            raise ValueError(f"OPA HTTP {response.status_code}: {detail}")
        if not response.content:
            if expected != 204:
                raise ValueError("OPA returned an empty response where JSON was expected")
            body = None
        else:
            body = response.json()
            if not isinstance(op, (SimpleQuery, EvaluateWebhookDocument)) and isinstance(body, dict) and ("code" in body and "message" in body):
                raise ValueError("OPA returned an error envelope")
        result = {"status": "success", "http_status": response.status_code, "data": body}
        if isinstance(op, ListPolicies):
            if not isinstance(body, dict) or not isinstance(body.get("result"), list):
                raise ValueError("OPA policy list is missing result")
            result["items"] = body["result"]
        if isinstance(op, (PutDocument, PatchDocument, DeleteDocument)):
            result["written"] = True
        return result

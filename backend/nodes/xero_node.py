"""Xero accounting, projects, files, and assets automation.

Routes and JSON envelopes follow Xero's official OpenAPI specifications:
https://github.com/XeroAPI/Xero-OpenAPI
OAuth scopes follow the current granular scope catalog, not the older broad
scope alternatives still present in parts of those specifications.
"""

import json
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.xero import XERO_SCOPES
from nodes.xero_operations import OPERATIONS, Operation


API_BASES = {
    "accounting": "https://api.xero.com/api.xro/2.0",
    "projects": "https://api.xero.com/projects.xro/2.0",
    "files": "https://api.xero.com/files.xro/1.0",
    "assets": "https://api.xero.com/assets.xro/1.0",
}


class XeroOAuthCredential(BaseModel):
    credential_type: Literal["xero_oauth"] = Field("xero_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    tenant_id: Optional[str] = Field(None, title="Default Organisation ID")
    tenant_name: Optional[str] = Field(None, title="Default Organisation")
    model_config = ConfigDict(json_schema_extra={
        "title": "Xero OAuth",
        "x-credential-type": "oauth", "x-oauth-provider": "xero",
        "x-oauth-scopes": XERO_SCOPES.declared_scopes(),
        "x-credential-url": "https://developer.xero.com/app/manage",
    })


TENANT_OPTIONS = {
    "field_name": "tenant_id", "placeholder": "Select an organisation...",
    "searchable": True, "allow_custom": True,
    "custom_placeholder": "Or paste a Xero tenant ID",
}


def _field(name: str, required: bool) -> tuple[Any, Any]:
    if name == "tenant_id":
        return (str, Field(..., min_length=1, title="Organisation",
                                     json_schema_extra={"x-dynamic-options": TENANT_OPTIONS}))
    if name == "record_json":
        return (str, Field(..., title="Record JSON",
                           description="One Xero record object, using API field names such as Name or LineItems",
                           json_schema_extra={"ui:widget": "textarea"}))
    if name == "query_json":
        return (Optional[str], Field(None, title="Query Parameters JSON",
                                     description='Optional object, for example {"page":1,"where":"Status==\\"DRAFT\\""}',
                                     json_schema_extra={"ui:widget": "textarea"}))
    if name == "status":
        return (str, Field(..., title="Asset Status", description="DRAFT, REGISTERED, or DISPOSED"))
    return (str if required else Optional[str],
            Field(... if required else None, title=name.replace("_", " ").title()))


def _make_config(name: str, op: Operation) -> type[BaseModel]:
    model_name = "Xero" + "".join(part.title() for part in name.split("_")) + "Config"
    extra: dict[str, Any] = {"const": name, "ui:hidden": True, "x-category": op.category,
                             "x-is-trigger": False, "x-display-name": op.label}
    if op.creates:
        extra.update({"x-creates-resource": True, "x-resource-type": f"xero_{op.creates}"})
    fields = {} if name == "list_connections" else {"tenant_id": _field("tenant_id", False)}
    fields.update({key: _field(key, True) for key in op.required_fields})
    if op.method == "GET" and name != "list_connections":
        fields["query_json"] = _field("query_json", False)
    return create_model(model_name, __module__=__name__,
                        operation=(Literal[name], Field(name, title=op.label, json_schema_extra=extra)),
                        **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
XeroConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class XeroNodeConfig(NodeConfig[XeroConfig, XeroOAuthCredential]):
    pass


class XeroNode(WorkflowNode):
    integration_type = "automation-xero"
    connection_evidence = ConnectionEvidence(operation="list_connections", noun="organisations")
    scope_registry = XERO_SCOPES
    edit_examples = [
        "List Xero invoices", "Create a Xero contact", "Read a Xero balance sheet",
        "Create a draft Xero invoice", "List Xero projects",
    ]

    @classmethod
    def get_config_model(cls):
        return XeroNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.xero_oauth import refresh_access_token
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="xero")

    @classmethod
    async def load_field_options(cls, field_name: str, credential_data: dict[str, Any],
                                 context: Optional[dict[str, Any]] = None,
                                 page_token: Optional[str] = None,
                                 search: Optional[str] = None) -> dict[str, Any]:
        if field_name != "tenant_id":
            return {"options": []}
        token = (credential_data or {}).get("access_token")
        if not token:
            raise ValueError("Connect Xero to list organisations")
        from nodes.oauth.xero_oauth import get_connections
        connections = await get_connections(token)
        return {"options": [
            {"value": item["tenantId"], "label": item.get("tenantName") or item["tenantId"]}
            for item in connections if item.get("tenantType") == "ORGANISATION"
            and item.get("tenantId") and (not search or search.lower() in
                                          (item.get("tenantName") or "").lower())]}

    @staticmethod
    async def _request(token: str, tenant_id: str, api: str, method: str, path: str,
                       *, params=None, body=None) -> Any:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, API_BASES[api] + path, params=params, json=body,
                headers={"Authorization": f"Bearer {token}", "xero-tenant-id": tenant_id,
                         "Accept": "application/json"})
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("Message") or payload.get("message") or payload.get("Title")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Xero API error {response.status_code}: {detail or 'request failed'}")
        return response.json() if response.content else {"ok": True}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, XeroNodeConfig):
            raise ValueError("Xero configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Xero account")
        op_config = self.config.config
        name = op_config.operation
        self.scope_registry.require(name)
        if name == "list_connections":
            from nodes.oauth.xero_oauth import get_connections
            token = await self._access_token(credential)
            return {"status": "success", "operation": name,
                    "data": {"connections": await get_connections(token)}}
        token = await self._access_token(credential)
        op = OPERATIONS[name]
        values = op_config.model_dump(exclude_none=True, exclude={"operation"})
        tenant_id = values.pop("tenant_id", None) or credential.tenant_id
        if not tenant_id:
            raise ValueError("Select a Xero organisation")
        path = op.path
        for field in op.required_fields:
            marker = "{" + field + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(field)), safe=""))
        params = None
        if "query_json" in values:
            try:
                params = json.loads(values.pop("query_json"))
            except json.JSONDecodeError as exc:
                raise ValueError("Query Parameters JSON must be valid JSON") from exc
            if not isinstance(params, dict):
                raise ValueError("Query Parameters JSON must be an object")
        if name == "list_assets":
            params = {**(params or {}), "status": values.pop("status")}
        body = None
        if "record_json" in values:
            try:
                record = json.loads(values.pop("record_json"))
            except json.JSONDecodeError as exc:
                raise ValueError("Record JSON must be valid JSON") from exc
            if not isinstance(record, dict):
                raise ValueError("Record JSON must be an object")
            body = {op.body_envelope: [record]} if op.body_envelope else record
        data = await self._request(token, tenant_id, op.api, op.method, path,
                                   params=params, body=body)
        return {"status": "success", "operation": name, "data": data}

    async def _access_token(self, credential: XeroOAuthCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.xero_oauth import refresh_access_token
        credential_data = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential_data, refresh=refresh_access_token,
            provider="xero", caller_path="execute")

        for key in ("access_token", "refresh_token", "expires_at"):
            setattr(credential, key, credential_data[key])
        return token

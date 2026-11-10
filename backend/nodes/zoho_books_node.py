"""Zoho Books v3 workflow actions from Zoho's published OpenAPI archive."""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.zoho_books_oauth import OAUTH_PROVIDER, validate_api_domain


from nodes.zoho_books_operations import OPERATIONS
from nodes.scopes.zoho_books import ZOHO_BOOKS_SCOPES
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.binary_output import BinaryOutput


class ZohoBooksOAuthCredential(BaseModel):
    credential_type: Literal["zoho_books_oauth"] = Field(
        "zoho_books_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    accounts: str = Field("https://accounts.zoho.com", title="Sign-in Accounts Server")
    api_domain: str = Field(..., title="Regional API Domain")
    accounts_server: str = Field(..., title="Regional Accounts Server")
    organization_id: Optional[str] = Field(None, title="Default Organization ID")
    organization_name: Optional[str] = Field(None, title="Default Organization")

    model_config = ConfigDict(title="Zoho Books OAuth", json_schema_extra={
        "x-credential-type": "oauth",
        "x-oauth-provider": "zoho_books",
        "x-oauth-scopes": ZOHO_BOOKS_SCOPES.declared_scopes(),
        "x-credential-url": "https://api-console.zoho.com/",
    })


_JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


def _field_name(prefix: str, raw: str) -> str:
    return prefix + "_" + re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()


def _make_config(op: dict[str, Any]) -> type[BaseModel]:
    name = op["name"]
    fields: dict[str, tuple[Any, Any]] = {
        "operation": (Literal[name], Field(
            name, title=op["label"], description=op["description"],
            json_schema_extra={"const": name, "ui:hidden": True,
                               "x-category": op["category"], "x-display-name": op["label"],
                               "x-is-trigger": False},
        )),
    }
    if op["requires_org_id"]:
        fields["organization_id"] = (str, Field(
            ..., title="Organization ID", min_length=1, description="Organization to run this accounting action in."))
    for raw in op["path_params"]:
        key = _field_name("path", raw)
        optional = raw == "organization_id"
        fields[key] = (Optional[str] if optional else str, Field(
            None if optional else ..., title=raw.replace("_", " ").title(),
            description="Uses the connected default organization when blank." if optional else None))
    for raw in op["required_query"]:
        key = _field_name("query", raw)
        fields[key] = (str, Field(..., title=raw.replace("_", " ").title()))
    for raw in op["required_headers"]:
        key = _field_name("header", raw)
        fields[key] = (str, Field(..., title=raw.replace("-", " ").title()))
    fields["query_json"] = (Optional[str], Field(
        None, title="Other Query Parameters (JSON)",
        description="Filters, pagination, and other optional API query parameters.",
        json_schema_extra=_JSON_EDITOR))
    if op["body_mime"] == "application/json":
        body_required = op["body_required"]
        required_keys = op["body_required_fields"]
        description = "Object or array matching Zoho Books' API reference for this action."
        if required_keys:
            description += " Required keys: " + ", ".join(required_keys) + "."
        fields["body_json"] = (str if body_required else Optional[str], Field(
            ... if body_required else None, title="Request Body (JSON)",
            description=description,
            json_schema_extra=_JSON_EDITOR))
    elif op["body_mime"] == "multipart/form-data":
        fields["file_base64"] = (str, Field(..., title="Attachment (Base64)",
                                            description="Base64 encoded file, maximum 10 MB."))
        fields["file_name"] = (str, Field(..., title="File Name"))
        fields["file_content_type"] = (str, Field("application/octet-stream", title="Content Type"))
        fields["form_json"] = (Optional[str], Field(None, title="Other Form Fields (JSON)",
                                                json_schema_extra=_JSON_EDITOR))
    return create_model(
        "ZohoBooks" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__, **fields,
    )


CONFIG_MODELS = {name: _make_config(op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
class ZohoBooksPollConfig(PollTriggerConfigBase):
    organization_id: str = Field(..., title="Organization ID", min_length=1)


class ZohoBooksInvoicePollConfig(ZohoBooksPollConfig):
    operation: Literal["on_invoice_updated"] = Field("on_invoice_updated", title="On New or Updated Invoice", json_schema_extra={
        "const": "on_invoice_updated", "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On New or Updated Invoice"})


class ZohoBooksContactPollConfig(ZohoBooksPollConfig):
    operation: Literal["on_contact_updated"] = Field("on_contact_updated", title="On New or Updated Contact", json_schema_extra={
        "const": "on_contact_updated", "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On New or Updated Contact"})


class ZohoBooksPaymentPollConfig(ZohoBooksPollConfig):
    operation: Literal["on_payment_updated"] = Field("on_payment_updated", title="On New or Updated Customer Payment", json_schema_extra={
        "const": "on_payment_updated", "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On New or Updated Customer Payment"})


ZohoBooksConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ZohoBooksInvoicePollConfig, ZohoBooksContactPollConfig, ZohoBooksPaymentPollConfig,)], Discriminator("operation")]


class ZohoBooksNodeConfig(NodeConfig[ZohoBooksConfig, ZohoBooksOAuthCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _parse_json(raw: Optional[str], label: str, *, allow_array: bool = False) -> Any:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain valid JSON") from exc
    if not isinstance(value, (dict, list) if allow_array else dict):
        raise ValueError(f"{label} must be a JSON {'object or array' if allow_array else 'object'}")
    return value


class ZohoBooksNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-zoho-books"
    scope_registry = ZOHO_BOOKS_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_organizations", noun="organizations")
    edit_examples = [
        "List Zoho Books customers", "Create an invoice in Zoho Books",
        "Record a customer payment", "Find overdue invoices",
    ]

    @classmethod
    def get_config_model(cls):
        return ZohoBooksNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        if not credential_data:
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields, provider="zoho_books")

    @staticmethod
    async def _request(credential: dict, name: str, values: dict[str, Any]) -> dict[str, Any]:
        op = OPERATIONS[name]
        path = op["path"]
        for raw in op["path_params"]:
            key = _field_name("path", raw)
            value = values.pop(key, None) or (credential.get("organization_id") if raw == "organization_id" else None)
            if not value or str(value) in {".", ".."} or "/" in str(value) or "\\" in str(value):
                raise ValueError(f"{raw} must be a valid identifier")
            path = path.replace("{" + raw + "}", quote(str(value), safe=""))
        params = _parse_json(values.pop("query_json", None), "Query Parameters") or {}
        if op["requires_org_id"]:
            org_id = values.pop("organization_id", None) or credential.get("organization_id")
            if not org_id:
                raise ValueError("Select a Zoho Books organization before running this action")
            params["organization_id"] = str(org_id)
        for raw in op["required_query"]:
            params[raw] = values.pop(_field_name("query", raw))
        headers = {"Authorization": f"Zoho-oauthtoken {credential['access_token']}",
                   "Accept": "application/json"}
        for raw in op["required_headers"]:
            headers[raw] = values.pop(_field_name("header", raw))
        request: dict[str, Any] = {}
        if op["body_mime"] == "application/json":
            body = _parse_json(values.pop("body_json", None), "Request Body", allow_array=True)
            if op["body_required"] and body is None:
                raise ValueError("Request Body is required for this action")
            required_keys = op["body_required_fields"]
            if required_keys:
                missing = [key for key in required_keys
                           if not isinstance(body, dict) or key not in body]
                if missing:
                    raise ValueError("Request Body is missing required keys: " + ", ".join(missing))
            if body is not None:
                request["json"] = body
        elif op["body_mime"] == "multipart/form-data":
            try:
                content = base64.b64decode(values.pop("file_base64"), validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("Attachment must be valid Base64") from exc
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("Attachment exceeds the 10 MB limit")
            form = _parse_json(values.pop("form_json", None), "Other Form Fields") or {}
            request["data"] = {key: str(value) for key, value in form.items()}
            request["files"] = {"attachment": (values.pop("file_name"), content,
                                                values.pop("file_content_type"))}
        base = validate_api_domain(credential["api_domain"])
        started = time.monotonic()
        from utils.ssrf import guarded_async_client
        async with guarded_async_client(timeout=60, follow_redirects=False) as client:
            response = await client.request(op["method"], base + "/books/v3" + path,
                                            params=params or None, headers=headers, **request)
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if content_type in {"application/pdf", "application/octet-stream"} or content_type.startswith("image/"):
            data: Any = BinaryOutput(data=response.content, content_type=content_type, filename="zoho-books-download")
        elif not response.content:
            data = {}
        else:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text[:1000]}
        if response.is_error or response.is_redirect or (isinstance(data, dict) and data.get("code") not in (None, 0)):
            message = data.get("message") if isinstance(data, dict) else None
            raise ValueError(f"Zoho Books API error {response.status_code}: {message or 'request failed'}")
        return {"status": "success", "operation": name, "status_code": response.status_code,
                "data": data, "timing_ms": {"api_request": round((time.monotonic()-started)*1000, 2)}}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ZohoBooksNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Zoho Books account before running this action")
        config = self.config.config
        self.scope_registry.require(config.operation)
        credential = self.config.credentials.model_dump()
        await self.freshen_credential(credential, user_id=self.user_id,
                                      credential_id=(self.node_data or {}).get("credential_id"))
        for key in ("access_token", "refresh_token", "expires_at", *OAUTH_PROVIDER.credential_fields):
            if key in credential:
                setattr(self.config.credentials, key, credential[key])
        if isinstance(config, ZohoBooksPollConfig):
            return await self._poll_records(credential, config)
        return await self._request(credential, config.operation,
                                   config.model_dump(exclude={"operation"}, exclude_none=True))

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation", "").startswith("on_"):
            return bool(output.get("records"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "records" not in output:
            return super().resolve_agent_event(output)
        records = output["records"]
        if not records:
            return None
        lines = []
        for row in records[:10]:
            if output["resource"] == "invoices":
                lines.append(f"Invoice {row.get('invoice_number')} for {row.get('customer_name')}: {row.get('status')}, total {row.get('total')} (invoice_id {row['invoice_id']})")
            elif output["resource"] == "contacts":
                lines.append(f"Contact {row.get('contact_name')}: {row.get('email')} (contact_id {row['contact_id']})")
            else:
                lines.append(f"Payment {row.get('payment_number')}: {row.get('amount')} by {row.get('payment_mode')} on {row.get('date')} (payment_id {row['payment_id']})")
        return {"text": f"Zoho Books: {len(records)} new or updated {output['resource']}:\n" + "\n".join(lines),
                "conversation_key": None}

    async def _filter_unseen(self, items, id_fn):
        """Remember the current version per record, so old versions cannot evict active ids.

        Unlike an append-only seen-id history, this stays bounded by the live list even
        after many updates. Baseline, config repoints, arm-time runs and CAS writes use
        the scheduled poll family's state seam.
        """
        from nodes.core.poll_trigger import poll_scope
        scope = poll_scope(type(self), self.config.config.model_dump(mode="json"))
        versions = {id_fn(row).rsplit(":", 1)[0]: id_fn(row) for row in items}
        baseline_only = getattr(self, "_poll_baseline_only", False)

        def update(state):
            initialized = "versions" in state or "seen_ids" in state
            repoint = state.get("scope") is not None and state["scope"] != scope
            previous = state.get("versions", {})
            if not initialized or repoint:
                return {"versions": versions, "scope": scope}, []
            if baseline_only:
                return None, []
            fresh = [row for row in items if previous.get(id_fn(row).rsplit(":", 1)[0]) != id_fn(row)]
            return ({"versions": versions, "scope": scope} if versions != previous else None), fresh

        fresh = await self._update_node_state(update, skip_result=[])
        self._poll_emitted_count = len(fresh)
        return fresh


    async def _poll_records(self, credential, config):
        resource, operation, id_key = {
            "on_invoice_updated": ("invoices", "list_invoices", "invoice_id"),
            "on_contact_updated": ("contacts", "list_contacts", "contact_id"),
            "on_payment_updated": ("customer_payments", "list_customer_payments", "payment_id"),
        }[config.operation]
        records = []
        for page in range(1, 51):
            result = await self._request(credential, operation, {
                "organization_id": config.organization_id,
                "query_json": json.dumps({"page": page, "per_page": 200, "sort_column": "created_time"}),
            })
            payload = result["data"]
            rows = payload.get(resource)
            if not isinstance(rows, list) or not all(isinstance(row, dict) and row.get(id_key) for row in rows):
                raise ValueError("Zoho Books returned an invalid " + resource + " list")
            records.extend(rows)
            context = payload.get("page_context")
            if isinstance(context, list) and len(context) == 1 and isinstance(context[0], dict):
                context = context[0]
            if context is not None and not isinstance(context, dict):
                raise ValueError("Zoho Books returned invalid pagination context")
            more = context.get("has_more_page", len(rows) == 200) if context else len(rows) == 200
            if not isinstance(more, bool):
                raise ValueError("Zoho Books returned invalid pagination flag")
            if not more:
                break
        else:
            raise ValueError("Zoho Books poll exceeds 10,000 records; use a smaller organization")
        # Fingerprint the provider's complete list record: updates to amounts/status/contact fields fire too.
        import hashlib
        fresh = await self._filter_unseen(records, lambda row: str(row[id_key]) + ":" +
            hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        return {"status": "success", "operation": config.operation, "resource": resource,
                "records": fresh, "count": len(fresh)}

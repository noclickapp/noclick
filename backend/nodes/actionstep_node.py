"""Actionstep matters, contacts, tasks, file notes and time-entry reads.

Wire envelopes and media type follow the developer portal's API Requests and
API Responses pages. Regional origins come only from the OAuth token response.
"""
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.actionstep_operations import OPERATIONS
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.actionstep_oauth import API_ENDPOINT, OAUTH_PROVIDER
from nodes.scopes.actionstep import ACTIONSTEP_SCOPES
from utils.ssrf import guarded_async_client


class ActionstepOAuthCredential(BaseModel):
    credential_type: Literal["actionstep_oauth"] = Field("actionstep_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    api_endpoint: str = Field(..., title="Regional API Endpoint", description="The api_endpoint from the Actionstep token response, for example https://ap-southeast-2.actionstep.com/api/.")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    orgkey: Optional[str] = Field(None, title="Organisation Key")
    model_config = ConfigDict(title="Actionstep Account", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "actionstep",
        "x-oauth-scopes": sorted(ACTIONSTEP_SCOPES.declared_scopes()),
        "x-credential-url": "https://docs.actionstep.com/api-credentials/",
        "x-credential-instructions": "Connect your Actionstep account. Your app must have production API credentials issued by Actionstep Support and the requested domain scopes. The regional API endpoint is supplied by Actionstep during sign-in.",
    })

    @field_validator("api_endpoint")
    @classmethod
    def endpoint(cls, value):
        return API_ENDPOINT.validate(value.strip())

    @field_validator("access_token", "refresh_token")
    @classmethod
    def secret(cls, value):
        return clean_secret(value, field_name="Actionstep token")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _TimestampInput(_Input):
    @field_validator("due_timestamp", check_fields=False)
    @classmethod
    def timestamp(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError("Use a timestamp with timezone") from None
        return value


def _text(title, required=False, *, maximum=1000):
    return (str if required else Optional[str], Field(... if required else None, title=title, min_length=1, max_length=maximum))


def _identifier(title, required=True):
    return (int if required else Optional[int], Field(... if required else None, title=title, ge=1, le=2147483647))


def _config(name, method, resource, single):
    fields = {}
    if single:
        fields["id"] = _identifier("Resource ID")
    if name.startswith("list_"):
        fields.update(page=(int, Field(1, ge=1, le=1000000, description="Page number; follow next_page returned by this operation.")),
                      page_size=(int, Field(50, ge=1, le=200)))
        if resource in {"tasks", "filenotes", "timeentries"}:
            fields["matter_id"] = _identifier("Matter ID", False)
        if resource in {"actions", "participants"}:
            fields["name_contains"] = _text("Name Contains")
    if method in {"POST", "PUT"}:
        if resource == "participants":
            # Keep updates partial; Actionstep derives displayName from names.
            if method == "POST":
                fields["display_name"] = _text("Display Name", True)
            fields.update(first_name=_text("First Name"), last_name=_text("Last Name"),
                          company_name=_text("Company Name"), email=_text("Email"))
        elif resource == "tasks":
            fields.update(name=_text("Task Name", True),
                status=(Literal["Incomplete", "Complete", "Hidden", "Deleted"], Field("Incomplete")),
                priority=(Literal["Low", "Normal", "High"], Field("Normal")),
                due_timestamp=(str, Field(..., title="Due Timestamp", json_schema_extra={"format": "date-time"})),
                description=_text("Description", maximum=20000),
                matter_id=_identifier("Matter ID"), assignee_id=_identifier("Assignee Participant ID"))
        elif resource == "filenotes":
            fields["text"] = _text("Note Text", True, maximum=20000)
            if method == "POST":
                fields["matter_id"] = _identifier("Matter ID")
    return create_model("Actionstep" + "".join(word.title() for word in name.split("_")) + "Config",
        __base__=_TimestampInput, __module__=__name__,
        operation=(Literal[name], Field(name, json_schema_extra={"ui:hidden": True,
            "x-display-name": name.replace("_", " ").title(), "x-is-trigger": False})), **fields)


CONFIG_MODELS = {name: _config(name, *operation) for name, operation in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
ActionstepConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class ActionstepNodeConfig(NodeConfig[ActionstepConfig, ActionstepOAuthCredential]):
    pass


class ActionstepNode(WorkflowNode):
    integration_type = "automation-actionstep"
    scope_registry = ACTIONSTEP_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_matters", noun="matters", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return ActionstepNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data), provider="actionstep",
            additional_token_fields=OAUTH_PROVIDER.credential_fields)

    @staticmethod
    def _body(op, resource, method):
        if resource == "participants":
            mapping = {"display_name": "displayName", "first_name": "firstName", "last_name": "lastName",
                       "company_name": "companyName", "email": "email"}
            body = {wire: getattr(op, key) for key, wire in mapping.items() if getattr(op, key, None) is not None}
            if not body:
                raise ValueError("Supply at least one contact field to update")
        elif resource == "tasks":
            body = {"name": op.name, "status": op.status, "priority": op.priority, "dueTimestamp": op.due_timestamp,
                    "links": {"action": op.matter_id, "assignee": op.assignee_id}}
            if op.description is not None:
                body["description"] = op.description
        else:
            body = {"text": op.text}
            if method == "POST":
                body["links"] = {"action": op.matter_id}
        if method == "PUT":
            body["id"] = op.id
        return {resource: body}

    @staticmethod
    def _data(payload, resource, *, single, expected_id=None):
        if not isinstance(payload, dict) or "errors" in payload or "error" in payload:
            raise ValueError("Actionstep returned an error or invalid response")
        data = payload.get(resource)
        rows = [data] if single else data
        if not isinstance(rows, list):
            raise ValueError("Actionstep resource envelope is missing")
        for row in rows:
            if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0:
                raise ValueError("Actionstep resource ID is missing or invalid")
        if len({row["id"] for row in rows}) != len(rows):
            raise ValueError("Actionstep returned duplicate resource IDs")
        if single and expected_id is not None and data["id"] != expected_id:
            raise ValueError("Actionstep returned a different resource ID")
        return data

    @staticmethod
    def _next_page(value, *, origin, resource, current):
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
            raise ValueError("Actionstep returned an invalid continuation URL")
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != urlsplit(origin).netloc
                or parsed.path != "/api/rest/" + resource or parsed.fragment):
            raise ValueError("Actionstep pagination changed the regional resource")
        pages = parse_qs(parsed.query, keep_blank_values=True).get("page", [])
        if len(pages) != 1 or not pages[0].isascii() or not pages[0].isdecimal():
            raise ValueError("Actionstep continuation has no single page number")
        page = int(pages[0])
        if not current < page <= 1000000:
            raise ValueError("Actionstep pagination did not advance")
        # Never follow provider links: return only the page number so the next
        # invocation retains its selected filters and page size.
        return page

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Actionstep account")
        op = self.config.config
        method, resource, single = OPERATIONS[op.operation]
        body = self._body(op, resource, method) if method in {"POST", "PUT"} else None
        credential = self.config.credentials.model_dump()
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credential, refresh=OAUTH_PROVIDER.bind_refresh(credential), provider="actionstep",
            additional_token_fields=OAUTH_PROVIDER.credential_fields, caller_path="execute")
        origin = API_ENDPOINT.validate(credential["api_endpoint"])
        path = "/api/rest/" + resource + ("/" + str(op.id) if single else "")
        params = {}
        if op.operation.startswith("list_"):
            params = {"page": op.page, "pageSize": op.page_size}
            if getattr(op, "matter_id", None) is not None:
                params["action_eq"] = op.matter_id
            if getattr(op, "name_contains", None) is not None:
                params["displayName_ilike" if resource == "participants" else "name_ilike"] = "*" + op.name_contains + "*"
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, origin + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.api+json",
                             "Content-Type": "application/vnd.api+json"}, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            return {"status": "error", "error": "Actionstep request did not complete", "write_outcome": "unknown" if method != "GET" else None}
        if response.status_code < 200 or response.status_code >= 300:
            return {"status": "error", "http_status": response.status_code,
                    "error": "Actionstep rejected the request", "write_outcome": "unknown" if method != "GET" and response.status_code >= 500 else None}
        if method == "DELETE":
            if response.status_code != 204:
                raise ValueError("Actionstep did not acknowledge deletion")
            return {"status": "success", "deleted_id": op.id, "deletion_acknowledged": True}
        try:
            if len(response.content) > 5000000 or response.headers.get("content-type", "").split(";", 1)[0] not in {"application/json", "application/vnd.api+json"}:
                raise ValueError("Expected bounded Actionstep JSON")
            payload = response.json()
            one = single or method == "POST"
            data = self._data(payload, resource, single=one, expected_id=op.id if single else None)
            result = {"status": "success", "data": data}
            if op.operation.startswith("list_"):
                paging = payload.get("meta", {}).get("paging", {}).get(resource)
                if not isinstance(paging, dict) or "nextPage" not in paging or type(paging.get("page")) is not int or paging["page"] != op.page:
                    raise ValueError("Actionstep pagination metadata is missing or mismatched")
                following = self._next_page(paging["nextPage"], origin=origin, resource=resource, current=op.page)
                result.update(next_page=following, has_more=following is not None, pagination=paging)
            if method != "GET":
                result["write_acknowledged"] = True
            return result
        except (ValueError, TypeError, AttributeError):
            return {"status": "error", "error": "Actionstep response could not be verified",
                    "write_outcome": "unknown" if method != "GET" else None}

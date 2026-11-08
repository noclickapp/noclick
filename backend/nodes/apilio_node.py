"""Apilio REST API actions, with verbatim Postman response fixtures.

The collection's Endpoints section names api.apilio.com; its saved request URLs
still name localhost:3000. Production calls always use the documented host.
"""
from __future__ import annotations

import base64
import binascii
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.apilio.com"
DOCS_URL = "https://documenter.getpostman.com/view/13480928/TzCHAVD2"


class ApilioAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Apilio API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://apilio.herokuapp.com/user",
            "x-credential-instructions": "Copy the preformatted API authorization token from your Apilio profile. Paste only the encoded token after Basic, without the Basic prefix. These API credentials differ from your web login. Connecting reads your boolean variables.",
            "x-help-url": DOCS_URL,
        })
    credential_type: Literal["apilio_api_token"] = Field("apilio_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the encoded API token from your Apilio profile")
        value = clean_secret(value, field_name="API token")
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
            username, separator, password = decoded.partition(":")
            if not separator or not username or not password or any(ord(c) < 32 or ord(c) == 127 for c in decoded):
                raise ValueError()
        except (ValueError, UnicodeError, binascii.Error):
            raise ValueError("Paste the encoded username:password token, without the Basic prefix") from None
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Resource(_Input):
    resource_id: str = Field(..., title="Resource UUID", pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        description="UUID from the corresponding list operation or the object's Apilio detail page.")


class ListBooleanVariables(_Input):
    operation: Literal["list_boolean_variables"] = "list_boolean_variables"


class GetBooleanVariable(_Resource):
    operation: Literal["get_boolean_variable"] = "get_boolean_variable"


class UpdateBooleanVariable(_Resource):
    operation: Literal["update_boolean_variable"] = "update_boolean_variable"
    boolean_value: StrictBool = Field(..., description="New boolean value.")


class ListNumericVariables(_Input):
    operation: Literal["list_numeric_variables"] = "list_numeric_variables"


class GetNumericVariable(_Resource):
    operation: Literal["get_numeric_variable"] = "get_numeric_variable"


class UpdateNumericVariable(_Resource):
    operation: Literal["update_numeric_variable"] = "update_numeric_variable"
    numeric_value: StrictFloat = Field(..., allow_inf_nan=False, description="New numeric value.")


class ListStringVariables(_Input):
    operation: Literal["list_string_variables"] = "list_string_variables"


class GetStringVariable(_Resource):
    operation: Literal["get_string_variable"] = "get_string_variable"


class UpdateStringVariable(_Resource):
    operation: Literal["update_string_variable"] = "update_string_variable"
    string_value: str = Field(..., description="New string value.")


class ListConditions(_Input):
    operation: Literal["list_conditions"] = "list_conditions"


class ListVariableConditions(_Input):
    operation: Literal["list_variable_conditions"] = "list_variable_conditions"


class GetVariableCondition(_Resource):
    operation: Literal["get_variable_condition"] = "get_variable_condition"


class ListTuyaConditions(_Input):
    operation: Literal["list_tuya_conditions"] = "list_tuya_conditions"


class GetTuyaCondition(_Resource):
    operation: Literal["get_tuya_condition"] = "get_tuya_condition"


class ListTimeConditions(_Input):
    operation: Literal["list_time_conditions"] = "list_time_conditions"


class GetTimeCondition(_Resource):
    operation: Literal["get_time_condition"] = "get_time_condition"


class ListLogicblocks(_Input):
    operation: Literal["list_logicblocks"] = "list_logicblocks"


class EvaluateLogicblock(_Resource):
    operation: Literal["evaluate_logicblock"] = "evaluate_logicblock"
    # Evaluation may trigger the Logicblock's configured actions.


class SetLogicblockActive(_Resource):
    operation: Literal["set_logicblock_active"] = "set_logicblock_active"
    active: StrictBool = Field(..., description="Whether the Logicblock is active.")


ApilioConfig = Annotated[Union[
    ListBooleanVariables,
    GetBooleanVariable,
    UpdateBooleanVariable,
    ListNumericVariables,
    GetNumericVariable,
    UpdateNumericVariable,
    ListStringVariables,
    GetStringVariable,
    UpdateStringVariable,
    ListConditions,
    ListVariableConditions,
    GetVariableCondition,
    ListTuyaConditions,
    GetTuyaCondition,
    ListTimeConditions,
    GetTimeCondition,
    ListLogicblocks,
    EvaluateLogicblock,
    SetLogicblockActive,
], Field(discriminator="operation")]


class ApilioFullConfig(NodeConfig[ApilioConfig, ApilioAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "list_boolean_variables": ('GET', '/api/v1/boolean_variables'),
    "get_boolean_variable": ('GET', '/api/v1/boolean_variables/{resource_id}'),
    "update_boolean_variable": ('PUT', '/api/v1/boolean_variables/{resource_id}'),
    "list_numeric_variables": ('GET', '/api/v1/numeric_variables'),
    "get_numeric_variable": ('GET', '/api/v1/numeric_variables/{resource_id}'),
    "update_numeric_variable": ('PUT', '/api/v1/numeric_variables/{resource_id}'),
    "list_string_variables": ('GET', '/api/v1/string_variables'),
    "get_string_variable": ('GET', '/api/v1/string_variables/{resource_id}'),
    "update_string_variable": ('PUT', '/api/v1/string_variables/{resource_id}'),
    "list_conditions": ('GET', '/api/v1/conditions/'),
    "list_variable_conditions": ('GET', '/api/v1/variableconditions'),
    "get_variable_condition": ('GET', '/api/v1/variableconditions/{resource_id}'),
    "list_tuya_conditions": ('GET', '/api/v1/tuyaconditions'),
    "get_tuya_condition": ('GET', '/api/v1/tuyaconditions/{resource_id}'),
    "list_time_conditions": ('GET', '/api/v1/timeconditions'),
    "get_time_condition": ('GET', '/api/v1/timeconditions/{resource_id}'),
    "list_logicblocks": ('GET', '/api/v1/logicblocks/'),
    "evaluate_logicblock": ('POST', '/api/v1/logicblocks/{resource_id}/evaluate'),
    "set_logicblock_active": ('PATCH', '/api/v1/logicblocks/{resource_id}'),
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()}
    return value


class ApilioNode(WorkflowNode):
    integration_type = "automation-apilio"
    connection_evidence = ConnectionEvidence(noun="boolean variables", operation="list_boolean_variables", label_keys=("name", "uuid"))

    @classmethod
    def get_config_model(cls):
        return ApilioFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, ApilioFullConfig) or not self.config.credentials:
            raise ValueError("Attach your Apilio API token")
        config, credential = self.config.config, self.config.credentials
        method, template = ROUTES[config.operation]
        path = template.format(resource_id=getattr(config, "resource_id", ""))
        body = None
        if method == "PUT":
            resource = template.split("/")[3].removesuffix("s")
            value = getattr(config, {"boolean_variable": "boolean_value", "numeric_variable": "numeric_value", "string_variable": "string_value"}[resource])
            body = {resource: {"value": value}}
        elif method == "PATCH":
            body = {"logicblock": {"active": config.active}}
        decoded = base64.b64decode(credential.api_token).decode("utf-8")
        _, _, password = decoded.partition(":")
        secrets = (credential.api_token, decoded, password)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Basic " + credential.api_token, "Accept": "application/json", "Content-Type": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Apilio request could not be completed; inspect provider state before retrying a write") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Apilio response exceeds the size limit")
        if response.status_code != 200:
            # Keep provider rejection text for connection evidence, but never secrets.
            message = response.text[:2000] or "Apilio did not confirm the request"
            return _redact({"status": "error", "http_status": response.status_code, "error": message}, secrets)
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from Apilio")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Apilio returned invalid JSON") from None
        listing = config.operation.startswith("list_")
        if listing:
            valid = isinstance(payload, list) and all(isinstance(row, dict) and isinstance(row.get("uuid"), str) and isinstance(row.get("name"), str) for row in payload)
        else:
            valid = isinstance(payload, dict) and isinstance(payload.get("uuid"), str) and isinstance(payload.get("name"), str)
        if not valid:
            raise ValueError("Apilio returned an unexpected resource response")
        return _redact({"status": "success", "operation": config.operation,
            "http_status": response.status_code, "data": payload}, secrets)

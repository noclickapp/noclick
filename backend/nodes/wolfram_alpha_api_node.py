"""Wolfram|Alpha queries with a person's pasted AppID.

Task presets each make one GET /api/v1/llm-api request from the pinned v0.1
contract. The legacy cloud-plugin has no documented personal-key flow.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://www.wolframalpha.com/api/v1/llm-api"


class WolframAlphaApiCredential(BaseModel):
    model_config = ConfigDict(title="Wolfram Alpha API AppID", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://developer.wolframalpha.com/",
            "x-credential-instructions": "Create an app in the Wolfram|Alpha Developer Portal and paste its AppID with LLM API access. NoClick sends it as a Bearer token to www.wolframalpha.com. The connection query consumes API usage and proves key acceptance, not account identity."})
    credential_type: Literal["wolfram_alpha_api_app_id"] = Field("wolfram_alpha_api_app_id", json_schema_extra={"ui:hidden": True})
    app_id: str = Field(..., title="AppID", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("app_id", mode="before")
    @classmethod
    def valid_app_id(cls, value):
        value = clean_secret(value, field_name="AppID")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the AppID without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def single_line(cls, value):
        if isinstance(value, str) and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use nonempty single-line English query text")
        return value


Text = Annotated[str, Field(min_length=1, max_length=4000)]


class CheckConnection(_Input):
    operation: Literal["check_connection"] = Field("check_connection", title="Check Connection", json_schema_extra={"ui:hidden": True})


class Query(_Input):
    operation: Literal["query"] = Field("query", title="Query Computational Knowledge", json_schema_extra={"ui:hidden": True})
    input: Text = Field(..., title="Query")


class Calculate(_Input):
    operation: Literal["calculate"] = Field("calculate", title="Calculate Expression", json_schema_extra={"ui:hidden": True})
    expression: Text = Field(..., title="Expression")


class SolveEquation(_Input):
    operation: Literal["solve_equation"] = Field("solve_equation", title="Solve Equation", json_schema_extra={"ui:hidden": True})
    equation: Text = Field(..., title="Equation")
    variable: Text = Field(..., title="Variable")


class Integrate(_Input):
    operation: Literal["integrate"] = Field("integrate", title="Integrate Expression", json_schema_extra={"ui:hidden": True})
    expression: Text = Field(..., title="Expression")
    variable: Text = Field(..., title="Integration Variable")


class Differentiate(_Input):
    operation: Literal["differentiate"] = Field("differentiate", title="Differentiate Expression", json_schema_extra={"ui:hidden": True})
    expression: Text = Field(..., title="Expression")
    variable: Text = Field(..., title="Differentiation Variable")


class ConvertUnits(_Input):
    operation: Literal["convert_units"] = Field("convert_units", title="Convert Units", json_schema_extra={"ui:hidden": True})
    quantity: Text = Field(..., title="Quantity with Units")
    target_unit: Text = Field(..., title="Target Unit")


class Statistics(_Input):
    operation: Literal["statistics"] = Field("statistics", title="Compute Descriptive Statistics", json_schema_extra={"ui:hidden": True})
    values: Text = Field(..., title="Comma-separated Numbers")


class FactorInteger(_Input):
    operation: Literal["factor_integer"] = Field("factor_integer", title="Factor Integer", json_schema_extra={"ui:hidden": True})
    integer: int = Field(..., title="Integer", strict=True)


class CurrencyConversion(_Input):
    operation: Literal["currency_conversion"] = Field("currency_conversion", title="Convert Currency", json_schema_extra={"ui:hidden": True})
    amount: Text = Field(..., title="Amount with Source Currency")
    target_currency: Text = Field(..., title="Target Currency")


class DateDifference(_Input):
    operation: Literal["date_difference"] = Field("date_difference", title="Calculate Date Difference", json_schema_extra={"ui:hidden": True})
    start_date: Text = Field(..., title="Start Date")
    end_date: Text = Field(..., title="End Date")


Config = Annotated[Union[CheckConnection, Query, Calculate, SolveEquation, Integrate, Differentiate, ConvertUnits, Statistics, FactorInteger, CurrencyConversion, DateDifference], Field(discriminator="operation")]


class WolframAlphaApiConfig(NodeConfig[Config, WolframAlphaApiCredential]):
    pass


def query_text(c):
    if isinstance(c, CheckConnection): return "10 densest elemental metals"
    if isinstance(c, Query): return c.input
    if isinstance(c, Calculate): return c.expression
    if isinstance(c, SolveEquation): return f"solve {c.equation} for {c.variable}"
    if isinstance(c, Integrate): return f"integrate {c.expression} with respect to {c.variable}"
    if isinstance(c, Differentiate): return f"differentiate {c.expression} with respect to {c.variable}"
    if isinstance(c, ConvertUnits): return f"convert {c.quantity} to {c.target_unit}"
    if isinstance(c, Statistics): return f"descriptive statistics {{{c.values}}}"
    if isinstance(c, FactorInteger): return f"factor {c.integer}"
    if isinstance(c, CurrencyConversion): return f"convert {c.amount} to {c.target_currency}"
    if isinstance(c, DateDifference): return f"days between {c.start_date} and {c.end_date}"
    raise ValueError("Unknown Wolfram Alpha API operation")


class WolframAlphaApiNode(WorkflowNode):
    integration_type = "automation-wolfram-alpha-api"
    connection_evidence = ConnectionEvidence(noun="Wolfram|Alpha results", operation="check_connection", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return WolframAlphaApiConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wolfram Alpha API AppID")
        c = self.config.config
        app_id = self.config.credentials.app_id
        output = {"operation": c.operation, "identity_verified": False}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE, params={"input": query_text(c)},
                    headers={"Authorization": f"Bearer {app_id}", "Accept": "text/plain"})
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if response.status_code != 200:
                # Keep the documented plain-text rejection while redacting an echoed key.
                message = response.text[:2000].replace(app_id, "[redacted]") if content_type == "text/plain" else "Wolfram Alpha API request failed"
                return {**output, "status": "error", "status_code": response.status_code, "message": message}
            if content_type != "text/plain" or not response.content or len(response.content) > 2_000_000:
                return {**output, "status": "error", "message": "Expected a nonempty, bounded text response from Wolfram Alpha API"}
            return {**output, "status": "success", "result": response.text.replace(app_id, "[redacted]")}
        except httpx.RequestError:
            return {**output, "status": "error", "message": "Wolfram Alpha API could not be reached"}

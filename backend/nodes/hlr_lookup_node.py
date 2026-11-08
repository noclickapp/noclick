"""HLR Lookup API v2. Each action makes one documented POST, without retries.

Contract: https://www.hlrlookup.com/hlr-api-v2.openapi.json (2.0.0).
Lookup actions can spend provider credits and write the provider's result cache.
"""
from __future__ import annotations

import json
import math
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client, SSRFError

BASE_URL = "https://api.hlrlookup.com"
CREDENTIAL_TYPE = "hlr_lookup_api_key"


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class HlrLookupApiKeyCredential(ClosedModel):
    model_config = ConfigDict(title="HLR Lookup API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.hlrlookup.com/knowledge"})
    credential_type: Literal["hlr_lookup_api_key"] = Field("hlr_lookup_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", description="Paste your API key from your HLR Lookup account.", repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, title="API Secret", description="Paste the API secret paired with your API key.", repr=False, json_schema_extra={"ui:widget": "password"})


class NumberInput(ClosedModel):
    telephone_number: str = Field(..., min_length=1, title="Telephone Number", description="Include the country code, for example 447790606023. Use Input Format for national numbers.")
    input_format: str | None = Field(None, title="Input Format", description="Provider format hint for national numbers; omit for international input.")
    output_format: str | None = Field(None, title="Output Format", description="For example E164, PLUS_E164 or NATIONAL. Omit to use the provider default.")


class LookupInput(NumberInput):
    cache_days_global: int | None = Field(None, ge=0, le=30, strict=True, title="Global Cache Age in Days")
    cache_days_private: int | None = Field(None, ge=0, le=30, strict=True, title="Private Cache Age in Days")
    save_to_cache: Literal["YES", "NO", "PRIVATE"] | None = Field(None, title="Save Result to Cache", description="YES shares new results, PRIVATE saves them to your account, NO disables cache writes. Omit for provider defaults.")
    get_ported_date: Literal["YES", "NO"] | None = Field(None, title="Include Ported Date", description="May incur additional credits.")
    get_landline_status: Literal["YES", "NO"] | None = Field(None, title="Include Landline Status", description="May incur additional credits.")
    get_imsi_hash: Literal["YES", "NO"] | None = Field(None, title="Include IMSI Hash")
    usa_status: Literal["YES", "NO"] | None = Field(None, title="Live USA Status", description="YES incurs an extra credit per US lookup.")


class HlrLookup(LookupInput):
    """Perform a full lookup; may spend credits and update the result cache."""
    operation: Literal["lookup_number"] = Field("lookup_number", title="Look Up Number", json_schema_extra={"ui:hidden": True})


class MnpLookup(LookupInput):
    """Find the current carrier and portability information."""
    operation: Literal["lookup_portability"] = Field("lookup_portability", title="Look Up Number Portability", json_schema_extra={"ui:hidden": True})


class ValidateNumber(NumberInput):
    operation: Literal["validate_number"] = Field("validate_number", title="Validate and Format Number", json_schema_extra={"ui:hidden": True})


class BatchHlrLookup(ClosedModel):
    operation: Literal["lookup_numbers"] = Field("lookup_numbers", title="Look Up Numbers in Batch", json_schema_extra={"ui:hidden": True})
    requests: list[LookupInput] = Field(..., min_length=1, max_length=80, title="Requests", description="One to 80 number requests. Each can set its own cache and optional paid features.")


class BatchMnpLookup(ClosedModel):
    operation: Literal["lookup_portabilities"] = Field("lookup_portabilities", title="Look Up Portability in Batch", json_schema_extra={"ui:hidden": True})
    requests: list[LookupInput] = Field(..., min_length=1, max_length=80, title="Requests")


class BatchValidate(ClosedModel):
    operation: Literal["validate_numbers"] = Field("validate_numbers", title="Validate and Format Numbers in Batch", json_schema_extra={"ui:hidden": True})
    requests: list[NumberInput] = Field(..., min_length=1, max_length=80, title="Requests")


class GetBalance(ClosedModel):
    operation: Literal["get_balance"] = Field("get_balance", title="Get Credit Balance", json_schema_extra={"ui:hidden": True})


class GetPortedDate(LookupInput):
    operation: Literal["lookup_ported_date"] = Field("lookup_ported_date", title="Look Up Ported Date", description="Full lookup requesting the optional ported date; may cost extra credits.", json_schema_extra={"ui:hidden": True})
    get_ported_date: Literal["YES"] = Field("YES", json_schema_extra={"ui:hidden": True})


class GetLandlineStatus(LookupInput):
    operation: Literal["lookup_landline_status"] = Field("lookup_landline_status", title="Look Up Landline Status", description="Full lookup requesting optional landline status; may cost extra credits.", json_schema_extra={"ui:hidden": True})
    get_landline_status: Literal["YES"] = Field("YES", json_schema_extra={"ui:hidden": True})


class GetImsiHash(LookupInput):
    operation: Literal["lookup_imsi_hash"] = Field("lookup_imsi_hash", title="Look Up IMSI Hash", json_schema_extra={"ui:hidden": True})
    get_imsi_hash: Literal["YES"] = Field("YES", json_schema_extra={"ui:hidden": True})


class GetUsaStatus(LookupInput):
    operation: Literal["lookup_usa_status"] = Field("lookup_usa_status", title="Look Up Live USA Status", description="Full lookup with live US status; costs an additional credit per US number.", json_schema_extra={"ui:hidden": True})
    usa_status: Literal["YES"] = Field("YES", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[HlrLookup, MnpLookup, ValidateNumber, BatchHlrLookup, BatchMnpLookup,
    BatchValidate, GetBalance, GetPortedDate, GetLandlineStatus, GetImsiHash, GetUsaStatus], Field(discriminator="operation")]


class HlrLookupConfig(NodeConfig[Operation, HlrLookupApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "lookup_number": "/apiv2/hlr", "lookup_numbers": "/apiv2/hlr",
    "lookup_portability": "/apiv2/mnp", "lookup_portabilities": "/apiv2/mnp",
    "validate_number": "/apiv2/validate", "validate_numbers": "/apiv2/validate",
    "get_balance": "/apiv2/balance", "lookup_ported_date": "/apiv2/hlr",
    "lookup_landline_status": "/apiv2/hlr", "lookup_imsi_hash": "/apiv2/hlr",
    "lookup_usa_status": "/apiv2/hlr",
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items() if key not in {"api_key", "api_secret"}}
    return value


class HlrLookupNode(WorkflowNode):
    integration_type = "automation-hlr-lookup"
    connection_evidence = ConnectionEvidence(operation="get_balance", noun="credit balance", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return HlrLookupConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your HLR Lookup API key and API secret")
        body = config.model_dump(exclude={"operation"}, exclude_none=True)
        body.update(api_key=credential.api_key, api_secret=credential.api_secret)
        operation = config.operation
        secrets = sorted({credential.api_key, credential.api_secret}, key=len, reverse=True)
        try:
            async with guarded_async_client(verify=True, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(45.0)) as client:
                async with client.stream("POST", BASE_URL + ROUTES[operation], json=body, headers={"Accept": "application/json"}) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 4 * 1024 * 1024:
                            raise ValueError("HLR Lookup response exceeded 4 MiB")
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        raise ValueError("HLR Lookup returned a non-JSON response") from None
                    if not isinstance(payload, dict):
                        raise ValueError("HLR Lookup returned an unexpected response shape")
                    payload = _redact(payload, secrets)
                    if response.status_code != 200 or "error" in payload:
                        return {"status": "error", "operation": operation, "status_code": response.status_code,
                            "error": payload.get("message") or payload.get("error") or "HLR Lookup request failed"}
            if operation == "get_balance":
                # The prose docs also show balance wrapped in `body`.
                balance = payload.get("body", payload)
                if not isinstance(balance, dict) or balance.get("Status") != "OK" or type(balance.get("Credits")) not in {int, float} or not math.isfinite(balance["Credits"]):
                    raise ValueError("HLR Lookup did not confirm the credit balance")
                return {"status": "success", "operation": operation, "credits": balance["Credits"]}
            results = payload.get("results")
            if not isinstance(results, list) or not results or len(results) > 80 or any(not isinstance(row, dict) or not isinstance(row.get("error"), str) for row in results):
                raise ValueError("HLR Lookup returned an invalid results array")
            for row in results:
                if row["error"] == "NONE" and (not isinstance(row.get("uuid"), str) or not isinstance(row.get("request_parameters"), dict) or not isinstance(row.get("formatted_telephone_number"), str)):
                    raise ValueError("HLR Lookup returned an incomplete successful result")
            failed = sum(row["error"] != "NONE" for row in results)
            return {"status": "error" if failed == len(results) else "partial" if failed else "success",
                "operation": operation, "results": results, "failed_count": failed,
                **({"error": "; ".join(dict.fromkeys(row["error"] for row in results))} if failed == len(results) else {})}
        except (ValueError, httpx.HTTPError, OSError, SSRFError) as exc:
            message = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, SSRFError) else "HLR Lookup request did not complete; a lookup may have spent credits, so check before retrying"
            return {"status": "error", "operation": operation, "error": _redact(message, secrets)}

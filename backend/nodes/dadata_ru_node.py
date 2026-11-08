"""Dadata's published Suggestions v4.1, Cleaner v1 and Profile v2 APIs.

Suggestions propose candidates for human selection. Cleaning submits records for
standardization and may incur provider charges; neither API edits a remote CRM.
"""
from __future__ import annotations

import math
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class DadataRuCredential(BaseModel):
    model_config = ConfigDict(title="Dadata Ru API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dadata.ru/profile/#info",
            "x-credential-instructions": "Paste the API key and secret key from your Dadata profile. Both are needed for the account balance check and standardization. Suggestions use only the API key. Confirm your email in Dadata before connecting. Cleaning requests may use paid balance."})
    credential_type: Literal["dadata_ru_api_key"] = Field("dadata_ru_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., title="Secret key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "secret_key", mode="before")
    @classmethod
    def validate_secret(cls, value):
        value = clean_secret(value, field_name="Dadata key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Query(_Input):
    query: str = Field(..., min_length=1, max_length=300, description="Search text or identifier, as required by the selected lookup. Suggestions require human selection before use.")
    count: int = Field(10, ge=1, le=20, strict=True, description="Maximum number of candidates; no pagination is offered by these methods.")


class DadataRuGetBalance(_Input):
    """Read the connected account balance in rubles."""
    operation: Literal["get_balance"] = Field("get_balance", json_schema_extra={"ui:hidden": True})


class DadataRuGetDailyStats(_Input):
    """Read today’s service usage for this account."""
    operation: Literal["get_daily_stats"] = Field("get_daily_stats", json_schema_extra={"ui:hidden": True})


class DadataRuGetVersions(_Input):
    """Read service and reference-data versions."""
    operation: Literal["get_versions"] = Field("get_versions", json_schema_extra={"ui:hidden": True})


class DadataRuSuggestParty(_Query):
    """Suggest party. Returns candidates, not a verified match."""
    operation: Literal["suggest_party"] = Field("suggest_party", json_schema_extra={"ui:hidden": True})
    type: Literal["LEGAL", "INDIVIDUAL"] | None = None
    branch_type: list[Literal["MAIN", "BRANCH"]] | None = None
    status: list[Literal["ACTIVE", "LIQUIDATING", "LIQUIDATED", "REORGANIZING", "BANKRUPT"]] | None = None


class DadataRuSuggestFio(_Query):
    """Suggest fio. Returns candidates, not a verified match."""
    operation: Literal["suggest_fio"] = Field("suggest_fio", json_schema_extra={"ui:hidden": True})
    gender: Literal["UNKNOWN", "MALE", "FEMALE"] | None = None
    parts: list[Literal["SURNAME", "NAME", "PATRONYMIC"]] | None = None


class DadataRuSuggestFias(_Query):
    """Suggest fias. Returns candidates, not a verified match."""
    operation: Literal["suggest_fias"] = Field("suggest_fias", json_schema_extra={"ui:hidden": True})


class DadataRuSuggestEmail(_Query):
    """Suggest email. Returns candidates, not a verified match."""
    operation: Literal["suggest_email"] = Field("suggest_email", json_schema_extra={"ui:hidden": True})


class DadataRuSuggestBank(_Query):
    """Suggest bank. Returns candidates, not a verified match."""
    operation: Literal["suggest_bank"] = Field("suggest_bank", json_schema_extra={"ui:hidden": True})


class DadataRuSuggestAddress(_Query):
    """Suggest address. Returns candidates, not a verified match."""
    operation: Literal["suggest_address"] = Field("suggest_address", json_schema_extra={"ui:hidden": True})
    language: Literal["RU", "EN"] | None = None
    division: Literal["ADMINISTRATIVE", "MUNICIPAL"] | None = None


class DadataRuFindParty(_Query):
    """Find party. Returns candidates, not a verified match."""
    operation: Literal["find_party"] = Field("find_party", json_schema_extra={"ui:hidden": True})
    kpp: str | None = Field(None, min_length=9, max_length=9, pattern=r"^[0-9]{9}$", description="Optional tax registration reason code.")
    type: Literal["LEGAL", "INDIVIDUAL"] | None = None
    branch_type: list[Literal["MAIN", "BRANCH"]] | None = None
    status: list[Literal["ACTIVE", "LIQUIDATING", "LIQUIDATED", "REORGANIZING", "BANKRUPT"]] | None = None


class DadataRuFindFias(_Query):
    """Find fias. Returns candidates, not a verified match."""
    operation: Literal["find_fias"] = Field("find_fias", json_schema_extra={"ui:hidden": True})


class DadataRuFindBank(_Query):
    """Find bank. Returns candidates, not a verified match."""
    operation: Literal["find_bank"] = Field("find_bank", json_schema_extra={"ui:hidden": True})
    kpp: str | None = Field(None, min_length=9, max_length=9, pattern=r"^[0-9]{9}$", description="Optional tax registration reason code.")


class DadataRuFindAddress(_Query):
    """Find address. Returns candidates, not a verified match."""
    operation: Literal["find_address"] = Field("find_address", json_schema_extra={"ui:hidden": True})
    language: Literal["RU", "EN"] | None = None
    division: Literal["ADMINISTRATIVE", "MUNICIPAL"] | None = None


class DadataRuFindCompanyByEmail(_Query):
    """Find company by email. Returns candidates, not a verified match."""
    operation: Literal["find_company_by_email"] = Field("find_company_by_email", json_schema_extra={"ui:hidden": True})


class DadataRuFindAffiliatedParty(_Query):
    """Find affiliated party. Returns candidates, not a verified match."""
    operation: Literal["find_affiliated_party"] = Field("find_affiliated_party", json_schema_extra={"ui:hidden": True})
    scope: list[Literal["MANAGERS", "FOUNDERS"]] | None = None


class DadataRuIpLocateAddress(_Input):
    """Locate the approximate city for an explicit IP address."""
    operation: Literal["ip_locate_address"] = Field("ip_locate_address", json_schema_extra={"ui:hidden": True})
    ip: str = Field(..., min_length=1, max_length=45, description="IP address to locate, not a URL.")

    @field_validator("ip")
    @classmethod
    def valid_ip(cls, value):
        import ipaddress
        ipaddress.ip_address(value)
        return value


class DadataRuGeoLocateAddress(_Input):
    """Find address candidates near latitude and longitude."""
    operation: Literal["geo_locate_address"] = Field("geo_locate_address", json_schema_extra={"ui:hidden": True})
    lat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    lon: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    radius_meters: float = Field(100, gt=0, le=1000, allow_inf_nan=False)
    count: int = Field(10, ge=1, le=20, strict=True)
    language: Literal["RU", "EN"] | None = None
    division: Literal["ADMINISTRATIVE", "MUNICIPAL"] | None = None


CleanType = Literal["NAME", "ADDRESS", "PHONE", "AS_IS", "BIRTHDATE", "EMAIL", "VEHICLE", "PASSPORT", "SIMPLE_PARTY_NAME"]


class DadataRuCleanData(_Input):
    """Submit data for paid standardization; returns parsed fields and quality codes."""
    operation: Literal["clean_data"] = Field("clean_data", json_schema_extra={"ui:hidden": True})
    data_type: Literal["name", "address", "phone", "birthdate", "email", "vehicle", "passport"] = Field(..., description="Data type to standardize.")
    data: list[StrictStr] = Field(..., min_length=1, max_length=1, description="The cleaner API accepts one source string per call.")


class DadataRuCleanRecord(_Input):
    """Submit one composite record, keeping the structure and cell order."""
    operation: Literal["clean_record"] = Field("clean_record", json_schema_extra={"ui:hidden": True})
    structure: list[CleanType] = Field(..., min_length=1, max_length=50)
    data: list[list[StrictStr]] = Field(..., min_length=1, max_length=1, description="One record; cells must match the structure order.")

    @model_validator(mode="after")
    def align_cells(self):
        if any(len(row) != len(self.structure) for row in self.data):
            raise ValueError("Each record must have one cell for each structure field")
        return self


DadataRuOperation = Annotated[Union[
    DadataRuGetBalance,
    DadataRuGetDailyStats,
    DadataRuGetVersions,
    DadataRuSuggestParty,
    DadataRuSuggestFio,
    DadataRuSuggestFias,
    DadataRuSuggestEmail,
    DadataRuSuggestBank,
    DadataRuSuggestAddress,
    DadataRuFindParty,
    DadataRuFindFias,
    DadataRuFindBank,
    DadataRuFindAddress,
    DadataRuFindCompanyByEmail,
    DadataRuFindAffiliatedParty,
    DadataRuIpLocateAddress,
    DadataRuGeoLocateAddress,
    DadataRuCleanData,
    DadataRuCleanRecord
], Field(discriminator="operation")]


class DadataRuFullConfig(NodeConfig[DadataRuOperation, DadataRuCredential]):
    pass


ROUTES = {'get_balance': ('GET', 'https://dadata.ru/api/v2/profile/balance'),
 'get_daily_stats': ('GET', 'https://dadata.ru/api/v2/stat/daily'),
 'get_versions': ('GET', 'https://dadata.ru/api/v2/version'),
 'suggest_party': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party'),
 'suggest_fio': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/fio'),
 'suggest_fias': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/fias'),
 'suggest_email': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/email'),
 'suggest_bank': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/bank'),
 'suggest_address': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address'),
 'find_party': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party'),
 'find_fias': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/fias'),
 'find_bank': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/bank'),
 'find_address': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/address'),
 'find_company_by_email': ('POST',
                           'https://suggestions.dadata.ru/suggestions/api/4_1/rs/findByEmail/company'),
 'find_affiliated_party': ('POST',
                           'https://suggestions.dadata.ru/suggestions/api/4_1/rs/findAffiliated/party'),
 'ip_locate_address': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/iplocate/address'),
 'geo_locate_address': ('POST', 'https://suggestions.dadata.ru/suggestions/api/4_1/rs/geolocate/address'),
 'clean_record': ('POST', 'https://cleaner.dadata.ru/api/v1/clean')}


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.secret_key):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    return value


class DadataRuNode(WorkflowNode):
    integration_type = "automation-dadata-ru"
    connection_evidence = ConnectionEvidence(operation="get_balance", noun="account balance", label_keys=("label",))

    @classmethod
    def get_config_model(cls):
        return DadataRuFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Dadata API key and secret key")
        credential = self.config.credentials
        op = self.config.config
        operation = op.operation
        payload = op.model_dump(exclude={"operation"}, exclude_none=True)
        if operation == "clean_data":
            # Official examples use lowercase paths; OpenAPI incorrectly enums uppercase.
            method, url = "POST", "https://cleaner.dadata.ru/api/v1/clean/" + op.data_type
            payload = op.data
        else:
            method, url = ROUTES[operation]
        headers = {"Authorization": "Token " + credential.api_key,
                   "Accept": "application/json", "Content-Type": "application/json"}
        if not url.startswith("https://suggestions.dadata.ru/"):
            headers["X-Secret"] = credential.secret_key
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, headers=headers,
                    **({"json": payload} if method == "POST" else {}))
            if response.status_code != 200:
                message = response.text[:2000]
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        message = str(error.get("message") or error.get("detail") or error.get("code") or message)
                except ValueError:
                    pass
                output = {"status": "error", "http_status": response.status_code, "message": message}
            else:
                if len(response.content) > 10_000_000 or "json" not in response.headers.get("Content-Type", "").lower():
                    raise ValueError("Dadata did not return bounded JSON")
                body = response.json()
                self._validate_response(operation, body)
                output = {"status": "success", "data": body}
                if operation == "get_balance":
                    output["items"] = [{"label": f"Balance: {body['balance']} RUB"}]
        except httpx.RequestError:
            output = {"status": "error", "message": "Dadata request could not be completed; check the connection before retrying paid cleaning."}
        except ValueError:
            output = {"status": "error", "message": "Dadata returned an unexpected response"}
        output = _redact(output, credential)
        await self.emit(output)
        return output

    @staticmethod
    def _validate_response(operation, body):
        if isinstance(body, dict) and any(k in body for k in ("error", "errors", "message")):
            raise ValueError("Dadata returned an error envelope")
        if operation == "get_balance":
            if not isinstance(body, dict) or type(body.get("balance")) not in (int, float) or not math.isfinite(body["balance"]):
                raise ValueError("Missing account balance")
        elif operation in {"get_daily_stats", "get_versions"}:
            if not isinstance(body, dict):
                raise ValueError("Expected profile object")
        elif operation == "clean_data":
            if not isinstance(body, list) or not body or any(not isinstance(row, dict) for row in body):
                raise ValueError("Expected cleaned data")
        elif operation == "clean_record":
            if not isinstance(body, dict) or not isinstance(body.get("structure"), list) or not isinstance(body.get("data"), list):
                raise ValueError("Expected cleaned record")
        elif operation == "ip_locate_address":
            if not isinstance(body, dict) or "location" not in body or (body.get("location") is not None and not isinstance(body["location"], dict)):
                raise ValueError("Expected location or null")
        else:
            if not isinstance(body, dict) or not isinstance(body.get("suggestions"), list):
                raise ValueError("Expected suggestions")
            if any(not isinstance(row, dict) or not isinstance(row.get("value"), str) for row in body["suggestions"]):
                raise ValueError("Invalid suggestion")

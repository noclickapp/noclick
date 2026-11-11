"""OpenFIGI v3 instrument discovery, pinned to the provider's OpenAPI 2.0.0.

All endpoints are read-only, including POST mapping/search/filter. There is no
account identity, webhook registration or created/updated-time polling API.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from datetime import date

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.openfigi.com/v3"
DOCS = "https://www.openfigi.com/api/documentation"


class OpenFIGIAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="OpenFIGI API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.openfigi.com/api",
        "x-credential-instructions": "Paste your OpenFIGI API key, without the header name. Reference data proves API reachability, not account identity. OpenFIGI accepts unauthenticated queries too; this integration always sends your key."})
    credential_type: Literal["openfigi_api_key"] = Field("openfigi_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstrumentFilters(_Input):
    exchCode: str | None = Field(None, title="Exchange Code")
    micCode: str | None = Field(None, title="MIC Code")
    currency: str | None = None
    marketSecDes: str | None = Field(None, title="Market Sector")
    securityType: str | None = Field(None, title="Security Type")
    securityType2: str | None = Field(None, title="Secondary Security Type")
    includeUnlistedEquities: bool | None = Field(None, title="Include Unlisted Equities")
    optionType: Literal["Put", "Call"] | None = Field(None, title="Option Type")
    strike: list[float | None] | None = Field(None, min_length=2, max_length=2, title="Strike Interval")
    contractSize: list[float | None] | None = Field(None, min_length=2, max_length=2, title="Contract Size Interval")
    coupon: list[float | None] | None = Field(None, min_length=2, max_length=2, title="Coupon Interval")
    expiration: list[date | None] | None = Field(None, min_length=2, max_length=2, title="Expiration Interval")
    maturity: list[date | None] | None = Field(None, min_length=2, max_length=2, title="Maturity Interval")
    stateCode: str | None = Field(None, title="State Code")

    @model_validator(mode="after")
    def intervals(self):
        if self.exchCode and self.micCode:
            raise ValueError("Use either Exchange Code or MIC Code, not both")
        for name in ("strike", "contractSize", "coupon", "expiration", "maturity"):
            interval = getattr(self, name)
            if interval is None:
                continue
            low, high = interval
            if low is None and high is None:
                raise ValueError(f"{name} needs at least one endpoint")
            if low is not None and high is not None:
                if low > high:
                    raise ValueError(f"{name} start must not exceed end")
                if isinstance(low, date):
                    try:
                        limit = low.replace(year=low.year + 1)
                    except ValueError:
                        limit = low.replace(year=low.year + 1, day=28)
                    if high > limit:
                        raise ValueError(f"{name} interval must be within one year")
        return self


IdentifierType = Literal['ID_ISIN', 'ID_BB_UNIQUE', 'ID_SEDOL', 'ID_COMMON', 'ID_WERTPAPIER', 'ID_CUSIP', 'ID_BB', 'ID_ITALY', 'ID_EXCH_SYMBOL', 'ID_FULL_EXCHANGE_SYMBOL', 'COMPOSITE_ID_BB_GLOBAL', 'ID_BB_GLOBAL_SHARE_CLASS_LEVEL', 'ID_BB_SEC_NUM_DES', 'ID_BB_GLOBAL', 'TICKER', 'ID_CUSIP_8_CHR', 'OCC_SYMBOL', 'UNIQUE_ID_FUT_OPT', 'OPRA_SYMBOL', 'TRADING_SYSTEM_IDENTIFIER', 'ID_CINS', 'ID_SHORT_CODE', 'BASE_TICKER', 'VENDOR_INDEX_CODE']


class MappingJob(InstrumentFilters):
    idType: IdentifierType = Field(..., title="Identifier Type")
    idValue: str | int = Field(..., title="Identifier Value")

    @model_validator(mode="after")
    def requirements(self):
        if isinstance(self.idValue, str) and not self.idValue.strip():
            raise ValueError("Identifier Value cannot be empty")
        if self.idType in {"BASE_TICKER", "ID_EXCH_SYMBOL"} and not self.securityType2:
            raise ValueError("This identifier requires Secondary Security Type in v3")
        if self.securityType2 in {"Option", "Warrant"} and self.expiration is None:
            raise ValueError("Options and warrants require an Expiration Interval")
        if self.securityType2 == "Pool" and self.maturity is None:
            raise ValueError("Pools require a Maturity Interval")
        return self


class MapIdentifiers(_Input):
    """Map a batch of identifiers to FIGIs. Results retain input order and per-job warnings/errors."""
    operation: Literal["map_identifiers"] = "map_identifiers"
    jobs: list[MappingJob] = Field(..., min_length=1, max_length=100, description="Up to 100 mapping jobs with an API key. Each job has idType and idValue, plus optional instrument filters.")


class SearchInstruments(InstrumentFilters):
    """Search instruments by keywords and optional filters; send next as start for another page."""
    operation: Literal["search_instruments"] = "search_instruments"
    query: str = Field(..., min_length=1, title="Search Keywords")
    start: str | None = Field(None, description="Opaque next token returned by the previous page. Keep the same filters.")


class FilterInstruments(InstrumentFilters):
    """Filter instruments, ordered alphabetically by FIGI, returning total and a continuation token."""
    operation: Literal["filter_instruments"] = "filter_instruments"
    query: str | None = None
    start: str | None = Field(None, description="Opaque next token returned by the previous page. Keep the same filters.")

    @model_validator(mode="after")
    def populated(self):
        if not any(v is not None and v != "" for k, v in self.model_dump().items() if k not in {"operation", "start"}):
            raise ValueError("Supply at least one instrument filter or keyword query")
        return self


class ListIdentifierTypes(_Input):
    """List OpenFIGI identifier types."""
    operation: Literal["list_identifier_types"] = "list_identifier_types"


class ListExchangeCodes(_Input):
    """List OpenFIGI exchange codes."""
    operation: Literal["list_exchange_codes"] = "list_exchange_codes"


class ListMicCodes(_Input):
    """List OpenFIGI market identifier codes."""
    operation: Literal["list_mic_codes"] = "list_mic_codes"


class ListCurrencies(_Input):
    """List OpenFIGI currencies."""
    operation: Literal["list_currencies"] = "list_currencies"


class ListMarketSectors(_Input):
    """List OpenFIGI market sectors."""
    operation: Literal["list_market_sectors"] = "list_market_sectors"


class ListSecurityTypes(_Input):
    """List OpenFIGI security types."""
    operation: Literal["list_security_types"] = "list_security_types"


class ListSecurityTypes2(_Input):
    """List OpenFIGI secondary security types."""
    operation: Literal["list_security_types_2"] = "list_security_types_2"


Operation = Annotated[Union[MapIdentifiers, SearchInstruments, FilterInstruments, ListIdentifierTypes, ListExchangeCodes, ListMicCodes, ListCurrencies, ListMarketSectors, ListSecurityTypes, ListSecurityTypes2], Field(discriminator="operation")]


class OpenFIGIConfig(NodeConfig[Operation, OpenFIGIAPIKeyCredential]):
    pass


VALUE_KEYS = {'list_identifier_types': 'idType', 'list_exchange_codes': 'exchCode', 'list_mic_codes': 'micCode', 'list_currencies': 'currency', 'list_market_sectors': 'marketSecDes', 'list_security_types': 'securityType', 'list_security_types_2': 'securityType2'}


class OpenFIGINode(WorkflowNode):
    integration_type = "automation-openfigi"
    connection_evidence = ConnectionEvidence(operation="list_identifier_types", noun="OpenFIGI reference values", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return OpenFIGIConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an OpenFIGI API key")
        config = self.config.config
        operation = config.operation
        if operation in VALUE_KEYS:
            method, path, body = "GET", "/mapping/values/" + VALUE_KEYS[operation], None
        elif operation == "map_identifiers":
            method, path = "POST", "/mapping"
            body = [job.model_dump(mode="json", exclude_none=True) for job in config.jobs]
        else:
            method, path = "POST", "/search" if operation == "search_instruments" else "/filter"
            body = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers={
                "X-OPENFIGI-APIKEY": credential.api_key, "Accept": "application/json",
            }, **({"json": body} if body is not None else {}))
        if response.status_code != 200:
            # Retain the provider's rejection for manual connect, but never echo the key.
            message = response.text.replace(credential.api_key, "[redacted]")[:1000]
            raise ValueError(f"OpenFIGI HTTP {response.status_code}: {message}")
        payload = response.json()
        if operation == "map_identifiers":
            if not isinstance(payload, list) or len(payload) != len(config.jobs) or not all(isinstance(row, dict) for row in payload):
                raise ValueError("OpenFIGI returned an invalid mapping response")
            return {"results": payload}
        if not isinstance(payload, dict):
            raise ValueError("OpenFIGI returned an invalid response object")
        if payload.get("error"):
            raise ValueError(str(payload["error"]).replace(credential.api_key, "[redacted]"))
        key = "values" if operation in VALUE_KEYS else "data"
        if not isinstance(payload.get(key), list):
            raise ValueError(f"OpenFIGI response is missing {key}")
        return payload

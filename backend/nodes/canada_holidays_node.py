"""Public Canadian statutory holidays, pinned to the provider's OpenAPI 1.15.0.

No account, credentials, writes, webhooks or created/updated-time polling API.
https://github.com/pcraig3/hols/blob/main/API.md
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://canada-holidays.ca"
Province = Literal["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]


def _operation(name, label):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Year(_Input):
    year: int | None = Field(None, ge=2013, le=2038, description="Calendar year. Leave empty for the provider's current year.")
    optional: bool = Field(False, title="Include optional holidays", description="Include holidays optionally observed by employers as well as legislated holidays.")


class ListHolidays(_Year):
    operation: Literal["list_holidays"] = _operation("list_holidays", "List Canadian Holidays")
    federal: bool | None = Field(None, description="Yes: only federal holidays. No: exclude federal holidays. Empty: all holidays.")


class ListFederalHolidays(_Year):
    operation: Literal["list_federal_holidays"] = _operation("list_federal_holidays", "List Federal Holidays")


class ListNonFederalHolidays(_Year):
    operation: Literal["list_non_federal_holidays"] = _operation("list_non_federal_holidays", "List Non-Federal Holidays")


class ListOptionalHolidays(_Input):
    operation: Literal["list_optional_holidays"] = _operation("list_optional_holidays", "List Holidays Including Optional Observances")
    year: int | None = Field(None, ge=2013, le=2038)
    federal: bool | None = Field(None, description="Filter by federal observance; leave empty for all holidays.")


class GetHoliday(_Year):
    operation: Literal["get_holiday"] = _operation("get_holiday", "Get Holiday and Observing Provinces")
    holiday_id: int = Field(..., ge=1, le=35, title="Holiday ID", description="Numeric ID returned by List Canadian Holidays.")


class ListProvinces(_Year):
    operation: Literal["list_provinces"] = _operation("list_provinces", "List Provinces and Their Holidays")


class GetProvince(_Year):
    operation: Literal["get_province"] = _operation("get_province", "Get Province Holiday Calendar")
    province_id: Province = Field(..., title="Province or territory")


class GetProvinceWithOptionalHolidays(_Input):
    operation: Literal["get_province_with_optional_holidays"] = _operation("get_province_with_optional_holidays", "Get Province Calendar Including Optional Holidays")
    province_id: Province = Field(..., title="Province or territory")
    year: int | None = Field(None, ge=2013, le=2038)


class GetApiInfo(_Input):
    operation: Literal["get_api_info"] = _operation("get_api_info", "Get API Information")


class GetApiSpec(_Input):
    operation: Literal["get_api_spec"] = _operation("get_api_spec", "Get Published API Specification")


CanadaHolidaysConfig = Annotated[Union[ListHolidays, ListFederalHolidays, ListNonFederalHolidays,
    ListOptionalHolidays, GetHoliday, ListProvinces, GetProvince,
    GetProvinceWithOptionalHolidays, GetApiInfo, GetApiSpec], Field(discriminator="operation")]


class CanadaHolidaysFullConfig(NodeConfig[CanadaHolidaysConfig, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        return None if value == {} else value


class CanadaHolidaysNode(WorkflowNode):
    integration_type = "automation-canada-holidays"
    connection_evidence = ConnectionEvidence(operation="get_api_info", noun="public Canadian holiday API", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return CanadaHolidaysFullConfig

    async def execute(self, inputs):
        config = self.config.config
        params = {}
        if isinstance(config, (GetApiInfo, GetApiSpec)):
            path = "/api/v1" + ("/spec" if isinstance(config, GetApiSpec) else "")
        else:
            if isinstance(config, (GetProvince, GetProvinceWithOptionalHolidays)):
                path = "/api/v1/provinces/" + config.province_id
            elif isinstance(config, ListProvinces):
                path = "/api/v1/provinces"
            elif isinstance(config, GetHoliday):
                path = "/api/v1/holidays/" + str(config.holiday_id)
            else:
                path = "/api/v1/holidays"
            if config.year is not None:
                params["year"] = config.year
            include_optional = True if isinstance(config, (ListOptionalHolidays, GetProvinceWithOptionalHolidays)) else config.optional
            params["optional"] = "true" if include_optional else "false"
            federal = True if isinstance(config, ListFederalHolidays) else False if isinstance(config, ListNonFederalHolidays) else getattr(config, "federal", None)
            if federal is not None:
                params["federal"] = "true" if federal else "false"
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request("GET", BASE + path, params=params,
                headers={"Accept": "text/yaml, application/json" if isinstance(config, GetApiSpec) else "application/json"})
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("Canada Holidays returned a redirect")
        if isinstance(config, GetApiSpec):
            return {"status": "success", "operation": config.operation, "spec": response.text}
        result = response.json()
        if not isinstance(result, dict) or "error" in result:
            raise ValueError("Canada Holidays returned an invalid response or error envelope")
        key = "message" if isinstance(config, GetApiInfo) else "province" if isinstance(config, (GetProvince, GetProvinceWithOptionalHolidays)) else "provinces" if isinstance(config, ListProvinces) else "holiday" if isinstance(config, GetHoliday) else "holidays"
        if key in {"holidays", "provinces"}:
            if not isinstance(result.get(key), list) or any(not isinstance(row, dict) for row in result[key]):
                raise ValueError("Canada Holidays returned an invalid list")
        elif key == "message":
            if not isinstance(result.get(key), str):
                raise ValueError("Canada Holidays returned invalid API information")
        elif not isinstance(result.get(key), dict):
            raise ValueError("Canada Holidays returned an invalid detail")
        return {**result, "status": "success", "operation": config.operation}

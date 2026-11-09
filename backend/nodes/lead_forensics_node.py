"""Lead Forensics WebApi_v2 reads, pinned to the provider's published v1.0 API.

The published API offers retrieval only. Every operation makes one GET, with
explicit page controls and no automatic retries against the provider's quotas.
Visit times use the account's global portal time zone, not the user's zone.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://interact.leadforensics.com/WebApi_v2"
CREDENTIAL_TYPE = "lead_forensics_api_key"
DOCS = "https://leadforensics-api.readme.io/docs/getting-started"


class LeadForensicsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Lead Forensics API Key",
        json_schema_extra={"x-credential-url": DOCS,
            "x-credential-instructions": "Paste the ClientID and API key supplied for your API-enabled Lead Forensics account. The key is sent in Authorization-Token, alongside ClientID. Request API access from Lead Forensics support if your account is not enabled. Connection checks list your account's assigned users; this does not verify your personal identity."})
    credential_type: Literal["lead_forensics_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, max_length=128, title="Client ID", description="Your Lead Forensics ClientID, supplied with the API key.")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("client_id", "api_key", mode="before")
    @classmethod
    def header_value(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste a single header value without whitespace")
        return value


def _portal_date(value):
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError("Use a valid ISO date or documented portal timestamp")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("datefrom", "dateto", check_fields=False)
    @classmethod
    def portal_date(cls, value):
        if value is not None:
            _portal_date(value)
        return value

    @model_validator(mode="after")
    def date_order(self):
        start, end = getattr(self, "datefrom", None), getattr(self, "dateto", None)
        if (start is None) != (end is None):
            raise ValueError("Provide both start and end dates")
        if start is not None and _portal_date(start) > _portal_date(end):
            raise ValueError("End date must be on or after start date")
        return self


class ListBusinesses(_Input):
    """GetAllBusinesses: one documented API request."""
    operation: Literal["list_businesses"] = Field("list_businesses", json_schema_extra={"ui:hidden": True})
    datefrom: date = Field(..., description='The date from which the businesses have visited')
    dateto: date = Field(..., description='The date to which the businesses have visited')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class GetBusiness(_Input):
    """GetBusiness: one documented API request."""
    operation: Literal["get_business"] = Field("get_business", json_schema_extra={"ui:hidden": True})
    businessid: int = Field(..., ge=1, le=2147483647, description='The Lead Forensics unique business identifier')


class ListBusinessesByCategory(_Input):
    """GetBusinessesByCategory: one documented API request."""
    operation: Literal["list_businesses_by_category"] = Field("list_businesses_by_category", json_schema_extra={"ui:hidden": True})
    categoryid: int = Field(..., ge=1, le=2147483647, description='The unique identifier for the category that the businesses are assigned to')
    datefrom: str = Field(..., min_length=10, max_length=19, description='The date from which the businesses have visited')
    dateto: str = Field(..., min_length=10, max_length=19, description='The date to which the businesses have visited')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListBusinessesByAssignee(_Input):
    """GetBusinessesByAssignedTo: one documented API request."""
    operation: Literal["list_businesses_by_assignee"] = Field("list_businesses_by_assignee", json_schema_extra={"ui:hidden": True})
    clientuserid: int = Field(..., ge=1, le=2147483647, description='The unique identifier for the user that the businesses are assigned to')
    datefrom: str = Field(..., min_length=10, max_length=19, description='The date from which the businesses have visited')
    dateto: str = Field(..., min_length=10, max_length=19, description='The date to which the businesses have visited')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListVisits(_Input):
    """GetAllVisits: one documented API request."""
    operation: Literal["list_visits"] = Field("list_visits", json_schema_extra={"ui:hidden": True})
    datefrom: str = Field(..., min_length=10, max_length=19, description='The date from which the businesses have visited')
    dateto: str = Field(..., min_length=10, max_length=19, description='The date to which the businesses have visited')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class GetVisit(_Input):
    """GetVisit: one documented API request."""
    operation: Literal["get_visit"] = Field("get_visit", json_schema_extra={"ui:hidden": True})
    visitid: int = Field(..., ge=1, le=2147483647, description='The unique identifier for the visit to be returned')


class GetVisitDetails(_Input):
    """GetVisitDetails: one documented API request."""
    operation: Literal["get_visit_details"] = Field("get_visit_details", json_schema_extra={"ui:hidden": True})
    visitid: int = Field(..., ge=1, le=2147483647, description='The unique identifier for the visit details to be returned')


class ListVisitsByBusiness(_Input):
    """GetVisitsByBusiness: one documented API request."""
    operation: Literal["list_visits_by_business"] = Field("list_visits_by_business", json_schema_extra={"ui:hidden": True})
    businessid: int = Field(..., ge=1, le=2147483647, description='The unique identifier for the business to return the visits for')
    datefrom: str = Field(..., min_length=10, max_length=19, description='The date from which the businesses have visited')
    dateto: str = Field(..., min_length=10, max_length=19, description='The date to which the businesses have visited')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListVisitsByConversion(_Input):
    """GetVisitsByConversion: one documented API request."""
    operation: Literal["list_visits_by_conversion"] = Field("list_visits_by_conversion", json_schema_extra={"ui:hidden": True})
    conversionid: int = Field(..., ge=1, le=2147483647, description='The unique identifier for the conversion to return the visits for')
    datefrom: str = Field(..., min_length=10, max_length=19, description='The date from which the businesses have visited')
    dateto: str = Field(..., min_length=10, max_length=19, description='The date to which the businesses have visited')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListVisitsByTriggerReport(_Input):
    """GetVisitsByTriggerReport: one documented API request."""
    operation: Literal["list_visits_by_trigger_report"] = Field("list_visits_by_trigger_report", json_schema_extra={"ui:hidden": True})
    triggerreportid: int = Field(..., ge=1, le=2147483647, description='The unique identifier for the trigger report to return the visits for')
    datefrom: str = Field(..., min_length=10, max_length=19, description='The date from which the businesses have visited')
    dateto: str = Field(..., min_length=10, max_length=19, description='The date to which the businesses have visited')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListRecentVisits(_Input):
    """Get10MostRecent: one documented API request."""
    operation: Literal["list_recent_visits"] = Field("list_recent_visits", json_schema_extra={"ui:hidden": True})
    datefrom: str | None = Field(None, min_length=10, max_length=19, description='The date from which the businesses have visited')
    dateto: str | None = Field(None, min_length=10, max_length=19, description='The date to which the businesses have visited')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListPages(_Input):
    """GetPages: one documented API request."""
    operation: Literal["list_pages"] = Field("list_pages", json_schema_extra={"ui:hidden": True})
    datefrom: date = Field(..., description='The date from which the visit pages will be returned. If no value is supplied, the current day will be used.')
    dateto: date = Field(..., description='The date to which the visit pages will be returned. If no value is entered, a value of a day later than the date from will be used.')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListPagesByVisit(_Input):
    """GetPagesByVisit: one documented API request."""
    operation: Literal["list_pages_by_visit"] = Field("list_pages_by_visit", json_schema_extra={"ui:hidden": True})
    visitid: int = Field(..., ge=1, le=2147483647, description='The unique identifier for the visit to be returned')
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListIndustries(_Input):
    """GetIndustryList: one documented API request."""
    operation: Literal["list_industries"] = Field("list_industries", json_schema_extra={"ui:hidden": True})
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListCountries(_Input):
    """GetCountryList: one documented API request."""
    operation: Literal["list_countries"] = Field("list_countries", json_schema_extra={"ui:hidden": True})
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListEmployeeBands(_Input):
    """GetEmployeeBandList: one documented API request."""
    operation: Literal["list_employee_bands"] = Field("list_employee_bands", json_schema_extra={"ui:hidden": True})
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListCategories(_Input):
    """GetCategoryList: one documented API request."""
    operation: Literal["list_categories"] = Field("list_categories", json_schema_extra={"ui:hidden": True})
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListAssignees(_Input):
    """GetAssignedToList: one documented API request."""
    operation: Literal["list_assignees"] = Field("list_assignees", json_schema_extra={"ui:hidden": True})
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListConversions(_Input):
    """GetConversionList: one documented API request."""
    operation: Literal["list_conversions"] = Field("list_conversions", json_schema_extra={"ui:hidden": True})
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListTriggerReports(_Input):
    """GetTriggerReportList: one documented API request."""
    operation: Literal["list_trigger_reports"] = Field("list_trigger_reports", json_schema_extra={"ui:hidden": True})
    pagesize: int = Field(5, ge=1, le=1000, description='Number of records to return in a page of results')
    pageno: int = Field(1, ge=1, le=1000000, description='The particular page of results to return')


class ListDateRanges(_Input):
    """GetDateList: one documented API request."""
    operation: Literal["list_date_ranges"] = Field("list_date_ranges", json_schema_extra={"ui:hidden": True})


class GetNewLeads(_Input):
    """New Leads: one documented API request."""
    operation: Literal["get_new_leads"] = Field("get_new_leads", json_schema_extra={"ui:hidden": True})
    numberOfResults: int = Field(10, ge=1, le=1000, description='The number of records to return in the call response')
    clientuserid: int | None = Field(None, ge=1, le=2147483647, description='The unique identifier of the user to return the funnel for (returned from the GetAssignedToList reference data call)')


class GetLeadFunnel(_Input):
    """Lead Funnel: one documented API request."""
    operation: Literal["get_lead_funnel"] = Field("get_lead_funnel", json_schema_extra={"ui:hidden": True})
    dateid: int = Field(1, ge=1, le=2147483647, description='The date range to return the results for (detailed in the GetDateList reference call)')
    numberOfResults: int = Field(10, ge=1, le=1000, description='The number of records to return in the call response')
    clientuserid: int | None = Field(None, ge=1, le=2147483647, description='The unique identifier of the user to return the funnel for (returned from the GetAssignedToList reference data call)')


class GetMostActiveCompanies(_Input):
    """Most Active Companies: one documented API request."""
    operation: Literal["get_most_active_companies"] = Field("get_most_active_companies", json_schema_extra={"ui:hidden": True})
    dateid: int = Field(1, ge=1, le=2147483647, description='The date range to return the results for (detailed in the GetDateList reference call)')
    numberOfResults: int = Field(10, ge=1, le=1000, description='The number of records to return in the call response')


class GetVisitKpi(_Input):
    """Visits: one documented API request."""
    operation: Literal["get_visit_kpi"] = Field("get_visit_kpi", json_schema_extra={"ui:hidden": True})
    datetypeid: int = Field(1, ge=1, le=3, description='The date type returned. Allowed values are 1: days, 2:weeks, 3:months')
    numberOfResults: int = Field(10, ge=1, le=1000, description='The number of records to return in the call response')
    clientuserid: int | None = Field(None, ge=1, le=2147483647, description='The unique identifier of the user to return the funnel for (returned from the GetAssignedToList reference data call)')


LeadForensicsOperation = Annotated[Union[
    ListBusinesses, GetBusiness, ListBusinessesByCategory, ListBusinessesByAssignee, ListVisits, GetVisit, GetVisitDetails, ListVisitsByBusiness, ListVisitsByConversion, ListVisitsByTriggerReport, ListRecentVisits, ListPages, ListPagesByVisit, ListIndustries, ListCountries, ListEmployeeBands, ListCategories, ListAssignees, ListConversions, ListTriggerReports, ListDateRanges, GetNewLeads, GetLeadFunnel, GetMostActiveCompanies, GetVisitKpi
], Field(discriminator="operation")]


class LeadForensicsConfig(NodeConfig[LeadForensicsOperation, LeadForensicsAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {'list_businesses': ('/Business/GetAllBusinesses', 'BusinessList', True),
 'get_business': ('/Business/GetBusiness', None, False),
 'list_businesses_by_category': ('/Business/GetBusinessesByCategory', 'BusinessList', True),
 'list_businesses_by_assignee': ('/Business/GetBusinessesByAssignedTo', 'BusinessList', True),
 'list_visits': ('/Visit/GetAllVisits', 'SiteVisitList', True),
 'get_visit': ('/Visit/GetVisit', None, False),
 'get_visit_details': ('/Visit/GetVisitDetails', None, False),
 'list_visits_by_business': ('/Visit/GetVisitsByBusiness', 'SiteVisitList', True),
 'list_visits_by_conversion': ('/Visit/GetVisitsByConversion', 'SiteVisitList', True),
 'list_visits_by_trigger_report': ('/Visit/GetVisitsByTriggerReport', 'SiteVisitList', True),
 'list_recent_visits': ('/Visit/Get10MostRecent', 'SiteVisitList', True),
 'list_pages': ('/Page/GetPages', 'PageVisitList', True),
 'list_pages_by_visit': ('/Page/GetPagesByVisit', 'PageVisitList', True),
 'list_industries': ('/Reference/GetIndustryList', 'List', True),
 'list_countries': ('/Reference/GetCountryList', 'List', True),
 'list_employee_bands': ('/Reference/GetEmployeeBandList', 'List', True),
 'list_categories': ('/Reference/GetCategoryList', 'List', True),
 'list_assignees': ('/Reference/GetAssignedToList', 'List', True),
 'list_conversions': ('/Reference/GetConversionList', 'List', True),
 'list_trigger_reports': ('/Reference/GetTriggerReportList', 'List', True),
 'list_date_ranges': ('/Reference/GetDateList', 'List', False),
 'get_new_leads': ('/KPI/NewLeads', 'NewLeadsList', False),
 'get_lead_funnel': ('/KPI/LeadFunnel', 'LeadFunnelList', False),
 'get_most_active_companies': ('/KPI/MostActiveCompanies', 'MostActiveCompaniesList', False),
 'get_visit_kpi': ('/KPI/Visits', 'VisitsList', False)}


def _redact(value, credential):
    if isinstance(value, str):
        return value.replace(credential.api_key, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    return value


def _response(body, operation, config):
    path, array, paged = OPERATIONS[operation]
    if not isinstance(body, dict) or any(k.lower() in {"error", "errors", "exception", "message"} for k in body):
        raise ValueError("Lead Forensics returned an error or unexpected response")
    if array:
        if not isinstance(body.get(array), list) or any(not isinstance(row, dict) for row in body[array]):
            raise ValueError("Lead Forensics did not return the documented record list")
        data = body[array]
    else:
        required = {"get_business": ("BusinessID", "Name"), "get_visit": ("VisitID", "BusinessID"),
                    "get_visit_details": ("Conversions", "Assignees", "Duration", "Browser", "OperatingSystem", "Device")}[operation]
        if not all(k in body for k in required):
            raise ValueError("Lead Forensics did not return the documented record")
        data = body
        identity = {"get_business": ("BusinessID", "businessid"), "get_visit": ("VisitID", "visitid")}.get(operation)
        if identity and (type(body[identity[0]]) is not int or body[identity[0]] != getattr(config, identity[1])):
            raise ValueError("Lead Forensics returned a different resource")
        if operation == "get_visit_details" and any(not isinstance(body[k], list) for k in ("Conversions", "Assignees")):
            raise ValueError("Lead Forensics visit details are malformed")
    result = {"data": data}
    if paged:
        keys = ("PageSize", "PageCount", "RecordCount", "CurrentPage")
        if any(type(body.get(k)) is not int or body[k] < 0 for k in keys):
            raise ValueError("Lead Forensics pagination metadata is missing or invalid")
        current, total = body["CurrentPage"], body["PageCount"]
        if current != config.pageno:
            raise ValueError("Lead Forensics returned a different page")
        result["pagination"] = {k: body[k] for k in keys}
        result["has_more"] = current < total
        result["next_page"] = current + 1 if current < total else None
        result["complete"] = current >= total
    return result


class LeadForensicsNode(WorkflowNode):
    integration_type = "automation-lead-forensics"
    connection_evidence = ConnectionEvidence(noun="assigned users", operation="list_assignees", label_keys=("Name", "ID"))

    @classmethod
    def get_config_model(cls):
        return LeadForensicsConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Lead Forensics API key and Client ID")
        credential = self.config.credentials
        config = self.config.config
        path = OPERATIONS[config.operation][0]
        params = config.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE_URL + path, params=params,
                    headers={"ClientID": credential.client_id, "Authorization-Token": credential.api_key, "Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Lead Forensics could not be reached; retry the read later") from None
        if response.status_code != 200:
            output = {"status": "error", "success": False, "http_status": response.status_code,
                      "message": _redact(response.text, credential)[:2000]}
        else:
            if len(response.content) > 10_000_000 or "application/json" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("Lead Forensics did not return bounded JSON")
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Lead Forensics returned invalid JSON") from None
            output = {"status": "success", "success": True, "operation": config.operation,
                      **_response(body, config.operation, config)}
            output = _redact(output, credential)
        await self.emit(output)
        return output

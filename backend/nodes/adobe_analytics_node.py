"""Native Adobe Analytics 2.0 reporting and owned component management.

Discovery binds each company before resource access. Provider responses are
bounded and projected by the node; raw errors and credential bytes stay private.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Literal, Union
import math
from email.utils import parsedate_to_datetime
import base64
import hashlib
import json
import re
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator, model_serializer

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence

from utils.ssrf import SSRFError, guarded_async_client

KIND = "adobe_analytics_token"
HOST = "https://analytics.adobe.io"
MAX_BYTES = 4 * 1024 * 1024


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_@.-]{1,160}", value) or value in {".", ".."}:
        raise ValueError("Adobe Analytics identifier is invalid.")
    return value


def component_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:variables/|metrics/)?[A-Za-z0-9_.-]{1,160}", value):
        raise ValueError("Adobe Analytics component identifier is invalid.")
    return value


class AdobeAnalyticsTokenCredential(BaseModel):
    credential_type: Literal["adobe_analytics_token"] = Field(KIND, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Issued OAuth Access Token", json_schema_extra={"ui:widget": "password"})
    client_id: str = Field(..., title="API Key (Client ID)", description="The Adobe Developer client ID that issued this OAuth token.")
    global_company_id: str = Field(..., title="Global Company ID", description="Select the Analytics company returned by discovery/me.")
    expires_at: str | None = Field(None, title="Token Expiry", description="Known ISO 8601 expiry with timezone. NoClick does not mint or refresh tokens.")
    model_config = ConfigDict(title="Adobe Analytics Access Token", extra="ignore", json_schema_extra={
        "x-credential-url": "https://developer.adobe.com/analytics-apis/docs/2.0/guides/",
        "x-credential-instructions": "Use an already-issued OAuth User or Server-to-Server access token, its public client ID, and a discovery-authorized global company ID. Analytics product-profile permissions are required. Legacy JWT grants are excluded."
    })

    @field_validator("access_token", "client_id")
    @classmethod
    def header_value(cls, value):
        if not value or len(value) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Adobe Analytics header credential is invalid.")
        return value

    @field_validator("global_company_id")
    @classmethod
    def company(cls, value):
        return identifier(value)

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Token expiry must include a timezone.")
        return value

    @model_serializer(mode="wrap")
    def tagged(self, handler):
        return {**handler(self), "credential_type": KIND}


def shape(data):
    try:
        if not isinstance(data, dict) or data.get("credential_type", KIND) != KIND:
            raise ValueError()
        return AdobeAnalyticsTokenCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Adobe Analytics credential shape is invalid.") from None


def check_expiry(data):
    expiry = data.get("expires_at")
    if expiry and datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise ValueError("Adobe Analytics authentication failed: issued token has expired; replace the credential.")


@dataclass
class GrantLease:
    """Validated issued token, with local expiry checks on each request.

    Saved credential resolution and admission use staging's standard loaders.
    This integration does not mint, refresh, or independently reload tokens.
    """
    data: dict

    async def recheck(self):
        check_expiry(self.data)


async def lease(data):
    result = GrantLease(shape(data))
    await result.recheck()
    return result


def retry_after(value):
    if not value:
        return None
    try:
        seconds = int(value) if value.isdigit() else int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        return min(max(seconds, 0), 86400)
    except (ValueError, TypeError, OverflowError):
        return None


class AnalyticsClient:
    def __init__(self, grant):
        self.grant = grant
        self.company = grant.data["global_company_id"]

    async def request(self, method, path, *, params=None, body=None, discovery=False, partial=False):
        # Paths are assembled exclusively from closed operations below. A caller
        # cannot supply a URL, redirect target, arbitrary headers or query body.
        await self.grant.recheck()
        url = HOST + ("/discovery/me" if discovery else "/api/" + quote(self.company, safe="") + path)
        headers = {"Accept": "application/json", "Authorization": "Bearer " + self.grant.data["access_token"],
                   "x-api-key": self.grant.data["client_id"]}
        try:
            async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=25.0) as client:
                async with client.stream(method, url, headers=headers, params=params, json=body) as response:
                    if response.status_code not in ({200, 206} if partial else {200}):
                        status = response.status_code
                        delay = retry_after(response.headers.get("Retry-After")) if status == 429 else None
                        suffix = f"; retry after {delay} seconds" if delay is not None else ""
                        raise ValueError(f"Adobe Analytics HTTP {status}{suffix}.")
                    if "json" not in response.headers.get("Content-Type", "").lower():
                        raise ValueError("Adobe Analytics returned an unexpected response media type.")
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > MAX_BYTES:
                            raise ValueError("Adobe Analytics response exceeded the bounded size.")
                    try:
                        data = json.loads(payload, parse_constant=lambda _s: (_ for _ in ()).throw(ValueError()))
                    except Exception:
                        raise ValueError("Adobe Analytics returned malformed JSON.") from None
                    if not isinstance(data, (dict, list)) or (isinstance(data, dict) and any(k in data for k in ("error", "error_code", "errorCode"))):
                        raise ValueError("Adobe Analytics rejected the request or returned an invalid envelope.")
                    status = response.status_code
        except (httpx.HTTPError, SSRFError):
            raise ValueError("Adobe Analytics transport failed; the provider outcome may be unknown.") from None
        await self.grant.recheck()
        return data, status

    async def discover(self):
        data, _ = await self.request("GET", "", discovery=True)
        if not isinstance(data, dict) or not isinstance(data.get("imsUserId"), str) or not data["imsUserId"] or not isinstance(data.get("imsOrgs"), list):
            raise ValueError("Adobe Analytics discovery did not identify the authenticated account.")
        companies = []
        if len(data["imsOrgs"]) > 100:
            raise ValueError("Adobe Analytics discovery exceeded the bounded size.")
        for org in data["imsOrgs"]:
            if not isinstance(org, dict) or not isinstance(org.get("companies"), list):
                raise ValueError("Adobe Analytics discovery envelope is invalid.")
            for company in org["companies"]:
                if not isinstance(company, dict) or not isinstance(company.get("companyName"), str) or not company["companyName"]:
                    raise ValueError("Adobe Analytics company identity is invalid.")
                companies.append({"id": identifier(company.get("globalCompanyId")), "name": company["companyName"]})
                if len(companies) > 500:
                    raise ValueError("Adobe Analytics discovery exceeded the bounded size.")
        matched = [c for c in companies if c["id"] == self.company]
        if not matched or len({c["name"] for c in matched}) != 1:
            raise ValueError("Adobe Analytics selected company is not authorized by discovery.")
        return {"ims_user_id": data["imsUserId"], "company_id": self.company,
                "company_name": matched[0]["name"], "companies": companies}

    async def suite(self, rsid):
        data, _ = await self.request("GET", "/reportsuites/collections/suites/" + quote(identifier(rsid), safe=""),
                                     params={"expansion": "name,currency"})
        if not isinstance(data, dict) or data.get("rsid") != rsid:
            raise ValueError("Adobe Analytics report suite does not match its requested parent.")
        return project(data, SUITE_FIELDS, key="rsid")


SUITE_FIELDS = ("rsid", "id", "name", "currency", "timezoneZoneinfo", "parentRsid")
COMPONENT_FIELDS = ("id", "name", "title", "description", "rsid", "reportSuiteName", "type", "category",
                    "segmentable", "allowedForReporting", "calculated", "template", "precision", "polarity", "created", "modified")


def project(data, fields, *, key="id"):
    if not isinstance(data, dict) or not isinstance(data.get(key), str) or not data[key]:
        raise ValueError("Adobe Analytics resource identity is missing.")
    return {k: data[k] for k in fields if k in data and (data[k] is None or isinstance(data[k], (str, bool, int, float)))}


def page(data, number, limit, *, fields=COMPONENT_FIELDS, key="id"):
    if isinstance(data, list):
        rows, last, metadata = data, None, {}
    elif isinstance(data, dict) and isinstance(data.get("content"), list):
        rows, last = data["content"], data.get("lastPage")
        if last is not None and type(last) is not bool:
            raise ValueError("Adobe Analytics pagination envelope is invalid.")
        if "number" in data and (type(data["number"]) is not int or data["number"] != number):
            raise ValueError("Adobe Analytics pagination returned a different page.")
        for key in ("totalPages", "totalElements", "numberOfElements"):
            if key in data and (type(data[key]) is not int or data[key] < 0):
                raise ValueError("Adobe Analytics pagination counts are invalid.")
        if "numberOfElements" in data and data["numberOfElements"] != len(rows):
            raise ValueError("Adobe Analytics pagination count differs from its rows.")
        metadata = {k: data[k] for k in ("totalPages", "totalElements", "number", "numberOfElements", "lastPage") if k in data}
    else:
        raise ValueError("Adobe Analytics list envelope is invalid.")
    if len(rows) > limit:
        raise ValueError("Adobe Analytics list exceeded its requested page size.")
    return {"items": [project(row, fields, key=key) for row in rows], "page": number,
            "next_page": number + 1 if rows and last is not True and (last is False or len(rows) == limit) else None,
            "continuation_confirmed": last is False, **metadata}


def cursor(scope, offset):
    return base64.urlsafe_b64encode(json.dumps({"scope": hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
                                               "page": offset}, separators=(",", ":")).encode()).decode().rstrip("=")


def cursor_page(scope, token):
    if not token:
        return 0
    try:
        if len(token) > 256:
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        number = data["page"]
        if type(number) is not int or not 0 <= number <= 10000 or cursor(scope, number) != token:
            raise ValueError()
        return number
    except Exception:
        raise ValueError("Adobe Analytics picker continuation belongs to a different scope or is invalid.") from None



def selection(name, *, dependencies=(), required=True):
    resource_type = {"rsid": "adobe-report-suite", "dimension_id": "adobe-dimension", "segment_id": "adobe-segment",
                     "calculated_metric_id": "adobe-calculated-metric"}.get(name, "adobe-metric")
    return Field(... if required else None, title=name.replace("_", " ").title(), json_schema_extra={
        "x-resource-type": resource_type,
        "x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True,
                              **({"depends_on": dependencies[0]} if dependencies else {})}})


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Saved FlowCanvas label/_settings are ordinary metadata.


class DiscoverCompanies(Config):
    operation: Literal["discover_companies"] = "discover_companies"


class ListSuites(Config):
    operation: Literal["list_report_suites"] = "list_report_suites"
    page: int = Field(0, ge=0, le=10000)
    limit: int = Field(25, ge=1, le=100, description="One page; array-only responses offer a candidate next page, without a fabricated total.")
    search: str | None = Field(None, max_length=120, description="Filter the suite ID with rsidContains.")


class SuiteConfig(Config):
    rsid: str = selection("rsid")

    @field_validator("rsid")
    @classmethod
    def suite_identifier(cls, value):
        return identifier(value)


class GetSuite(SuiteConfig):
    operation: Literal["get_report_suite"] = "get_report_suite"


class MetadataList(SuiteConfig):
    offset: int = Field(0, ge=0, le=2000, description="Local slice of the documented unpaginated metadata list.")
    limit: int = Field(100, ge=1, le=100)


class ListDimensions(MetadataList):
    operation: Literal["list_dimensions"] = "list_dimensions"


class ListMetrics(MetadataList):
    operation: Literal["list_metrics"] = "list_metrics"


class GetDimension(SuiteConfig):
    operation: Literal["get_dimension"] = "get_dimension"
    dimension_id: str = selection("dimension_id", dependencies=("rsid",))

    @field_validator("dimension_id")
    @classmethod
    def dimension(cls, value):
        value = component_id(value)
        if not value.startswith("variables/"):
            raise ValueError("Use a full variables/ dimension ID.")
        return value


class GetMetric(SuiteConfig):
    operation: Literal["get_metric"] = "get_metric"
    metric_id: str = selection("metric_id", dependencies=("rsid",))

    @field_validator("metric_id")
    @classmethod
    def metric(cls, value):
        value = component_id(value)
        if not value.startswith("metrics/"):
            raise ValueError("Use a full metrics/ metric ID.")
        return value


class ComponentList(SuiteConfig):
    page: int = Field(0, ge=0, le=10000)
    limit: int = Field(25, ge=1, le=100)
    search: str | None = Field(None, max_length=120)


class ListSegments(ComponentList):
    operation: Literal["list_segments"] = "list_segments"


class GetSegment(SuiteConfig):
    operation: Literal["get_segment"] = "get_segment"
    segment_id: str = selection("segment_id", dependencies=("rsid",))

    @field_validator("segment_id")
    @classmethod
    def segment_identifier(cls, value):
        return identifier(value)


class ListCalculatedMetrics(ComponentList):
    operation: Literal["list_calculated_metrics"] = "list_calculated_metrics"


class GetCalculatedMetric(SuiteConfig):
    operation: Literal["get_calculated_metric"] = "get_calculated_metric"
    calculated_metric_id: str = selection("calculated_metric_id", dependencies=("rsid",))

    @field_validator("calculated_metric_id")
    @classmethod
    def calculated_identifier(cls, value):
        return identifier(value)


class CreateCalculatedMetric(SuiteConfig):
    operation: Literal["create_calculated_metric"] = "create_calculated_metric"
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    numerator_metric_id: str = selection("numerator_metric_id", dependencies=("rsid",))
    denominator_metric_id: str = selection("denominator_metric_id", dependencies=("rsid",))
    precision: int = Field(2, ge=0, le=10)
    metric_type: Literal["DECIMAL", "PERCENT", "CURRENCY", "TIME"] = "DECIMAL"
    confirm_component_creation: Literal[True] = Field(..., description="Creates a persistent calculated metric for the token's Analytics user. It does not create shares.")

    @field_validator("numerator_metric_id", "denominator_metric_id")
    @classmethod
    def metric_identifier(cls, value):
        value = component_id(value)
        if not value.startswith("metrics/"):
            raise ValueError("Use full metrics/ IDs for the ratio.")
        return value


class UpdateCalculatedMetric(GetCalculatedMetric):
    operation: Literal["update_calculated_metric"] = "update_calculated_metric"
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    confirm_component_update: Literal[True] = Field(..., description="Updates an owned, unshared metric's name/description; formula, owner and suite are preserved.")


class DeleteCalculatedMetric(GetCalculatedMetric):
    operation: Literal["delete_calculated_metric"] = "delete_calculated_metric"
    confirm_component_deletion: Literal[True] = Field(..., description="Deletes the owned, unshared metric. This is a provider mutation, without an atomic share/revision guard.")


class RunReport(SuiteConfig):
    operation: Literal["run_report"] = "run_report"
    metric_ids: list[str] = Field(..., min_length=1, max_length=10, description="Full metrics/ IDs available in this report suite.")
    dimension_id: str | None = selection("dimension_id", dependencies=("rsid",), required=False)
    start: str = Field(..., description="Suite-local ISO date/time, without a timezone, e.g. 2026-01-01T00:00:00.")
    end: str = Field(..., description="Exclusive end in suite-local time. NoClick does not convert UTC to suite time.")
    page: int = Field(0, ge=0, le=10000)
    limit: int = Field(100, ge=1, le=100)

    @field_validator("metric_ids")
    @classmethod
    def report_metrics(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Report metric IDs must be distinct.")
        for value in values:
            if not component_id(value).startswith("metrics/"):
                raise ValueError("Use full metrics/ IDs.")
        return values

    @field_validator("dimension_id")
    @classmethod
    def report_dimension(cls, value):
        if value is not None and not component_id(value).startswith("variables/"):
            raise ValueError("Use a full variables/ ID.")
        return value

    @model_validator(mode="after")
    def report_dates(self):
        first, last = datetime.fromisoformat(self.start), datetime.fromisoformat(self.end)
        if first.tzinfo is not None or last.tzinfo is not None or "T" not in self.start or "T" not in self.end or first >= last or (last-first).days > 366:
            raise ValueError("Reports require an ordered suite-local date range of at most 366 days.")
        if self.dimension_id is None and self.page != 0:
            raise ValueError("A totals report has no dimension pages.")
        return self


AdobeAnalyticsConfig = Annotated[Union[DiscoverCompanies, ListSuites, GetSuite, ListDimensions, GetDimension,
    ListMetrics, GetMetric, ListSegments, GetSegment, ListCalculatedMetrics, GetCalculatedMetric,
    CreateCalculatedMetric, UpdateCalculatedMetric, DeleteCalculatedMetric, RunReport], Field(discriminator="operation")]


class AdobeAnalyticsNodeConfig(NodeConfig[AdobeAnalyticsConfig, AdobeAnalyticsTokenCredential]):
    pass


class AdobeAnalyticsNode(WorkflowNode):
    integration_type = "automation-adobe-analytics"
    connection_evidence = ConnectionEvidence(operation="list_report_suites", noun="Analytics report suites",
        label_keys=("name", "rsid"), proves="account")
    edit_examples = ["List report suites and available dimensions", "Report weekly visits by page",
                     "Create an owned calculated ratio metric without sharing it"]

    @classmethod
    def get_config_model(cls):
        return AdobeAnalyticsNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        data = config_data
        try:
            credential = data.get("credentials")
            if isinstance(credential, dict) and credential.get("credential_type", KIND) != KIND:
                raise ValueError()
            return TypeAdapter(cls.get_config_model()).validate_python(runtime_config_view(data, cls.get_config_model()))
        except Exception:
            raise ValueError("Adobe Analytics configuration or credential shape is invalid.") from None

    @classmethod
    def validate_credential(cls, data):
        shape(data)
        return True

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Already-issued tokens have no refresh flow. Fail on known expiry.
        return (await lease(credential_data)).data

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        fields = {"rsid", "dimension_id", "metric_id", "numerator_metric_id", "denominator_metric_id", "segment_id", "calculated_metric_id"}
        if field_name not in fields:
            return {"options": [], "next_page_token": None}
        grant = await lease(credential_data)
        rsid = None if field_name == "rsid" else identifier((context or {}).get("rsid"))
        scope = {"company": grant.data["global_company_id"], "field": field_name, "rsid": rsid, "search": search or ""}
        number = cursor_page(scope, page_token)
        client = AnalyticsClient(grant)
        await client.discover()
        if rsid is None:
            raw, _ = await client.request("GET", "/reportsuites/collections/suites", params={"page": number, "limit": 50, **({"rsidContains": search} if search else {})})
            output = page(raw, number, 50, fields=SUITE_FIELDS, key="rsid")
            rows, next_number = output["items"], output["next_page"]
        else:
            await client.suite(rsid)
            if field_name in {"dimension_id", "metric_id", "numerator_metric_id", "denominator_metric_id"}:
                path = "/dimensions" if field_name == "dimension_id" else "/metrics"
                rows = await cls._metadata(client, path, rsid)
                if search:
                    rows = [row for row in rows if search.casefold() in str(row.get("name", row["id"])).casefold()]
                offset = number * 50
                next_number = number + 1 if offset + 50 < len(rows) else None
                rows = rows[offset:offset + 50]
            else:
                path = "/segments" if field_name == "segment_id" else "/calculatedmetrics"
                output = await cls._components(client, path, rsid, number, 50, search)
                rows, next_number = output["items"], output["next_page"]
        return {"options": [{"value": row.get("rsid") if rsid is None else row["id"],
                             "label": row.get("name") or row.get("title") or row.get("rsid") or row["id"]} for row in rows],
                "next_page_token": cursor(scope, next_number) if next_number is not None else None}

    @staticmethod
    async def _metadata(client, path, rsid):
        raw, _ = await client.request("GET", path, params={"rsid": rsid, "expansion": "allowedForReporting"})
        if not isinstance(raw, list) or len(raw) > 2000:
            raise ValueError("Adobe Analytics metadata list is invalid or exceeds the 2000-item bound.")
        return [project(row, COMPONENT_FIELDS) for row in raw]

    @staticmethod
    async def _components(client, path, rsid, number, limit, search=None, only_id=None):
        params = {"rsid" if path == "/segments" else "rsids": rsid, "page": number, "limit": limit}
        if search:
            params["name"] = search
        if only_id:
            params["segmentFilter" if path == "/segments" else "filterByIds"] = only_id
        # Omitting includeType preserves Adobe's documented owned-only default.
        raw, _ = await client.request("GET", path, params=params)
        output = page(raw, number, limit)
        if any(row.get("rsid") != rsid for row in output["items"]):
            raise ValueError("Adobe Analytics component list crossed its report-suite parent.")
        return output

    @classmethod
    async def _component(cls, client, path, rsid, resource_id):
        identifier(resource_id)
        owned = await cls._components(client, path, rsid, 0, 100, only_id=resource_id)
        if not any(row["id"] == resource_id for row in owned["items"]):
            raise ValueError("Adobe Analytics component is not in the token user's owned suite-scoped list.")
        raw, _ = await client.request("GET", path + "/" + quote(resource_id, safe=""))
        if not isinstance(raw, dict) or raw.get("id") != resource_id or raw.get("rsid") != rsid:
            raise ValueError("Adobe Analytics component identity or report-suite parent differs.")
        return raw

    @classmethod
    async def _private_metric(cls, client, rsid, resource_id):
        if resource_id.startswith("cm_"):
            raise ValueError("Adobe Analytics calculated-metric templates cannot be modified.")
        raw = await cls._component(client, "/calculatedmetrics", rsid, resource_id)
        me, _ = await client.request("GET", "/users/me")
        owner = raw.get("owner")
        if not isinstance(me, dict) or type(me.get("loginId")) is not int or not isinstance(owner, dict) or owner.get("id") != me["loginId"] or raw.get("template") is True:
            raise ValueError("Adobe Analytics component ownership is not established for this token.")
        shares, _ = await client.request("POST", "/componentmetadata/shares/component/search",
            params={"page": 0, "limit": 100}, body={"componentType": "calculatedMetric", "componentIds": [resource_id]})
        if not isinstance(shares, dict) or not isinstance(shares.get("content"), list) or shares.get("lastPage") is not True or shares.get("number") != 0:
            raise ValueError("Adobe Analytics component sharing could not be completely checked.")
        for row in shares["content"]:
            if not isinstance(row, dict) or row.get("componentId") != resource_id or row.get("componentType") != "calculatedMetric" or not isinstance(row.get("shares"), list) or row["shares"]:
                raise ValueError("Adobe Analytics shared or mismatched components cannot be modified.")
        return raw

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Adobe Analytics issued-token credential is required.")
        original = self.node_data.get("credentials") or self.config.credentials.model_dump()
        grant = await lease(original)
        client, config = AnalyticsClient(grant), self.config.config
        discovery = await client.discover()
        op = config.operation
        if op == "discover_companies":
            return discovery
        if op == "list_report_suites":
            raw, _ = await client.request("GET", "/reportsuites/collections/suites", params={"page": config.page, "limit": config.limit, **({"rsidContains": config.search} if config.search else {})})
            return page(raw, config.page, config.limit, fields=SUITE_FIELDS, key="rsid")
        suite = await client.suite(config.rsid)
        if op == "get_report_suite":
            return suite
        if op in {"list_dimensions", "list_metrics"}:
            rows = await self._metadata(client, "/dimensions" if op == "list_dimensions" else "/metrics", config.rsid)
            return {"items": rows[config.offset:config.offset + config.limit], "next_offset": config.offset + config.limit if config.offset + config.limit < len(rows) else None}
        if op in {"get_dimension", "get_metric"}:
            dimension = op == "get_dimension"
            resource = config.dimension_id if dimension else config.metric_id
            # Adobe's single-component paths use the suffix, while report IDs
            # and metadata output retain full variables/ or metrics/ prefixes.
            raw, _ = await client.request("GET", ("/dimensions/" if dimension else "/metrics/") + quote(resource.split("/", 1)[1], safe=""), params={"rsid": config.rsid})
            if not isinstance(raw, dict) or raw.get("id") != resource:
                raise ValueError("Adobe Analytics returned a different requested component.")
            return project(raw, COMPONENT_FIELDS)
        if op in {"list_segments", "list_calculated_metrics"}:
            return await self._components(client, "/segments" if op == "list_segments" else "/calculatedmetrics", config.rsid, config.page, config.limit, config.search)
        if op in {"get_segment", "get_calculated_metric"}:
            raw = await self._component(client, "/segments" if op == "get_segment" else "/calculatedmetrics", config.rsid,
                                        config.segment_id if op == "get_segment" else config.calculated_metric_id)
            return project(raw, COMPONENT_FIELDS)
        if op == "create_calculated_metric":
            metrics = await self._metadata(client, "/metrics", config.rsid)
            allowed = {row["id"] for row in metrics if row.get("allowedForReporting") is not False}
            if not {config.numerator_metric_id, config.denominator_metric_id} <= allowed:
                raise ValueError("Adobe Analytics ratio metrics are unavailable in this suite.")
            body = {"name": config.name, "description": config.description, "rsid": config.rsid,
                "precision": config.precision, "type": config.metric_type, "definition": {
                    "func": "calc-metric", "version": [1, 0, 0], "formula": {"func": "divide",
                    "col1": {"func": "metric", "name": config.numerator_metric_id},
                    "col2": {"func": "metric", "name": config.denominator_metric_id}}}}
            validation, _ = await client.request("POST", "/calculatedmetrics/validate", body=body)
            if not isinstance(validation, dict) or validation.get("valid") is not True:
                raise ValueError("Adobe Analytics did not validate the submitted ratio definition.")
            raw, _ = await client.request("POST", "/calculatedmetrics", body=body)
            if not isinstance(raw, dict) or raw.get("rsid") != config.rsid or not isinstance(raw.get("id"), str):
                raise ValueError("Adobe Analytics create response is invalid; creation outcome requires manual readback.")
            verified = await self._private_metric(client, config.rsid, raw["id"])
            return {"created": project(verified, COMPONENT_FIELDS), "sharing_check": "no_visible_shares", "atomic_visibility_guarantee": False}
        if op in {"update_calculated_metric", "delete_calculated_metric"}:
            resource = config.calculated_metric_id
            await self._private_metric(client, config.rsid, resource)
            if op == "update_calculated_metric":
                body = {"name": config.name, **({"description": config.description} if config.description is not None else {})}
                raw, _ = await client.request("PUT", "/calculatedmetrics/" + quote(resource, safe=""), body=body)
                if not isinstance(raw, dict) or raw.get("id") != resource or raw.get("rsid") != config.rsid:
                    raise ValueError("Adobe Analytics update outcome requires manual readback.")
                verified = await self._private_metric(client, config.rsid, resource)
                if verified.get("name") != config.name or (config.description is not None and verified.get("description") != config.description):
                    raise ValueError("Adobe Analytics update readback did not match the submitted fields.")
                return {"updated": project(verified, COMPONENT_FIELDS), "atomic_revision_guarantee": False}
            raw, _ = await client.request("DELETE", "/calculatedmetrics/" + quote(resource, safe=""))
            # Swagger documents DeleteResponse.result as an opaque string,
            # without an enum. Do not invent success words or echo its message.
            if not isinstance(raw, dict) or not isinstance(raw.get("result"), str) or not raw["result"]:
                raise ValueError("Adobe Analytics delete response is invalid; outcome requires manual readback.")
            remaining = await self._components(client, "/calculatedmetrics", config.rsid, 0, 100, only_id=resource)
            if any(row["id"] == resource for row in remaining["items"]):
                raise ValueError("Adobe Analytics deletion readback still lists the component.")
            return {"id": resource, "delete_http_status": 200, "deleted_from_owned_list": True, "hard_erasure_verified": False}
        if op == "run_report":
            return await self._report(client, config)
        raise ValueError("Adobe Analytics operation is unsupported.")

    @classmethod
    async def _report(cls, client, config):
        metrics = await cls._metadata(client, "/metrics", config.rsid)
        allowed = {row["id"] for row in metrics if row.get("allowedForReporting") is not False}
        if not set(config.metric_ids) <= allowed:
            raise ValueError("Adobe Analytics report metrics are unavailable in the selected suite.")
        if config.dimension_id is not None:
            dimensions = await cls._metadata(client, "/dimensions", config.rsid)
            if not any(row["id"] == config.dimension_id and row.get("allowedForReporting") is not False for row in dimensions):
                raise ValueError("Adobe Analytics report dimension is unavailable in the selected suite.")
        body = {"rsid": config.rsid, "globalFilters": [{"type": "dateRange", "dateRange": config.start + "/" + config.end}],
            "metricContainer": {"metrics": [{"columnId": str(i), "id": metric} for i, metric in enumerate(config.metric_ids)]},
            "settings": {"page": config.page, "limit": config.limit, "reflectRequest": False}}
        if config.dimension_id is not None:
            body["dimension"] = config.dimension_id
        raw, status = await client.request("POST", "/reports", body=body, partial=True)
        if not isinstance(raw, dict) or not isinstance(raw.get("summaryData"), dict):
            raise ValueError("Adobe Analytics report envelope is invalid.")
        columns = raw.get("columns", {})
        expected = [str(i) for i in range(len(config.metric_ids))]
        if not isinstance(columns, dict) or columns.get("columnIds", expected) != expected:
            raise ValueError("Adobe Analytics report columns differ from the request.")
        rows = raw.get("rows", [])
        if not isinstance(rows, list) or len(rows) > config.limit:
            raise ValueError("Adobe Analytics report exceeded its bounded row count.")
        def values(items):
            if not isinstance(items, list) or len(items) != len(expected) or any(v is not None and (type(v) not in (int, float) or not math.isfinite(v)) for v in items):
                raise ValueError("Adobe Analytics report value shape is invalid.")
            return items
        projected = []
        for row in rows:
            if not isinstance(row, dict) or config.dimension_id is None or not isinstance(row.get("itemId"), str) or not isinstance(row.get("value"), str):
                raise ValueError("Adobe Analytics report row identity is invalid.")
            projected.append({"itemId": row["itemId"], "value": row["value"], "data": values(row.get("data"))})
        summary = {key: values(raw["summaryData"][key]) for key in ("totals", "filteredTotals") if key in raw["summaryData"]}
        if not summary:
            raise ValueError("Adobe Analytics report did not return usable totals.")
        errors = columns.get("columnErrors", [])
        allowed_errors = {"unauthorized_metric", "unauthorized_dimension", "unauthorized_dimension_global", "anomaly_detection_failure_unexpected_item_count", "anomaly_detection_failure_tsa_service", "not_enabled_metric", "not_enabled_dimension", "not_enabled_dimension_global"}
        if not isinstance(errors, list) or any(not isinstance(error, dict) or error.get("columnId") not in expected or error.get("errorCode") not in allowed_errors for error in errors):
            raise ValueError("Adobe Analytics report partial-error envelope is invalid.")
        last = raw.get("lastPage")
        if config.dimension_id is not None and (type(last) is not bool or type(raw.get("number")) is not int or raw["number"] != config.page):
            raise ValueError("Adobe Analytics report pagination is invalid.")
        for key in ("totalPages", "totalElements", "numberOfElements"):
            if key in raw and (type(raw[key]) is not int or raw[key] < 0):
                raise ValueError("Adobe Analytics report pagination counts are invalid.")
        if "numberOfElements" in raw and raw["numberOfElements"] != len(projected):
            raise ValueError("Adobe Analytics report count differs from its rows.")
        return {"rsid": config.rsid, "dimension": config.dimension_id, "metric_ids": config.metric_ids,
            "rows": projected, "summaryData": summary, "partial": status == 206 or bool(errors),
            "column_errors": [{"columnId": error["columnId"], "errorCode": error["errorCode"]} for error in errors],
            "page": config.page, "next_page": config.page + 1 if config.dimension_id and last is False else None,
            **{key: raw[key] for key in ("totalPages", "totalElements", "numberOfElements") if key in raw}}

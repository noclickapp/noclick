"""CFPB's public Consumer Complaint Database, pinned to ccdb5-api OpenAPI 1.0.0.

The published contract has four read endpoints, no writes and no authentication.
Polling watches a bounded window of the 100 most recently received complaints;
it does not promise to catch more than 100 arrivals between successful polls.
"""
from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1"


def _operation(name, label, *, trigger=False):
    return Field(name, title=label, json_schema_extra={
        "ui:hidden": True, "x-display-name": label,
        "x-category": "Triggers" if trigger else "Consumer Complaints",
        **({"x-is-trigger": True} if trigger else {}),
    })


class ComplaintFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_public_response: list[str] | None = None
    company_response: list[str] | None = None
    company_received_min: date | None = Field(None, description="Inclusive date sent to company (YYYY-MM-DD).")
    company_received_max: date | None = Field(None, description="Exclusive date sent to company (YYYY-MM-DD).")
    date_received_min: date | None = Field(None, description="Inclusive date received (YYYY-MM-DD).")
    date_received_max: date | None = Field(None, description="Exclusive date received (YYYY-MM-DD).")
    issue: list[str] | None = Field(None, description="Issue, or issue•subissue.")
    product: list[str] | None = Field(None, description="Product, or product•subproduct, e.g. Mortgage•FHA mortgage.")
    state: list[str] | None = Field(None, description="State abbreviations, e.g. CA, VA.")
    submitted_via: list[str] | None = None
    tags: list[str] | None = None
    timely: list[str] | None = None
    zip_code: list[str] | None = None

    @model_validator(mode="after")
    def ordered_dates(self):
        for prefix in ("date_received", "company_received"):
            start, end = getattr(self, prefix + "_min"), getattr(self, prefix + "_max")
            if start is not None and end is not None and start >= end:
                raise ValueError("Exclusive end date must be after the inclusive start date")
        return self


class SearchComplaints(ComplaintFilters):
    operation: Literal["search_complaints"] = _operation("search_complaints", "Search Complaints")
    company: list[str] | None = Field(None, description="Company names, sent as repeated query parameters.")
    search_term: str | None = None
    field: Literal["all", "company"] = "all"
    size: int = Field(10, ge=1, le=100)
    frm: int | None = Field(None, ge=1, le=100000, description="Result offset. Omit for the first page; combine with search_after for deep pagination.")
    search_after: str | None = Field(None, description="Use the API's _meta.break_points values as documented in CFPB's pagination guide.")
    sort: Literal["relevance_desc", "relevance_asc", "created_date_desc", "created_date_asc"] = "relevance_desc"
    no_aggs: bool = False
    no_highlight: bool = False


class GetComplaint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["get_complaint"] = _operation("get_complaint", "Get Complaint")
    complaint_id: int = Field(..., ge=0, le=9999999999, title="Complaint ID")


class SuggestCompanies(ComplaintFilters):
    operation: Literal["suggest_companies"] = _operation("suggest_companies", "Suggest Companies")
    text: str = Field(..., min_length=1, title="Company search text")
    size: int = Field(10, ge=1, le=100)


class SuggestZipCodes(ComplaintFilters):
    operation: Literal["suggest_zip_codes"] = _operation("suggest_zip_codes", "Suggest ZIP Codes")
    text: str = Field(..., min_length=1, title="ZIP code prefix")
    size: int = Field(10, ge=1, le=100)


class OnNewComplaint(PollTriggerConfigBase, ComplaintFilters):
    operation: Literal["on_new_complaint"] = _operation("on_new_complaint", "On New Complaint", trigger=True)
    company: list[str] | None = Field(None, description="Filter to these company names.")
    search_term: str | None = None
    field: Literal["all", "company"] = "all"
    model_config = ConfigDict(extra="ignore", json_schema_extra={
        "x-requires-webhook": True,
        "description": "Watch the latest 100 matching complaints by received date. Existing complaints are baselined when armed; more than 100 arrivals between polls can be missed. CFPB generally publishes daily and may publish older received dates later.",
    })


ConsumerfinanceConfig = Annotated[Union[
    SearchComplaints, GetComplaint, SuggestCompanies, SuggestZipCodes, OnNewComplaint,
], Field(discriminator="operation")]


class ConsumerfinanceFullConfig(NodeConfig[ConsumerfinanceConfig, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        return None if value == {} else value


class ConsumerfinanceNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-consumerfinance"
    connection_evidence = ConnectionEvidence(
        operation="search_complaints", noun="public consumer complaints", proves="reachability",
    )
    edit_examples = ["Find mortgage complaints about this company", "Watch for new matching consumer complaints"]

    @classmethod
    def get_config_model(cls):
        return ConsumerfinanceFullConfig

    @staticmethod
    async def _get(path, params):
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.get(BASE + path, params=params, headers={"Accept": "application/json"})
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("CFPB returned a redirect instead of API data")
        body = response.json()
        if isinstance(body, dict) and ("error" in body or "errors" in body):
            raise ValueError("CFPB returned an API error")
        return body

    async def execute(self, inputs):
        config = self.config.config
        operation = config.operation
        if isinstance(config, GetComplaint):
            body = await self._get("/" + str(config.complaint_id), {})
            if not isinstance(body, dict):
                raise ValueError("CFPB returned an invalid complaint")
            return {"status": "success", "operation": operation, "data": body}

        fields = set(ComplaintFilters.model_fields)
        if isinstance(config, (SuggestCompanies, SuggestZipCodes)):
            fields |= {"text", "size"}
            path = "/_suggest_company" if isinstance(config, SuggestCompanies) else "/_suggest_zip"
        else:
            fields |= {"company", "search_term", "field", "size", "frm", "search_after", "sort", "no_aggs", "no_highlight"}
            path = "/"
        params = config.model_dump(mode="json", include=fields, exclude_none=True)
        if isinstance(config, OnNewComplaint):
            params.update(size=100, sort="created_date_desc", no_aggs=True, no_highlight=True)
        body = await self._get(path, params)
        if isinstance(config, (SuggestCompanies, SuggestZipCodes)):
            if not isinstance(body, list) or any(not isinstance(item, str) for item in body):
                raise ValueError("CFPB returned invalid suggestions")
            return {"status": "success", "operation": operation, "suggestions": body}
        if not isinstance(body, dict) or not isinstance(body.get("hits"), dict) or not isinstance(body["hits"].get("hits"), list):
            raise ValueError("CFPB returned an invalid search result")
        if not isinstance(config, OnNewComplaint):
            # Preserve aggregations, totals and pagination break points exactly.
            return {"status": "success", "operation": operation, "data": body}
        complaints = []
        for hit in body["hits"]["hits"]:
            complaint = hit.get("_source") if isinstance(hit, dict) else None
            identifier = complaint.get("complaint_id") if isinstance(complaint, dict) else None
            # OpenAPI declares an integer; the public API also returns decimal strings.
            if not (type(identifier) is int and identifier >= 0 or
                    isinstance(identifier, str) and identifier.isascii() and identifier.isdecimal()):
                raise ValueError("CFPB returned a complaint without a numeric ID")
            complaints.append(complaint)
        fresh = await self._filter_unseen(complaints, lambda item: str(item["complaint_id"]))
        return {"status": "success", "operation": operation, "complaints": fresh, "new_complaint_count": len(fresh), "window_size": 100}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") != "on_new_complaint":
            return super().resolve_agent_event(output)
        complaints = output.get("complaints")
        if not complaints:
            return None
        lines = [
            f"- Complaint {item['complaint_id']} about {item.get('company') or 'an unnamed company'}: "
            f"{item.get('product') or 'unspecified product'} — {item.get('issue') or 'unspecified issue'}; "
            f"received {item.get('date_received') or 'unknown date'}, {item.get('state') or 'unknown state'}. "
            f"Company response: {item.get('company_response') or 'not provided'}. "
            f"https://www.consumerfinance.gov/data-research/consumer-complaints/search/detail/{item['complaint_id']}"
            for item in complaints[:10]
        ]
        if len(complaints) > 10:
            lines.append(f"… and {len(complaints) - 10} more complaints in this poll.")
        return {"text": f"CFPB published {len(complaints)} new matching complaint(s):\n" + "\n".join(lines), "conversation_key": None}

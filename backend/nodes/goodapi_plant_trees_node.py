"""GoodAPI v2 impact actions. Contract: https://app.thegoodapi.com/openapi.json.

Each operation makes one request. Live writes can create billable impact;
NoClick never retries them automatically. Use a stable idempotency key for retries.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.thegoodapi.com"
CREDENTIAL_TYPE = "goodapi_plant_trees_api_key"



class GoodapiPlantTreesCredential(BaseModel):
    model_config = ConfigDict(title="Goodapi Plant Trees API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.thegoodapi.com",
            "x-credential-instructions": "Paste your production or test API key from GoodAPI. Test keys do not generate Stripe charges. Paste only the key, without Authorization or Bearer. Live tree and plastic actions are metered; donation endpoints are early access.",
        })
    credential_type: Literal["goodapi_plant_trees_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your GoodAPI API key")
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the raw API key without a header or prefix")
        return value



class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")



class PlantTreesConfig(_Input):
    """Plant trees."""
    operation: Literal["plant_trees"] = Field("plant_trees", json_schema_extra={"ui:hidden": True})
    count: int = Field(..., ge=1, description='Number of trees to plant.')
    project_id: str | None = Field(None, description="Optional project identifier to direct the tree planting to a specific project (e.g. 'veritree-kenya', 'veritree-us', 'veritree-bc-kelp', 'samauma-brazil', 'arbor-michigan', 'veritree-haiti'). Defaults to 'veritree-kenya'.")
    attribution: str | None = Field(None, description='Free-form tag for grouping registrations (e.g. order ID, campaign).')
    metadata: dict[str, Any] | None = Field(None, description='Arbitrary key-value pairs stored with the registration.')
    idempotency_key: str | None = Field(None, description='Unique key to prevent duplicate registrations.')


class ListPlantedTreesConfig(_Input):
    """List planted trees."""
    operation: Literal["list_planted_trees"] = Field("list_planted_trees", json_schema_extra={"ui:hidden": True})
    attribution_key: str | None = Field(None, description='Filter by attribution tag.')
    id: str | None = Field(None, description='Fetch a single registration by ID.')
    created_at: date | None = Field(None, description='Registrations created on or after this date (YYYY-MM-DD).')
    end_at: date | None = Field(None, description='Registrations created on or before this date (YYYY-MM-DD).')
    metadata: str | None = Field(None, description='JSON-encoded metadata filter, e.g. `{"order_id":"ord_123"}`.')
    project_id: str | None = Field(None, description="Filter registrations by project identifier (e.g. 'veritree-kenya', 'veritree-us').")


class RefundTreesConfig(_Input):
    """Refund a tree registration in the current billing cycle with a Stripe usage record. Omit count for a full refund."""
    operation: Literal["refund_trees"] = Field("refund_trees", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Registration ID to refund.')
    count: int | None = Field(None, ge=1, description='Optional partial refund count. If omitted, the full registration is refunded.')
    reason: str | None = Field(None, description='Optional human-readable reason for the refund.')
    idempotency_key: str | None = Field(None, description='Unique key to prevent duplicate refund processing.')
    metadata: dict[str, Any] | None = Field(None, description='Arbitrary key-value pairs stored with the refund.')


class ListTreeProjectsConfig(_Input):
    """List tree planting projects."""
    operation: Literal["list_tree_projects"] = Field("list_tree_projects", json_schema_extra={"ui:hidden": True})
    locale: str = Field('en', description="Locale code for localized text (e.g. 'en', 'fr', 'de', 'es', 'ja', 'nl', 'zh-CN'). Defaults to 'en'.")
    all: bool = Field(False, description='If true, includes private projects.')


class GetTreeProjectConfig(_Input):
    """Get tree planting project by ID."""
    operation: Literal["get_tree_project"] = Field("get_tree_project", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description="Project identifier (e.g. 'veritree-kenya', 'veritree-us').")
    locale: str = Field('en', description="Locale code for localized text (e.g. 'en', 'fr', 'de', 'es'). Defaults to 'en'.")


class RescuePlasticBottlesConfig(_Input):
    """Rescue ocean-bound plastic bottles."""
    operation: Literal["rescue_plastic_bottles"] = Field("rescue_plastic_bottles", json_schema_extra={"ui:hidden": True})
    count: int = Field(..., ge=1, description='Number of plastic bottles to rescue.')
    attribution: str | None = Field(None, description='Free-form tag for grouping registrations.')
    metadata: dict[str, Any] | None = Field(None, description='Arbitrary key-value pairs stored with the registration.')
    idempotency_key: str | None = Field(None, description='Unique key to prevent duplicate registrations.')


class ListRescuedBottlesConfig(_Input):
    """List rescued bottles."""
    operation: Literal["list_rescued_bottles"] = Field("list_rescued_bottles", json_schema_extra={"ui:hidden": True})
    attribution_key: str | None = Field(None, description='Filter by attribution tag.')
    id: str | None = Field(None, description='Fetch a single registration by ID.')
    created_at: date | None = Field(None, description='Registrations created on or after this date (YYYY-MM-DD).')
    end_at: date | None = Field(None, description='Registrations created on or before this date (YYYY-MM-DD).')
    metadata: str | None = Field(None, description='JSON-encoded metadata filter, e.g. `{"order_id":"ord_123"}`.')


class RefundPlasticBottlesConfig(_Input):
    """Refund a plastic bottle registration in the current billing cycle with a Stripe usage record. Omit count for a full refund."""
    operation: Literal["refund_plastic_bottles"] = Field("refund_plastic_bottles", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Registration ID to refund.')
    count: int | None = Field(None, ge=1, description='Optional partial refund count. If omitted, the full registration is refunded.')
    reason: str | None = Field(None, description='Optional human-readable reason for the refund.')
    idempotency_key: str | None = Field(None, description='Unique key to prevent duplicate refund processing.')
    metadata: dict[str, Any] | None = Field(None, description='Arbitrary key-value pairs stored with the refund.')


class GetEvidenceConfig(_Input):
    """Read global planting evidence cached for 30 days; it is not filtered to your organization."""
    operation: Literal["get_evidence"] = Field("get_evidence", json_schema_extra={"ui:hidden": True})


class GetTreeEvidenceConfig(_Input):
    """Get tree planting timeline and evidence."""
    operation: Literal["get_tree_evidence"] = Field("get_tree_evidence", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='The unique tree registration ID.')
    evidence_stage: Literal['registered', 'funds_distributed', 'planted', 'planted_and_verified'] | None = Field(None, description='Optional testing parameter to return a mocked evidence response at a specific milestone stage (`registered`, `funds_distributed`, or `planted`). Only permitted for test API keys. Seeded from a verified Kenya planting registration.')


class SearchCharitiesConfig(_Input):
    """Search charities."""
    operation: Literal["search_charities"] = Field("search_charities", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, description='Search by charity name.')
    id: str | None = Field(None, description='Change nonprofit ID for direct lookup (detail mode). Returns a curated nonprofit object with written consent info instead of a paginated search.')
    ein: str | None = Field(None, description='Search by Employer Identification Number.')
    page_size: int = Field(20, ge=1, le=20, description='Number of results per page.')
    page: int = Field(1, ge=1, description='Page number (1-indexed).')


class CreateDonationConfig(_Input):
    """Record a USD donation (early access). Activate donation billing first; use an idempotency key for retries."""
    operation: Literal["create_donation"] = Field("create_donation", json_schema_extra={"ui:hidden": True})
    amount_cents: int = Field(..., ge=1, description='Donation amount in cents (must be > 0).')
    ein: str | None = Field(None, description='Employer Identification Number of the charity. At least one of `ein` or `nonprofit_id` is required.')
    nonprofit_id: str | None = Field(None, description='Provider-specific nonprofit identifier. At least one of `ein` or `nonprofit_id` is required.')
    charity_name: str | None = Field(None, description='Human-readable charity name. Auto-filled from the search result if omitted.')
    idempotency_key: str | None = Field(None, description='Unique key to prevent duplicate donations.')
    attribution: str | None = Field(None, description='Free-form tag for grouping donations.')
    metadata: dict[str, Any] | None = Field(None, description='Arbitrary key-value pairs stored with the donation.')

    @model_validator(mode="after")
    def charity(self):
        if not self.ein and not self.nonprofit_id:
            raise ValueError("Provide the charity EIN or nonprofit ID")
        return self


class ListDonationsConfig(_Input):
    """List donations."""
    operation: Literal["list_donations"] = Field("list_donations", json_schema_extra={"ui:hidden": True})
    attribution: str | None = Field(None, description='Filter by attribution tag.')
    metadata_key: str | None = Field(None, description='Filter by metadata key (existence check unless `metadata_value` is also provided).')
    metadata_value: str | None = Field(None, description='Filter by metadata value. Requires `metadata_key`.')
    start_date: date | None = Field(None, description='Filter donations on or after this date (YYYY-MM-DD).')
    end_date: date | None = Field(None, description='Filter donations on or before this date (YYYY-MM-DD, inclusive).')
    page: int = Field(1, ge=1, description='Page number (1-indexed).')
    page_size: int = Field(20, ge=1, le=100, description='Number of results per page.')


class SubscribeDonationsConfig(_Input):
    """Activate donation billing items once before making live donations (early access)."""
    operation: Literal["subscribe_donations"] = Field("subscribe_donations", json_schema_extra={"ui:hidden": True})


class RefundDonationConfig(_Input):
    """Mark a donation refunded (early access). This does not automatically reverse Stripe usage."""
    operation: Literal["refund_donation"] = Field("refund_donation", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Unique donation ID to refund.')
    reason: str | None = Field(None, description='Reason for refund.')
    idempotency_key: str | None = Field(None, description='Unique key to prevent duplicate refund processing.')
    metadata: dict[str, Any] | None = Field(None, description='Arbitrary key-value pairs stored with the refund.')


class GetDashboardUrlConfig(_Input):
    """Get the public impact dashboard URL."""
    operation: Literal["get_dashboard_url"] = Field("get_dashboard_url", json_schema_extra={"ui:hidden": True})


GoodapiPlantTreesOperation = Annotated[Union[
    PlantTreesConfig,
    ListPlantedTreesConfig,
    RefundTreesConfig,
    ListTreeProjectsConfig,
    GetTreeProjectConfig,
    RescuePlasticBottlesConfig,
    ListRescuedBottlesConfig,
    RefundPlasticBottlesConfig,
    GetEvidenceConfig,
    GetTreeEvidenceConfig,
    SearchCharitiesConfig,
    CreateDonationConfig,
    ListDonationsConfig,
    SubscribeDonationsConfig,
    RefundDonationConfig,
    GetDashboardUrlConfig
], Field(discriminator="operation")]



class GoodapiPlantTreesNodeConfig(NodeConfig[GoodapiPlantTreesOperation, GoodapiPlantTreesCredential]):
    pass


# Fixed routes from the published v2 contract; configuration cannot supply a host.
ROUTES = {'plant_trees': ('POST', '/plant/trees', ()),
 'list_planted_trees': ('GET', '/plant/trees', ()),
 'refund_trees': ('POST', '/refund/trees', ()),
 'list_tree_projects': ('GET', '/tree/projects', ()),
 'get_tree_project': ('GET', '/tree/projects/{id}', ('id',)),
 'rescue_plastic_bottles': ('POST', '/rescue/plastic_bottles', ()),
 'list_rescued_bottles': ('GET', '/rescue/plastic_bottles', ()),
 'refund_plastic_bottles': ('POST', '/refund/plastic_bottles', ()),
 'get_evidence': ('GET', '/evidence', ()),
 'get_tree_evidence': ('GET', '/evidence/tree/{id}', ('id',)),
 'search_charities': ('GET', '/charities/search', ()),
 'create_donation': ('POST', '/charities/donate', ()),
 'list_donations': ('GET', '/charities/donations', ()),
 'subscribe_donations': ('POST', '/charities/subscribe', ()),
 'refund_donation': ('POST', '/refund/donations', ()),
 'get_dashboard_url': ('GET', '/dashboard_url', ())}



class GoodapiPlantTreesNode(WorkflowNode):
    integration_type = "automation-goodapi-plant-trees"
    connection_evidence = ConnectionEvidence(
        noun="impact dashboard", identity_operation="get_dashboard_url",
        identity_keys=("org_id", "dashboard_url"),
    )

    @classmethod
    def get_config_model(cls):
        return GoodapiPlantTreesNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a GoodAPI API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, path_fields = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for field in path_fields:
            if values[field] in {".", ".."}:
                raise ValueError("Use a GoodAPI resource ID")
            path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in values.items()} if method == "GET" else None
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": token, "Accept": "application/json"},
                    params=params, **({"json": values} if method == "POST" and values else {}))
        except httpx.RequestError:
            raise ValueError("GoodAPI request did not complete; inspect impact records before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("GoodAPI returned a non-JSON response") from None
        # Never return credentials even if the provider includes them in an error.
        def redact(value):
            if isinstance(value, str):
                return value.replace(token, "[redacted]")
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items()}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value
        data = redact(data)
        if response.status_code != 200 or not isinstance(data, dict) or data.get("error") or data.get("success") is False:
            output = {"status": "error", "http_status": response.status_code,
                      "error": data.get("error", "GoodAPI request failed") if isinstance(data, dict) else "Unexpected GoodAPI response"}
        else:
            output = {**data, "data": data, "status": "success"}
        await self.emit(output)
        return output

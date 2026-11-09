"""Birdeye business, review, contact and survey automation using a pasted API key.

Each operation makes one documented request to the fixed Birdeye API origin.
Connection evidence reads the business identified in the saved credential.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.birdeye.com/resources"
ResourceID = Annotated[str, StringConstraints(pattern=r"^[0-9]+$", min_length=1, max_length=30)]



class BirdeyeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Birdeye API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.birdeye.com/",
        "x-credential-instructions": "Paste your Birdeye dashboard API key and business ID. The business read verifies access; other operations need their own account permissions.",
    })
    credential_type: Literal["birdeye_api_key"] = Field("birdeye_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    business_id: ResourceID = Field(..., title="Business ID", description="The numeric ID of your business in Birdeye.")

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value



class _BusinessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    business_id: ResourceID | None = Field(None, title="Business ID", description="Leave empty to use the business in the connection.")



class GetBusinessConfig(_BusinessConfig):
    operation: Literal["get_business"] = Field("get_business", title="Get Business", json_schema_extra={"ui:hidden": True})


class ListChildBusinessesConfig(_BusinessConfig):
    operation: Literal["list_child_businesses"] = Field("list_child_businesses", title="List Child Businesses", json_schema_extra={"ui:hidden": True})
    pid: int = Field(..., gt=0, title="Parent Business ID")


class ListReviewsConfig(_BusinessConfig):
    operation: Literal["list_reviews"] = Field("list_reviews", title="List Reviews", json_schema_extra={"ui:hidden": True})
    sindex: int = Field(0, ge=0, le=99999, title="Start Index")
    count: int = Field(20, ge=1, le=1000, title="Page Size")
    fromDate: str | None = None
    toDate: str | None = None
    searchStr: str | None = None
    sources: str | None = None
    ratings: list[int] | None = None
    statuses: list[str] | None = None
    tags: list[str] | None = None
    includeNonAggregatedReviews: bool | None = None

    @model_validator(mode="after")
    def pagination_window(self):
        if self.sindex + self.count > 100000:
            raise ValueError("Start index plus page size must not exceed 100000")
        return self


class GetReviewSummaryConfig(_BusinessConfig):
    operation: Literal["get_review_summary"] = Field("get_review_summary", title="Get Review Summary", json_schema_extra={"ui:hidden": True})
    statuses: list[str] | None = None


class ReplyToReviewConfig(_BusinessConfig):
    operation: Literal["reply_to_review"] = Field("reply_to_review", title="Reply To Review", json_schema_extra={"ui:hidden": True})
    reviewId: ResourceID = Field(..., title="Review ID")
    response: str = Field(..., min_length=1, title="Reply Text", description="Posts a public reply to the review.")


class UpsertContactConfig(_BusinessConfig):
    operation: Literal["upsert_contact"] = Field("upsert_contact", title="Upsert Contact", json_schema_extra={"ui:hidden": True})
    id: str | None = Field(None, title="Existing Contact ID")
    email: str = Field(..., min_length=1, title="Email")
    firstName: str | None = None
    lastName: str | None = None
    phone: str | None = None
    countryCode: str | None = None
    externalId: str | None = None
    businessIds: list[int] = Field(..., min_length=1, title="Location Business IDs", description="Explicit location IDs. Required for creating a contact; removal only affects these locations.")


class GetContactConfig(_BusinessConfig):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, title="Contact Email")
    experienceScore: bool | None = None


class DeleteContactConfig(_BusinessConfig):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Remove Contact From Locations", json_schema_extra={"ui:hidden": True})
    id: ResourceID = Field(..., title="Contact ID", description="Removes the contact from the location business IDs below.")
    businessIds: list[int] = Field(..., min_length=1, title="Location Business IDs", description="Explicit location IDs. Required for creating a contact; removal only affects these locations.")


class GetContactActivityConfig(_BusinessConfig):
    operation: Literal["get_contact_activity"] = Field("get_contact_activity", title="Get Contact Activity", json_schema_extra={"ui:hidden": True})
    customerId: ResourceID = Field(..., title="Contact ID")
    startDate: str | None = None
    endDate: str | None = None


class ListContactsConfig(_BusinessConfig):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    page: int = Field(0, ge=0, title="Page")
    size: int = Field(20, ge=1, le=1000, title="Page Size")
    sortby: str = Field("lastActivityOn", title="Sort By")
    startDate: str | None = None
    endDate: str | None = None


class ListReviewSourcesConfig(_BusinessConfig):
    operation: Literal["list_review_sources"] = Field("list_review_sources", title="List Review Sources", json_schema_extra={"ui:hidden": True})


class AddReviewSourceConfig(_BusinessConfig):
    operation: Literal["add_review_source"] = Field("add_review_source", title="Add Review Source", json_schema_extra={"ui:hidden": True})
    sourceAlias: str = Field(..., min_length=1, title="Source Alias")
    url: str = Field(..., min_length=1, title="Review Profile URL")


class DeleteReviewSourceConfig(_BusinessConfig):
    operation: Literal["delete_review_source"] = Field("delete_review_source", title="Delete Review Source", json_schema_extra={"ui:hidden": True})
    aggregationID: int = Field(..., gt=0, title="Aggregation ID")


class ListSurveysConfig(_BusinessConfig):
    operation: Literal["list_surveys"] = Field("list_surveys", title="List Surveys", json_schema_extra={"ui:hidden": True})
    sortby: str | None = None
    sorder: str | None = None
    searchStr: str | None = None


class ListEmployeesConfig(_BusinessConfig):
    operation: Literal["list_employees"] = Field("list_employees", title="List Employees", json_schema_extra={"ui:hidden": True})


class CheckInCustomerConfig(_BusinessConfig):
    operation: Literal["check_in_customer"] = Field("check_in_customer", title="Check In Customer", description="Records a check-in and may send review requests according to your Birdeye settings.", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Customer Name")
    emailId: str = Field(..., min_length=1, title="Customer Email")
    phone: str | None = Field(None, title="Customer Phone")
    smsEnabled: Literal[0, 1] = Field(0, title="Customer Opted Into SMS", description="Only choose 1 when the customer opted to receive SMS requests. Email requests may still be sent according to business settings.")
    externalId: str | None = Field(None, title="External Contact ID")

Operation = Annotated[Union[GetBusinessConfig, ListChildBusinessesConfig, ListReviewsConfig, GetReviewSummaryConfig, ReplyToReviewConfig, UpsertContactConfig, GetContactConfig, DeleteContactConfig, GetContactActivityConfig, ListContactsConfig, ListReviewSourcesConfig, AddReviewSourceConfig, DeleteReviewSourceConfig, ListSurveysConfig, ListEmployeesConfig, CheckInCustomerConfig], Field(discriminator="operation")]



class BirdeyeNodeConfig(NodeConfig[Operation, BirdeyeAPIKeyCredential]):
    pass


ROUTES = {'get_business': {'method': 'GET',
                  'path': '/v1/business/{business_id}',
                  'query': [],
                  'business': 'business_id',
                  'body': None},
 'list_child_businesses': {'method': 'GET',
                           'path': '/v1/business/child/all',
                           'query': ['pid'],
                           'business': None,
                           'body': None},
 'list_reviews': {'method': 'POST',
                  'path': '/v1/review/businessId/{businessId}',
                  'query': ['sindex', 'count', 'includeNonAggregatedReviews'],
                  'business': 'businessId',
                  'body': ['fromDate',
                           'toDate',
                           'fromTimestamp',
                           'toTimestamp',
                           'updateFromDate',
                           'updateToDate',
                           'sources',
                           'ratings',
                           'searchStr',
                           'subBusinessIds',
                           'statuses',
                           'allChild',
                           'tags',
                           'fetchExtraParams',
                           'needCustomerInfo',
                           'fetchAssitedByDetails',
                           'messageOptions']},
 'get_review_summary': {'method': 'GET',
                        'path': '/v1/review/businessid/{businessId}/summary',
                        'query': ['statuses'],
                        'business': 'businessId',
                        'body': None},
 'reply_to_review': {'method': 'PUT',
                     'path': '/v1/review/reply/business/{businessNumber}/review/{reviewId}',
                     'query': [],
                     'business': 'businessNumber',
                     'body': ['response', 'isPrivateResponse']},
 'upsert_contact': {'method': 'POST',
                    'path': '/v1/customer-v2/external/saveCustomer',
                    'query': ['businessId'],
                    'business': 'businessId',
                    'body': ['id',
                             'firstName',
                             'lastName',
                             'email',
                             'phone',
                             'countryCode',
                             'smsOptin',
                             'emailOptin',
                             'blocked',
                             'businessIds',
                             'tags',
                             'customFields',
                             'externalId']},
 'get_contact': {'method': 'POST',
                 'path': '/v1/customer-v2/external/getCustomer',
                 'query': ['businessId'],
                 'business': 'businessId',
                 'body': ['id', 'cid', 'email', 'phone', 'experienceScore']},
 'delete_contact': {'method': 'POST',
                    'path': '/v1/customer-v2/external/deleteCustomer',
                    'query': ['businessId'],
                    'business': 'businessId',
                    'body': ['id', 'businessIds']},
 'get_contact_activity': {'method': 'GET',
                          'path': '/v1/customer/history/{customerId}',
                          'query': ['businessId', 'startDate', 'endDate'],
                          'business': 'businessId',
                          'body': None},
 'list_contacts': {'method': 'POST',
                   'path': '/v2/customer/list',
                   'query': ['businessId', 'page', 'size', 'sortby'],
                   'business': 'businessId',
                   'body': ['startDate', 'endDate']},
 'list_review_sources': {'method': 'GET',
                         'path': '/v1/aggregation/business/{businessId}',
                         'query': [],
                         'business': 'businessId',
                         'body': None},
 'add_review_source': {'method': 'POST',
                       'path': '/v1/aggregation/business/{business_id}',
                       'query': [],
                       'business': 'business_id',
                       'body': ['sourceAlias', 'url']},
 'delete_review_source': {'method': 'DELETE',
                          'path': '/v1/aggregation/business/{businessID}/aggregation/{aggregationID}',
                          'query': [],
                          'business': 'businessID',
                          'body': None},
 'list_surveys': {'method': 'GET',
                  'path': '/v1/survey/business/{business_id}/all',
                  'query': ['sortby', 'sorder', 'searchStr'],
                  'business': 'business_id',
                  'body': None},
 'list_employees': {'method': 'GET',
                    'path': '/v1/employee/{businessId}',
                    'query': [],
                    'business': 'businessId',
                    'body': None},
 'check_in_customer': {'method': 'POST',
                       'path': '/v1/customer/checkin',
                       'query': ['bid'],
                       'business': 'bid',
                       'body': ['name', 'emailId', 'phone', 'smsEnabled', 'externalId']}}


class BirdeyeNode(WorkflowNode):
    integration_type = "automation-birdeye"
    connection_evidence = ConnectionEvidence(noun="business", identity_operation="get_business")
    edit_examples = ["Find recent reviews", "Reply to a review", "Create or update a contact"]

    @classmethod
    def get_config_model(cls):
        return BirdeyeNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Birdeye API key and business ID")
        credential = self.config.credentials
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation", "business_id"})
        if route["business"]:
            values[route["business"]] = config.business_id or credential.business_id
        path = route["path"]
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in route["query"] if key in values}
        # Birdeye query arrays use the default OpenAPI form/explode encoding.
        body = {key: values[key] for key in route["body"] if key in values} if route["body"] is not None else None
        headers = {"x-api-key": credential.api_key, "Accept": "application/json"}
        kwargs = {"params": params, "headers": headers}
        if body is not None:
            kwargs["json"] = body
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(route["method"], BASE_URL + path, **kwargs)
        if not 200 <= response.status_code < 300:
            # Keep the provider's rejection words, without reflecting the secret.
            try:
                error = response.json()
                message = error.get("message", error.get("errorMessage", "Birdeye request failed")) if isinstance(error, dict) else "Birdeye request failed"
            except ValueError:
                message = "Birdeye returned a non-JSON error"
            raise ValueError(f"Birdeye HTTP {response.status_code}: {str(message).replace(credential.api_key, '[redacted]')}")
        if response.status_code == 204 or not response.content:
            data = None
        else:
            data = response.json()
            if isinstance(data, dict) and (data.get("errorCode") or (data.get("code") and data.get("message"))):
                raise ValueError(str(data.get("message", data.get("errorMessage", "Birdeye request failed"))).replace(credential.api_key, "[redacted]"))
        output = {"data": data, "operation": config.operation}
        await self.emit(output)
        return output

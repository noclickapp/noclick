"""Brilliant Directories v2 REST operations using a directory owner's API key."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from utils.ssrf import guarded_async_client


class BrilliantDirectoriesApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Brilliant Directories API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://support.brilliantdirectories.com/support/solutions/articles/12000088768",
            "x-credential-instructions": "In your directory Admin, open Developer Hub and generate an API key. Paste it with your canonical HTTPS directory URL, including www if used. Enable only the Advanced Endpoint permissions needed for leads, reviews, posts, categories and membership plans. NoClick checks access by listing members; this does not prove write permissions.",
        })
    credential_type: Literal["brilliant_directories_api_key"] = Field("brilliant_directories_api_key", json_schema_extra={"ui:hidden": True})
    site_url: str = Field(..., title="Directory URL", description="Your canonical HTTPS directory origin, for example https://www.your-site.com. HTTPS is required to protect the API key.")
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("site_url", mode="before")
    @classmethod
    def directory_origin(cls, value):
        origin = https_origin(value, field_name="Directory URL")
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or parsed.port is not None or not parsed.hostname or parsed.hostname == "localhost":
            raise ValueError("Use the public HTTPS directory URL without a port")
        return origin

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value)


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Operation):
    limit: int = Field(25, ge=1, le=100, title="Page Size")
    page: str | None = Field(None, max_length=8192, title="Page Cursor", description="Copy next_page from the preceding response. One page is returned per execution.")


class ListMembers(_Page):
    operation: Literal["list_members"] = Field("list_members", title="List Members", json_schema_extra={"ui:hidden": True})
    property: str | None = Field(None, title='Property', min_length=0, max_length=2000)
    property_value: str | None = Field(None, title='Property Value', min_length=0, max_length=2000)

    @model_validator(mode="after")
    def paired_filter(self):
        if (self.property is None) != (self.property_value is None):
            raise ValueError("Supply both property and property value")
        return self


class GetMember(_Operation):
    operation: Literal["get_member"] = Field("get_member", title="Get Member", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., title='User Id', ge=1)


class CreateMember(_Operation):
    operation: Literal["create_member"] = Field("create_member", title="Create Member", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title='Email', min_length=1, max_length=2000)
    password: str = Field(..., title='Password', min_length=1, max_length=2000, repr=False, json_schema_extra={"ui:widget": "password"})
    subscription_id: int = Field(..., title='Subscription Id', ge=1)
    first_name: str | None = Field(None, title='First Name', min_length=0, max_length=2000)
    last_name: str | None = Field(None, title='Last Name', min_length=0, max_length=2000)
    company: str | None = Field(None, title='Company', min_length=0, max_length=2000)
    phone_number: str | None = Field(None, title='Phone Number', min_length=0, max_length=2000)
    city: str | None = Field(None, title='City', min_length=0, max_length=2000)
    state_code: str | None = Field(None, title='State Code', min_length=0, max_length=2000)
    country_code: str | None = Field(None, title='Country Code', min_length=0, max_length=2000)
    active: Literal['1', '2', '3', '4', '5', '6'] | None = Field(None, title='Active', min_length=0, max_length=2000)
    listing_type: Literal['Individual', 'Company'] | None = Field(None, title='Listing Type', min_length=0, max_length=2000)
    profession_id: int | None = Field(None, title='Profession Id', ge=1)
    about_me: str | None = Field(None, title='About Me', min_length=0, max_length=100000)


class UpdateMember(_Operation):
    operation: Literal["update_member"] = Field("update_member", title="Update Member", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., title='User Id', ge=1)
    email: str | None = Field(None, title='Email', min_length=0, max_length=2000)
    first_name: str | None = Field(None, title='First Name', min_length=0, max_length=2000)
    last_name: str | None = Field(None, title='Last Name', min_length=0, max_length=2000)
    company: str | None = Field(None, title='Company', min_length=0, max_length=2000)
    phone_number: str | None = Field(None, title='Phone Number', min_length=0, max_length=2000)
    city: str | None = Field(None, title='City', min_length=0, max_length=2000)
    state_code: str | None = Field(None, title='State Code', min_length=0, max_length=2000)
    country_code: str | None = Field(None, title='Country Code', min_length=0, max_length=2000)
    subscription_id: int | None = Field(None, title='Subscription Id', ge=1)
    active: Literal['1', '2', '3', '4', '5', '6'] | None = Field(None, title='Active', min_length=0, max_length=2000)
    listing_type: Literal['Individual', 'Company'] | None = Field(None, title='Listing Type', min_length=0, max_length=2000)
    profession_id: int | None = Field(None, title='Profession Id', ge=1)
    about_me: str | None = Field(None, title='About Me', min_length=0, max_length=100000)


class ListReviews(_Page):
    operation: Literal["list_reviews"] = Field("list_reviews", title="List Reviews", json_schema_extra={"ui:hidden": True})
    property: str | None = Field(None, title='Property', min_length=0, max_length=2000)
    property_value: str | None = Field(None, title='Property Value', min_length=0, max_length=2000)

    @model_validator(mode="after")
    def paired_filter(self):
        if (self.property is None) != (self.property_value is None):
            raise ValueError("Supply both property and property value")
        return self


class GetReview(_Operation):
    operation: Literal["get_review"] = Field("get_review", title="Get Review", json_schema_extra={"ui:hidden": True})
    review_id: int = Field(..., title='Review Id', ge=1)


class CreateReview(_Operation):
    operation: Literal["create_review"] = Field("create_review", title="Create Review", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., title='User Id', ge=1)
    review_name: str | None = Field(None, title='Review Name', min_length=0, max_length=2000)
    review_email: str = Field(..., title='Review Email', min_length=1, max_length=2000)
    review_title: str | None = Field(None, title='Review Title', min_length=0, max_length=2000)
    review_description: str | None = Field(None, title='Review Description', min_length=0, max_length=100000)
    rating_overall: int | None = Field(None, title='Rating Overall')
    recommend: Literal[0, 1] | None = Field(None, title='Recommend')
    review_status: Literal[0, 2, 3, 4] | None = Field(None, title='Review Status')


class UpdateReview(_Operation):
    operation: Literal["update_review"] = Field("update_review", title="Update Review", json_schema_extra={"ui:hidden": True})
    review_id: int = Field(..., title='Review Id', ge=1)
    review_name: str | None = Field(None, title='Review Name', min_length=0, max_length=2000)
    review_title: str | None = Field(None, title='Review Title', min_length=0, max_length=2000)
    review_description: str | None = Field(None, title='Review Description', min_length=0, max_length=100000)
    rating_overall: int | None = Field(None, title='Rating Overall')
    recommend: int | None = Field(None, title='Recommend')
    review_status: Literal[0, 2, 3, 4] | None = Field(None, title='Review Status')


class ListLeads(_Page):
    operation: Literal["list_leads"] = Field("list_leads", title="List Leads", json_schema_extra={"ui:hidden": True})
    property: str | None = Field(None, title='Property', min_length=0, max_length=2000)
    property_value: str | None = Field(None, title='Property Value', min_length=0, max_length=2000)

    @model_validator(mode="after")
    def paired_filter(self):
        if (self.property is None) != (self.property_value is None):
            raise ValueError("Supply both property and property value")
        return self


class GetLead(_Operation):
    operation: Literal["get_lead"] = Field("get_lead", title="Get Lead", json_schema_extra={"ui:hidden": True})
    lead_id: int = Field(..., title='Lead Id', ge=1)


class CreateLead(_Operation):
    operation: Literal["create_lead"] = Field("create_lead", title="Create Lead", json_schema_extra={"ui:hidden": True})
    lead_name: str = Field(..., title='Lead Name', min_length=1, max_length=2000)
    lead_email: str = Field(..., title='Lead Email', min_length=1, max_length=2000)
    lead_phone: str = Field(..., title='Lead Phone', min_length=1, max_length=2000)
    lead_message: str = Field(..., title='Lead Message', min_length=1, max_length=100000)
    lead_location: str = Field(..., title='Lead Location', min_length=1, max_length=2000)
    top_id: int = Field(..., title='Top Id', ge=1)
    send_lead_email_notification: Literal[0, 1] | None = Field(None, title='Send Lead Email Notification')
    auto_match: Literal[0, 1] | None = Field(None, title='Auto Match')


class UpdateLead(_Operation):
    operation: Literal["update_lead"] = Field("update_lead", title="Update Lead", json_schema_extra={"ui:hidden": True})
    lead_id: int = Field(..., title='Lead Id', ge=1)
    lead_name: str | None = Field(None, title='Lead Name', min_length=0, max_length=2000)
    lead_email: str | None = Field(None, title='Lead Email', min_length=0, max_length=2000)
    lead_phone: str | None = Field(None, title='Lead Phone', min_length=0, max_length=2000)
    lead_message: str | None = Field(None, title='Lead Message', min_length=0, max_length=100000)
    lead_location: str | None = Field(None, title='Lead Location', min_length=0, max_length=2000)
    lead_notes: str | None = Field(None, title='Lead Notes', min_length=0, max_length=2000)
    lead_status: Literal[1, 2, 4, 5, 6, 7, 8] | None = Field(None, title='Lead Status')
    lead_price: float | None = Field(None, title='Lead Price')
    top_id: int | None = Field(None, title='Top Id', ge=1)
    sub_id: int | None = Field(None, title='Sub Id', ge=1)


class ListPosts(_Page):
    operation: Literal["list_posts"] = Field("list_posts", title="List Posts", json_schema_extra={"ui:hidden": True})
    property: str | None = Field(None, title='Property', min_length=0, max_length=2000)
    property_value: str | None = Field(None, title='Property Value', min_length=0, max_length=2000)

    @model_validator(mode="after")
    def paired_filter(self):
        if (self.property is None) != (self.property_value is None):
            raise ValueError("Supply both property and property value")
        return self


class GetPost(_Operation):
    operation: Literal["get_post"] = Field("get_post", title="Get Post", json_schema_extra={"ui:hidden": True})
    post_id: int = Field(..., title='Post Id', ge=1)


class CreatePost(_Operation):
    operation: Literal["create_post"] = Field("create_post", title="Create Post", json_schema_extra={"ui:hidden": True})
    user_id: int = Field(..., title='User Id', ge=1)
    data_id: int = Field(..., title='Data Id', ge=1)
    data_type: int = Field(..., title='Data Type', description="Use the data_type value from the selected post type; this operation supports single-image post types.")
    post_title: str | None = Field(None, title='Post Title', min_length=0, max_length=2000)
    post_content: str | None = Field(None, title='Post Content', min_length=0, max_length=100000)
    post_status: Literal[0, 1, 3] | None = Field(None, title='Post Status')
    post_tags: str | None = Field(None, title='Post Tags', min_length=0, max_length=2000)
    post_category: str | None = Field(None, title='Post Category', min_length=0, max_length=2000)


class UpdatePost(_Operation):
    operation: Literal["update_post"] = Field("update_post", title="Update Post", json_schema_extra={"ui:hidden": True})
    post_id: int = Field(..., title='Post Id', ge=1)
    post_title: str | None = Field(None, title='Post Title', min_length=0, max_length=2000)
    post_content: str | None = Field(None, title='Post Content', min_length=0, max_length=100000)
    post_status: Literal[0, 1, 3] | None = Field(None, title='Post Status')
    post_tags: str | None = Field(None, title='Post Tags', min_length=0, max_length=2000)
    post_category: str | None = Field(None, title='Post Category', min_length=0, max_length=2000)


class ListPostTypes(_Page):
    operation: Literal["list_post_types"] = Field("list_post_types", title="List Post Types", json_schema_extra={"ui:hidden": True})
    property: str | None = Field(None, title='Property', min_length=0, max_length=2000)
    property_value: str | None = Field(None, title='Property Value', min_length=0, max_length=2000)

    @model_validator(mode="after")
    def paired_filter(self):
        if (self.property is None) != (self.property_value is None):
            raise ValueError("Supply both property and property value")
        return self


class ListMembershipPlans(_Page):
    operation: Literal["list_membership_plans"] = Field("list_membership_plans", title="List Membership Plans", json_schema_extra={"ui:hidden": True})


class GetMembershipPlan(_Operation):
    operation: Literal["get_membership_plan"] = Field("get_membership_plan", title="Get Membership Plan", json_schema_extra={"ui:hidden": True})
    subscription_id: int = Field(..., title='Subscription Id', ge=1)


class ListCategories(_Page):
    operation: Literal["list_categories"] = Field("list_categories", title="List Categories", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[ListMembers, GetMember, CreateMember, UpdateMember, ListReviews, GetReview, CreateReview, UpdateReview, ListLeads, GetLead, CreateLead, UpdateLead, ListPosts, GetPost, CreatePost, UpdatePost, ListPostTypes, ListMembershipPlans, GetMembershipPlan, ListCategories], Field(discriminator="operation")]


class BrilliantDirectoriesNodeConfig(NodeConfig[Operation, BrilliantDirectoriesApiKeyCredential]):
    pass


ROUTES = {'list_members': ('GET', '/api/v2/user/get'), 'get_member': ('GET', '/api/v2/user/get/{user_id}'), 'create_member': ('POST', '/api/v2/user/create'), 'update_member': ('PUT', '/api/v2/user/update'), 'list_reviews': ('GET', '/api/v2/users_reviews/get'), 'get_review': ('GET', '/api/v2/users_reviews/get/{review_id}'), 'create_review': ('POST', '/api/v2/users_reviews/create'), 'update_review': ('PUT', '/api/v2/users_reviews/update'), 'list_leads': ('GET', '/api/v2/leads/get'), 'get_lead': ('GET', '/api/v2/leads/get/{lead_id}'), 'create_lead': ('POST', '/api/v2/leads/create'), 'update_lead': ('PUT', '/api/v2/leads/update'), 'list_posts': ('GET', '/api/v2/data_posts/get'), 'get_post': ('GET', '/api/v2/data_posts/get/{post_id}'), 'create_post': ('POST', '/api/v2/data_posts/create'), 'update_post': ('PUT', '/api/v2/data_posts/update'), 'list_post_types': ('GET', '/api/v2/data_categories/get'), 'list_membership_plans': ('GET', '/api/v2/subscription_types/get'), 'get_membership_plan': ('GET', '/api/v2/subscription_types/get/{subscription_id}'), 'list_categories': ('GET', '/api/v2/list_professions/get')}


def _public_record(value):
    # The direct API can include login secrets even when no include flag is sent.
    if isinstance(value, dict):
        return {k: _public_record(v) for k, v in value.items()
                if k.lower() not in {"password", "token", "cookie", "api_key", "access_token", "refresh_token"}}
    if isinstance(value, list):
        return [_public_record(v) for v in value]
    return value


class BrilliantDirectoriesNode(WorkflowNode):
    integration_type = "automation-brilliant-directories"
    connection_evidence = ConnectionEvidence(noun="members", operation="list_members", label_keys=("company", "email", "first_name", "user_id"))

    @classmethod
    def get_config_model(cls):
        return BrilliantDirectoriesNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Brilliant Directories API key")
        config = self.config.config
        credential = self.config.credentials
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.site_url + path,
                headers={"X-Api-Key": credential.api_key, "Accept": "application/json"},
                **({"params": values} if method == "GET" else {"data": values}))
        if not response.is_success:
            # Keep provider rejections verbatim for connect; redact submitted secrets.
            message = response.text.replace(credential.api_key, "[redacted]")
            if getattr(config, "password", None):
                message = message.replace(config.password, "[redacted]")
            return {"status": "error", "status_code": response.status_code, "error": message[:2000]}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Brilliant Directories returned a non-JSON response; check the canonical directory URL") from None
        if not isinstance(body, dict) or body.get("status") != "success":
            error = str(body.get("message", "Unexpected Brilliant Directories response")) if isinstance(body, dict) else "Unexpected Brilliant Directories response"
            error = error.replace(credential.api_key, "[redacted]")
            if getattr(config, "password", None):
                error = error.replace(config.password, "[redacted]")
            return {"status": "error", "error": error[:2000]}
        data = body.get("message")
        if not isinstance(data, (dict, list)):
            raise ValueError("Brilliant Directories success response is missing record data")
        data = _public_record(data)
        result = {"status": "success", "operation": config.operation, "data": data}
        if config.operation.startswith("list_"):
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise ValueError("Brilliant Directories list response must contain an array of records")
            result.update(items=data, **{k: body[k] for k in ("total", "current_page", "total_pages", "next_page", "prev_page") if k in body})
        return result

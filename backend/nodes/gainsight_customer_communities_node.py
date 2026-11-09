"""Gainsight Customer Communities Community API, version 20261106104747.

Contract: https://api2-eu-west-1.insided.com/v2/swagger.json
Auth: https://developer-portal.gainsight.com/docs/api/api-authentication.md
Every operation performs exactly one resource request. Lists expose one numbered
page; write acknowledgments do not claim readback or delivery verification.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.gainsight_customer_communities import GAINSIGHT_CUSTOMER_COMMUNITIES_SCOPES
from utils.ssrf import guarded_async_client

HIDDEN = {"ui:hidden": True}
HOSTS = ("https://api2-eu-west-1.insided.com", "https://api2-us-west-2.insided.com")


class GainsightCustomerCommunitiesToken(BaseModel):
    model_config = ConfigDict(title="Gainsight Customer Communities Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer-portal.gainsight.com/docs/api/api-authentication.md",
            "x-credential-instructions": "In Control > Integrations > API, find your API region and create client credentials. Exchange them at that region's /oauth2/token with grant_type=client_credentials and scope=read write, then paste only the access_token here. Tokens expire (the documented example lasts 7200 seconds); replace the token after expiry. NoClick does not renew pasted tokens. Read-only workflows need only read scope. The categories read checks community access, not user identity or write permissions."
        })
    credential_type: Literal["gainsight_customer_communities_token"] = Field("gainsight_customer_communities_token", json_schema_extra=HIDDEN)
    api_base_url: Literal["https://api2-eu-west-1.insided.com", "https://api2-us-west-2.insided.com"] = Field(HOSTS[0], title="API region", description="Choose the Base URL shown in Control > Integrations > API.")
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the access token without a Bearer prefix or whitespace")
        return value

    @field_validator("api_base_url", mode="before")
    @classmethod
    def origin(cls, value):
        return value.strip().rstrip("/") if isinstance(value, str) else value


def operation(name):
    return Field(name, json_schema_extra={**HIDDEN, "x-display-name": name.replace("_", " ").title(), "x-is-trigger": False})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Resource(Input):
    id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", description="The private resource ID, not its public topic ID or URL.")


class Page(Input):
    page: int = Field(1, ge=1, description="Page number. One page per run; increment to retrieve another page.")
    page_size: int = Field(25, ge=1, le=100)


class SearchPage(Page):
    q: str | None = Field(None, description="Search term; omit to return all results.")


class ResourcePage(Resource, Page):
    pass


class CreateContent(Input):
    author_id: str = Field(..., min_length=1, description="User ID to act as; the provider enforces category access.")
    category_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=250, pattern="[a-z0-9]")
    content: str = Field(..., min_length=1, max_length=100000)
    tags: list[Annotated[str, Field(max_length=45)]] | None = None


class ReplyContent(Resource):
    author_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=100000)


class EditTitle(Resource):
    moderator_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=250)


class EditTags(Resource):
    author_id: str = Field(..., min_length=1)
    tags: list[Annotated[str, Field(max_length=45)]] = Field(..., description="Replaces the entire public tag list; an empty list removes all public tags.")


class NewTag(Input):
    author_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=45)


class ListCategories(Page):
    operation: Literal["list_categories"] = operation("list_categories")


class GetCategory(Resource):
    operation: Literal["get_category"] = operation("get_category")


class ListTopics(SearchPage):
    operation: Literal["list_topics"] = operation("list_topics")


class ListConversations(Page):
    operation: Literal["list_conversations"] = operation("list_conversations")


class GetConversation(Resource):
    operation: Literal["get_conversation"] = operation("get_conversation")


class ListConversationReplies(ResourcePage):
    operation: Literal["list_conversation_replies"] = operation("list_conversation_replies")


class StartConversation(CreateContent):
    operation: Literal["start_conversation"] = operation("start_conversation")


class ReplyConversation(ReplyContent):
    operation: Literal["reply_conversation"] = operation("reply_conversation")


class EditConversationTitle(EditTitle):
    operation: Literal["edit_conversation_title"] = operation("edit_conversation_title")


class EditConversationTags(EditTags):
    operation: Literal["edit_conversation_tags"] = operation("edit_conversation_tags")


class ListQuestions(Page):
    operation: Literal["list_questions"] = operation("list_questions")


class GetQuestion(Resource):
    operation: Literal["get_question"] = operation("get_question")


class AskQuestion(CreateContent):
    operation: Literal["ask_question"] = operation("ask_question")


class ReplyQuestion(ReplyContent):
    operation: Literal["reply_question"] = operation("reply_question")


class ListArticles(Page):
    operation: Literal["list_articles"] = operation("list_articles")


class GetArticle(Resource):
    operation: Literal["get_article"] = operation("get_article")


class ListIdeas(Page):
    operation: Literal["list_ideas"] = operation("list_ideas")


class GetIdea(Resource):
    operation: Literal["get_idea"] = operation("get_idea")


class ListTags(SearchPage):
    operation: Literal["list_tags"] = operation("list_tags")


class CreateTag(NewTag):
    operation: Literal["create_tag"] = operation("create_tag")


GainsightCustomerCommunitiesConfig = Annotated[Union[
    ListCategories, GetCategory, ListTopics, ListConversations, GetConversation, ListConversationReplies, StartConversation, ReplyConversation, EditConversationTitle, EditConversationTags, ListQuestions, GetQuestion, AskQuestion, ReplyQuestion, ListArticles, GetArticle, ListIdeas, GetIdea, ListTags, CreateTag
], Field(discriminator="operation")]


class GainsightCustomerCommunitiesFullConfig(NodeConfig[GainsightCustomerCommunitiesConfig, GainsightCustomerCommunitiesToken]):
    pass


ROUTES = {'list_categories': ('GET', '/categories'),
 'get_category': ('GET', '/categories/{id}'),
 'list_topics': ('GET', '/topics'),
 'list_conversations': ('GET', '/conversations'),
 'get_conversation': ('GET', '/conversations/{id}'),
 'list_conversation_replies': ('GET', '/conversations/{id}/replies'),
 'start_conversation': ('POST', '/conversations/start'),
 'reply_conversation': ('POST', '/conversations/{id}/reply'),
 'edit_conversation_title': ('POST', '/conversations/{id}/editTitle'),
 'edit_conversation_tags': ('POST', '/conversations/{id}/editTags'),
 'list_questions': ('GET', '/questions'),
 'get_question': ('GET', '/questions/{id}'),
 'ask_question': ('POST', '/questions/ask'),
 'reply_question': ('POST', '/questions/{id}/reply'),
 'list_articles': ('GET', '/articles'),
 'get_article': ('GET', '/articles/{id}'),
 'list_ideas': ('GET', '/ideas'),
 'get_idea': ('GET', '/ideas/{id}'),
 'list_tags': ('GET', '/tags'),
 'create_tag': ('POST', '/tags/create')}


def redact(value, token):
    if isinstance(value, dict):
        return {k: redact(v, token) for k, v in value.items() if k.lower().replace("_", "") not in {"accesstoken", "refreshtoken", "clientsecret", "authorization"}}
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value


class GainsightCustomerCommunitiesNode(WorkflowNode):
    integration_type = "automation-gainsight-customer-communities"
    scope_registry = GAINSIGHT_CUSTOMER_COMMUNITIES_SCOPES
    connection_evidence = ConnectionEvidence(noun="community categories", operation="list_categories", label_keys=("name", "title", "id"))

    @classmethod
    def get_config_model(cls):
        return GainsightCustomerCommunitiesFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Gainsight Customer Communities access token")
        credential, config = self.config.credentials, self.config.config
        method, path = ROUTES[config.operation]
        if isinstance(config, Resource):
            path = path.replace("{id}", quote(config.id, safe=""))
        params = {}
        if isinstance(config, Page):
            params.update(page=config.page, pageSize=config.page_size)
        if isinstance(config, SearchPage) and config.q is not None:
            params["q"] = config.q
        if hasattr(config, "author_id"):
            params["authorId"] = config.author_id
        if hasattr(config, "moderator_id"):
            params["moderatorId"] = config.moderator_id
        body = None
        if method == "POST":
            fields = config.model_dump(exclude_none=True, exclude={"operation", "id", "author_id", "moderator_id"})
            body = {"categoryId" if k == "category_id" else k: v for k, v in fields.items()}
        write = method != "GET"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                kwargs = {"params": params, "headers": {"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}}
                if body is not None:
                    kwargs["json"] = body
                response = await client.request(method, credential.api_base_url + "/v2" + path, **kwargs)
            if len(response.content) > 10_000_000:
                raise ValueError("Response exceeds supported size")
            if not 200 <= response.status_code < 300:
                try:
                    payload = response.json() if response.content else None
                except ValueError:
                    payload = response.text
                result = {"status": "error", "success": False, "http_status": response.status_code,
                    "error": payload if payload is not None else "Gainsight rejected the request"}
            else:
                payload = response.json() if response.content else None
                if isinstance(payload, dict) and (payload.get("error") or payload.get("errors") or payload.get("success") is False):
                    result = redact({"status": "error", "success": False, "http_status": response.status_code, "error": payload}, credential.access_token)
                    await self.emit(result)
                    return result
                expected_status = 200 if not write else 204 if isinstance(config, (EditTitle, EditTags)) else 201
                if response.status_code != expected_status:
                    raise ValueError("Unexpected acknowledgment status")
                result = {"status": "success", "success": True, "http_status": response.status_code}
                if not write:
                    if not isinstance(payload, dict):
                        raise ValueError("Expected a JSON object")
                    if isinstance(config, Page):
                        items = payload.get("result")
                        if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                            raise ValueError("Expected result array")
                        result.update(data=items, page=config.page, page_size=config.page_size,
                            next_page=config.page + 1 if len(items) == config.page_size else None,
                            has_more=None if len(items) == config.page_size else False)
                    else:
                        result["data"] = payload
                else:
                    if isinstance(config, CreateContent) and (not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or not isinstance(payload.get("publicId"), str)):
                        raise ValueError("Missing created resource identifiers")
                    result.update(data=payload, write_acknowledged=True, readback_verified=False)
        except httpx.TransportError:
            result = {"status": "unknown" if write else "error", "success": False,
                "error": "Gainsight request could not complete. Inspect the community before retrying a write."}
        except ValueError:
            result = {"status": "unknown" if write else "error", "success": False,
                "error": "Gainsight response could not be verified. Inspect the community before retrying a write."}
        result = redact(result, credential.access_token)
        await self.emit(result)
        return result

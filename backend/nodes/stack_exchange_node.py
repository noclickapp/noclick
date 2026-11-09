"""Stack Exchange v2 fixed-endpoint reads and comment writes.

Contract: https://api.stackexchange.com/docs
Authentication: https://stackapps.com/help/api-authentication
The caller supplies an existing application key and user token. NoClick neither
issues nor refreshes these tokens. Write calls are never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.scopes.stack_exchange import STACK_EXCHANGE_SCOPES

BASE_URL = "https://api.stackexchange.com/2.0"


class StackExchangeAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Stack Exchange Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://stackapps.com/apps/oauth",
            "x-credential-instructions": "Paste your Stack Apps application's API key and an existing OAuth access token issued to that same application. The token needs write_access for comment writes and read_inbox for inbox and notifications. Generate the token through your application's documented OAuth flow; NoClick does not create or refresh it. Use no_expiry only when perpetual access is needed, otherwise replace an expired token. The site is the API site parameter, for example stackoverflow. Connection verification reads your profile on that site.",
        })
    credential_type: Literal["stack_exchange_access_token"] = Field("stack_exchange_access_token", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="Application API key", json_schema_extra={"ui:widget": "password"})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})
    site: str = Field("stackoverflow", max_length=255, description="Stack Exchange API site parameter for connection verification.")

    @field_validator("api_key", "access_token", mode="before")
    @classmethod
    def secret(cls, value):
        return clean_secret(value, field_name="Stack Exchange credential")


class _SiteConfig(BaseModel):
    site: Optional[str] = Field(None, min_length=1, max_length=255, description="API site parameter; defaults to the connected credential's site.")


class _PageConfig(_SiteConfig):
    page: int = Field(1, ge=1, description="One page per execution; increment when has_more is true.")
    pagesize: int = Field(30, ge=1, le=100)


class _IdsConfig(_PageConfig):
    ids: str = Field(..., pattern=r"^[0-9]+(?:;[0-9]+){0,99}$", description="Up to 100 numeric IDs separated by semicolons.")


class _CommentConfig(_SiteConfig):
    id: int = Field(..., gt=0, description="Post ID for create; comment ID for edit or delete.")
    preview: bool = Field(False, description="Validate without persisting the change when true.")


class StackExchangeGetMeConfig(_PageConfig):
    operation: Literal["get_me"] = Field("get_me", title="Get Me", json_schema_extra={"ui:hidden": True})

class StackExchangeListQuestionsConfig(_PageConfig):
    operation: Literal["list_questions"] = Field("list_questions", title="List Questions", json_schema_extra={"ui:hidden": True})
    tagged: Optional[str] = Field(None, description="Semicolon-separated tag names; all must match.")

class StackExchangeGetQuestionsConfig(_IdsConfig):
    operation: Literal["get_questions"] = Field("get_questions", title="Get Questions", json_schema_extra={"ui:hidden": True})

class StackExchangeListQuestionAnswersConfig(_IdsConfig):
    operation: Literal["list_question_answers"] = Field("list_question_answers", title="List Question Answers", json_schema_extra={"ui:hidden": True})

class StackExchangeListQuestionCommentsConfig(_IdsConfig):
    operation: Literal["list_question_comments"] = Field("list_question_comments", title="List Question Comments", json_schema_extra={"ui:hidden": True})

class StackExchangeGetAnswersConfig(_IdsConfig):
    operation: Literal["get_answers"] = Field("get_answers", title="Get Answers", json_schema_extra={"ui:hidden": True})

class StackExchangeListAnswerCommentsConfig(_IdsConfig):
    operation: Literal["list_answer_comments"] = Field("list_answer_comments", title="List Answer Comments", json_schema_extra={"ui:hidden": True})

class StackExchangeGetCommentsConfig(_IdsConfig):
    operation: Literal["get_comments"] = Field("get_comments", title="Get Comments", json_schema_extra={"ui:hidden": True})

class StackExchangeSearchQuestionsConfig(_PageConfig):
    operation: Literal["search_questions"] = Field("search_questions", title="Search Questions", json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, description="Free-form search text.")
    tagged: Optional[str] = Field(None, description="Semicolon-separated tag names.")

class StackExchangeListTagsConfig(_PageConfig):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})
    inname: Optional[str] = Field(None, description="Tag name substring.")

class StackExchangeGetUsersConfig(_IdsConfig):
    operation: Literal["get_users"] = Field("get_users", title="Get Users", json_schema_extra={"ui:hidden": True})

class StackExchangeListUserQuestionsConfig(_IdsConfig):
    operation: Literal["list_user_questions"] = Field("list_user_questions", title="List User Questions", json_schema_extra={"ui:hidden": True})

class StackExchangeListUserAnswersConfig(_IdsConfig):
    operation: Literal["list_user_answers"] = Field("list_user_answers", title="List User Answers", json_schema_extra={"ui:hidden": True})

class StackExchangeListMyInboxConfig(_PageConfig):
    operation: Literal["list_my_inbox"] = Field("list_my_inbox", title="List My Inbox", json_schema_extra={"ui:hidden": True})

class StackExchangeListMyNotificationsConfig(_PageConfig):
    operation: Literal["list_my_notifications"] = Field("list_my_notifications", title="List My Notifications", json_schema_extra={"ui:hidden": True})

class StackExchangeCreateCommentConfig(_CommentConfig):
    operation: Literal["create_comment"] = Field("create_comment", title="Create Comment", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=15, max_length=600, description="Comment markdown, 15 to 600 characters.")

class StackExchangeEditCommentConfig(_CommentConfig):
    operation: Literal["edit_comment"] = Field("edit_comment", title="Edit Comment", json_schema_extra={"ui:hidden": True})
    body: str = Field(..., min_length=15, max_length=600, description="Comment markdown, 15 to 600 characters.")

class StackExchangeDeleteCommentConfig(_CommentConfig):
    operation: Literal["delete_comment"] = Field("delete_comment", title="Delete Comment", json_schema_extra={"ui:hidden": True})


OPERATIONS = {'get_me': ('GET', '/me'),
 'list_questions': ('GET', '/questions'),
 'get_questions': ('GET', '/questions/{ids}'),
 'list_question_answers': ('GET', '/questions/{ids}/answers'),
 'list_question_comments': ('GET', '/questions/{ids}/comments'),
 'get_answers': ('GET', '/answers/{ids}'),
 'list_answer_comments': ('GET', '/answers/{ids}/comments'),
 'get_comments': ('GET', '/comments/{ids}'),
 'search_questions': ('GET', '/search/advanced'),
 'list_tags': ('GET', '/tags'),
 'get_users': ('GET', '/users/{ids}'),
 'list_user_questions': ('GET', '/users/{ids}/questions'),
 'list_user_answers': ('GET', '/users/{ids}/answers'),
 'list_my_inbox': ('GET', '/me/inbox'),
 'list_my_notifications': ('GET', '/me/notifications'),
 'create_comment': ('POST', '/posts/{id}/comments/add'),
 'edit_comment': ('POST', '/comments/{id}/edit'),
 'delete_comment': ('POST', '/comments/{id}/delete')}

StackExchangeConfig = Annotated[Union[StackExchangeGetMeConfig, StackExchangeListQuestionsConfig, StackExchangeGetQuestionsConfig, StackExchangeListQuestionAnswersConfig, StackExchangeListQuestionCommentsConfig, StackExchangeGetAnswersConfig, StackExchangeListAnswerCommentsConfig, StackExchangeGetCommentsConfig, StackExchangeSearchQuestionsConfig, StackExchangeListTagsConfig, StackExchangeGetUsersConfig, StackExchangeListUserQuestionsConfig, StackExchangeListUserAnswersConfig, StackExchangeListMyInboxConfig, StackExchangeListMyNotificationsConfig, StackExchangeCreateCommentConfig, StackExchangeEditCommentConfig, StackExchangeDeleteCommentConfig], Field(discriminator="operation")]


class StackExchangeNodeConfig(NodeConfig[StackExchangeConfig, StackExchangeAccessTokenCredential]):
    pass


class StackExchangeNode(WorkflowNode):
    integration_type = "automation-stack-exchange"
    scope_registry = STACK_EXCHANGE_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_me", noun="Stack Exchange profile", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return StackExchangeNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Stack Exchange access token and application key")
        config = self.config.config
        credential = self.config.credentials
        method, path = OPERATIONS[config.operation]
        params = config.model_dump(exclude_none=True, exclude={"operation"})
        params["site"] = params.get("site") or credential.site
        for key in ("ids", "id"):
            if key in params:
                path = path.replace("{" + key + "}", quote(str(params.pop(key)), safe=";"))
        params.update(key=credential.api_key, access_token=credential.access_token)
        # The pinned contract declares POST fields in the query, rather than a
        # requestBody. Stack Exchange accepts these method parameters there.
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                    headers={"Accept": "application/json", "User-Agent": "NoClick Stack Exchange integration"})
        except httpx.HTTPError:
            # HTTP errors embed the URL, which carries this provider's tokens.
            raise ValueError("Stack Exchange request could not be completed") from None
        if config.operation == "delete_comment" and response.status_code in (200, 204) and not response.content:
            return {"status": "success"}
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Stack Exchange returned an invalid JSON response") from None
        if not isinstance(body, dict):
            raise ValueError("Stack Exchange returned an unexpected response")
        if response.status_code != 200 or "error_id" in body:
            message = body.get("error_message", "Stack Exchange rejected the request")
            # Retain provider rejection wording without exposing query secrets.
            message = str(message).replace(credential.access_token, "[redacted]").replace(credential.api_key, "[redacted]")
            raise ValueError(message)
        if "items" in body and not isinstance(body["items"], list):
            raise ValueError("Stack Exchange returned invalid items")
        if config.operation == "get_me" and not body.get("items"):
            raise ValueError("Stack Exchange returned no profile on the connected site")
        # Return the documented wrapper intact, including has_more, backoff,
        # quota_remaining and quota_max; a backoff is never silently retried.
        return {"status": "success", **body}

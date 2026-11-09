"""Exercise the real node through its native factory with offline HTTP."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes.core.registry import NodeFactory
from nodes.stack_exchange_node import StackExchangeNodeConfig, StackExchangeAccessTokenCredential

AUTH = {"credential_type": "stack_exchange_access_token", "api_key": "fixture-application-key", "access_token": "fixture-access-token", "site": "superuser"}
RESPONSE = json.loads((Path(__file__).parent / "fixtures/stack-exchange/wrapper.json").read_text())
CASES = [
    ("get_me", {}, "GET", "/me"),
    ("list_questions", {"tagged": "python;httpx"}, "GET", "/questions"),
    ("get_questions", {"ids": "1;2"}, "GET", "/questions/1;2"),
    ("list_question_answers", {"ids": "1"}, "GET", "/questions/1/answers"),
    ("list_question_comments", {"ids": "1"}, "GET", "/questions/1/comments"),
    ("get_answers", {"ids": "2"}, "GET", "/answers/2"),
    ("list_answer_comments", {"ids": "2"}, "GET", "/answers/2/comments"),
    ("get_comments", {"ids": "3"}, "GET", "/comments/3"),
    ("search_questions", {"q": "python timeout & retry", "tagged": "python"}, "GET", "/search/advanced"),
    ("list_tags", {"inname": "python"}, "GET", "/tags"),
    ("get_users", {"ids": "4"}, "GET", "/users/4"),
    ("list_user_questions", {"ids": "4"}, "GET", "/users/4/questions"),
    ("list_user_answers", {"ids": "4"}, "GET", "/users/4/answers"),
    ("list_my_inbox", {}, "GET", "/me/inbox"),
    ("list_my_notifications", {}, "GET", "/me/notifications"),
    ("create_comment", {"id": 1, "body": "An example comment & markdown", "preview": True}, "POST", "/posts/1/comments/add"),
    ("edit_comment", {"id": 3, "body": "An edited example comment"}, "POST", "/comments/3/edit"),
    ("delete_comment", {"id": 3}, "POST", "/comments/3/delete"),
]


def node(operation, arguments=None, credentials=AUTH):
    return NodeFactory.create_node(node_id="stack-exchange-test", node_type="automation-stack-exchange",
        node_data={"config": {"operation": operation, **(arguments or {})}, "credentials": credentials})


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient
    def send(request):
        requests.append(request)
        reply = replies.pop(0) if replies else httpx.Response(200, json=RESPONSE)
        if isinstance(reply, Exception): raise reply
        return reply
    monkeypatch.setattr("nodes.stack_exchange_node.httpx.AsyncClient", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,method,path", CASES)
async def test_stack_exchange_routes_and_parameters(transport, operation, args, method, path):
    requests, _ = transport
    result = await node(operation, args).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.stackexchange.com"
    assert request.url.path == "/2.0" + path
    query = dict(request.url.params)
    assert query["key"] == AUTH["api_key"]
    assert query["access_token"] == AUTH["access_token"]
    assert query["site"] == "superuser"
    for key, value in args.items():
        if key not in {"id", "ids"}:
            assert query[key] == (str(value).lower() if type(value) is bool else str(value))
    assert result == {"status": "success", **RESPONSE}


@pytest.mark.asyncio
async def test_stack_exchange_explicit_site_page_and_quota(transport):
    requests, _ = transport
    result = await node("list_questions", {"site": "stackoverflow", "page": 2, "pagesize": 100}).execute({})
    assert dict(requests[0].url.params)["site"] == "stackoverflow"
    assert requests[0].url.params["page"] == "2"
    assert result["has_more"] and result["backoff"] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, json=[]), httpx.Response(200, json={"items": {}}), httpx.Response(200, text="invalid json"), httpx.Response(302, text="redirect")])
async def test_stack_exchange_rejects_malformed_response(transport, response):
    transport[1].append(response)
    with pytest.raises(ValueError): await node("get_me").execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [200, 400, 403, 429])
async def test_stack_exchange_error_envelope_and_redaction(transport, code):
    transport[1].append(httpx.Response(code, json={"error_id": 403, "error_message": "Rejected " + AUTH["access_token"]}))
    with pytest.raises(ValueError, match=r"Rejected \[redacted\]"):
        await node("get_me").execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_stack_exchange_transport_failure_hides_query_secrets(transport):
    transport[1].append(httpx.ConnectError("private " + AUTH["access_token"]))
    with pytest.raises(ValueError) as exc: await node("get_me").execute({})
    assert AUTH["access_token"] not in str(exc.value)


@pytest.mark.parametrize("config", [
    {"operation": "get_questions", "ids": "../me"},
    {"operation": "get_questions", "ids": ";1"},
    {"operation": "delete_comment", "id": -1},
    {"operation": "create_comment", "id": 1, "body": "short"},
    {"operation": "edit_comment", "id": 1},
    {"operation": "list_questions", "page": 0},
    {"operation": "list_questions", "pagesize": 101},
    {"operation": "search_questions"},
])
def test_stack_exchange_config_rejects_bad_inputs(config):
    with pytest.raises(ValidationError): StackExchangeNodeConfig.model_validate({"config": config, "credentials": AUTH})


def test_stack_exchange_manual_credential_has_default_type():
    credential = StackExchangeAccessTokenCredential.model_validate({k: v for k, v in AUTH.items() if k != "credential_type"})
    assert credential.credential_type == "stack_exchange_access_token"


@pytest.mark.asyncio
async def test_stack_exchange_delete_empty_success(transport):
    transport[1].append(httpx.Response(200, content=b""))
    assert await node("delete_comment", {"id": 3}).execute({}) == {"status": "success"}


@pytest.mark.asyncio
async def test_stack_exchange_redirect_json_is_not_success(transport):
    transport[1].append(httpx.Response(302, json={}))
    with pytest.raises(ValueError): await node("get_me").execute({})


@pytest.mark.asyncio
async def test_stack_exchange_empty_profile_cannot_prove_account(transport):
    transport[1].append(httpx.Response(200, json={"items": [], "has_more": False}))
    with pytest.raises(ValueError, match="no profile"):
        await node("get_me").execute({})

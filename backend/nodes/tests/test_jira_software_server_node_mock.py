"""Wire regressions for Server/Data Center; no live account or network access.

Fixtures use synthetic Jira values and cover each operation's independent
method, route, payload, pagination and response shape through NodeFactory.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import jira_software_server_node as jira
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-jira-server-token"
CASES = json.loads(
    (Path(__file__).parent / "fixtures/jira-software-server/requests.json").read_text()
)


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(
        node_id="jira-server-test",
        node_type="automation-jira-software-server",
        node_data={
            "config": config,
            "credentials": credential
            or {
                "credential_type": "jira_software_server_token",
                "server_url": "https://jira.example.com/jira",
                "api_token": TOKEN,
            },
        },
    )


def transport(monkeypatch, responder):
    requests = []

    def handle(request):
        requests.append(request)
        return responder(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(jira, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", CASES, ids=lambda c: "jira-software-server-" + c["config"]["operation"]
)
async def test_jira_software_server_operation_contract(monkeypatch, case):
    requests = transport(
        monkeypatch,
        lambda _: httpx.Response(
            case["status"],
            **({} if case["status"] == 204 else {"json": case["response"]}),
        ),
    )
    result = await node(case["config"]).execute({})
    assert result["status"] == "success"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case["method"]
    assert (
        str(request.url).split("?")[0]
        == "https://jira.example.com/jira/rest" + case["path"]
    )
    assert dict(request.url.params) == case["query"]
    assert (json.loads(request.content) if request.content else None) == case["body"]
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    if case["body"] is not None:
        assert request.headers["Content-Type"] == "application/json"
    assert TOKEN not in str(result)
    if case["status"] != 204:
        assert result["data"] == case["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404, 429, 500])
async def test_rejections_are_not_successful_or_retried(monkeypatch, status):
    requests = transport(
        monkeypatch,
        lambda _: httpx.Response(
            status,
            json={"errorMessages": ["Token refused " + TOKEN]},
            headers={"Location": "https://untrusted.example/"},
        ),
    )
    with pytest.raises(ValueError, match=f"{status}.*Token refused") as exc:
        await node({"operation": "get_current_user"}).execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"displayName": "Anonymous"}, {"errors": {}}, []])
async def test_identity_requires_an_authenticated_user(monkeypatch, body):
    transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({"operation": "get_current_user"}).execute({})


@pytest.mark.asyncio
async def test_html_login_page_is_not_connection_evidence(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, text="<html>Login</html>"))
    with pytest.raises(ValueError, match="non-JSON"):
        await node({"operation": "get_current_user"}).execute({})


@pytest.mark.asyncio
async def test_unassign_sends_explicit_null(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(204))
    await node(
        {"operation": "assign_issue", "issue_key": "EX-1", "username": None}
    ).execute({})
    assert json.loads(requests[0].content) == {"name": None}


@pytest.mark.asyncio
async def test_write_transport_failure_is_not_retried(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("untrusted transport detail", request=request)

    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match="inspect Jira before retrying"):
        await node(
            {"operation": "add_comment", "issue_key": "EX-1", "body": "A comment"}
        ).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "ftp://jira.example.com",
        "https://user:pass@jira.example.com",
        "https://jira.example.com?next=x",
        "https://jira.example.com/#token",
        "https://jira.example.com/../admin",
        "https://jira.example.com/%2fadmin",
        "https://jira.example.com/rest",
        "https://127.0.0.1",
        "https://localhost",
        "https://jira.example.com:99999",
    ],
)
def test_unsafe_instance_urls_are_refused(url):
    with pytest.raises(ValidationError):
        jira.JiraSoftwareServerTokenCredential(server_url=url, api_token=TOKEN)


def test_manual_credential_default_and_context_path():
    credential = jira.JiraSoftwareServerTokenCredential(
        server_url=" https://JIRA.example.com/jira/ ", api_token=" " + TOKEN + "\n"
    )
    assert credential.credential_type == "jira_software_server_token"
    assert credential.server_url == "https://jira.example.com/jira"
    assert credential.api_token == TOKEN


@pytest.mark.parametrize(
    "token",
    [
        "https://jira.example.com/token",
        "<token>",
        "Bearer secret",
        "bad\nheader",
        "bad\x00token",
        "nonascii-é",
    ],
)
def test_invalid_tokens_are_refused(token):
    with pytest.raises(ValidationError):
        jira.JiraSoftwareServerTokenCredential(
            server_url="https://jira.example.com", api_token=token
        )


@pytest.mark.parametrize(
    "config",
    [
        {"operation": "get_issue", "issue_key": "EX-1/../../myself"},
        {"operation": "move_issues_to_sprint", "sprint_id": 5, "issues": ["EX-1?x=1"]},
        {"operation": "move_issues_to_sprint", "sprint_id": 5, "issues": ["EX-1"] * 51},
        {"operation": "list_boards", "max_results": 101},
        {
            "operation": "create_sprint",
            "board_id": 5,
            "name": "Sprint 1",
            "start_date": "tomorrow",
        },
    ],
)
def test_invalid_configs_make_no_request(config):
    with pytest.raises(ValueError):
        node(config)


def test_explicit_http_and_port_for_self_hosted_jira():
    credential = jira.JiraSoftwareServerTokenCredential(
        server_url="http://jira.example.com:8080/jira", api_token=TOKEN
    )
    assert credential.server_url == "http://jira.example.com:8080/jira"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "example",
    json.loads(
        (
            Path(__file__).parent
            / "fixtures/jira-software-server/provider-responses.json"
        ).read_text()
    ),
    ids=lambda e: "jira-software-server-" + e["operation"],
)
async def test_provider_published_response_examples(monkeypatch, example):
    case = next(c for c in CASES if c["config"]["operation"] == example["operation"])
    transport(
        monkeypatch, lambda _: httpx.Response(case["status"], json=example["body"])
    )
    result = await node(case["config"]).execute({})
    assert result == {"status": "success", "data": example["body"]}

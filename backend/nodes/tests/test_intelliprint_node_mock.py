"""Exercise the real factory and HTTP wire for every Intelliprint operation."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import intelliprint_node as native
from nodes.core.registry import NodeFactory

CONTRACT = json.loads((Path(__file__).parent / "fixtures/intelliprint/contract.json").read_text())

KEY = "intelliprint-test-private-key"
ADDRESS = {"name": "John Doe", "line": "123 Main St, Anytown, Anyplace", "postcode": "AB1 2CD", "country": "GB"}


def node(config):
    return NodeFactory.create_node(node_id="intelliprint-test", node_type="automation-intelliprint",
        node_data={"config": config, "credentials": {"credential_type": "intelliprint_api_key", "api_key": KEY}})


def mock(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests



@pytest.mark.asyncio
@pytest.mark.parametrize("operation,route", [(name, (op["method"], op["path"])) for name, op in CONTRACT["operations"].items()])
async def test_every_operation_exact_method_path_and_bearer(monkeypatch, operation, route):
    config = {"operation": operation}
    if "{id}" in route[1]: config["id"] = "resource_eg"
    if "{mailing_list}" in route[1]: config["mailing_list"] = "mal_eg"
    config.update({
        "create_print": {"content": "<h1>Hello, world!</h1>", "recipients": [{"address": ADDRESS}]},
        "update_print": {"reference": "My first print job"},
        "create_background": {"file": {"url": "https://example.com/file.pdf"}},
        "update_background": {"name": "Company Letterhead"},
        "create_mailing_list": {"name": "Black Friday Leads"},
        "update_mailing_list": {"name": "Black Friday Leads"},
        "create_recipient": {"address": ADDRESS},
        "update_recipient": {"variables": {"salutation": "Mr."}},
    }.get(operation, {}))
    body = {"object": "list", "data": [], "has_more": False, "total_available": 0} if operation.startswith("list_") else {"id": "resource_eg", "object": "print"}
    requests = mock(monkeypatch, body)
    output = await node(config).execute({})
    request = requests[0]
    assert len(requests) == 1
    assert request.method == route[0]
    assert request.url.path == "/v1" + route[1].replace("{id}", "resource_eg").replace("{mailing_list}", "mal_eg")
    assert request.headers["authorization"] == "Bearer " + KEY
    assert output["status"] == "success"
    assert KEY not in str(output)
    if operation.startswith("list_"):
        assert dict(request.url.params)["limit"] == "10"
        assert dict(request.url.params)["skip"] == "0"
        assert output["next_skip"] is None
    if route[0] == "POST":
        sent = json.loads(request.content)
        assert request.headers["content-type"] == "application/json"
        assert "id" not in sent and "mailing_list" not in sent and "operation" not in sent
        if operation == "create_print":
            assert sent["recipients"] == [{"address": ADDRESS}]
            assert sent["testmode"] is True and sent["confirmed"] is False
        elif operation == "update_print":
            assert sent == {"reference": "My first print job"}
        elif operation == "create_background":
            assert sent["file"] == {"url": "https://example.com/file.pdf"}



@pytest.mark.asyncio
async def test_pagination_and_dotted_boolean_filters(monkeypatch):
    requests = mock(monkeypatch, {"object": "list", "data": [{"id": "pr_eg"}], "has_more": True, "total_available": 100})
    output = await node({"operation": "list_prints", "skip": 10, "testmode": False,
        "letters_status": "waiting_to_print,printing", "returned_acknowledged": False}).execute({})
    assert output["next_skip"] == 11
    assert dict(requests[0].url.params)["testmode"] == "false"
    assert dict(requests[0].url.params)["letters.returned.acknowledged"] == "false"
    assert dict(requests[0].url.params)["letters.status"] == "waiting_to_print,printing"


@pytest.mark.asyncio
async def test_partial_update_preserves_false_empty_values_and_team_null(monkeypatch):
    requests = mock(monkeypatch, {"id": "mal_eg", "object": "mailing_list"})
    await node({"operation": "update_mailing_list", "id": "mal_eg", "delete_old_recipients": False, "recipients": []}).execute({})
    assert json.loads(requests[0].content) == {"delete_old_recipients": False, "recipients": []}
    requests = mock(monkeypatch, {"id": "bg_eg", "object": "background"})
    await node({"operation": "update_background", "id": "bg_eg", "team": None}).execute({})
    assert json.loads(requests[0].content) == {"team": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 202])
async def test_cancellation_acknowledgement_does_not_claim_all_mail_cancelled(monkeypatch, status):
    mock(monkeypatch, {"id": "pr_eg", "object": "print", "confirmed": True}, status)
    output = await node({"operation": "delete_print", "id": "pr_eg"}).execute({})
    assert output["http_status"] == status and output["cancellation_complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_errors_keep_provider_message_redact_token_and_never_retry(monkeypatch, status):
    requests = mock(monkeypatch, {"error": {"message": "Rejected " + KEY}}, status)
    output = await node({"operation": "list_mailing_lists"}).execute({})
    assert output["status"] == "error" and output["http_status"] == status
    assert "Rejected" in output["error"] and KEY not in str(output)
    assert len(requests) == 1


@pytest.mark.parametrize("id", ["../secret", "bad/id", "x?test=true", "https://evil.example"])
def test_path_injection_rejected(id):
    with pytest.raises(ValueError): node({"operation": "get_print", "id": id})


def test_manual_key_defaults_type_and_trims():
    credential = native.IntelliprintAPIKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == "intelliprint_api_key" and credential.api_key == KEY


@pytest.mark.asyncio
async def test_empty_update_refused_before_request(monkeypatch):
    requests = mock(monkeypatch, {})
    with pytest.raises(ValueError, match="at least one field"):
        await node({"operation": "update_print", "id": "pr_eg"}).execute({})
    assert not requests

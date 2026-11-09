"""Native requests and v1.1.8 provider responses.

Fixtures identify two synthetic empty pages where no example is published.
"""
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import abcgymsales_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/abcgymsales/contract_examples.json").read_text()
)["operations"]
CREDS = {
    "credential_type": "abcgymsales_basic",
    "email": "api@example.test",
    "password": "fixture-only-password",
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(
        node_id="abcgymsales-test",
        node_type="automation-abcgymsales",
        node_data={"config": config, "credentials": CREDS},
    )


def transport(monkeypatch, responder):
    requests = []

    def reply(request):
        requests.append(request)
        return responder(request)

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_published_operation_and_response(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = transport(
        monkeypatch,
        lambda _: httpx.Response(example["response_status"], json=example["response"]),
    )
    result = await node(example["config"]).execute({})
    request = requests[0]
    assert result["status"] == "success" and result["data"] == example["response"]
    assert len(requests) == 1 and request.method == example["method"]
    expected = example["path"]
    for key, value in example["config"].items():
        expected = expected.replace("{" + key + "}", str(value))
    assert request.url.path == "/api/v1" + expected
    assert request.url.host == "login.gymsales.net"
    assert (
        request.headers["Authorization"]
        == "Basic "
        + base64.b64encode(b"api@example.test:fixture-only-password").decode()
    )
    if request.method != "GET":
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
        form = parse_qs(request.content.decode())
        for key, value in example["config"].items():
            if key == "operation" or "{" + key + "}" in example["path"]:
                continue
            assert form[key] == [
                str(value).lower() if isinstance(value, bool) else str(value)
            ]
    assert CREDS["password"] not in str(result)


@pytest.mark.asyncio
async def test_repeated_query_filters_page_and_company_evidence(monkeypatch):
    body = {
        "collection": [{"id": 438, "name": "API company"}],
        "pagination": {"total_pages": 3, "total_entries": 57},
    }
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=body))
    out = await node(
        {
            "operation": "list_companies",
            "page": 2,
            "per_page": 25,
            "status_values": ["active", "free"],
            "group_ids": [3, 38],
            "name": "Gym + Yoga",
        }
    ).execute({})
    assert requests[0].url.params.get_list("status[]") == ["active", "free"]
    assert requests[0].url.params.get_list("group_id[]") == ["3", "38"]
    assert (
        requests[0].url.params["name"] == "Gym + Yoga"
        and requests[0].url.params["page"] == "2"
    )
    assert (
        out["items"] == body["collection"] and out["pagination"] == body["pagination"]
    )
    assert native.ABCGymSalesNode.connection_evidence.operation == "list_companies"


@pytest.mark.asyncio
async def test_optional_write_fields_false_and_unicode_survive(monkeypatch):
    requests = transport(
        monkeypatch, lambda _: httpx.Response(200, json={"id": 9191588})
    )
    await node(
        {
            "operation": "update_person",
            "id": "9191588",
            "company_id": "438",
            "first_name": "Zoë + 李",
            "email_opted_out": False,
            "do_not_call": True,
            "birthday": "1987-03-10",
        }
    ).execute({})
    assert parse_qs(requests[0].content.decode()) == {
        "company_id": ["438"],
        "first_name": ["Zoë + 李"],
        "email_opted_out": ["false"],
        "do_not_call": ["true"],
        "birthday": ["1987-03-10"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 422, 429, 500])
async def test_provider_rejection_is_not_success_and_no_retry(monkeypatch, status):
    requests = transport(
        monkeypatch,
        lambda _: httpx.Response(status, text="Denied " + CREDS["password"]),
    )
    result = await node(EXAMPLES["create_person"]["config"]).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Denied [redacted]" and len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelopes_and_malformed_json(monkeypatch):
    transport(
        monkeypatch,
        lambda _: httpx.Response(200, json={"errors": {"message": "Not permitted"}}),
    )
    assert (await node({"operation": "list_companies"}).execute({}))[
        "status"
    ] == "error"
    transport(monkeypatch, lambda _: httpx.Response(200, text="<html>sign in</html>"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await node({"operation": "list_companies"}).execute({})


@pytest.mark.asyncio
async def test_network_failure_does_not_retry_write(monkeypatch):
    def timeout(request):
        raise httpx.ReadTimeout("Timed out", request=request)

    requests = transport(monkeypatch, timeout)
    with pytest.raises(httpx.ReadTimeout):
        await node(EXAMPLES["create_person"]["config"]).execute({})
    assert len(requests) == 1


def test_registration_manual_credentials_and_required_fields():
    assert NODE_REGISTRY["automation-abcgymsales"] is native.ABCGymSalesNode
    assert (
        native.ABCGymSalesCredential(
            email="api@example.test", password="fixture-only"
        ).credential_type
        == "abcgymsales_basic"
    )
    for op in [
        "create_person",
        "update_person",
        "create_activity",
        "create_note",
        "add_tag",
        "extend_trial",
    ]:
        with pytest.raises(ValidationError):
            native.ABCGymSalesFullConfig.model_validate({"config": {"operation": op}})
    for identifier in ["../search", "1?email=x", "1/notes", "https://elsewhere.test"]:
        with pytest.raises(ValidationError):
            native.GetPersonConfig(id=identifier)
    with pytest.raises(ValidationError):
        native.ABCGymSalesCredential(
            email="api@example.test:other", password="fixture-only"
        )

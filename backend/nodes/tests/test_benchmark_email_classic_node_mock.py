"""Replay the provider collection's saved responses; no invented success data.

contract_cases.json preserves all examples of each of the 22 selected requests.
The negative Status fixture is the collection's Get Contact Import Status example.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import benchmark_email_classic_node as benchmark


FIXTURES = Path(__file__).parent / "fixtures" / "benchmark-email-classic"
CASES = json.loads((FIXTURES / "contract_cases.json").read_text())["cases"]


def node(config):
    return benchmark.BenchmarkEmailClassicNode(
        node_id="test", node_type="automation-benchmark-email-classic", node_data={},
        config=benchmark.BenchmarkEmailClassicNodeConfig.model_validate({
            "config": config,
            "credentials": {"api_token": "classic-test-token"},
        }),
    )


def install_api(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(benchmark.httpx, "AsyncClient", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["operation"] + ":" + c["example"]["name"])
async def test_every_saved_example_and_exact_wire_contract(monkeypatch, case):
    seen = []

    def handler(request):
        seen.append(request)
        expected = case["request"]
        assert request.method == expected["method"]
        assert str(request.url).split("?")[0] == expected["url"]
        assert dict(request.url.params) == expected["query"]
        assert request.headers["AuthToken"] == "classic-test-token"
        assert request.headers["Content-Type"] == "application/json"
        assert "Authorization" not in request.headers
        assert (json.loads(request.content) if request.content else None) == expected["body"]
        example = case["example"]
        return httpx.Response(example["code"], content=example["body"].encode(),
            headers=[(h["key"], h["value"]) for h in example.get("header", [])])

    install_api(monkeypatch, handler)
    result = await node(case["config"]).execute({})
    assert len(seen) == 1
    assert result["status"] == "success"
    response = json.loads(case["example"]["body"])["Response"]
    assert result["data"] == response.get("Data", response)
    if "Count" in response:
        assert result["count"] == response["Count"]
    assert "classic-test-token" not in json.dumps(result)


def test_credential_is_manual_and_separate_from_new_api():
    credential = benchmark.BenchmarkEmailClassicCredential(api_token=" classic-test-token ")
    assert credential.credential_type == "benchmark_email_classic_api_token"
    assert credential.api_token == "classic-test-token"
    assert set(benchmark.BenchmarkEmailClassicCredential.model_fields) == {"credential_type", "api_token"}
    assert not benchmark.BenchmarkEmailClassicCredential.model_fields["credential_type"].is_required()
    with pytest.raises(ValidationError):
        benchmark.BenchmarkEmailClassicCredential(credential_type="benchmark_email_api_key", api_token="token")


@pytest.mark.parametrize("token", ["", "https://example.com/token", "one\ntwo", "AuthToken: token"])
def test_invalid_tokens_are_refused(token):
    with pytest.raises(ValidationError):
        benchmark.BenchmarkEmailClassicCredential(api_token=token)


@pytest.mark.parametrize("identifier", ["../Client", "1/2", "?x=y", "1#2", "https://example.com", "1%2f2"])
def test_resource_ids_cannot_change_the_route(identifier):
    with pytest.raises(ValidationError):
        benchmark.GetList(list_id=identifier)


def test_contact_changes_and_permission_are_explicit():
    with pytest.raises(ValidationError):
        benchmark.CreateContact(list_id="1", email="test@cybermaxsolutions.com")
    with pytest.raises(ValidationError):
        benchmark.UpdateContact(list_id="1", contact_id="2")
    # Empty text deliberately clears a name, while absent fields stay absent.
    update = benchmark.UpdateContact(list_id="1", contact_id="2", first_name="")
    assert benchmark._body(update) == {"Data": {"FirstName": ""}}


@pytest.mark.asyncio
async def test_documented_negative_status_is_not_success(monkeypatch):
    install_api(monkeypatch, lambda request: httpx.Response(200,
        content=(FIXTURES / "negative_status.json").read_bytes()))
    result = await node({"operation": "list_contacts", "list_id": "15242968"}).execute({})
    assert result["status"] == "error"
    assert result["data"]["Status"] == "-1"


@pytest.mark.asyncio
async def test_transport_failure_does_not_retry_a_write(monkeypatch):
    seen = []

    def timeout(request):
        seen.append(request)
        raise httpx.ReadTimeout("classic-test-token must not appear", request=request)

    install_api(monkeypatch, timeout)
    result = await node({"operation": "delete_list", "list_id": "15242968"}).execute({})
    assert result["status"] == "error"
    assert len(seen) == 1
    assert "classic-test-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_redirect_is_not_followed(monkeypatch):
    seen = []

    def redirect(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://example.com/"})

    install_api(monkeypatch, redirect)
    result = await node({"operation": "list_lists"}).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 302
    assert len(seen) == 1


def test_evidence_uses_account_owned_lists_and_identity_fallback():
    evidence = benchmark.BenchmarkEmailClassicNode.connection_evidence
    assert evidence.operation == "list_lists"
    assert evidence.identity_operation == "get_account"
    assert evidence.proves == "account"
    assert benchmark.ROUTES[evidence.operation][0] == "GET"
    assert benchmark.ROUTES[evidence.identity_operation][0] == "GET"

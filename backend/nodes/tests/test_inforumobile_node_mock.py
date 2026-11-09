"""Replay the provider's verbatim saved Postman examples through the factory."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import inforumobile_node as provider
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / "fixtures/inforumobile/postman_examples.json").read_text())
CREDENTIAL = {"credential_type": "inforumobile_api_token", "username": "fixture-user", "api_token": "fixture-api-token-73912"}
CASES = [(op, index) for op, row in FIXTURES.items() for index in range(len(row["item"]["response"]))]


@pytest.fixture
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="inforumobile-test", node_type="automation-inforumobile",
        node_data={"config": config, "credentials": CREDENTIAL})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,index", CASES)
async def test_saved_response_and_exact_request(monkeypatch, operation, index):
    item = FIXTURES[operation]["item"]
    example = item["response"][index]
    body = json.loads(item["request"]["body"]["raw"])
    requests = []

    def transport(request):
        requests.append(request)
        assert request.method == item["request"]["method"]
        assert str(request.url) == item["request"]["url"]
        assert json.loads(request.content) == body
        assert request.headers["authorization"] == "Basic " + base64.b64encode(b"fixture-user:fixture-api-token-73912").decode()
        assert CREDENTIAL["api_token"] not in str(request.url)
        return httpx.Response(example["code"], content=example["body"].encode(),
            headers=[(h["key"], h["value"]) for h in example.get("header", [])])

    monkeypatch.setattr(provider, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(**kwargs, transport=httpx.MockTransport(transport)))
    instance = node({"operation": operation, **body["Data"]})
    if example["code"] >= 400:
        with pytest.raises(ValueError, match="Missing Authorization"):
            await instance.execute({})
    else:
        output = await instance.execute({})
        assert output["status"] == "success"
        assert output["response"] == json.loads(example["body"])
        if operation == "list_groups":
            assert output["items"] == json.loads(example["body"])["Data"]["List"]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_connection_evidence_reads_account_groups(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    item = FIXTURES["list_groups"]["item"]
    requests = []
    def transport(request):
        requests.append(request)
        assert request.url.path == provider.ROUTES["list_groups"]
        assert json.loads(request.content) == {"Data": {}}
        r = item["response"][0]
        return httpx.Response(r["code"], content=r["body"].encode())
    monkeypatch.setattr(provider, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(**kwargs, transport=httpx.MockTransport(transport)))
    result = await collect_evidence(node_type="automation-inforumobile", credential_data=CREDENTIAL,
        user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is True
    assert result.samples
    assert result.samples[0].label == str(json.loads(item["response"][0]["body"])["Data"]["List"][0]["GroupName"])
    assert len(requests) == 1


@pytest.mark.parametrize("value", ["", "https://example.com/token", "<token>"])
def test_manual_token_rejects_placeholders(value):
    with pytest.raises(ValueError):
        provider.InforUMobileCredential(username="fixture-user", api_token=value)


def test_credential_type_defaults_for_manual_connect():
    assert provider.InforUMobileCredential(username="fixture-user", api_token=CREDENTIAL["api_token"]).credential_type == "inforumobile_api_token"


def test_refuses_unidentified_contacts_and_oversized_sync_batch():
    with pytest.raises(ValidationError):
        provider.UpsertContacts(List=[{}])
    with pytest.raises(ValidationError):
        provider.UpsertContacts(List=[{"Email": "someone@example.test"}] * 11)

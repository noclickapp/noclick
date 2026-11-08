"""Contract-shaped request and response checks through the actual node factory."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import go_to_training_node as native
from nodes.core.registry import NodeFactory
from nodes.oauth.go_to_training_oauth import OAUTH_PROVIDER

TOKEN = "synthetic-goto-training-token"
CREDS = {"credential_type": "go_to_training_oauth", "access_token": TOKEN, "refresh_token": "synthetic-refresh-token"}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/go-to-training/actions.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="training-test", node_type="automation-go-to-training",
        node_data={"config": config, "credentials": CREDS})


def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        assert request.url.host == "api.getgo.com"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        return response(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("name", list(native.OPERATIONS))
async def test_action_request_body_and_response(monkeypatch, name):
    fixture = FIXTURES[name]
    op = native.OPERATIONS[name]
    def respond(request):
        assert request.method == op["method"]
        path = op["path"]
        for raw, field in native.PATH_FIELDS.items():
            if field in fixture["config"]:
                path = path.replace("{" + raw + "}", fixture["config"][field])
        assert str(request.url) == native.BASE + path
        assert not request.url.query
        if op["body"]:
            assert json.loads(request.content) == fixture["config"]["body"]
        else:
            assert request.content == b""
        return httpx.Response(fixture["status"], json=fixture["response"]) if fixture["status"] != 204 else httpx.Response(204)
    requests = transport(monkeypatch, respond)
    result = await node(fixture["config"]).execute({})
    assert result == {"status": "success", "operation": name, "data": fixture["response"]}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_identity_picker_is_connection_evidence(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={"id": "123456", "displayName": "Training Organizer", "userName": "organizer@example.com"}))
    result = await native.GoToTrainingNode.load_field_options("organizer_key", CREDS)
    assert str(requests[0].url) == native.IDENTITY
    assert result == {"options": [{"value": "123456", "label": "Training Organizer"}], "next_page_token": None}
    assert native.GoToTrainingNode.connection_evidence.field == "organizer_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_provider_errors_and_redirects_are_not_success(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={"description": "Provider rejected the call"}, headers={"Location": "https://other.example.test/"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node(FIXTURES["get_training"]["config"]).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize("key", ["../123", "1/2", "https://example.com", "12?x=1", "1#x"])
def test_path_keys_cannot_change_route(key):
    config = {**FIXTURES["get_training"]["config"], "training_key": key}
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS["get_training"].model_validate(config)


def test_required_fields_and_dates():
    with pytest.raises(ValidationError):
        native.CONFIG_MODELS["register_for_training"].model_validate({"operation": "register_for_training", "organizer_key": "1", "training_key": "2", "body": {"email": "person@example.com"}})
    with pytest.raises(ValidationError):
        native.DateTimeRange(startDate="2030-01-02T12:00:00Z", endDate="2030-01-01T12:00:00Z")


def test_oauth_declaration_and_refresh_policy():
    assert OAUTH_PROVIDER.identity_url == native.IDENTITY
    assert OAUTH_PROVIDER.token_auth == "basic"
    assert OAUTH_PROVIDER.rotates_refresh_tokens is False
    assert OAUTH_PROVIDER.scopes == [] or OAUTH_PROVIDER.scopes == ()
    assert OAUTH_PROVIDER.client_id_env == "GO_TO_TRAINING_CLIENT_ID"

"""Contract tests using mocked HTTP only; no Teamwork account is exercised here."""

import base64
import json
import re
from unittest.mock import Mock

import httpx
import pytest
import respx

from nodes.oauth.teamwork_oauth import OAUTH_PROVIDER

TOKEN_URL = OAUTH_PROVIDER.token_url
USERINFO_URL = OAUTH_PROVIDER.identity_url
from nodes.teamwork_node import (
    CONFIG_MODELS,
    OPERATIONS,
    BODY_SCHEMAS,
    TeamworkAPIKeyCredential,
    TeamworkNode,
    TeamworkNodeConfig,
    TeamworkOAuthCredential,
    _path_field,
    _site_base,
)


SITE = "https://example.teamwork.com"


def node(config, credential=None):
    return TeamworkNode(
        node_id="teamwork-test",
        node_type="automation-teamwork",
        node_data={},
        config=TeamworkNodeConfig(
            config=config,
            credentials=credential
            or TeamworkAPIKeyCredential(api_key="key-1", site_url=SITE),
        ),
        sio=Mock(),
        sid="sid",
        workflow_id="workflow",
        user_id="user",
    )


def sample_config(name, op):
    fields = {
        _path_field(variable): "123"
        for variable in re.findall(r"\{([^}]+)\}", op["path"])
    }
    if op["body"]:
        if name in BODY_SCHEMAS:
            from tests.conformance.harness import sample

            fields["body_json"] = json.dumps(sample({}, BODY_SCHEMAS[name], full=False))
        else:
            fields["body_json"] = "{}"
    return CONFIG_MODELS[name](**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,op", list(OPERATIONS.items()))
async def test_catalog_operation_routes_to_documented_method_and_path(name, op):
    path = re.sub(r"\{[^}]+\}", "123", op["path"])
    with respx.mock(assert_all_called=True) as router:
        route = router.request(op["method"], SITE + path).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = await node(sample_config(name, op)).execute({})
    request = route.calls[0].request
    assert (
        request.headers["Authorization"]
        == "Basic " + base64.b64encode(b"key-1:password").decode()
    )
    assert (json.loads(request.content) if request.content else None) == (
        json.loads(sample_config(name, op).body_json) if op["body"] else None
    )
    assert result["operation"] == name and result["status_code"] == 200


@pytest.mark.asyncio
async def test_oauth_endpoint_path_encoding_and_query_filters():
    credential = TeamworkOAuthCredential(
        access_token="token-1", installation={"apiEndPoint": SITE + "/"}
    )
    config = CONFIG_MODELS["get_task"](
        path_taskid="A/B?C",
        query_json='{"include":"tags","page":2}',
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.get(SITE + "/projects/api/v3/tasks/A%2FB%3FC.json").mock(
            return_value=httpx.Response(200, json={"task": {"id": 1}})
        )
        result = await node(config, credential).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer token-1"
    assert request.url.params["page"] == "2"
    assert request.url.params["include"] == "tags"
    assert result["data"]["task"]["id"] == 1


@pytest.mark.asyncio
async def test_invalid_json_and_api_errors_fail_clearly():
    with pytest.raises(ValueError, match="valid JSON"):
        await node(
            CONFIG_MODELS["create_task"](path_tasklistid="1", body_json="{")
        ).execute({})
    with pytest.raises(ValueError, match="JSON object"):
        await node(CONFIG_MODELS["list_tasks"](query_json="[]")).execute({})
    with respx.mock:
        respx.get(SITE + "/projects/api/v3/tasks.json").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        with pytest.raises(ValueError, match="Teamwork API error 403"):
            await node(CONFIG_MODELS["list_tasks"]()).execute({})
    with respx.mock:
        respx.get(SITE + "/projects/api/v3/tasks.json").mock(
            return_value=httpx.Response(
                302, headers={"Location": "https://elsewhere.example/"}
            )
        )
        with pytest.raises(ValueError, match="Teamwork API error 302"):
            await node(CONFIG_MODELS["list_tasks"]()).execute({})


@pytest.mark.parametrize(
    "url",
    [
        "http://example.teamwork.com",
        "https://teamwork.com.evil.example",
        "https://127.0.0.1",
        "https://example.teamwork.com:444",
        "https://user@example.teamwork.com",
        "https://example.teamwork.com/other",
        "https://example.teamwork.com?x=1",
    ],
)
def test_teamwork_origin_validation_rejects_non_vendor_targets(url):
    with pytest.raises(ValueError, match="HTTPS .*teamwork.com origin"):
        _site_base(url)


@pytest.mark.asyncio
async def test_oauth_exchange_uses_official_json_contract_and_installation_endpoint(
    monkeypatch,
):
    monkeypatch.setenv("TEAMWORK_CLIENT_ID", "client-1")
    monkeypatch.setenv("TEAMWORK_CLIENT_SECRET", "secret-1")
    with respx.mock(assert_all_called=True) as router:
        token_route = router.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "installation": {"apiEndPoint": SITE + "/"},
                },
            )
        )
        user_route = router.get(USERINFO_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "email": "admin@example.com",
                    "installation_id": 42,
                },
            )
        )
        tokens, name = await OAUTH_PROVIDER.exchange(
            "code-1", "https://app.example/api/auth/teamwork/callback"
        )
    assert json.loads(token_route.calls[0].request.content) == {
        "client_id": "client-1",
        "client_secret": "secret-1",
        "code": "code-1",
        "redirect_uri": "https://app.example/api/auth/teamwork/callback",
    }
    assert user_route.calls[0].request.headers["Authorization"] == "Bearer access-1"
    assert tokens.access_token == "access-1"
    assert tokens.installation == {"apiEndPoint": SITE + "/"}
    assert name == "admin@example.com"


@pytest.mark.asyncio
async def test_oauth_node_rejects_untrusted_installation_endpoint():
    credential = TeamworkOAuthCredential(
        access_token="token", installation={"apiEndPoint": "https://attacker.example"}
    )
    with pytest.raises(ValueError, match="HTTPS .*teamwork.com origin"):
        await node(CONFIG_MODELS["list_tasks"](), credential).execute({})


@pytest.mark.asyncio
async def test_missing_required_request_envelope_fails_before_http():
    with pytest.raises(ValueError, match="Teamwork request body.*required property"):
        await node(CONFIG_MODELS["create_tag"](body_json="{}")).execute({})


@pytest.mark.asyncio
async def test_optional_request_fields_keep_their_documented_types():
    with pytest.raises(ValueError, match="Teamwork request body.*integer"):
        await node(
            CONFIG_MODELS["create_tag"](
                body_json='{ "tag": { "projectId": "invalid" } }'
            )
        ).execute({})


@pytest.mark.parametrize("value", [None, "text", 1, False, ["choice"]])
def test_custom_field_value_accepts_documented_types(value):
    from nodes.teamwork_node import _BODY_VALIDATOR

    assert _BODY_VALIDATOR({"type": "any"}).is_valid(value)


def test_custom_field_value_rejects_undocumented_object():
    from nodes.teamwork_node import _BODY_VALIDATOR

    assert not _BODY_VALIDATOR({"type": "any"}).is_valid({})

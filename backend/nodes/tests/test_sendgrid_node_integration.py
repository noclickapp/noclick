"""SendGrid action routing, region, authentication, and mail payload tests."""

import json
import re
from unittest.mock import Mock
from urllib.parse import quote

import httpx
import pytest
import respx

from nodes.sendgrid_node import (
    CONFIG_MODELS, HOSTS, OPERATIONS, SendGridApiKeyCredential,
    SendGridNode, SendGridNodeConfig, _field_name,
)


def make_node(config, *, region="us"):
    return SendGridNode(
        node_id="sendgrid-test", node_type="automation-sendgrid", node_data={},
        config=SendGridNodeConfig(
            config=config, credentials=SendGridApiKeyCredential(api_key="test-api-key", region=region)
        ),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


def sample_config(name, op):
    fields = {_field_name(variable, "path"): "example" for variable in re.findall(r"\{([^}]+)\}", op["path"])}
    fields.update({_field_name(param["name"], param["in"]): "example" for param in op["required_params"]
                   if param["name"].lower() != "accept"})
    if name == "send_email":
        fields.update(from_email="sender@example.com", to_emails="recipient@example.com", text_body="Hello")
    elif op["body_required"]:
        fields["body_input"] = '{"example":true}'
    return CONFIG_MODELS[name](**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,op", list(OPERATIONS.items()))
async def test_every_documented_action_reaches_the_correct_endpoint(name, op):
    path = op["path"]
    for variable in re.findall(r"\{([^}]+)\}", path):
        path = path.replace("{" + variable + "}", quote("example", safe=""))
    with respx.mock(assert_all_called=True) as router:
        route = router.request(op["method"], HOSTS["us"] + path).mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        result = await make_node(sample_config(name, op)).execute({})
    assert route.called, name
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-api-key"
    assert result["status"] == "success"
    assert result["operation"] == name
    if op["body_required"]:
        assert route.calls[0].request.content


@pytest.mark.asyncio
async def test_send_email_simple_fields_and_accepted_response():
    config = CONFIG_MODELS["send_email"](
        from_email="sender@example.com", to_emails="a@example.com,b@example.com",
        cc_emails="cc@example.com", subject="Hello", text_body="Hi there",
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.sendgrid.com/v3/mail/send").mock(
            return_value=httpx.Response(202, headers={"x-message-id": "message-123"})
        )
        result = await make_node(config).execute({})
    body = json.loads(route.calls[0].request.content)
    assert body["personalizations"][0]["to"] == [
        {"email": "a@example.com"}, {"email": "b@example.com"},
    ]
    assert body["personalizations"][0]["cc"] == [{"email": "cc@example.com"}]
    assert body["content"] == [{"type": "text/plain", "value": "Hi there"}]
    assert result["message_id"] == "message-123"
    assert result["status_code"] == 202


@pytest.mark.asyncio
async def test_dynamic_template_and_raw_body():
    config = CONFIG_MODELS["send_email"](
        from_email="sender@example.com", to_emails="a@example.com",
        template_id="d-123", dynamic_template_data_json='{"name":"Ada"}',
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.sendgrid.com/v3/mail/send").mock(return_value=httpx.Response(202))
        await make_node(config).execute({})
    body = json.loads(route.calls[0].request.content)
    assert body["template_id"] == "d-123"
    assert body["personalizations"][0]["dynamic_template_data"] == {"name": "Ada"}

    raw = CONFIG_MODELS["send_email"](body_input='{"personalizations":[{"to":[{"email":"raw@example.com"}]}],"from":{"email":"sender@example.com"},"content":[{"type":"text/plain","value":"Hi"}]}')
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.sendgrid.com/v3/mail/send").mock(return_value=httpx.Response(202))
        await make_node(raw).execute({})
    assert json.loads(route.calls[0].request.content)["personalizations"][0]["to"][0]["email"] == "raw@example.com"


@pytest.mark.asyncio
async def test_eu_routing_and_restriction():
    config = CONFIG_MODELS["send_email"](
        from_email="sender@example.com", to_emails="a@example.com", text_body="Hi",
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.eu.sendgrid.com/v3/mail/send").mock(return_value=httpx.Response(202))
        await make_node(config, region="eu").execute({})
    assert route.called
    us_only = next(name for name, op in OPERATIONS.items() if op["regions"] == ["us"])
    with pytest.raises(ValueError, match="unavailable on SendGrid's EU API"):
        await make_node(sample_config(us_only, OPERATIONS[us_only]), region="eu").execute({})


@pytest.mark.asyncio
async def test_query_subuser_validation_and_errors():
    config = CONFIG_MODELS["test_connection"](
        query_json='{"limit":2}', on_behalf_of="child-user",
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://api.sendgrid.com/v3/scopes").mock(
            return_value=httpx.Response(200, json={"scopes": ["mail.send"]})
        )
        result = await make_node(config).execute({})
    assert route.calls[0].request.headers["On-Behalf-Of"] == "child-user"
    assert route.calls[0].request.url.params["limit"] == "2"
    assert result["data"]["scopes"] == ["mail.send"]

    with pytest.raises(ValueError, match="must be an object"):
        await make_node(CONFIG_MODELS["test_connection"](query_json="[]")).execute({})
    with pytest.raises(ValueError, match="From Email and To Emails"):
        await make_node(CONFIG_MODELS["send_email"]()).execute({})
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.sendgrid.com/v3/scopes").mock(
            return_value=httpx.Response(403, json={"errors": [{"message": "permission denied"}]})
        )
        with pytest.raises(ValueError, match="SendGrid API error 403"):
            await make_node(CONFIG_MODELS["test_connection"]()).execute({})


@pytest.mark.asyncio
async def test_partner_sso_accepts_documented_303_without_following_redirect():
    # tsg_account_provisioning_v3.json documents 303, not 2xx, as success.
    name = "account_provisioning_authenticate_account"
    op = OPERATIONS[name]
    path = re.sub(r"\{[^}]+\}", "example", op["path"])
    with respx.mock(assert_all_called=True) as router:
        router.request(op["method"], HOSTS["us"] + path).mock(
            return_value=httpx.Response(303, headers={"Location": "https://app.sendgrid.com/"})
        )
        result = await make_node(sample_config(name, op)).execute({})
    assert result["status"] == "success"
    assert result["status_code"] == 303
    assert result["redirect_url"] == "https://app.sendgrid.com/"


@pytest.mark.asyncio
async def test_other_redirects_are_still_rejected():
    with respx.mock(assert_all_called=True) as router:
        router.get(HOSTS["us"] + "/v3/scopes").mock(return_value=httpx.Response(303))
        with pytest.raises(ValueError, match="SendGrid API error 303"):
            await make_node(CONFIG_MODELS["test_connection"]()).execute({})

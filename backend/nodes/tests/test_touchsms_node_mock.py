"""Native factory requests against touchSMS's published JSON examples; no live sends."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import touchsms_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/touchsms/documented_examples.json").read_text())
CREDENTIAL = {"credential_type": "touchsms_api_key", "access_token": "synthetic-access-token", "token_id": "synthetic-token-id"}


def node(config):
    return NodeFactory.create_node(node_id="touchsms-test", node_type="automation-touchsms", node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "get_account"}, "GET", "/v2/account", "Account"),
    ({"operation": "list_groups", "page": 2, "search": "Customers + VIP"}, "GET", "/v2/groups", "Group"),
    ({"operation": "get_group", "group_id": 123}, "GET", "/v2/groups/123", "Group"),
    ({"operation": "list_contacts"}, "GET", "/v2/contacts", "Contact"),
    ({"operation": "get_contact", "contact_id": 4040}, "GET", "/v2/contacts/4040", "Contact"),
    ({"operation": "create_contact", "number": "+61412345678", "firstname": "Sam", "update_if_exists": True}, "POST", "/v2/contacts", "Contact"),
    ({"operation": "update_contact", "contact_id": 4040, "number": "+61412345678", "surname": "Taylor"}, "PUT", "/v2/contacts/4040", "Contact"),
    ({"operation": "delete_contact", "contact_id": 4040}, "DELETE", "/v2/contacts/4040", None),
    ({"operation": "list_templates"}, "GET", "/v2/templates", "Template"),
    ({"operation": "get_template", "template_id": 1234}, "GET", "/v2/templates/1234", "Template"),
    ({"operation": "create_template", "sender_id": "SHARED_NUMBER", "name": "Reminder", "message": "Hello"}, "POST", "/v2/templates", "Template"),
    ({"operation": "update_template", "template_id": 1234, "sender_id": "SHARED_NUMBER", "name": "Reminder", "message": "Hello", "subject": None}, "PUT", "/v2/templates/1234", "Template"),
    ({"operation": "delete_template", "template_id": 1234}, "DELETE", "/v2/templates/1234", None),
    ({"operation": "list_optouts"}, "GET", "/v2/optouts", "Optout"),
    ({"operation": "get_optout", "optout_id": 123}, "GET", "/v2/optouts/123", "Optout"),
    ({"operation": "create_optout", "number": "+61412345678", "opt_out_list_name": "Marketing Opt-Outs"}, "POST", "/v2/optouts", "Optout"),
    ({"operation": "delete_optout", "optout_id": 123}, "DELETE", "/v2/optouts/123", None),
    ({"operation": "list_optout_lists"}, "GET", "/v2/optout-lists", "OptoutList"),
    ({"operation": "get_optout_list", "optout_list_id": 2}, "GET", "/v2/optout-lists/2", "OptoutList"),
    ({"operation": "list_optout_list_optouts", "optout_list_id": 2}, "GET", "/v2/optout-lists/2/optouts", "Optout"),
    ({"operation": "list_sender_ids", "country": "AU", "message_type": "mms"}, "GET", "/v2/account/sender-ids", "SenderId"),
    ({"operation": "list_sender_ids_for_number", "number": "+61412345678"}, "GET", "/v2/account/sender-ids/for/+61412345678", "SenderId"),
    ({"operation": "list_inbounds", "id_after": 1350660, "created_after": "2024-03-11T00:00:00Z"}, "GET", "/v2/inbounds", "Inbound"),
    ({"operation": "send_messages", "messages": [{"to": "+61412345678", "from": "SHARED_NUMBER", "body": "Hi Sam, your order has shipped."}]}, "POST", "/v2/sms", "SendResult"),
    ({"operation": "validate_messages", "messages": [{"to": "+61412345678", "from": "SHARED_NUMBER", "body": "Hi Sam, your order has shipped."}]}, "POST", "/v2/sms/dry", "SendResult"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,kind", CASES, ids=[c[0]["operation"] for c in CASES])
async def test_provider_contract_routes_auth_body_and_examples(monkeypatch, config, method, path, kind):
    action = config["operation"]
    status = 204 if action in {"delete_contact", "delete_template"} else 201 if action.startswith("create_") else 200
    data = [EXAMPLES[kind]] if action.startswith("list_") else EXAMPLES.get(kind)
    body = {"data": data}
    if action in {"list_groups", "list_contacts", "list_optouts", "list_optout_list_optouts", "list_inbounds"}:
        body.update({"links": {"next": "https://app.touchsms.com.au/api" + path + "?page=3"}, "meta": {"current_page": config.get("page", 1), "last_page": 3}})
    response = httpx.Response(status, json=body) if kind else httpx.Response(status)
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert result["status"] in {"success", "partial"} and result["http_status"] == status
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.host == "app.touchsms.com.au" and req.url.path == "/api" + path
    assert base64.b64decode(req.headers["Authorization"].split()[1]).decode() == "synthetic-access-token:synthetic-token-id"
    if method == "GET":
        assert not req.content
        assert result["data"] == data
        if "page" in req.url.params:
            assert result["links"] == body["links"] and result["meta"] == body["meta"]
    elif method == "DELETE":
        assert not req.content and result["deletion_acknowledged"]
    else:
        sent = json.loads(req.content)
        assert "operation" not in sent
        assert all(not key.endswith("_id") or key in {"sender_id", "opt_out_list_id"} for key in sent)
        for key, value in config.items():
            if key != "operation" and key in sent:
                assert sent[key] == value
        if kind == "SendResult":
            assert sent["messages"][0]["from"] == "SHARED_NUMBER"
            assert result["all_accepted"] is False and result["delivery_verified"] is False
            assert result["dry_run"] == (action == "validate_messages")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 404, 406, 422, 429, 500])
async def test_provider_failures_are_not_success_and_secrets_are_redacted(monkeypatch, status):
    transport(monkeypatch, httpx.Response(status, json={"message": "Rejected " + CREDENTIAL["access_token"]}))
    result = await node({"operation": "get_account"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"data": None}, {"data": []}, {"data": {}}])
async def test_invalid_account_envelope_does_not_prove_connection(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    assert (await node({"operation": "get_account"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
async def test_transport_uncertainty_never_retries_a_send(monkeypatch):
    def fail(req):
        raise httpx.ReadTimeout("ambiguous", request=req)
    requests = transport(monkeypatch, fail)
    result = await node(CASES[-2][0]).execute({})
    assert result["status"] == "error" and result["write_outcome"] == "unknown" and len(requests) == 1


@pytest.mark.parametrize("config", [
    {"operation": "send_messages", "messages": []},
    {"operation": "send_messages", "messages": [{"to": "+61412345678", "from": "SHARED_NUMBER"}]},
    {"operation": "update_contact", "contact_id": 4040},
    {"operation": "get_contact", "contact_id": "../account"},
    {"operation": "list_contacts", "per_page": 1000},
    {"operation": "create_optout", "number": "+61412345678", "opt_out_list_id": 1, "opt_out_list_name": "Both"},
])
def test_invalid_inputs(config):
    with pytest.raises((ValidationError, ValueError)):
        native.TouchSMSNode.parse_config({"config": config, "credentials": CREDENTIAL})


def test_hand_connect_default_type_and_evidence():
    shaped, errors, resolved = shape_credential("touchsms_api_key", {"access_token": "  synthetic-access-token  ", "token_id": "synthetic-token-id"})
    assert not errors and resolved is not None
    assert shaped == {k: v for k, v in CREDENTIAL.items() if k != "credential_type"}
    assert native.TouchSMSCredential.model_validate(shaped).credential_type == "touchsms_api_key"
    evidence = native.TouchSMSNode.connection_evidence
    assert evidence.identity_operation == "get_account" and evidence.proves == "account"
    assert len(native.ROUTES) == 25

"""Verify Zadarma wire requests and parsing against provider-authored examples.

Synthetic credentials stay local; no real SMS, callback or account is used.
"""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError
from nodes import zadarma_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/zadarma/responses.json").read_text())["examples"]
CREDENTIAL = {"credential_type": "zadarma_api_key", "api_key": "synthetic-key-zadarma", "api_secret": "synthetic-secret-zadarma"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="zadarma-test", node_type="automation-zadarma",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def test_php_rfc1738_and_hex_hmac_vector():
    query = native.encode_params({"to": "+442037691881", "message": "Hello ~ + &", "predicted": False})
    assert query == "message=Hello+%7E+%2B+%26&predicted=0&to=%2B442037691881"
    # Independently calculated with OpenSSL MD5 and SHA1 HMAC, then hex base64.
    credential = native.ZadarmaAPIKeyCredential.model_validate(CREDENTIAL)
    assert native.authorization(credential, "/v1/sms/send", query) == "synthetic-key-zadarma:MjM1NTdlMDg3YjUwYzNjMDgxY2YxNTgxYWM3N2MwMTc1YmYzYmE0YQ=="
    assert credential.credential_type == "zadarma_api_key"
    assert native.ZadarmaAPIKeyCredential(api_key="key", api_secret="secret").credential_type == "zadarma_api_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,example,method,path,params", [
    ({"operation":"list_sip_numbers"}, "api_sip_method", "GET", "/v1/sip", {}),
    ({"operation":"request_callback", "from_number":"442037691880", "to":"442037691881", "predicted":False}, "api_callback", "GET", "/v1/request/callback", {"from":["442037691880"],"to":["442037691881"],"predicted":["0"]}),
    ({"operation":"get_sip_status", "sip":"00001"}, "api_sip_status", "GET", "/v1/sip/00001/status", {}),
    ({"operation":"set_sip_caller_id", "id":"00001", "number":"442037691880"}, "api_sip_callerid", "PUT", "/v1/sip/callerid", {"id":["00001"],"number":["442037691880"]}),
    ({"operation":"set_sip_forwarding", "id":"00001", "status":"on"}, "api_sip_redirection_put", "PUT", "/v1/sip/redirection", {"id":["00001"],"status":["on"]}),
    ({"operation":"get_pbx_extension_status", "pbxsip":"100"}, "api_pbx_internal_status", "GET", "/v1/pbx/internal/100/status", {}),
    ({"operation":"get_pbx_extension_info", "pbxsip":"100"}, "api_pbx_internal_info", "GET", "/v1/pbx/internal/100/info", {}),
    ({"operation":"set_pbx_forwarding", "pbx_number":"100", "status":"on", "type":"phone", "destination":"442037691880", "condition":"noanswer"}, "api_pbx_redirection_post", "POST", "/v1/pbx/redirection", {"pbx_number":["100"],"status":["on"],"type":["phone"],"destination":["442037691880"],"condition":["noanswer"]}),
    ({"operation":"send_sms", "number":"1234567890", "message":"Hello ~ + &"}, "api_sms_send", "POST", "/v1/sms/send", {"number":["1234567890"],"message":["Hello ~ + &"]}),
    ({"operation":"list_sms_templates"}, "api_sms_template", "GET", "/v1/sms/templates", {"skip":["0"],"limit":["25"]}),
])
async def test_provider_examples_and_wire(monkeypatch, config, example, method, path, params):
    requests = transport(monkeypatch, EXAMPLES[example])
    result = await node(config).execute({})
    assert result["status"] == "success"
    assert result["data"] == EXAMPLES[example]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.zadarma.com"
    query = request.url.query.decode() if method == "GET" else request.content.decode()
    assert parse_qs(query) == params
    assert "params" not in parse_qs(query)
    assert request.headers["Authorization"] == native.authorization(native.ZadarmaAPIKeyCredential(**CREDENTIAL), path, query)
    if method != "GET":
        assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert CREDENTIAL["api_secret"] not in str(result)


@pytest.mark.asyncio
async def test_connection_names_own_sips(monkeypatch):
    transport(monkeypatch, EXAMPLES["api_sip_method"])
    result = await node({"operation":"list_sip_numbers"}).execute({})
    assert result["items"] == [{"id":"00001", "name":"SIP 1"}, {"id":"00002", "name":"SIP 2"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200,401,429])
async def test_rejection_is_not_success_and_not_retried(monkeypatch,status):
    requests=transport(monkeypatch,{"status":"error","message":"Check phone's number"},status)
    result=await node({"operation":"list_sip_numbers"}).execute({})
    assert result["status"] == "error" and result["error"] == "Check phone's number"
    assert len(requests)==1


@pytest.mark.parametrize("config", [
    {"operation":"get_sip_status","sip":"../100"},
    {"operation":"get_pbx_extension_info","pbxsip":"100/../../"},
    {"operation":"set_pbx_forwarding","pbx_number":"100","status":"on"},
    {"operation":"set_pbx_forwarding","pbx_number":"100","status":"off","destination":"123"},
    {"operation":"get_call_statistics","start":"2026-02-30 00:00:00","end":"2026-03-01 00:00:00"},
    {"operation":"get_call_statistics","start":"2026-03-01 00:00:00","end":"2026-02-01 00:00:00"},
])
def test_invalid_configuration_is_rejected(config):
    with pytest.raises((ValidationError,ValueError)):
        node(config)

"""Kernel's real node factory against HTTP fixtures; never a provider account."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import kernel_node as native
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential

TOKEN = "kernel-synthetic-test-key"
AUTH = {"credential_type": "kernel_api_key", "api_key": TOKEN}
FIXTURES = json.loads((Path(__file__).parent / "fixtures/kernel/responses.json").read_text())
BROWSER = "htzv5orfit78e1m2biiifpbv"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    seen, replies, policies = [], [], []
    def send(request):
        seen.append(request)
        assert request.url.host == "api.onkernel.com"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert TOKEN not in str(request.url)
        return replies.pop(0)
    def client(**kwargs):
        policies.append(kwargs)
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return seen, replies, policies


async def run(config, credential=AUTH):
    node = NodeFactory.create_node(node_id="kernel-fixture", node_type="automation-kernel",
                                   node_data={"config": config, "credentials": credential})
    return await node.execute({})


CASES = [
    ("get_auth_context", {}, "GET", "/auth/context", "auth"),
    ("list_browsers", {}, "GET", "/browsers", "browser"),
    ("get_browser", {"browser_id": BROWSER}, "GET", "/browsers/" + BROWSER, "browser"),
    ("create_browser", {}, "POST", "/browsers", "browser"),
    ("update_browser", {"browser_id": BROWSER, "name": "checkout-flow-1"}, "PATCH", "/browsers/" + BROWSER, "browser"),
    ("delete_browser", {"browser_id": BROWSER}, "DELETE", "/browsers/" + BROWSER, None),
    ("execute_playwright", {"browser_id": BROWSER, "code": "return await page.title();"}, "POST", "/browsers/" + BROWSER + "/playwright/execute", "playwright"),
    ("list_profiles", {}, "GET", "/profiles", "profile"),
    ("get_profile", {"profile_id": "profile-fixture"}, "GET", "/profiles/profile-fixture", "profile"),
    ("create_profile", {"name": "fixture-profile"}, "POST", "/profiles", "profile"),
    ("rename_profile", {"profile_id": "profile-fixture", "name": "renamed"}, "PATCH", "/profiles/profile-fixture", "profile"),
    ("delete_profile", {"profile_id": "profile-fixture"}, "DELETE", "/profiles/profile-fixture", None),
    ("list_proxies", {}, "GET", "/proxies", "proxy"),
    ("get_proxy", {"proxy_id": "proxy-fixture"}, "GET", "/proxies/proxy-fixture", "proxy"),
    ("delete_proxy", {"proxy_id": "proxy-fixture"}, "DELETE", "/proxies/proxy-fixture", None),
    ("list_apps", {}, "GET", "/apps", "app"),
    ("list_invocations", {}, "GET", "/invocations", "invocation"),
    ("invoke_action", {"app_name": "my-app", "action_name": "analyze", "payload": '{"data":"example input"}'}, "POST", "/invocations", "invoke"),
    ("get_invocation", {"invocation_id": "rr33xuugxj9h0bkf1rdt2bet"}, "GET", "/invocations/rr33xuugxj9h0bkf1rdt2bet", "invocation"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,fixture", CASES)
async def test_every_operation_uses_one_contract_endpoint(wire, operation, config, method, path, fixture):
    payload = FIXTURES[fixture] if fixture else None
    if operation.startswith("list_"):
        payload = [payload]
    status = 204 if method == "DELETE" else 202 if operation == "invoke_action" else 201 if operation == "create_profile" else 200
    wire[1].append(httpx.Response(status, json=payload) if payload is not None else httpx.Response(status))
    result = await run({"operation": operation, **config})
    assert len(wire[0]) == 1 and not wire[1]
    request = wire[0][0]
    assert (request.method, request.url.path) == (method, path)
    assert result["http_status"] == status
    if method == "DELETE":
        assert result["acknowledged"] is True
    elif operation == "get_auth_context":
        assert result["organization"] == payload["organization"]
    else:
        assert result["data"] == payload
    if operation == "invoke_action":
        assert json.loads(request.content) == {"app_name":"my-app", "action_name":"analyze", "version":"latest", "payload":'{"data":"example input"}', "async":True, "async_timeout_seconds":900}
        assert result["data"]["status"] == "queued" and "success" not in result
    if method == "GET":
        assert request.content == b""


@pytest.mark.asyncio
async def test_browser_profile_proxy_and_false_values(wire):
    wire[1].append(httpx.Response(200, json=FIXTURES["browser"]))
    await run({"operation":"create_browser", "profile_id":"profile-fixture", "save_changes":True, "proxy_id":"proxy-fixture", "headless":False, "stealth":False})
    body = json.loads(wire[0][0].content)
    assert body == {"timeout_seconds":60, "headless":False, "stealth":False,
                    "profile":{"id":"profile-fixture", "save_changes":True}, "proxy":{"id":"proxy-fixture"}}


@pytest.mark.asyncio
async def test_pagination_and_filters_remain_explicit(wire):
    wire[1].append(httpx.Response(200, json=[FIXTURES["profile"]], headers={"X-Has-More":"true", "X-Next-Offset":"40"}))
    result = await run({"operation":"list_profiles", "limit":20, "offset":20, "query":"fixture", "name":"fixture-profile"})
    assert result["has_more"] is True and result["next_offset"] == 40
    assert dict(wire[0][0].url.params) == {"limit":"20", "offset":"20", "query":"fixture", "name":"fixture-profile"}
    wire[1].append(httpx.Response(200, json=[], headers={"X-Has-More":"false", "X-Next-Offset":"0"}))
    result = await run({"operation":"list_profiles", "offset":40})
    assert result["has_more"] is False and result["next_offset"] is None
    wire[1].append(httpx.Response(200, json=[]))
    assert (await run({"operation":"list_profiles"}))["has_more"] is None


@pytest.mark.asyncio
async def test_missing_or_repeated_continuation_is_rejected(wire):
    for headers in [{"X-Has-More":"true"}, {"X-Has-More":"true", "X-Next-Offset":"0"}, {"X-Has-More":"maybe"}]:
        wire[1].append(httpx.Response(200, json=[], headers=headers))
        with pytest.raises(ValueError):
            await run({"operation":"list_profiles"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302,401,403,404,429,500])
async def test_http_failures_and_redirects_are_not_retried(wire, status):
    wire[1].append(httpx.Response(status, json={"message":"refused"}, headers={"Location":"https://foreign.test"}))
    with pytest.raises(httpx.HTTPStatusError):
        await run({"operation":"list_browsers"})
    assert len(wire[0]) == 1


@pytest.mark.asyncio
async def test_playwright_failure_is_preserved(wire):
    wire[1].append(httpx.Response(200, json={"success":False, "error":"Execution failed"}))
    result = await run({"operation":"execute_playwright", "browser_id":BROWSER, "code":"throw Error('failed')"})
    assert result["success"] is False and result["data"]["error"] == "Execution failed"


@pytest.mark.asyncio
async def test_sync_invocation_omits_async_timeout(wire):
    wire[1].append(httpx.Response(200, json={**FIXTURES["invoke"], "status":"succeeded"}))
    await run({"operation":"invoke_action", "app_name":"my-app", "action_name":"analyze", "asynchronous":False})
    assert json.loads(wire[0][0].content) == {"app_name":"my-app", "version":"latest", "action_name":"analyze", "async":False}


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [httpx.Response(200, text="<html>login</html>", headers={"Content-Type":"text/html"}), httpx.Response(200,json={"error":"refused"}), httpx.Response(200,json={"items":[]})])
async def test_bad_list_response_does_not_prove_connection(wire, reply):
    wire[1].append(reply)
    with pytest.raises(ValueError):
        await run({"operation":"list_profiles"})


@pytest.mark.asyncio
async def test_identity_uses_authenticated_organization(wire):
    wire[1].append(httpx.Response(200, json=FIXTURES["auth"]))
    result = await run({"operation":"get_auth_context"})
    assert result["name"] == "org-fixture"
    wire[1].append(httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        await run({"operation":"get_auth_context"})


@pytest.mark.parametrize("config", [
    {"operation":"update_browser", "browser_id":BROWSER},
    {"operation":"create_browser", "save_changes":True},
    {"operation":"create_browser", "name":"not a name"},
    {"operation":"execute_playwright", "browser_id":BROWSER, "code":"return 1", "timeout_sec":301},
    {"operation":"invoke_action", "app_name":"my-app", "action_name":"analyze", "payload":"not-json"},
    {"operation":"get_browser", "browser_id":".."},
    {"operation":"get_browser", "browser_id":"id\n"},
    {"operation":"list_browsers", "limit":101},
    {"operation":"list_browsers", "url":"https://foreign.test"},
])
def test_invalid_inputs_refused_before_http(wire, config):
    with pytest.raises(ValueError):
        native.KernelNode.parse_config({"config":config, "credentials":AUTH})
    assert not wire[0]


def test_pasted_key_connect_fields_and_default_type():
    credential = native.KernelApiKeyCredential(api_key=TOKEN)
    assert credential.credential_type == "kernel_api_key"
    shaped, errors, resolved = shape_credential("kernel_api_key", {"api_key":TOKEN})
    assert not errors and shaped["api_key"] == TOKEN
    assert resolved[1] is native.KernelApiKeyCredential


@pytest.mark.parametrize("key", ["https://example.test/key", "Bearer token", "key\nvalue", "<token>"])
def test_invalid_pasted_keys(key):
    with pytest.raises(ValueError):
        native.KernelApiKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize("has_profiles", [True, False])
async def test_connection_evidence_samples_or_names_the_organization(wire, monkeypatch, has_profiles):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence

    async def native_operation(**kwargs):
        return await run({"operation":kwargs["operation"], **kwargs["arguments"]}, kwargs["credential_data"])

    monkeypatch.setattr(run_op, "run_node_operation", native_operation)
    wire[1].append(httpx.Response(200, json=[FIXTURES["profile"]] if has_profiles else []))
    if not has_profiles:
        wire[1].append(httpx.Response(200, json=FIXTURES["auth"]))
    result = await collect_evidence(node_type="automation-kernel", user_id="fixture-user", credential_data=AUTH)
    assert result.reachable is True
    if has_profiles:
        assert [sample.label for sample in result.samples] == ["fixture-profile"]
        assert len(wire[0]) == 1
    else:
        assert result.account_label == "org-fixture" and not result.samples
        assert [request.url.path for request in wire[0]] == ["/profiles", "/auth/context"]

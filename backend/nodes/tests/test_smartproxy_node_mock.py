"""Exercise the registered Smartproxy node against a real HTTP mock transport."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import smartproxy_node as node
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": "smartproxy_api_key", "api_key": "synthetic-smartproxy-key"}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    async def send(request):
        requests.append(request)
        assert request.url.host == "api.decodo.com"
        assert request.headers["Authorization"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(node, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None, auth=AUTH):
    return await run_node_operation(node_type="automation-smartproxy", operation=operation,
        arguments=arguments or {}, credential_data=auth, user_id=USER)


CASES = [
    ("list_sub_users", {}, "GET", "/v2/sub-users", {"service_type": "residential_proxies"}, 200, [{"id": 1, "username": "name"}]),
    ("create_sub_user", {"username": "tester_1", "password": "Test_password12", "traffic_limit": 2, "auto_disable": True}, "POST", "/v2/sub-users", {"username": "tester_1", "password": "Test_password12", "service_type": "residential_proxies", "traffic_limit": 2, "auto_disable": True}, 201, {}),
    ("get_sub_user", {"sub_user_id": 24570}, "GET", "/v2/sub-users/24570", {}, 200, {"id": 24570, "username": "name", "traffic_limit": None}),
    ("update_sub_user", {"sub_user_id": 24570, "traffic_limit": 0, "auto_disable": False, "status": "disabled"}, "PUT", "/v2/sub-users/24570", {"traffic_limit": 0, "auto_disable": False, "status": "disabled"}, 201, {}),
    ("delete_sub_user", {"sub_user_id": 24570}, "DELETE", "/v2/sub-users/24570", {}, 204, None),
    ("get_sub_user_traffic", {"sub_user_id": 24570, "period": "custom", "from_date": "2024-09-01", "to_date": "2024-10-01"}, "GET", "/v2/sub-users/24570/traffic", {"service_type": "residential_proxies", "type": "custom", "from": "2024-09-01", "to": "2024-10-01"}, 200, {"traffic": 4.7, "traffic_rx": 4.2, "traffic_tx": 0.5}),
    ("get_allocated_traffic", {}, "GET", "/v2/allocated-traffic-limit", {"service_type": "residential_proxies"}, 200, {"allocated_traffic_limit": 728}),
    ("list_whitelisted_ips", {}, "GET", "/v2/whitelisted-ips", {}, 200, [{"id": 69489, "ip": "127.0.0.1", "enabled": True}]),
    ("add_whitelisted_ips", {"ip_addresses": ["127.0.0.1", "192.0.2.10"]}, "POST", "/v2/whitelisted-ips", {"IPAddressList": ["127.0.0.1", "192.0.2.10"]}, 200, {}),
    ("delete_whitelisted_ip", {"whitelist_id": "69489"}, "DELETE", "/v2/whitelisted-ips/69489", {}, 204, None),
    ("list_endpoint_types", {}, "GET", "/v2/endpoints", {}, 200, [{"type": "random", "available_locations": "148", "url": "endpoints/random"}]),
    ("get_endpoints_by_type", {"session_type": "sticky"}, "GET", "/v2/endpoints/sticky", {}, 200, [{"location": "Random", "hostname": "gate.decodo.com", "port_range": "7000"}]),
    ("get_subscriptions", {}, "GET", "/v2/subscriptions", {}, 200, {"traffic_limit": "50", "users_limit": 3, "service_type": "residential_proxies"}),
    ("get_targets", {"start_date": "2024-09-01 00:00:00", "end_date": "2024-10-01 00:00:00", "search": "example", "proxy_users": ["1"]}, "POST", "/api/v2/statistics/targets", {"proxyType": "residential_proxies", "startDate": "2024-09-01 00:00:00", "endDate": "2024-10-01 00:00:00", "search": "example", "proxyUsers": ["1"]}, 200, {}),
    ("get_traffic", {"proxy_type": "mobile_proxies", "start_date": "2024-09-01 00:00:00", "end_date": "2024-10-01 00:00:00", "page": 2, "limit": 10, "locations": ["US"], "protocols": ["https"], "group_by": "country", "sort_order": "desc", "targets": ["example.com"]}, "POST", "/api/v2/statistics/traffic", {"proxyType": "mobile_proxies", "startDate": "2024-09-01 00:00:00", "endDate": "2024-10-01 00:00:00", "page": 2, "limit": 10, "locations": ["US"], "protocols": ["https"], "groupBy": "country", "sortOrder": "desc", "sortBy": "grouping_key", "targets": ["example.com"]}, 200, {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments,method,path,payload,status,body", CASES)
async def test_operations(transport, operation, arguments, method, path, payload, status, body):
    requests, replies = transport
    replies.append((status, body))
    result = await run(operation, arguments)
    assert result == {"status": "success", "operation": operation, "data": body}
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert (request.method, request.url.path) == (method, path)
    if method == "GET":
        assert dict(request.url.params) == {key: str(value) for key, value in payload.items()}
        assert not request.content
    elif method == "DELETE":
        assert not request.content
    else:
        assert json.loads(request.content) == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
async def test_http_errors_are_not_successes_or_retried(transport, status):
    transport[1].append((status, {"message": "Access refused"}))
    with pytest.raises(httpx.HTTPStatusError):
        await run("list_sub_users")
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_error_envelope_redacts_key(transport):
    transport[1].append((200, {"error_code": "bad_request", "message": AUTH["api_key"]}))
    with pytest.raises(ValueError, match=r"\[redacted\]"):
        await run("list_sub_users")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,arguments", [
    ("get_sub_user", {"sub_user_id": -1}),
    ("delete_whitelisted_ip", {"whitelist_id": "../foreign"}),
    ("get_endpoints_by_type", {"session_type": "../foreign"}),
    ("add_whitelisted_ips", {"ip_addresses": ["invalid"]}),
    ("update_sub_user", {"sub_user_id": 1}),
    ("get_traffic", {"start_date": "2024-10-01 00:00:00", "end_date": "2024-09-01 00:00:00"}),
])
async def test_invalid_arguments_make_no_request(transport, operation, arguments):
    with pytest.raises(ValueError):
        await run(operation, arguments)
    assert not transport[0]


@pytest.mark.parametrize("key", ["https://example.test/key", "Bearer abc", "", "abc\nInjected: value"])
def test_pasted_credential_validation(key):
    with pytest.raises((ValidationError, ValueError)):
        node.SmartproxyAPIKeyCredential(api_key=key)


def test_credential_can_be_filled_by_hand():
    credential = node.SmartproxyAPIKeyCredential(api_key=AUTH["api_key"])
    assert credential.credential_type == "smartproxy_api_key"


@pytest.mark.asyncio
async def test_connection_evidence_shows_subuser_names(transport):
    from nodes.core.connection_evidence import collect_evidence

    transport[1].append((200, [{"id": 24570, "username": "project_proxy"}]))
    result = await collect_evidence(node_type="automation-smartproxy", user_id=USER, credential_data=AUTH)
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ["project_proxy"]
    assert transport[0][0].method == "GET"
    assert transport[0][0].url.path == "/v2/sub-users"


@pytest.mark.asyncio
async def test_connection_evidence_keeps_provider_rejection(transport):
    from nodes.core.connection_evidence import collect_evidence

    transport[1].append((401, {"message": "API key is invalid"}))
    result = await collect_evidence(node_type="automation-smartproxy", user_id=USER, credential_data=AUTH)
    assert result.reachable is False
    assert result.error == "API key is invalid (HTTP 401)"

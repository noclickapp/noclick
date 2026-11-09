"""Native-factory tests against captured requests and synthetic contract fixtures."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import safetyculture_node as sc
from nodes.core.run_op import run_node_operation
from utils import ssrf

AUTH = {"credential_type": sc.CREDENTIAL_TYPE, "api_token": "synthetic-safetyculture-test-token"}
IDENTIFIER = "80e42a67-01d2-40f5-9e65-011bd09ee0f0"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.mitti.com"
        assert request.headers["Authorization"] == "Bearer " + AUTH["api_token"]
        assert AUTH["api_token"] not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(sc, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


async def run(operation, arguments=None):
    return await run_node_operation(node_type=sc.SafetyCultureNode.integration_type,
        operation=operation, arguments=arguments or {}, credential_data=deepcopy(AUTH),
        user_id="00000000-0000-4000-8000-000000000001")


CASES = json.loads((Path(__file__).parent / "fixtures/safetyculture/wire_cases.json").read_text())["cases"]


@pytest.mark.parametrize("operation,arguments,method,path,body,payload", CASES)
@pytest.mark.asyncio
async def test_safetyculture_wire_contract(transport, operation, arguments, method, path, body, payload):
    requests, replies = transport
    replies.append((200, payload))
    result = await run(operation, arguments)
    assert result["status"] == "success" and result["data"] == payload
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == path
    if body is not None:
        assert json.loads(request.content) == body
    else:
        assert request.content == b""
    if operation == "search_inspections":
        assert request.url.params.get_list("field") == ["audit_id", "modified_at", "template_id"]
    if operation == "search_templates":
        assert request.url.params.get_list("field") == ["template_id", "name", "modified_at", "created_at"]


@pytest.mark.asyncio
async def test_safetyculture_search_parameters(transport):
    requests, replies = transport
    replies.append((200, {"audits": []}))
    await run("search_inspections", {"template": [IDENTIFIER, "another-template"], "modified_after": "2026-11-01T00:00:00Z", "completed": "true", "owner": "me"})
    assert requests[0].url.params.get_list("template") == [IDENTIFIER, "another-template"]
    assert requests[0].url.params["modified_after"] == "2026-11-01T00:00:00Z"
    assert requests[0].url.params["completed"] == "true"


@pytest.mark.parametrize("code", [301, 401, 403, 429, 500])
@pytest.mark.asyncio
async def test_safetyculture_refusals_and_no_retry(transport, code):
    requests, replies = transport
    replies.append((code, {"message": "Provider rejected " + AUTH["api_token"]}))
    result = await run("create_action", {"title": "Check"})
    assert result["success"] is False and result["http_status"] == code
    assert result["write_outcome"] == "unverified" and len(requests) == 1
    assert AUTH["api_token"] not in json.dumps(result)


@pytest.mark.asyncio
async def test_safetyculture_rejects_error_envelope(transport):
    _, replies = transport
    replies.append((200, {"code": 7, "message": "Denied"}))
    with pytest.raises(ValueError, match="invalid or error"):
        await run("list_groups")


@pytest.mark.parametrize("value", ["https://app.mitti.com", "<token>", "Bearer token", "a\r\nb", "unicode–token", ""])
def test_safetyculture_manual_credential_validation(value):
    with pytest.raises(ValidationError):
        sc.SafetyCultureAPITokenCredential(api_token=value)


def test_safetyculture_default_credential_type():
    assert sc.SafetyCultureAPITokenCredential(api_token="  synthetic-token\n").model_dump() == {"credential_type": sc.CREDENTIAL_TYPE, "api_token": "synthetic-token"}


@pytest.mark.parametrize("value", ["../other", "a/b", "a?x=y", "%2f", ".."])
def test_safetyculture_resource_path_validation(value):
    with pytest.raises(ValidationError):
        sc.GetAction(action_id=value)


def test_safetyculture_dates_and_write_body_limits():
    with pytest.raises(ValidationError):
        sc.CreateAction(title="x" * 256)
    with pytest.raises(ValidationError):
        sc.UpdateActionDueDate(action_id=IDENTIFIER, due_at="2026-11-10T09:00:00")

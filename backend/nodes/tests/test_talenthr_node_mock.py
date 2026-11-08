"""Replay the pinned collection's saved responses through NoClick's native runner."""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import talenthr_node as db
from nodes.core.run_op import run_node_operation
from utils import ssrf

FIXTURES = Path(__file__).parent / "fixtures" / "talenthr"
EXAMPLES = json.loads((FIXTURES / "postman_examples.json").read_text())["operations"]
INPUTS = json.loads((FIXTURES / "inputs.json").read_text())
AUTH = {"credential_type": "talenthr_api_key", "api_key": "fixture-talenthr-key"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        code, body, content_type = responses.pop(0)
        return httpx.Response(code, content=body, headers={"Content-Type": content_type})
    native = ssrf.guarded_async_client
    monkeypatch.setattr(db, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(op, arguments=None):
    return await run_node_operation(node_type="automation-talenthr", operation=op,
        arguments=INPUTS[op] if arguments is None else arguments,
        credential_data=AUTH, user_id="00000000-0000-4000-8000-000000000001")


REPLAYS = [(op, response) for op, example in EXAMPLES.items() for response in example["responses"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("op,response", REPLAYS, ids=[f"{op}:{r['name']}" for op,r in REPLAYS])
async def test_saved_postman_responses(transport, op, response):
    requests, responses = transport
    responses.append((response["code"], response["body"].encode(), "application/json"))
    payload = json.loads(response["body"])
    if response["code"] >= 400:
        with pytest.raises(httpx.HTTPStatusError):
            await run(op)
    elif payload.get("success") is False or payload.get("error"):
        with pytest.raises(ValueError):
            await run(op)
    else:
        result = await run(op)
        assert result == {"status": "success", "operation": op, "data": payload}
    assert len(requests) == 1
    request = requests[0]
    expected = EXAMPLES[op]
    assert request.method == expected["method"]
    assert request.url.host == "pubapi.talenthr.io"
    assert request.url.path == "/v1" + expected["path"].format(**INPUTS[op])
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"fixture-talenthr-key:").decode()
    assert request.headers["Accept"] == "application/json"
    assert AUTH["api_key"] not in str(request.url)
    if request.method == "GET":
        assert not request.content
    elif request.content:
        body = json.loads(request.content)
        assert "operation" not in body
        assert not any(name in body for name in ("employee_id", "department_id", "location_id", "request_id"))
        if op == "hire_employee":
            assert body["reports_to_employee_id"] is None
            assert body["employment_status"] == {"employment_status_id":1}
            assert "prevent_email" not in body and "is_existing" not in body



@pytest.mark.parametrize("op,args", [
    ("list_employees", {"limit":101}),
    ("get_employee", {"employee_id":"../departments"}),
    ("get_employee", {"employee_id":0}),
    ("reply_time_off_request", {"employee_id":1,"request_id":2,"accept":"false"}),
    ("hire_employee", {k:v for k,v in INPUTS["hire_employee"].items() if k != "reports_to_employee_id"}),
])
def test_reject_invalid_configs(op,args):
    with pytest.raises(ValidationError):
        db.TalenthrFullConfig.model_validate({"config":{"operation":op,**args},"credentials":AUTH})


@pytest.mark.parametrize("key", ["https://example.com/key","Basic key:password","key\nvalue","<token>"])
def test_reject_credential_headers_urls_placeholders(key):
    with pytest.raises(ValidationError):
        db.TalenthrApiKeyCredential(api_key=key)


@pytest.mark.asyncio
async def test_no_redirect_follow_or_retry(transport):
    requests,responses=transport
    responses.append((302,b"", "text/html"))
    with pytest.raises(httpx.HTTPStatusError):
        await run("list_departments")
    assert len(requests)==1


@pytest.mark.asyncio
async def test_non_json_is_not_connection_evidence(transport):
    _,responses=transport
    responses.append((200,b"<html>sign in</html>","text/html"))
    with pytest.raises(ValueError,match="web page"):
        await run("list_departments")


@pytest.mark.asyncio
async def test_connection_evidence_uses_tenant_departments(transport):
    from nodes.core.connection_evidence import collect_evidence
    _,responses=transport
    saved=EXAMPLES["list_departments"]["responses"][0]
    responses.append((200,saved["body"].encode(),"application/json"))
    evidence=await collect_evidence(node_type="automation-talenthr", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert evidence.reachable is True
    assert evidence.samples

"""Wire checks against the published Higgsfield v2 contract."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import higgsfield_node as h
from nodes.core.run_op import run_node_operation

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/higgsfield/request-lifecycle.json").read_text())

RID = "d7e6c0f3-6699-4f6c-bb45-2ad7fd9158ff"
AUTH = {"credential_type": "higgsfield_api_key", "api_key_id": "fixture-key-id", "api_key_secret": "fixture-secret", "verification_request_id": RID}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, responses = [], []
    native = httpx.AsyncClient
    def send(request):
        requests.append(request)
        assert request.url.host == "api.higgsfield.ai"
        assert request.headers["Authorization"] == "Key fixture-key-id:fixture-secret"
        assert "fixture" not in str(request.url)
        code, data = responses.pop(0)
        return httpx.Response(code, json=data) if data is not None else httpx.Response(code)
    monkeypatch.setattr(h.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, responses


async def run(operation, **arguments):
    return await run_node_operation(node_type="automation-higgsfield", operation=operation,
        arguments=arguments, credential_data=AUTH.copy(), user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("operation,path", list(h.GENERATION_PATHS.items()))
async def test_generation_wire(wire, operation, path):
    requests, responses = wire
    responses.append((200, EXAMPLES["POST " + path]["body"]))
    args = {"prompt": "Editorial portrait in soft daylight"}
    if "image_video" in operation:
        args["image_url"] = "https://example.com/input.jpg"
    result = await run(operation, **args)
    assert result["status"] == "success" and result["data"]["status"] == "queued"
    assert len(requests) == 1 and requests[0].method == "POST" and requests[0].url.path == path
    body = json.loads(requests[0].content)
    assert body["prompt"] == args["prompt"] and "operation" not in body
    if "kling" in operation:
        assert body["duration"] == 5 and body["cfg_scale"] == 0.5 and body["negative_prompt"] == ""
    if "hailuo" in operation:
        assert body["duration"] == 6 and body["prompt_optimizer"] is True


@pytest.mark.parametrize("operation,method,suffix,code,data", [
    ("get_request_status", "GET", "/status", 200, {"status": "in_progress", "request_id": RID}),
    ("get_request_outputs", "GET", "/status", 200, {"status": "completed", "request_id": RID, "images": [{"url": "https://cdn.example.com/image-1.jpg"}]}),
    ("cancel_request", "POST", "/cancel", 202, None),
    ("delete_request", "DELETE", "", 200, {"status": "deleted", "request_id": RID}),
])
async def test_request_lifecycle(wire, operation, method, suffix, code, data):
    requests, responses = wire
    responses.append((code, data))
    result = await run(operation, request_id=RID)
    assert result["status"] == "success"
    assert len(requests) == 1 and requests[0].method == method
    assert requests[0].url.path == f"/requests/{RID}{suffix}" and not requests[0].content
    if operation == "get_request_outputs":
        assert result["outputs_ready"] is True and result["outputs"] == {"images": data["images"]}
    if operation == "cancel_request":
        assert result["cancellation_accepted"] is True and "data" not in result


async def test_pending_outputs(wire):
    wire[1].append((200, {"status": "queued", "request_id": RID}))
    result = await run("get_request_outputs", request_id=RID)
    assert result["outputs_ready"] is False and result["outputs"] == {}


@pytest.mark.parametrize("code", [401, 404, 409, 429, 503])
async def test_provider_errors_no_retries(wire, code):
    wire[1].append((code, {"detail": "Invalid credentials"}))
    result = await run("get_request_status", request_id=RID)
    assert result["status"] == "error" and result["error"] == "Invalid credentials" and result["http_status"] == code
    assert len(wire[0]) == 1


async def test_evidence_reads_owned_request(wire):
    wire[1].append((200, {"status": "completed", "request_id": RID}))
    result = await h.HiggsfieldNode.load_field_options("request_id", credential_data=AUTH)
    assert result["options"] == [{"value": RID, "label": f"{RID} (completed)"}]
    assert wire[0][0].method == "GET"


async def test_missing_probe_stays_unverified(wire):
    with pytest.raises(ValueError, match="existing verification"):
        await h.HiggsfieldNode.load_field_options("request_id", credential_data={k:v for k,v in AUTH.items() if k != "verification_request_id"})
    assert wire[0] == []


async def test_connection_seam_without_request_is_unverified(wire):
    from nodes.core.connection_evidence import collect_evidence
    result = await collect_evidence(node_type="automation-higgsfield",
        credential_data={k:v for k,v in AUTH.items() if k != "verification_request_id"},
        user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is None and wire[0] == []


async def test_connection_seam_shows_account_owned_request(wire):
    from nodes.core.connection_evidence import collect_evidence
    wire[1].append((200, {"status": "completed", "request_id": RID}))
    result = await collect_evidence(node_type="automation-higgsfield", credential_data=AUTH,
        user_id="00000000-0000-4000-8000-000000000001")
    assert result.reachable is True and result.samples[0].value == RID


async def test_redirect_not_followed(wire):
    wire[1].append((302, {"detail": "Redirect refused"}))
    result = await run("get_request_status", request_id=RID)
    assert result["status"] == "error" and len(wire[0]) == 1


@pytest.mark.parametrize("body", [{}, {"status": "completed", "request_id": "bad"}, {"status": "queued", "request_id": "00000000-0000-4000-8000-000000000001"}])
async def test_malformed_or_cross_request_responses(wire, body):
    wire[1].append((200, body))
    with pytest.raises(ValueError, match="invalid request response"):
        await run("get_request_status", request_id=RID)


@pytest.mark.parametrize("arguments", [
    {"operation": "generate_soul_image", "prompt": "test", "num_images": 5},
    {"operation": "generate_kling_pro_text_video", "prompt": "test", "duration": 6},
    {"operation": "generate_kling_pro_text_video", "prompt": "test", "cfg_scale": 1.01},
    {"operation": "get_request_status", "request_id": "../bad"},
])
def test_input_bounds(arguments):
    assert h.HiggsfieldNode.validate_config({"config": arguments, "credentials": AUTH})["valid"] is False


def test_manual_credential():
    credential = h.HiggsfieldAPIKeyCredential(api_key_id="fixture-key-id", api_key_secret="fixture-secret")
    assert credential.credential_type == "higgsfield_api_key"
    with pytest.raises(ValueError):
        h.HiggsfieldAPIKeyCredential(api_key_id="Key id:secret", api_key_secret="fixture-secret")

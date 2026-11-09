"""Requests through the factory, pagination, mutation responses and key rejection."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import studio_by_ai21_labs_node as module
from nodes.core.credential_connect import shape_credential
from nodes.core.registry import NodeFactory

KEY = "fixture-ai21-workspace-key"
AUTH = {"credential_type": "studio_by_ai21_labs_api_key", "api_key": KEY}
ID = "da13301a-14e4-4487-aa2f-cc6048e73cdc"
FIXTURES = Path(__file__).parent / "fixtures/studio-by-ai21-labs"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []

    async def send(request):
        requests.append(request)
        code, body = replies.pop(0)
        if isinstance(body, bytes):
            return httpx.Response(code, content=body)
        return httpx.Response(code, json=body)

    native = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies


def node(operation, **config):
    return NodeFactory.create_node(node_id="ai21-test", node_type=module.StudioByAI21LabsNode.integration_type,
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})


CASES = [
    ("list_files", {}, "GET", "/library/files", []),
    ("get_file", {"file_id": ID}, "GET", "/library/files/" + ID, {"fileId": ID, "name": "report.txt"}),
    ("update_file", {"file_id": ID, "labels": '[]'}, "PUT", "/library/files/" + ID, b""),
    ("delete_file", {"file_id": ID}, "DELETE", "/library/files/" + ID, b""),
    ("get_file_download_link", {"file_id": ID}, "GET", "/library/files/" + ID + "/download", json.loads((FIXTURES / "download.json").read_text())),
    ("upload_file", {"filename": "report.txt", "file_content": "Quarterly report", "labels": '["finance","report"]'}, "POST", "/library/files", json.loads((FIXTURES / "upload.json").read_text())),
    ("get_batch_status", {"batch_id": ID}, "GET", "/library/batches/" + ID + "/status", {"batch_id": ID, "total_documents": 0, "statuses": []}),
    ("create_chat_completion", {"messages": '[{"role":"user","content":"Hello how are you?"}]'}, "POST", "/chat/completions", {"choices": [{"message": {"role": "assistant", "content": "Hello"}}]}),
    ("create_maestro_run", {"input": "Summarize this report", "requirements": '[{"name":"clarity","description":"Be concise"}]'}, "POST", "/maestro/runs", {"id": ID, "status": "in_progress"}),
    ("get_maestro_run", {"execution_id": ID}, "GET", "/maestro/runs/" + ID, {"id": ID, "status": "completed", "result": {"answer": "Done"}, "error": None}),
]


@pytest.mark.parametrize("operation,config,method,path,payload", CASES)
async def test_operation_request_and_response(transport, operation, config, method, path, payload):
    requests, replies = transport
    replies.append((200, payload))
    result = await node(operation, **config).execute({})
    assert result["status"] == "success"
    assert result["data"] == (None if payload == b"" else payload)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == "api.ai21.com"
    assert request.url.path == "/studio/v1" + path
    assert request.headers["authorization"] == "Bearer " + KEY
    assert KEY not in str(request.url)
    if operation == "upload_file":
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        assert b'filename="report.txt"' in request.content
        assert b"Content-Type: text/plain" in request.content
        assert b"Quarterly report" in request.content
        assert request.content.count(b'name="labels"') == 2
    elif operation == "create_chat_completion":
        body = json.loads(request.content)
        assert body == {"model": "jamba-large", "messages": [{"role": "user", "content": "Hello how are you?"}], "max_tokens": 1024, "n": 1, "stream": False}
    elif operation == "create_maestro_run":
        body = json.loads(request.content)
        assert body["requirements"] == [{"name": "clarity", "description": "Be concise", "is_mandatory": False}]
        assert body["input"] == config["input"] and body["stream"] is False
    elif operation == "update_file":
        assert json.loads(request.content) == {"labels": []}
    elif method in {"GET", "DELETE"}:
        assert not request.content


async def test_list_filters_repeated_labels_and_page_offset(transport):
    requests, replies = transport
    replies.extend([(200, [{"fileId": ID, "name": "report.txt"}]), (200, [])])
    config = {"label": '["finance","report"]', "name": "report.txt", "path": "quarterly/", "status": "PROCESSED", "limit": 1}
    first = await node("list_files", **config).execute({})
    assert first["next_offset"] == 1
    second = await node("list_files", **config, offset=first["next_offset"]).execute({})
    assert second["next_offset"] is None
    assert requests[0].url.params.get_list("label") == ["finance", "report"]
    assert requests[1].url.params["offset"] == "1"
    assert requests[0].url.params["status"] == "PROCESSED"


@pytest.mark.parametrize("code", [301, 401, 403, 422, 429, 500])
async def test_no_retry_or_redirect_and_provider_error_is_redacted(transport, code):
    requests, replies = transport
    replies.append((code, {"detail": "Invalid API key: " + KEY}))
    with pytest.raises(ValueError, match=f"AI21 HTTP {code}") as exc:
        await node("list_files").execute({})
    assert KEY not in str(exc.value)
    assert len(requests) == 1


async def test_maestro_failed_run_is_preserved_for_branching(transport):
    _, replies = transport
    payload = {"id": ID, "status": "failed", "error": {"message": "Budget exhausted"}}
    replies.append((200, payload))
    assert (await node("get_maestro_run", execution_id=ID).execute({}))["data"] == payload


async def test_error_envelope_cannot_prove_connection(transport):
    _, replies = transport
    replies.append((200, {"detail": "Invalid API key"}))
    with pytest.raises(ValueError, match="Invalid API key"):
        await node("list_files").execute({})


@pytest.mark.parametrize("operation,config", [
    ("get_file", {"file_id": "../secret"}),
    ("upload_file", {"filename": "../report.txt", "file_content": "report"}),
    ("upload_file", {"filename": "image.png", "file_content": "report"}),
    ("create_chat_completion", {"messages": '[]'}),
    ("create_chat_completion", {"messages": '[{"role":"user","content":"Hello"}]', "temperature": 0, "n": 2}),
    ("create_maestro_run", {"input": "Hello", "models": '["a","b"]'}),
])
def test_invalid_inputs_fail_before_request(operation, config):
    with pytest.raises((ValueError, ValidationError)):
        node(operation, **config)


def test_manual_key_has_default_type_and_only_one_required_input():
    cls = module.StudioByAI21LabsAPIKey
    assert {name for name, field in cls.model_fields.items() if field.is_required()} == {"api_key"}
    assert cls(api_key=KEY).credential_type == AUTH["credential_type"]
    assert shape_credential(AUTH["credential_type"], {"api_key": "  " + KEY + "  "})[0]["api_key"] == KEY
    assert module.StudioByAI21LabsNode.connection_evidence.operation == "list_files"

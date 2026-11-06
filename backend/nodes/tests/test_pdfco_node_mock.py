"""Every PDF.co operation against unchanged provider-authored responses.

Each fixture includes its official https://developer.pdf.co/api/... source.
The annotationsString input also comes from the official Postman collection:
https://pdfco-docs-mintlify.s3.ap-southeast-2.amazonaws.com/PDF.co+API+v.1.00.postman_collection.json
No account, remote files, or network is needed.
"""
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from nodes.pdfco_node import ENDPOINTS, PDFCoNode, PDFCoNodeConfig

FIXTURES = json.loads((Path(__file__).parent / "fixtures/pdfco/documented_responses.json").read_text())
KEY = "pdfco-test-secret-never-log"


def node(config, *, credentials=True):
    parsed = PDFCoNodeConfig.model_validate({"config": config, "credentials": {"api_key": KEY} if credentials else None})
    return PDFCoNode(node_id="test-pdfco", node_type="automation-pdfco", node_data={}, config=parsed, sio=Mock())


def mock_api(monkeypatch, handler):
    original = httpx.AsyncClient

    def client(*args, **kwargs):
        assert kwargs.get("follow_redirects") is False
        kwargs.update(transport=httpx.MockTransport(handler), trust_env=False)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", list(FIXTURES))
async def test_documented_operation(monkeypatch, operation):
    """One test case per operation, with the provider's exact JSON response."""
    fixture = FIXTURES[operation]
    requests = []

    def transport(request):
        requests.append(request)
        expected = fixture["request"]
        assert request.method == expected["method"]
        assert str(request.url) == "https://api.pdf.co" + expected["path"]
        assert request.headers["x-api-key"] == KEY
        assert "authorization" not in request.headers
        assert KEY not in str(request.url) and KEY.encode() not in request.content
        if expected["body"] is None:
            assert not request.content
        else:
            assert request.headers["content-type"] == "application/json"
            assert json.loads(request.content) == expected["body"]
        return httpx.Response(200, json=fixture["response"])

    mock_api(monkeypatch, transport)
    result = await node(fixture["config"]).execute({})
    assert len(requests) == 1
    assert result["status"] == "success"
    assert result["action"] == operation
    assert result["data"] == fixture["response"]
    assert result["timing_ms"]["api_request"] >= 0


def test_fixture_and_operation_coverage():
    assert set(FIXTURES) == set(ENDPOINTS)
    assert len(FIXTURES) == 20
    assert all(f["source"].startswith("https://developer.pdf.co/api/") for f in FIXTURES.values())


@pytest.mark.asyncio
async def test_async_submission_does_not_poll_or_download(monkeypatch):
    """Async response from https://developer.pdf.co/api/ai-invoice-parser.md."""
    documented = FIXTURES["parse_invoice"]["response"]
    seen = []

    def transport(request):
        seen.append(request)
        assert request.url.path == "/v1/ai-invoice-parser"
        return httpx.Response(200, json=documented)

    mock_api(monkeypatch, transport)
    result = await node(FIXTURES["parse_invoice"]["config"]).execute({})
    assert result["data"]["jobId"] == documented["jobId"]
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_async_alias_and_request_fields(monkeypatch):
    seen = []

    def transport(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=FIXTURES["parse_invoice"]["response"])

    mock_api(monkeypatch, transport)
    result = await node({"operation": "pdf_to_text", "url": FIXTURES["pdf_to_text"]["config"]["url"], "async": True, "inline": False, "pages": "0-", "expiration": 60}).execute({})
    assert result["status"] == "success"
    assert seen == [{"url": FIXTURES["pdf_to_text"]["config"]["url"], "async": True, "inline": False, "pages": "0-", "expiration": 60, "lang": "eng"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"status": "working", "remainingCredits": 60227},
    FIXTURES["get_job_status"]["response"],
])
async def test_job_states_are_returned_without_polling(monkeypatch, body):
    # https://developer.pdf.co/api/job-check.md
    mock_api(monkeypatch, lambda request: httpx.Response(200, json=body))
    result = await node(FIXTURES["get_job_status"]["config"]).execute({})
    assert result["status"] == "success"
    assert result["data"] == body


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status,body", [
    (200, {"error": True, "status": 402, "message": "Not enough credits."}),
    (401, {"error": True, "status": 401, "message": "Unauthorized. Authentication is required and has failed or has not yet been provided."}),
    (429, {"error": True, "message": "Too many requests. Your current limit is <limit> requests per minute. Please try again later"}),
    (200, {"errorCode": 404, "error": True, "message": "Job not found", "remainingCredits": 60227, "credits": 0}),
    (200, {"status": "failed", "message": "Processing failed"}),
    (200, {"status": "aborted", "message": "Processing aborted"}),
])
async def test_provider_errors_and_failed_jobs(monkeypatch, http_status, body):
    # Documented error envelopes: pdf-to-text/basic.md and job-check.md.
    # Failed/aborted status values: job-check.md; message text is a regression sentinel.
    mock_api(monkeypatch, lambda request: httpx.Response(http_status, json=body))
    result = await node(FIXTURES["get_job_status"]["config"]).execute({})
    assert result["status"] == "error"
    assert result["error"] == body["message"]
    assert result["status_code"] >= 400


@pytest.mark.asyncio
async def test_secret_echo_is_redacted(monkeypatch):
    mock_api(monkeypatch, lambda request: httpx.Response(401, json={"error": True, "message": f"Invalid key {KEY}"}))
    result = await node({"operation": "get_account_balance"}).execute({})
    assert KEY not in json.dumps(result)
    assert "[redacted]" in result["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>unavailable</html>"), httpx.Response(200, json=[]), httpx.Response(200, json={}), httpx.Response(302, json={"message": "Redirected"}, headers={"location": "https://other.example.test"})])
async def test_invalid_response_or_redirect(monkeypatch, response):
    mock_api(monkeypatch, lambda request: response)
    assert (await node({"operation": "get_account_balance"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code", [(httpx.ReadTimeout("secret transport detail"), 408), (httpx.ConnectError("secret transport detail"), 502)])
async def test_transport_errors(monkeypatch, error, code):
    def transport(request):
        raise error

    mock_api(monkeypatch, transport)
    result = await node({"operation": "get_account_balance"}).execute({})
    assert result["status"] == "error" and result["status_code"] == code
    assert "secret transport detail" not in str(result)


@pytest.mark.asyncio
async def test_missing_credential():
    with pytest.raises(ValueError, match="Connect a PDF.co API key"):
        await node({"operation": "get_account_balance"}, credentials=False).execute({})


@pytest.mark.asyncio
async def test_connect_reads_account_credit_balance(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence

    # https://developer.pdf.co/api/account-balance-info.md
    requests = []

    def transport(request):
        requests.append(request)
        assert request.method == "GET" and request.url.path == "/v1/account/credit/balance"
        return httpx.Response(200, json=FIXTURES["get_account_balance"]["response"])

    mock_api(monkeypatch, transport)
    evidence = await collect_evidence(node_type="automation-pdfco", user_id="test-user", credential_data={"credential_type": "pdfco_api_key", "api_key": KEY})
    assert evidence.reachable is True
    assert evidence.account_label == "99795868"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_connect_rejects_invalid_key(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence

    mock_api(monkeypatch, lambda request: httpx.Response(401, json={"error": True, "status": 401, "message": "Unauthorized. Authentication is required and has failed or has not yet been provided."}))
    evidence = await collect_evidence(node_type="automation-pdfco", user_id="test-user", credential_data={"credential_type": "pdfco_api_key", "api_key": KEY})
    assert evidence.reachable is False


@pytest.mark.asyncio
@pytest.mark.parametrize("body,reachable,label", [
    ({"remainingCredits": 0}, True, "0"),
    ({"remainingCredits": 99795868}, True, "99795868"),
    ({"remainingCredits": True}, None, None),
    ({"remainingCredits": "unknown"}, None, None),
    ({"status": "success"}, None, None),
])
async def test_connect_requires_a_real_balance(monkeypatch, body, reachable, label):
    from nodes.core.connection_evidence import collect_evidence

    mock_api(monkeypatch, lambda request: httpx.Response(200, json=body))
    evidence = await collect_evidence(node_type="automation-pdfco", user_id="test-user", credential_data={"credential_type": "pdfco_api_key", "api_key": KEY})
    assert evidence.reachable is reachable
    assert evidence.account_label == label

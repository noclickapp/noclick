"""Offline regressions against Artificial Analysis's published V2 routes/examples."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import artificial_analysis_node as native
from nodes.core.registry import NodeFactory
from nodes.core.base import ConfigValidationError

FIXTURES = Path(__file__).parent / "fixtures/artificial-analysis"
OPERATIONS = json.loads((FIXTURES / "operations.json").read_text())
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
KEY = "synthetic-artificial-analysis-key"

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id="aa-fixture", node_type="automation-artificial-analysis", node_data={"config": config, "credentials": {"credential_type": "artificial_analysis_api_key", "api_key": KEY}})

def transport(monkeypatch, body, status=200):
    requests = []
    client_class = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return client_class(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda o: o["operation"])
async def test_published_routes_and_response_examples(monkeypatch, operation):
    config = {"operation": operation["operation"]}
    if "slug" in operation["params"]:
        config["slug"] = "claude-sonnet-4" if "/models/" in operation["path"] else "anthropic"
    if operation["method"] == "POST":
        config.update(submissions=[{"problem_id": "prob_001", "generated_code": "def solve():\n    return 42", "model": "claude-sonnet-4-20250514", "generation_config": {"temperature": 0}}], batch_metadata={"run_id": "my-eval-run-001"})
    body = RESPONSES.get(operation["operation"], {} if operation["method"] == "POST" else {"data": []})
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["attribution"] == "Artificial Analysis"
    for k, v in body.items():
        assert result[k] == v
    assert len(requests) == 1
    request = requests[0]
    assert request.method == operation["method"]
    assert request.url.path == operation["path"].replace("{slug}", config.get("slug", ""))
    assert request.url.host == "artificialanalysis.ai" and request.headers["x-api-key"] == KEY
    assert "authorization" not in request.headers
    if request.method == "POST":
        assert json.loads(request.content) == {k: v for k, v in config.items() if k != "operation"}
    assert KEY not in json.dumps(result)

@pytest.mark.asyncio
async def test_filters_dates_and_pagination_preserved_without_extra_calls(monkeypatch):
    body = {"data": [], "pagination": {"page": 3, "page_size": 200, "total_pages": 4, "has_more": True}}
    requests = transport(monkeypatch, body)
    result = await node({"operation": "get_language_models", "page": 3, "prompt_type": "100k"}).execute({})
    assert dict(requests[0].url.params) == {"page": "3", "prompt_type": "100k"}
    assert result["pagination"] == body["pagination"] and len(requests) == 1
    requests = transport(monkeypatch, {"data": []})
    await node({"operation": "get_language_provider_measurements", "slug": "anthropic", "start_date": "2025-01-01", "prompt_type": "medium_parallel"}).execute({})
    assert dict(requests[0].url.params) == {"start_date": "2025-01-01", "prompt_type": "medium_parallel"}

@pytest.mark.asyncio
async def test_boolean_and_history_queries(monkeypatch):
    requests = transport(monkeypatch, {"data": []})
    await node({"operation": "get_text_to_image_arena", "include_categories": True}).execute({})
    assert dict(requests[0].url.params) == {"include_categories": "true"}
    requests = transport(monkeypatch, {"data": []})
    await node({"operation": "get_language_model_performance_over_time", "slug": "claude-sonnet-4", "window": "30d", "interval": "daily"}).execute({})
    assert dict(requests[0].url.params) == {"window": "30d", "interval": "daily", "prompt_type": "long"}

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500, 503, 504])
async def test_provider_failures_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, {"error": "Rejected " + KEY}, status)
    result = await node({"operation": "get_language_models_free"}).execute({})
    assert result == {"status": "error", "error": "Rejected [redacted]", "http_status": status}
    assert len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, [], {"error": "invalid"}, {"data": None}, {"data": True}])
async def test_malformed_success_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "get_language_models_free"}).execute({})

@pytest.mark.parametrize("config", [
    {"operation": "get_language_models", "page": 0},
    {"operation": "get_language_models", "page": 10001},
    {"operation": "get_language_models", "prompt_type": "invalid"},
    {"operation": "get_language_model_by_slug", "slug": "../providers"},
    {"operation": "get_language_model_by_slug"},
    {"operation": "evaluate_crit_pt", "submissions": [{}], "batch_metadata": {}},
    {"operation": "evaluate_crit_pt", "submissions": []},
])
def test_invalid_inputs_rejected(config):
    with pytest.raises(ConfigValidationError):
        native.ArtificialAnalysisNode.parse_config({"config": config})

def test_manual_credential_default_and_reachability():
    assert native.ArtificialAnalysisAPIKeyCredential(api_key=KEY).credential_type == "artificial_analysis_api_key"
    assert native.ArtificialAnalysisNode.connection_evidence.proves == "reachability"
    for key in ["https://example.test/key", "bad\nkey"]:
        with pytest.raises(ValidationError):
            native.ArtificialAnalysisAPIKeyCredential(api_key=key)

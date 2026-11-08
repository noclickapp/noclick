"""Exercise CrewAI requests through the native factory, without live deployments."""
import json

import httpx
import pytest
from pydantic import ValidationError

from nodes import crew_ai_node as native
from nodes.core.registry import NodeFactory

ID = "550e8400-e29b-41d4-a716-446655440000"
TOKEN = "synthetic-crew-ai-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def credential(**changes):
    return {"credential_type": "crew_ai_bearer", "deployment_url": "https://my-travel-crew.crewai.com", "bearer_token": TOKEN, **changes}


def node(config, **changes):
    return NodeFactory.create_node(node_id="crew-test", node_type="automation-crew-ai", node_data={"config": config, "credentials": credential(**changes)})


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


@pytest.mark.parametrize("config,method,path,body", [
    ({"operation": "get_inputs"}, "GET", "/inputs", {"inputs": ["budget"], "required_inputs": ["budget"]}),
    ({"operation": "start_execution", "inputs": {"budget": "1000 USD"}, "meta": {"source": "web-app"}, "crewWebhookUrl": "https://api.example.com/webhooks/crew"}, "POST", "/kickoff", {"kickoff_id": ID}),
    ({"operation": "get_status", "kickoff_id": ID}, "GET", "/status/" + ID, {"status": "completed", "result": {"output": "Itinerary", "tasks": []}, "execution_time": 108.5}),
    ({"operation": "resume_execution", "execution_id": ID, "task_id": "research_task", "human_feedback": "Proceed", "is_approve": False, "crewWebhookUrl": "https://api.example.com/webhooks/crew"}, "POST", "/resume", {"status": "retrying", "message": "Task will be retried with your feedback"}),
])
async def test_crew_ai_contract_requests(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result == {"status": "success", "data": body}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "my-travel-crew.crewai.com"
    assert request.headers["Authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == ({k: v for k, v in config.items() if k != "operation"} if method == "POST" else None)


@pytest.mark.parametrize("state", ["running", "completed", "error"])
async def test_crew_ai_execution_state_distinct_from_http_success(monkeypatch, state):
    body = {"status": state, "error": "Task failed"} if state == "error" else {"status": state}
    transport(monkeypatch, body)
    assert (await node({"operation": "get_status", "kickoff_id": ID}).execute({}))["data"] == body


async def test_crew_ai_provider_rejection_preserves_words_and_redacts_token(monkeypatch):
    transport(monkeypatch, {"message": "Invalid bearer token " + TOKEN}, 401)
    assert await node({"operation": "get_inputs"}).execute({}) == {"status": "error", "status_code": 401, "message": "Invalid bearer token [redacted]"}


@pytest.mark.parametrize("url", ["http://my-travel-crew.crewai.com", "https://crewai.com.attacker.test", "https://evil.test", "https://user@my-travel-crew.crewai.com", "https://my-travel-crew.crewai.com/kickoff", "https://my-travel-crew.crewai.com:443", "https://127.0.0.1"])
def test_crew_ai_refuses_unsafe_deployment_urls(url):
    with pytest.raises((ValueError, ValidationError)):
        native.CrewAIBearerCredential(**credential(deployment_url=url))


async def test_crew_ai_no_automatic_retry_on_network_failure(monkeypatch):
    count = 0
    def respond(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("Timeout " + TOKEN)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(ValueError, match="check execution status") as error:
        await node({"operation": "start_execution", "inputs": {}}).execute({})
    assert count == 1 and TOKEN not in str(error.value)


async def test_crew_ai_resume_keeps_false_and_all_original_webhooks(monkeypatch):
    requests = transport(monkeypatch, {"status": "retrying", "message": "Task will be retried with your feedback"})
    config = {"operation": "resume_execution", "execution_id": ID, "task_id": "analysis_task", "human_feedback": "Please revise", "is_approve": False,
              **{field: "https://api.example.com/webhooks/" + field for field in ("taskWebhookUrl", "stepWebhookUrl", "crewWebhookUrl")}}
    await node(config).execute({})
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if k != "operation"}


async def test_crew_ai_connection_does_not_accept_an_unrelated_json_object(monkeypatch):
    transport(monkeypatch, {"html": "sign-in page"})
    with pytest.raises(ValueError, match="unexpected inputs response"):
        await node({"operation": "get_inputs"}).execute({})


async def test_crew_ai_connection_evidence_rejection_and_success(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {"inputs": ["budget"], "required_inputs": ["budget"]})
    good = await collect_evidence(node_type="automation-crew-ai", user_id="crew-test-user", credential_data=credential())
    assert good.reachable is True
    transport(monkeypatch, {"error": "Unauthorized", "message": "Invalid or missing bearer token"}, 401)
    rejected = await collect_evidence(node_type="automation-crew-ai", user_id="crew-test-user", credential_data=credential())
    assert rejected.reachable is False
    assert "Invalid or missing bearer token" in rejected.error

"""Markup AI factory and HTTP behavior; synthetic account, no live service."""
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError

from nodes import markup_ai_node as native
from nodes.core.registry import NodeFactory

KEY = "synthetic-markup-key-42"
ID = "00000000-0000-4000-8000-000000000001"
CREDENTIAL = {"credential_type": "markup_ai_api_key", "api_key": KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="markup-fixture", node_type="automation-markup-ai",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, body=None, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs) as session:
            yield session
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path", [
    ({"operation": "get_style_config"}, "GET", "/style-agent/config"),
    ({"operation": "list_style_guides"}, "GET", "/style-agent/style-guides"),
    ({"operation": "get_style_guide", "style_guide_id": "style-1"}, "GET", "/style-agent/style-guides/style-1"),
    ({"operation": "list_content_profiles"}, "GET", "/style-agent/content-profiles"),
    ({"operation": "run_style_check", "text": "A clear sentence."}, "POST", "/style-agent/run"),
    ({"operation": "get_style_workflow", "workflow_id": "workflow-1"}, "GET", "/style-agent/workflows/workflow-1"),
    ({"operation": "list_agents"}, "GET", "/agents"),
    ({"operation": "get_agent", "agent_id": "agent-1"}, "GET", "/agents/agent-1"),
    ({"operation": "run_agent", "agent_id": "agent-1", "text": "A clear sentence."}, "POST", "/agents/agent-1/run"),
    ({"operation": "get_persona", "persona_id": ID}, "GET", "/personas/" + ID),
    ({"operation": "get_workflow", "workflow_id": "workflow-1"}, "GET", "/agents/workflows/workflow-1"),
    ({"operation": "cancel_workflow", "workflow_id": "workflow-1"}, "DELETE", "/agents/workflows/workflow-1"),
    ({"operation": "search_terminology", "query": "cloud service"}, "GET", "/brand-terms/search"),
    ({"operation": "list_term_sets"}, "GET", "/brand-terms/term-sets"),
    ({"operation": "create_term_set", "context": "Cloud product"}, "POST", "/brand-terms/term-sets"),
    ({"operation": "get_term_set", "term_set_id": ID}, "GET", "/brand-terms/term-sets/" + ID),
    ({"operation": "update_term_set", "term_set_id": ID, "context": "Updated"}, "PATCH", "/brand-terms/term-sets/" + ID),
    ({"operation": "delete_term_set", "term_set_id": ID}, "DELETE", "/brand-terms/term-sets/" + ID),
    ({"operation": "create_term", "term_set_id": ID, "term": "Markup", "type": "preferred"}, "POST", "/brand-terms/term-sets/" + ID + "/terms"),
    ({"operation": "get_term", "term_set_id": ID, "term_id": ID}, "GET", "/brand-terms/term-sets/" + ID + "/terms/" + ID),
    ({"operation": "update_term", "term_set_id": ID, "term_id": ID, "term": "Markup AI", "type": "preferred"}, "PUT", "/brand-terms/term-sets/" + ID + "/terms/" + ID),
    ({"operation": "delete_term", "term_set_id": ID, "term_id": ID}, "DELETE", "/brand-terms/term-sets/" + ID + "/terms/" + ID),
    ({"operation": "list_domains"}, "GET", "/brand-terms/domains"),
    ({"operation": "list_personas"}, "GET", "/personas"),
    ({"operation": "list_voice_profiles"}, "GET", "/brand-voice-profiles"),
])
async def test_markup_ai_factory_routes(monkeypatch, config, method, path):
    payload = {"domains": [], "pagination": {"next_cursor": "next-page"}}
    requests = transport(monkeypatch, payload)
    output = await node(config).execute({})
    assert output["status"] == "success" and output["data"] == payload
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.markup.ai"
    assert request.headers["Authorization"] == "Bearer " + KEY
    assert KEY not in str(output)
    if method in {"GET", "DELETE"}:
        assert not request.content
    if config["operation"] in {"run_style_check", "run_agent"}:
        assert request.url.params["wait"] == "false"
        assert json.loads(request.content)["text"] == config["text"]


@pytest.mark.asyncio
async def test_markup_ai_pagination_and_repeated_filters(monkeypatch):
    payload = {"term_sets": [], "page": 2, "total_pages": 3, "total_count": 45, "page_size": 20}
    requests = transport(monkeypatch, payload)
    output = await node({"operation": "list_term_sets", "page": 2, "domain_ids": [ID, ID], "has_context": False}).execute({})
    assert requests[0].url.params.get_list("domain_ids") == [ID, ID]
    assert requests[0].url.params["has_context"] == "false"
    assert output["data"] == payload and len(requests) == 1


@pytest.mark.asyncio
async def test_markup_ai_json_editors_and_patch_null(monkeypatch):
    requests = transport(monkeypatch, {"id": ID})
    await node({"operation": "create_term_set", "context": "Cloud", "terms": '[{"term":"cloud","type":"preferred"}]', "domain_ids": [ID]}).execute({})
    assert json.loads(requests[0].content) == {"context": "Cloud", "terms": [{"term": "cloud", "type": "preferred", "case_sensitive": False}], "domain_ids": [ID]}
    requests = transport(monkeypatch, {"id": ID})
    await node({"operation": "update_term_set", "term_set_id": ID, "clear_context": True}).execute({})
    assert json.loads(requests[0].content) == {"context": None}
    requests = transport(monkeypatch, {"id": ID})
    await node({"operation": "update_term_set", "term_set_id": ID}).execute({})
    assert json.loads(requests[0].content) == {}
    with pytest.raises(ValueError, match="never both"):
        await node({"operation": "update_term_set", "term_set_id": ID, "clear_context": True, "context": "Cloud"}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_markup_ai_rejections_do_not_retry_and_redact(monkeypatch, status):
    requests = transport(monkeypatch, {"detail": "Rejected " + KEY}, status)
    output = await node({"operation": "run_agent", "agent_id": "agent-1", "text": "Content"}).execute({})
    assert output == {"status": "error", "http_status": status, "message": "Rejected [redacted]"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_markup_ai_delete_204_and_evidence(monkeypatch):
    transport(monkeypatch, None, 204)
    assert (await node({"operation": "delete_term_set", "term_set_id": ID}).execute({}))["data"] is None
    transport(monkeypatch, {"domains": [{"id": ID, "name": "Brand"}], "page": 1, "page_size": 20, "total_count": 1, "total_pages": 1})
    output = await node({"operation": "list_domains"}).execute({})
    assert output["items"] == [{"id": ID, "name": "Brand"}]
    transport(monkeypatch, {"unexpected": []})
    assert (await node({"operation": "list_domains"}).execute({}))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["..", "a/b", "a?token=secret", "a#fragment"])
async def test_markup_ai_path_boundaries(monkeypatch, identifier):
    requests = transport(monkeypatch, {})
    with pytest.raises(ValueError, match="single Markup AI"):
        await node({"operation": "get_agent", "agent_id": identifier}).execute({})
    assert not requests


def test_markup_ai_manual_credentials_and_request_validation():
    assert native.MarkupAiAPIKeyCredential(api_key=KEY).credential_type == "markup_ai_api_key"
    assert native.MarkupAiAPIKeyCredential(api_key="\r\n" + KEY + "\n").api_key == KEY
    for key in ["Bearer " + KEY, "https://api.markup.ai", "bad\rinjected"]:
        with pytest.raises(ValidationError):
            native.MarkupAiAPIKeyCredential(api_key=key)
    with pytest.raises(ValidationError):
        native.MarkupAiRunStyleCheckConfig(text="Content", webhook_url="not-a-url")
    with pytest.raises(ValidationError):
        native.MarkupAiRunAgentConfig(agent_id="agent-1", text="Content", persona_id=ID, persona_ids=[ID])
    with pytest.raises(ValidationError):
        native.MarkupAiListAgentsConfig(page_size=101)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,status", [("run_style_check", 201), ("run_agent", 202)])
async def test_markup_ai_published_run_responses(monkeypatch, operation, status):
    from pathlib import Path
    body = json.loads((Path(__file__).parent / "fixtures" / "markup_ai" / (operation + ".json")).read_text())
    transport(monkeypatch, body, status)
    config = {"operation": operation, "text": "string"}
    if operation == "run_agent":
        config["agent_id"] = "agent_id"
    output = await node(config).execute({})
    assert output == {"status": "success", "http_status": status, "data": body}

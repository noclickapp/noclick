"""Contract tests for every supported Neon API v2 operation."""

import json
import re
from unittest.mock import patch

import httpx
import pytest

from nodes.neon_node import NEON_ENDPOINTS, NEON_TRIGGERS, NeonNode, NeonNodeConfig
from tests.utils.sweep import check_each


def make_node(config):
    return NeonNode(
        node_id="test", node_type="automation-neon", node_data={},
        config=NeonNodeConfig(config=config, credentials={"api_key": "napi_test"}),
        sio=None, sid=None, workflow_id=None, user_id=None,
    )


def config_for(action):
    _, path, _, _, body_requirement, required_query, _ = NEON_ENDPOINTS[action]
    data = {"operation": action}
    data.update({name: f"test-{name}" for name in re.findall(r"\{([^}]+)\}", path)})
    if required_query:
        data["query_json"] = json.dumps({key: "sample" for key in required_query})
    if action == "set_organization_spending_limit":
        data["spending_limit_cents"] = 10000
    elif body_requirement is True:
        data["body_json"] = '{"example":"value"}'
    return data


async def _every_documented_operation_routes_through_authenticated_api(action):
    method, path, _, _, body_requirement, required_query, _ = NEON_ENDPOINTS[action]
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"items": [{"id": "1"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch("nodes.neon_node.httpx.AsyncClient", return_value=client):
        result = await make_node(config_for(action)).execute({})

    assert result["status"] == "success"
    assert result["action"] == action
    assert result["timing_ms"]["api_request"] >= 0
    assert len(seen) == 1
    request = seen[0]
    assert request.method == method
    expected_path = re.sub(r"\{([^}]+)\}", lambda m: f"test-{m.group(1)}", path)
    assert request.url.path == "/api/v2" + expected_path
    assert request.headers["Authorization"] == "Bearer napi_test"
    assert set(request.url.params) == set(required_query)
    if action == "set_organization_spending_limit":
        assert json.loads(request.content) == {"spending_limit_cents": 10000}
    elif body_requirement is True:
        assert json.loads(request.content) == {"example": "value"}
    else:
        assert request.content == b""


@pytest.mark.asyncio
async def test_every_documented_operation_routes_through_authenticated_api():
    await check_each(sorted(NEON_ENDPOINTS), _every_documented_operation_routes_through_authenticated_api)


@pytest.mark.asyncio
async def test_optional_query_and_body_are_sent_as_json():
    config = {
        "operation": "create_project_branch",
        "project_id": "project-one",
        "body_json": '{"branch":{"name":"qa"}}',
    }
    captured = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: captured.append(request) or httpx.Response(201, json={"branch": {"id": "br-1"}})
    ))
    with patch("nodes.neon_node.httpx.AsyncClient", return_value=client):
        result = await make_node(config).execute({})
    assert result["status"] == "success"
    assert json.loads(captured[0].content) == {"branch": {"name": "qa"}}


@pytest.mark.asyncio
async def test_optional_query_is_sent():
    captured = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: captured.append(request) or httpx.Response(200, json={"projects": []})
    ))
    with patch("nodes.neon_node.httpx.AsyncClient", return_value=client):
        result = await make_node({"operation": "list_projects", "query_json": '{"search":"qa"}'}).execute({})
    assert result["status"] == "success"
    assert captured[0].url.params["search"] == "qa"


@pytest.mark.asyncio
async def test_error_response_cannot_echo_request_body_or_api_key():
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(400, json={"message": "napi_test sensitive-body"})
    ))
    with patch("nodes.neon_node.httpx.AsyncClient", return_value=client):
        result = await make_node({"operation": "create_project", "body_json": '{"project":{"name":"sensitive-body"}}'}).execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 400
    assert "napi_test" not in json.dumps(result)
    assert "sensitive-body" not in json.dumps(result)


@pytest.mark.asyncio
async def test_non_json_success_is_sanitized():
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="unexpected napi_test")
    ))
    with patch("nodes.neon_node.httpx.AsyncClient", return_value=client):
        result = await make_node({"operation": "list_projects"}).execute({})
    assert result["status"] == "error"
    assert result["error"] == "Neon returned a non-JSON response"
    assert "napi_test" not in json.dumps(result)


@pytest.mark.asyncio
async def test_project_and_branch_pickers_use_the_credential_and_project_context():
    def handle(request):
        assert request.headers["Authorization"] == "Bearer napi_test"
        if request.url.path == "/api/v2/projects":
            return httpx.Response(200, json={"projects": [{"id": "p-1", "name": "QA project"}]})
        assert request.url.path == "/api/v2/projects/p-1/branches"
        return httpx.Response(200, json={"branches": [{"id": "br-1", "name": "dev"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch("nodes.neon_node.httpx.AsyncClient", return_value=client):
        projects = await NeonNode.load_field_options("project_id", {"api_key": "napi_test"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch("nodes.neon_node.httpx.AsyncClient", return_value=client):
        branches = await NeonNode.load_field_options("branch_id", {"api_key": "napi_test"}, {"project_id": "p-1"})
    assert projects == {"options": [{"value": "p-1", "label": "QA project"}], "next_page_token": None}
    assert branches == {"options": [{"value": "br-1", "label": "dev"}], "next_page_token": None}


@pytest.mark.asyncio
async def test_project_picker_passes_search_and_pagination():
    def handle(request):
        assert request.url.params["limit"] == "100"
        assert request.url.params["cursor"] == "next-page"
        assert request.url.params["search"] == "qa"
        return httpx.Response(200, json={"projects": [{"id": "p-2", "name": "QA"}],
                                         "pagination": {"next": "final-page"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch("nodes.neon_node.httpx.AsyncClient", return_value=client):
        result = await NeonNode.load_field_options(
            "project_id", {"api_key": "napi_test"}, page_token="next-page", search="qa"
        )
    assert result == {"options": [{"value": "p-2", "label": "QA"}],
                      "next_page_token": "final-page"}


@pytest.mark.parametrize("value", ["not json", "[]", "null"])
def test_query_json_must_be_an_object(value):
    # Validation happens before any request is sent.
    with pytest.raises(ValueError, match="Query parameters"):
        import asyncio
        asyncio.run(make_node({"operation": "list_projects", "query_json": value}).execute({}))


def test_generated_schema_exposes_every_operation_to_flow_canvas():
    schema = NeonNode.get_config_schema()
    choices = schema["properties"]["config"]["oneOf"]
    assert len(choices) == len(NEON_ENDPOINTS) + len(NEON_TRIGGERS) == 179


@pytest.mark.parametrize("value", [0, -1, None, 1.5, "10000", True])
def test_spending_limit_requires_positive_integer_cents(value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_node({"operation": "set_organization_spending_limit",
                   "org_id": "org-bold-bonus-12345678", "spending_limit_cents": value})


# Official listProjectBranches response example, copied without editing payload fields.
def branch_example():
    from pathlib import Path
    return json.loads((Path(__file__).parent / 'fixtures/neon/list-branches.json').read_text())


def memory_state(node, state):
    async def update(mutator, **kwargs):
        new_state, result = mutator(dict(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    node._update_node_state = update


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', NEON_TRIGGERS)
async def test_branch_trigger_paginates_baselines_and_emits_new_items(operation):
    import copy
    from nodes.core.poll_trigger import poll_scope
    body = branch_example()
    node = make_node({'operation': operation, 'project_id': 'shiny-wind-028834'})
    state = {}
    memory_state(node, state)
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.path == '/api/v2/projects/shiny-wind-028834/branches'
        assert request.headers['Authorization'] == 'Bearer napi_test'
        assert request.url.params['sort_order'] == 'desc'
        assert request.url.params['sort_by'] == ('created_at' if operation == 'on_new_branch' else 'updated_at')
        if request.url.params.get('cursor'):
            assert request.url.params['cursor'] == body['pagination']['next']
            return httpx.Response(200, json={'branches': body['branches'][1:]})
        first = copy.deepcopy(body)
        first['branches'] = body['branches'][:1]
        return httpx.Response(200, json=first)

    async def poll():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch('nodes.neon_node.httpx.AsyncClient', return_value=client):
            return await node.execute({})

    # Baseline just the main branch, then let the other documented branches arrive.
    all_branches = body['branches']
    body['branches'] = all_branches[:1]
    first = await poll()
    assert first['branches'] == []
    assert node.trigger_produced_no_event(first)
    assert NeonNode.resolve_agent_event(first) is None
    body['branches'] = all_branches
    new = await poll()
    assert new['branches'] == all_branches[1:]
    assert new['branch_count'] == 2
    assert node.trigger_emitted_event(new)
    event = NeonNode.resolve_agent_event(new)
    assert 'dev2' in event['text'] and 'br-sweet-breeze-497520' in event['text']
    assert 'shiny-wind-028834' in event['text']
    assert NeonNode.should_propagate_output(new, {'operation': operation})
    repeated = await poll()
    assert repeated['branch_count'] == 0
    assert not NeonNode.should_propagate_output(repeated, {'operation': operation})
    assert state['scope'] == poll_scope(NeonNode, node.config.config.model_dump())
    assert len(calls) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', NEON_TRIGGERS)
async def test_branch_trigger_detects_updates_only_in_update_mode(operation):
    body = branch_example()
    body.pop('pagination')
    node = make_node({'operation': operation, 'project_id': 'shiny-wind-028834'})
    state = {}
    memory_state(node, state)
    async def poll():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
        with patch('nodes.neon_node.httpx.AsyncClient', return_value=client):
            return await node.execute({})
    await poll()
    # Replay another documented timestamp to represent an existing branch changing.
    body['branches'][0]['updated_at'] = body['branches'][1]['updated_at']
    changed = await poll()
    assert changed['branch_count'] == (0 if operation == 'on_new_branch' else 1)
    assert (await poll())['branch_count'] == 0
    # Changing the watched project establishes a fresh, quiet baseline.
    node.config.config.project_id = 'spring-example-302709'
    assert (await poll())['branch_count'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['http', 'invalid-list', 'cursor-loop'])
async def test_branch_trigger_failed_pages_never_consume_events(failure):
    body = branch_example()
    node = make_node({'operation': 'on_new_branch', 'project_id': 'shiny-wind-028834'})
    state = {'seen_ids': []}
    memory_state(node, state)
    def handle(request):
        if not request.url.params.get('cursor'):
            return httpx.Response(200, json=body)
        if failure == 'http':
            return httpx.Response(403, json={'message': 'napi_test'})
        if failure == 'invalid-list':
            return httpx.Response(200, json={'branches': {}})
        return httpx.Response(200, json=body)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch('nodes.neon_node.httpx.AsyncClient', return_value=client), pytest.raises(ValueError):
        await node.execute({})
    assert state == {'seen_ids': []}


@pytest.mark.asyncio
async def test_contract_permits_empty_object_for_updates_with_optional_fields():
    captured = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: captured.append(request) or httpx.Response(200, json={})
    ))
    with patch('nodes.neon_node.httpx.AsyncClient', return_value=client):
        result = await make_node({'operation': 'update_neon_auth_email_and_password_config',
                                  'project_id': 'shiny-wind-028834',
                                  'branch_id': 'br-aged-salad-637688',
                                  'body_json': '{}'}).execute({})
    assert result['status'] == 'success'
    assert json.loads(captured[0].content) == {}

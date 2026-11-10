"""Stable API requests and polling, with Apache's own endpoint-test payload."""
import base64
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import apache_node as apache
from nodes.core.registry import NodeFactory
from nodes.core.poll_trigger import poll_scope
from utils import ssrf

RESOLVE_HOST_ADDRESSES = ssrf._resolve_host_addresses
AUTH = {"credential_type": "apache_basic", "api_base_url": "https://airflow.example.com/api/v1", "username": "reader", "password": "fixture-password"}
RUNS = json.loads((Path(__file__).parent / "fixtures/apache/dag_runs.json").read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))

    def transport(request):
        requests.append(request)
        code, body = replies.pop(0)
        return httpx.Response(code, content=b"" if code == 204 else json.dumps(body).encode(), headers={"Content-Type": "application/json"})

    native = ssrf.guarded_async_client
    monkeypatch.setattr(apache, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(transport)))
    return requests, replies


def node(operation, **config):
    return NodeFactory.create_node(node_id="apache-test", node_type="automation-apache",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})


CASES = [
    ("list_dags", {}, "GET", "/dags", None, {"dags": [{"dag_id": "TEST_DAG_ID"}], "total_entries": 1}),
    ("get_dag", {"dag_id": "TEST_DAG_ID"}, "GET", "/dags/TEST_DAG_ID", None, {"dag_id": "TEST_DAG_ID"}),
    ("update_dag", {"dag_id": "TEST_DAG_ID", "is_paused": True}, "PATCH", "/dags/TEST_DAG_ID", {"is_paused": True}, {"is_paused": True}),
    ("list_dag_runs", {"dag_id": "TEST_DAG_ID"}, "GET", "/dags/TEST_DAG_ID/dagRuns", None, RUNS),
    ("create_dag_run", {"dag_id": "TEST_DAG_ID", "conf_json": '{"batch":42}'}, "POST", "/dags/TEST_DAG_ID/dagRuns", {"conf": {"batch": 42}}, RUNS["dag_runs"][0]),
    ("get_dag_run", {}, "GET", "", None, RUNS["dag_runs"][0]),
    ("update_dag_run_state", {"state": "failed"}, "PATCH", "", {"state": "failed"}, RUNS["dag_runs"][0]),
    ("clear_dag_run", {}, "POST", "/clear", {"dry_run": True}, {"task_instances": [], "total_entries": 0}),
    ("set_dag_run_note", {"note": "Investigating"}, "PATCH", "/setNote", {"note": "Investigating"}, RUNS["dag_runs"][0]),
    ("delete_dag_run", {}, "DELETE", "", None, None),
    ("list_task_instances", {}, "GET", "/taskInstances", None, {"task_instances": [], "total_entries": 0}),
    ("get_task_instance", {"task_id": "task"}, "GET", "/taskInstances/task", None, {"task_id": "task"}),
    ("list_tasks", {"dag_id": "TEST_DAG_ID"}, "GET", "/dags/TEST_DAG_ID/tasks", None, {"tasks": []}),
    ("get_task", {"dag_id": "TEST_DAG_ID", "task_id": "task"}, "GET", "/dags/TEST_DAG_ID/tasks/task", None, {"task_id": "task"}),
    ("list_variables", {}, "GET", "/variables", None, {"variables": [], "total_entries": 0}),
    ("get_variable", {"variable_key": "batch"}, "GET", "/variables/batch", None, {"key": "batch", "value": "42"}),
    ("create_variable", {"key": "batch", "value": "42"}, "POST", "/variables", {"key": "batch", "value": "42"}, {"key": "batch", "value": "42"}),
    ("update_variable", {"variable_key": "batch", "value": "43"}, "PATCH", "/variables/batch", {"value": "43"}, {"key": "batch", "value": "43"}),
    ("delete_variable", {"variable_key": "batch"}, "DELETE", "/variables/batch", None, None),
    ("list_pools", {}, "GET", "/pools", None, {"pools": [], "total_entries": 0}),
    ("get_pool", {"pool_name": "workers"}, "GET", "/pools/workers", None, {"name": "workers", "slots": 3}),
    ("create_pool", {"name": "workers", "slots": 3}, "POST", "/pools", {"name": "workers", "slots": 3, "description": ""}, {"name": "workers", "slots": 3}),
    ("update_pool", {"pool_name": "workers", "slots": 5}, "PATCH", "/pools/workers", {"slots": 5}, {"name": "workers", "slots": 5}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body,response", CASES)
async def test_apache_actions(wire, operation, config, method, path, body, response):
    requests, replies = wire
    config = dict(config)
    if operation in {"get_dag_run", "update_dag_run_state", "clear_dag_run", "set_dag_run_note", "delete_dag_run", "list_task_instances", "get_task_instance"}:
        config.update(dag_id="TEST_DAG_ID", dag_run_id="manual__2020-06-11T18:00:00+00:00")
        path = "/dags/TEST_DAG_ID/dagRuns/manual__2020-06-11T18:00:00+00:00" + path
    replies.append((204 if method == "DELETE" else 200, deepcopy(response)))
    result = await node(operation, **config).execute({})
    assert result is not None
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == method and request.url.path == "/api/v1" + path
    assert request.url.host == "airflow.example.com"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"reader:fixture-password").decode()
    assert "fixture-password" not in str(request.url)
    assert (json.loads(request.content) if request.content else None) == body
    if operation in {"update_dag", "update_variable", "update_pool"}:
        assert request.url.params["update_mask"] == next(iter(body))


@pytest.mark.asyncio
async def test_apache_poll_documented_payload_pagination_and_dedup(wire):
    requests, replies = wire
    instance = node("on_new_dag_run", dag_id="TEST_DAG_ID")
    state = {}

    async def update_state(mutator, *, skip_result):
        updated, result = mutator(deepcopy(state))
        if updated is not None:
            state.clear()
            state.update(updated)
        return result

    instance._update_node_state = update_state
    replies.append((200, {"dag_runs": RUNS["dag_runs"][:1], "total_entries": 1}))
    baseline = await instance.execute({})
    assert baseline["new_run_count"] == 0
    replies.extend([(200, {"dag_runs": RUNS["dag_runs"][:1], "total_entries": 2}),
                    (200, {"dag_runs": RUNS["dag_runs"][1:], "total_entries": 2})])
    first = await instance.execute({})
    assert first["new_run_count"] == 1
    assert requests[2].url.params["offset"] == "1"
    assert requests[0].url.params["order_by"] == "-start_date"
    event = apache.ApacheNode.resolve_agent_event(first)
    assert "TEST_DAG_ID" in event["text"] and "TEST_DAG_RUN_ID_2" in event["text"] and "running" in event["text"]
    replies.append((200, deepcopy(RUNS)))
    second = await instance.execute({})
    assert second["new_run_count"] == 0
    assert apache.ApacheNode.resolve_agent_event(second) is None
    assert not apache.ApacheNode.should_propagate_output(second, {"operation": "on_new_dag_run"})


def test_apache_poll_scope_ignores_canvas_metadata():
    base = {"operation": "on_new_dag_run", "dag_id": "a"}
    assert poll_scope(apache.ApacheNode, base) == poll_scope(apache.ApacheNode, {**base, "goal": "other", "label": "Renamed"})
    assert poll_scope(apache.ApacheNode, base) != poll_scope(apache.ApacheNode, {**base, "dag_id": "b"})


@pytest.mark.parametrize("config", [
    {"operation": "create_dag_run", "dag_id": "a", "conf_json": "[]"},
    {"operation": "get_dag", "dag_id": ".."},
    {"operation": "get_variable", "variable_key": "a/b"},
    {"operation": "update_dag_run_state", "dag_id": "a", "dag_run_id": "b", "state": "running"},
])
def test_apache_invalid_inputs(config):
    with pytest.raises(ValueError):
        apache.ApacheNode.parse_config({"config": config, "credentials": AUTH})


def test_apache_manual_credential_defaults_and_url_validation():
    credential = apache.ApacheBasicCredential(api_base_url="https://airflow.example.com/", username="reader", password="fixture-password")
    assert credential.credential_type == "apache_basic"
    assert credential.api_base_url == AUTH["api_base_url"]
    for url in ["http://example.com/api/v1", "https://user:password@example.com/api/v1", "https://example.com/api/v1?next=other", "https://example.com/api/v2"]:
        with pytest.raises(ValidationError):
            apache.ApacheBasicCredential(**{**AUTH, "api_base_url": url})


@pytest.mark.asyncio
async def test_apache_provider_error_survives_without_password(wire):
    requests, replies = wire
    replies.append((401, {"detail": "Invalid password fixture-password"}))
    with pytest.raises(ValueError, match="Airflow API error 401: Invalid password ") as error:
        await node("list_dags").execute({})
    assert "fixture-password" not in str(error.value)


@pytest.mark.asyncio
async def test_apache_private_destination_is_rejected(wire, monkeypatch):
    requests, replies = wire
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "false")
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", RESOLVE_HOST_ADDRESSES)
    instance = node("list_dags")
    instance.config.credentials.api_base_url = "https://127.0.0.1/api/v1"
    with pytest.raises(ssrf.SSRFError):
        await instance.execute({})
    assert not requests

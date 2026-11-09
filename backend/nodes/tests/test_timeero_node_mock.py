"""Exercise Timeero's native factory with provider-authored API and event examples.

Transport stays offline while assertions cover the actual route, credential,
write body, webhook signature, registration ownership and agent event seams.
"""
import hashlib
import hmac
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import timeero_node as node
from nodes.core.run_op import run_node_operation

FIXTURES = Path(__file__).parent / "fixtures" / "timeero"
RESPONSES = json.loads((FIXTURES / "responses.json").read_text())
EVENTS = json.loads((FIXTURES / "events.json").read_text())
AUTH = {"credential_type": "timeero_api_key", "api_key": "fixture-timeero-key"}
USER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    native = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        assert request.url.host == "api.timeero.app"
        assert request.headers["Authorization"] == AUTH["api_key"]
        assert AUTH["api_key"] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(node.httpx, "AsyncClient", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(respond)))
    return requests, replies


CASES = [
    ("list_users", {"page": 2, "per_page": 20, "active": False, "sort": "first_name"}, "GET", "/api/public/users", None),
    ("get_user", {"user_id": 660}, "GET", "/api/public/users/660", None),
    ("list_groups", {"page": 1, "name": "Staff"}, "GET", "/api/public/groups", None),
    ("list_jobs", {"page_size": 20, "job_status": True}, "GET", "/api/public/jobs", None),
    ("get_job", {"job_id": 2}, "GET", "/api/public/jobs/2", None),
    ("create_job", {"name": "Job A", "users": [1, 2], "track_mileage": False}, "POST", "/api/public/jobs", {"name": "Job A", "users": [1, 2], "track_mileage": False}),
    ("update_job", {"job_id": 2, "name": "Player B Updated"}, "PUT", "/api/public/jobs/2", {"name": "Player B Updated"}),
    ("list_tasks", {"jobId": 3295, "task_status": False}, "GET", "/api/public/tasks", None),
    ("get_task", {"task_id": 96}, "GET", "/api/public/tasks/96", None),
    ("create_task", {"name": "Gardening", "user_id": 678, "jobs": [3295], "billable": False}, "POST", "/api/public/tasks", {"name": "Gardening", "user_id": 678, "jobs": [3295], "billable": False}),
    ("update_task", {"task_id": 96, "name": "Gardening", "user_id": 678}, "PUT", "/api/public/tasks/96", {"name": "Gardening", "user_id": 678}),
    ("list_timesheets", {"user_id": 661, "date_range": "2025-07-18,2025-07-31"}, "GET", "/api/public/timesheets", None),
    ("get_timesheet", {"timesheet_id": 3018248}, "GET", "/api/public/timesheets/3018248", None),
    ("create_timesheet", {"user_id": 661, "start": "2024-10-02T08:00:00-08:00"}, "POST", "/api/public/timesheets", {"user_id": 661, "start": "2024-10-02T08:00:00-08:00"}),
    ("update_timesheet", {"timesheet_id": 3018248, "user_id": 661, "start": "2024-10-02T08:00:00-08:00", "notes": "Corrected"}, "PUT", "/api/public/timesheets/3018248", {"user_id": 661, "start": "2024-10-02T08:00:00-08:00", "notes": "Corrected"}),
    ("approve_timesheets", {"ids": [3018248], "mute_notification": True}, "POST", "/api/public/timesheets/approve", {"ids": [3018248], "mute_notification": True}),
    ("clock_in", {"user_id": 681, "job_id": "5102"}, "POST", "/api/public/timesheets/clock-in", {"user_id": 681, "job_id": "5102"}),
    ("clock_out", {"user_id": 681, "clock_out_time": "2024-10-02T17:00:00-08:00"}, "POST", "/api/public/timesheets/clock-out", {"user_id": 681, "clock_out_time": "2024-10-02T17:00:00-08:00"}),
    ("list_schedules", {"date_range": "2025-07-18,2025-07-31", "status": "published"}, "GET", "/api/public/schedules", None),
    ("get_schedule", {"schedule_id": 16902}, "GET", "/api/public/schedules/16902", None),
]


async def run(operation, arguments=None):
    return await run_node_operation(node_type="automation-timeero", operation=operation, arguments=arguments or {},
                                    credential_data=deepcopy(AUTH), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,body", CASES)
async def test_native_actions_against_published_responses(transport, operation, config, method, path, body):
    requests, replies = transport
    replies.append((200, RESPONSES[operation]["body"]))
    result = await run(operation, config)
    assert result["status"] == "success"
    assert result["data"] == RESPONSES[operation]["body"]
    request, = requests
    assert (request.method, request.url.path) == (method, path)
    if body is not None:
        assert json.loads(request.content) == body
        assert not request.url.query
    else:
        assert not request.content
        assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items() if not k.endswith("_id") or k in {"user_id"} and operation == "list_timesheets"}
    assert not replies


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Invalid API key"}), (200, {"status": False, "message": "Rejected"}), (500, {"error_code": 500, "message": "An error has occurred."}), (200, {})])
async def test_errors_never_become_successful_evidence(transport, status, body):
    transport[1].append((status, body))
    with pytest.raises(Exception):
        await run("list_users")


@pytest.mark.parametrize("bad", ["Bearer secret", "https://example.test/key", "secret\r\nHeader: bad", "<token>", ""])
def test_credential_shape_and_manual_default(bad):
    with pytest.raises(ValidationError):
        node.TimeeroAPIKeyCredential(api_key=bad)
    assert node.TimeeroAPIKeyCredential(api_key=AUTH["api_key"]).credential_type == "timeero_api_key"


@pytest.mark.parametrize("bad", ["../1", "1?x=2", 0, -1, True])
def test_path_ids_never_inject_routes(bad):
    with pytest.raises(ValidationError):
        node.TimeeroGetJobConfig(job_id=bad)


def test_resource_id_normalization_and_registration_scope():
    assert node.TimeeroGetJobConfig(job_id="2").job_id == 2
    assert node.TimeeroClockInConfig(user_id="681", job_id="5102").job_id == "5102"
    assert node.TimeeroNode.registration_fingerprint_fields({"replace_existing_subscription": True}) != node.TimeeroNode.registration_fingerprint_fields({})


def test_write_requirements_and_false_values():
    with pytest.raises(ValidationError):
        node.TimeeroCreateTaskConfig(name="Gardening")
    with pytest.raises(ValidationError):
        node.TimeeroUpdateJobConfig(job_id=2)
    with pytest.raises(ValidationError):
        node.TimeeroCreateJobConfig(name="Job", require_geofence=True)
    with pytest.raises(ValidationError):
        node.TimeeroCreateTimesheetConfig(user_id=661, start="2024-10-02T08:00:00Z", end="2024-10-01T08:00:00Z")
    assert node.TimeeroCreateJobConfig(name="Job", track_mileage=False).track_mileage is False


@pytest.mark.parametrize("name", list(EVENTS))
@pytest.mark.parametrize("prefix", ["x-webhook-", "x-"])
def test_documented_signatures_authenticate_exact_body(name, prefix):
    body = json.dumps(EVENTS[name]["body"]).encode()
    stamp, secret = "1756209841", "fixture-shared-secret"
    digest = hmac.new(secret.encode(), stamp.encode() + body, hashlib.sha256).hexdigest()
    headers = {prefix + "timestamp": stamp, prefix + "signature": digest}
    config = {"signing_secret": secret}
    assert node.TimeeroNode.verify_webhook_signature(body, headers, config)
    assert not node.TimeeroNode.verify_webhook_signature(body + b" ", headers, config)
    assert not node.TimeeroNode.verify_webhook_signature(body, headers, {"signing_secret": "wrong"})
    assert not node.TimeeroNode.verify_webhook_signature(body, {}, config)
    assert not node.TimeeroNode.verify_webhook_signature(body, headers, {})


@pytest.mark.asyncio
async def test_webhook_lifecycle_and_ownership(transport, monkeypatch):
    requests, replies = transport
    monkeypatch.setattr(node.secrets, "token_hex", lambda n: "pass1234")
    config = {"operation": "on_new_job", "replace_existing_subscription": True, "webhook_url": "https://timeero.com"}
    # Whole subscription examples are copied from the provider's published contract.
    subscription = {"id": 13, "url": "https://timeero.com", "signature_secret_key": "pass1234", "active": True, "events": ["*"], "created_at": 1724925651, "updated_at": 1724926490}
    replies.append((200, {"status": True, "message": "Webhook URL is subscribed successfully.", "payload": subscription}))
    registration = await node.TimeeroNode._register_external_webhook(webhook_url=config["webhook_url"], credential=AUTH, config=config, node_id="test")
    assert registration == {"external_webhook_id": "13", "signing_secret": "pass1234"}
    assert json.loads(requests[0].content) == {"url": "https://timeero.com", "signature_secret_key": "pass1234", "active": True, "events": ["*"]}
    config.update(registration)
    replies.extend([(200, {"status": True, "payload": {"subscription": subscription}}), (200, {"status": True, "message": "Webhook URL is unsubscribed successfully.", "payload": None})])
    await node.TimeeroNode._unregister_external_webhook(credential=AUTH, config=config, node_id="test")
    assert [(r.method, r.url.path) for r in requests] == [("POST", "/webhooks/subscription/subscribe"), ("GET", "/api/public/webhooks/subscription/list"), ("DELETE", "/webhooks/subscription/unsubscribe")]
    replies.append((200, {"status": True, "payload": {"subscription": subscription}}))
    await node.TimeeroNode._unregister_external_webhook(credential=AUTH, config={**config, "signing_secret": "replaced"}, node_id="test")
    assert requests[-1].method == "GET" and not replies


@pytest.mark.asyncio
async def test_registration_requires_explicit_replacement_choice(transport):
    with pytest.raises(ValueError, match="Replace Company Webhook"):
        await node.TimeeroNode._register_external_webhook(webhook_url="https://example.test", credential=AUTH, config={"operation": "on_new_job"}, node_id="test")
    assert not transport[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,event_name,get_operation", [("on_clock_in", "clockin", "get_timesheet"), ("on_clock_out", "clockout", "get_timesheet"), ("on_new_job", "jobs", "get_job"), ("on_new_task", "tasks", "get_task"), ("on_new_schedule", "schedules", "get_schedule")])
async def test_documented_event_filter_hydration_and_human_turn(transport, operation, event_name, get_operation):
    payload = EVENTS[event_name]["body"]
    for name, example in EVENTS.items():
        assert node.TimeeroNode.filter_trigger_payload(example["body"], {"operation": operation}) is (name == event_name)
    config = node.TimeeroNodeConfig.model_validate({"config": {"operation": operation}, "credentials": AUTH})
    instance = node.TimeeroNode(node_id="test", node_type="automation-timeero", node_data={"config": {"_triggerPayload": payload}}, config=config, sio=Mock())
    transport[1].append((200, RESPONSES[get_operation]["body"]))
    result = await instance.execute({})
    identifier = payload["payload"]["data"]["id"]
    assert transport[0][0].url.path.endswith("/" + str(identifier))
    turn = node.TimeeroNode.resolve_agent_event(result)
    assert str(identifier) in turn["text"] and "To act:" in turn["text"]
    assert turn["conversation_key"].endswith(":" + str(identifier))
    assert node.TimeeroNode.resolve_agent_event({"status": "success", "data": {}}) is None

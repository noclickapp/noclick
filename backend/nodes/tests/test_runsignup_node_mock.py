"""RunSignup operations through the native node factory with offline HTTP fixtures."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes import runsignup_node as rsu
from nodes.core.registry import NodeFactory
from utils import ssrf

FIXTURES = Path(__file__).parent / "fixtures" / "runsignup"
AUTH = {"credential_type": "runsignup_api_key", "api_key": "fixture-key", "api_secret": "fixture-secret"}


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text())


@pytest.fixture
def transport(monkeypatch):
    requests, queue = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
    native = ssrf.guarded_async_client
    monkeypatch.setattr(rsu, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, queue


async def run(operation, config=None, credential=None):
    node = NodeFactory.create_node(node_id="rsu-test", node_type="automation-runsignup",
        node_data={"config": {"operation": operation, **(config or {})}, "credentials": credential or AUTH})
    return await node.execute({})


CASES = [
    ("get_api_key_entity", {}, "GET", "/v2/auth-info/entity-info.json", {"generic_entity_id": 999, "entity_type": "race", "entity_name": "My Race Name", "entity_specific_id": 111}),
    ("list_races", {"page": 2, "name": "5K"}, "GET", "/races", {"races": [{"race": {"race_id": 12345, "name": "5K"}}]}),
    ("get_race", {"race_id": 12345}, "GET", "/race/12345", {"race": {"race_id": 12345, "name": "5K", "events": []}}),
    ("list_participants", {"race_id": 12345, "event_id": 11111}, "GET", "/race/12345/participants", "race-race_id-participants-GET"),
    ("get_participant_counts", {"race_id": 12345, "event_id": 11111}, "GET", "/race/12345/participant-counts", "race-race_id-participant-counts-GET"),
    ("list_removed_participants", {"race_id": 12345, "event_id": 12890}, "GET", "/race/12345/removed-participants", "race-race_id-removed-participants-GET"),
    ("list_donations", {"race_id": 12345, "since_ts": 1427132552}, "GET", "/race/12345/donations/list", "race-race_id-donations-list-GET"),
    ("list_fundraisers", {"race_id": 12345, "page": 2, "num": 10}, "GET", "/v2/race-fundraisers/get-race-fundraisers.json", {"race_fundraisers": []}),
    ("list_teams", {"race_id": 12345, "event_id": 11111}, "GET", "/race/12345/teams", {"teams": []}),
    ("list_coupons", {"race_id": 12345, "coupon_code": "abc"}, "GET", "/race/12345/coupons", {"coupons": []}),
    ("list_result_sets", {"race_id": 12345, "event_id": 11111}, "GET", "/race/12345/results/get-result-sets", {"individual_results_sets": []}),
    ("list_results", {"race_id": 12345, "event_id": 11111, "individual_result_set_id": 123}, "GET", "/race/12345/results/get-results", {"individual_results_sets": []}),
    ("list_volunteer_tasks", {"race_id": 12345}, "GET", "/v2/volunteers/get-race-volunteer-tasks.json", "v2-volunteers-get-race-volunteer-tasks.json-GET"),
    ("update_race_description", {"race_id": 12345, "description": "<p>New description</p>"}, "POST", "/race/12345/race-description", {"success": True}),
    ("upsert_participants", {"race_id": 12345, "event_id": 11111, "request": '{"participants":[{"registration_id":1454457,"bib_num":1013}]}'}, "POST", "/race/12345/participants", {"participants": [{"registration_id": 1454457}]}),
    ("upsert_coupons", {"race_id": 12345, "request": '{"coupons":[{"coupon_id":null,"coupon_code":"abc","percentage":25}]}'}, "POST", "/race/12345/coupons", {"coupon_ids": [12345]}),
    ("assign_bib_chip", {"race_id": 12345, "event_id": 11111, "request": '{"assignments":[{"registration_id":123,"bib_num":1,"chip_num":"chip1"}]}'}, "POST", "/race/12345/assign-bib-chip", {"success": True}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,config,method,path,payload", CASES)
async def test_native_operation_wire_contract(transport, operation, config, method, path, payload):
    requests, queue = transport
    payload = fixture(payload) if isinstance(payload, str) else payload
    queue.append(httpx.Response(200, json=payload))
    result = await run(operation, config)
    assert result["status"] == "success" and result["data"] == payload
    assert len(requests) == 1 and not queue
    request = requests[0]
    assert request.method == method and request.url.path == "/rest" + path
    assert request.url.scheme == "https" and request.url.host == "api.runsignup.com"
    assert request.url.params["rsu_api_key"] == AUTH["api_key"]
    assert request.headers["X-RSU-API-SECRET"] == AUTH["api_secret"]
    assert AUTH["api_secret"] not in str(request.url)
    assert "api_key" not in request.url.params and "api_secret" not in request.url.params
    if operation != "get_api_key_entity":
        assert request.url.params["format"] == "json"
    for key, value in config.items():
        if key in {"race_id", "description", "request"}:
            continue
        assert request.url.params[key] == str(value)
    if method == "POST":
        from email.parser import BytesParser
        from email.policy import default
        parts = BytesParser(policy=default).parsebytes(b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
        fields = {p.get_param("name", header="content-disposition"): p.get_content().decode() if isinstance(p.get_content(), bytes) else p.get_content() for p in parts.iter_parts()}
        if "request" in config:
            assert fields["request"] == config["request"] and fields["request_format"] == "json"
        else:
            assert fields == {"description": config["description"]}
        if operation == "upsert_participants":
            assert fields["restrict_potential_dup"] == "T"
    else:
        assert request.content == b""
    if operation == "list_races":
        assert result["page"] == 2 and result["results_per_page"] == 50
    if operation == "get_api_key_entity":
        assert result["name"] == "My Race Name" and result["id"] == 111


@pytest.mark.asyncio
@pytest.mark.parametrize("code,body", [(401, {"error": "Invalid API key"}), (403, {"error": "Permission denied"}), (200, {"error": {"error_code": 100, "error_msg": "Invalid API key"}}), (200, {"success": False})])
async def test_rejections_are_not_successful_evidence(transport, code, body):
    requests, queue = transport
    queue.append(httpx.Response(code, json=body))
    with pytest.raises(ValueError):
        await run("get_api_key_entity")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_redacts_secrets_and_url_encodings(transport):
    _, queue = transport
    queue.append(httpx.Response(401, json={"error": "fixture-key fixture-secret"}))
    with pytest.raises(ValueError) as exc:
        await run("get_api_key_entity")
    assert "fixture-key" not in str(exc.value) and "fixture-secret" not in str(exc.value)
    queue.append(httpx.Response(200, json={"race": {"api_key": "fixture-key", "detail": "fixture-secret"}}))
    result = await run("get_race", {"race_id": 12345})
    assert AUTH["api_key"] not in json.dumps(result) and AUTH["api_secret"] not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://other.test"}), httpx.Response(200, text="<html>Sign in</html>"), httpx.Response(200, json="not an envelope"), httpx.Response(200, content=b"{broken", headers={"content-type": "application/json"})])
async def test_unexpected_responses_fail_without_following_redirects(transport, response):
    requests, queue = transport
    queue.append(response)
    with pytest.raises(ValueError):
        await run("get_api_key_entity")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_write_timeout_never_retries_or_echoes_http_error(transport):
    requests, queue = transport
    queue.append(httpx.ReadTimeout("fixture-key fixture-secret"))
    with pytest.raises(ValueError, match="inspect the race") as exc:
        await run("update_race_description", {"race_id": 12345, "description": "Updated"})
    assert len(requests) == 1 and "fixture-secret" not in str(exc.value)


@pytest.mark.parametrize("config", [
    {"operation": "get_race", "race_id": "../users"},
    {"operation": "get_race", "race_id": 0},
    {"operation": "list_races", "page": 0},
    {"operation": "list_races", "results_per_page": 10000},
    {"operation": "list_races", "api_secret": "override"},
    {"operation": "upsert_coupons", "race_id": 123, "request": '{"participants":[{}]}'},
    {"operation": "upsert_coupons", "race_id": 123, "request": '{"coupons":[]}'},
    {"operation": "assign_bib_chip", "race_id": 123, "event_id": 1, "request": 'null'},
])
def test_invalid_inputs_never_reach_transport(config):
    with pytest.raises(ValueError):
        rsu.RunSignupNodeConfig.model_validate({"config": config, "credentials": AUTH})


def test_manual_credential_default_and_family():
    parsed = rsu.RunSignupAPIKeyCredential.model_validate({"api_key": "fixture-key", "api_secret": "fixture-secret"})
    assert parsed.credential_type == "runsignup_api_key"
    for change in [{"credential_type": "foreign"}, {"api_key": "https://example.test"}, {"api_secret": "Bearer secret"}]:
        with pytest.raises(ValueError):
            rsu.RunSignupAPIKeyCredential.model_validate({**AUTH, **change})


@pytest.mark.asyncio
async def test_published_request_and_response_examples(transport):
    _, queue = transport
    for op, name in [("upsert_participants", "participants"), ("assign_bib_chip", "assignments")]:
        request, response = fixture(name)
        queue.append(httpx.Response(200, json=response))
        result = await run(op, {"race_id": 12345, "event_id": 11111, "request": json.dumps(request)})
        assert result["data"] == response


@pytest.mark.asyncio
async def test_published_entity_identity_has_numeric_specific_id(transport):
    _, queue = transport
    entity = fixture("entity")[0]
    queue.append(httpx.Response(200, json=entity))
    result = await run("get_api_key_entity")
    assert result["name"] == entity["entity_name"] and result["id"] == entity["entity_specific_id"]


def poll_node(operation, **scope):
    return NodeFactory.create_node(node_id="rsu-poll", node_type="automation-runsignup",
        node_data={"config": {"operation": operation, **scope}, "credentials": AUTH})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,key,filename,scope", [
    ("on_new_or_updated_participant", "participants", "race-race_id-participants-GET", {"race_id": 12345, "event_id": 11111}),
    ("on_new_donation", "donations", "race-race_id-donations-list-GET", {"race_id": 12345}),
])
async def test_poll_baseline_new_items_and_agent_event(transport, operation, key, filename, scope):
    from copy import deepcopy
    node = poll_node(operation, **scope)
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(state)
        if replacement is not None:
            state = replacement
        return result
    node._update_node_state = update
    requests, queue = transport
    payload = fixture(filename)
    queue.append(httpx.Response(200, json=payload))
    baseline = await node.execute({})
    assert baseline['new_item_count'] == 0
    assert node.trigger_produced_no_event(baseline)
    assert node.resolve_agent_event(baseline) is None
    changed = deepcopy(payload)
    if key == 'participants':
        changed[key][0]['last_modified'] += 1
    else:
        changed[key][0]['donation_id'] += 1
    queue.append(httpx.Response(200, json=changed))
    output = await node.execute({})
    assert output['items'] == changed[key] and output['new_item_count'] == 1
    assert node.should_propagate_output(output, {'operation': operation})
    event = node.resolve_agent_event(output)
    assert str(scope['race_id']) in event['text']
    assert changed[key][0]['user']['first_name'] in event['text']
    queue.append(httpx.Response(200, json=changed))
    assert (await node.execute({}))['items'] == []
    assert requests[0].url.params['page'] == '1'
    assert requests[0].url.params['results_per_page'] == '100'
    assert 'schedule' not in requests[0].url.params


@pytest.mark.asyncio
async def test_poll_reads_later_pages_and_never_commits_partial_response(transport):
    from copy import deepcopy
    node = poll_node('on_new_donation', race_id=12345)
    requests, queue = transport
    row = fixture('race-race_id-donations-list-GET')['donations'][0]
    rows = [{**deepcopy(row), 'donation_id': i} for i in range(1, 101)]
    node._filter_unseen = AsyncMock(return_value=[row])
    queue.extend([httpx.Response(200, json={'donations': rows}), httpx.Response(200, json={'donations': [row]})])
    await node.execute({})
    assert [r.url.params['page'] for r in requests] == ['1', '2']
    assert len(node._filter_unseen.call_args.args[0]) == 101
    node._filter_unseen.reset_mock()
    queue.extend([httpx.Response(200, json={'donations': rows}), httpx.Response(500, json={'error': 'Unavailable'})])
    with pytest.raises(ValueError):
        await node.execute({})
    node._filter_unseen.assert_not_called()


def test_poll_scope_is_declared_and_changes_with_race_event():
    from nodes.core.poll_trigger import poll_scope
    config = {'operation': 'on_new_or_updated_participant', 'race_id': 12345, 'event_id': 11111}
    original = poll_scope(rsu.RunSignupNode, config)
    assert original != poll_scope(rsu.RunSignupNode, {**config, 'event_id': 12890})
    assert original != poll_scope(rsu.RunSignupNode, {**config, 'race_id': 23456})
    assert original == poll_scope(rsu.RunSignupNode, {**config, 'schedule': {'frequency': 'minutes', 'interval': 10}})

"""HTTP-boundary tests replaying CleverTap's own saved Postman responses."""
import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import clevertap_node as native

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/clevertap/postman_examples.json").read_text())["operations"]
CREDENTIAL = {"account_id": "fixture-account-42", "passcode": "fixture-passcode-42", "region": "in1"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    parsed = native.CleverTapNodeConfig(config=config, credentials=credential or CREDENTIAL)
    return native.CleverTapNode(node_id="clevertap-test", node_type=native.CleverTapNode.integration_type,
                               node_data={"config": config}, config=parsed)


def transport(monkeypatch, response, status=200):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, content=response if isinstance(response, str) else json.dumps(response))
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [op for op in EXAMPLES if not op.startswith("on_")])
async def test_each_operation_replays_its_own_saved_example(monkeypatch, operation):
    example = EXAMPLES[operation]
    saved = example["responses"][0]
    requests = transport(monkeypatch, saved["body"], saved["code"])
    output = await node(example["config"]).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example["request"]["method"]
    assert request.url.host == "in1.api.clevertap.com"
    assert request.url.path == "/" + "/".join(example["request"]["url"]["path"])
    assert request.headers["X-CleverTap-Account-Id"] == CREDENTIAL["account_id"]
    assert request.headers["X-CleverTap-Passcode"] == CREDENTIAL["passcode"]
    assert request.headers["Content-Type"] == "application/json"
    if request.method == "POST":
        expected = json.loads(example["request"]["body"]["raw"])
        if operation.startswith("send_"):
            expected["content"].pop("platform_specific", None)
        assert json.loads(request.content) == expected
    elif operation == "get_profile":
        assert dict(request.url.params) == {"identity": "12345"}
    elif "export_page" in operation:
        assert dict(request.url.params) == {"cursor": example["config"]["cursor"]}
    else:
        assert not dict(request.url.params)
    expected = json.loads(saved["body"])
    if operation == "list_subscription_groups":
        assert output["groups"] == expected["list"]
    else:
        assert output == {"operation": operation, **expected}
    assert CREDENTIAL["passcode"] not in json.dumps(output)


@pytest.mark.asyncio
@pytest.mark.parametrize("region,host", [("in1", "in1.api.clevertap.com"), ("sg1", "sg1.api.clevertap.com"), ("us1", "us1.api.clevertap.com"), ("aps3", "aps3.api.clevertap.com"), ("mec1", "mec1.api.clevertap.com"), ("eu1", "api.clevertap.com")])
async def test_documented_regions_are_fixed_hosts(monkeypatch, region, host):
    requests = transport(monkeypatch, EXAMPLES["list_subscription_groups"]["responses"][0]["body"])
    await node({"operation": "list_subscription_groups"}, {**CREDENTIAL, "region": region}).execute({})
    assert requests[0].url.host == host


def test_manual_credential_default_and_header_validation():
    credential = native.CleverTapCredential(**CREDENTIAL)
    assert credential.credential_type == "clevertap_passcode"
    for bad in ["https://evil.example", "in1.api.clevertap.com.evil.example"]:
        with pytest.raises(ValidationError):
            native.CleverTapCredential(**{**CREDENTIAL, "region": bad})
    for field in ("account_id", "passcode"):
        for bad in ["https://example.com/key", "bad\r\nHeader: injected"]:
            with pytest.raises(ValidationError):
                native.CleverTapCredential(**{**CREDENTIAL, field: bad})


@pytest.mark.asyncio
@pytest.mark.parametrize("http_status", [401, 429, 500, 302])
async def test_rejections_and_redirects_never_retry_a_send(monkeypatch, http_status):
    # Published error from https://developer.clevertap.com/docs/get-campaigns-api.
    requests = transport(monkeypatch, {"status": "fail", "error": "Invalid Credentials", "code": 401}, http_status)
    with pytest.raises(ValueError, match=f"CleverTap HTTP {http_status}"):
        await node(EXAMPLES["send_email"]["config"]).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_error_envelope_is_not_success(monkeypatch):
    transport(monkeypatch, {"status": "fail", "error": "Invalid Credentials", "code": 401})
    with pytest.raises(ValueError, match="Invalid Credentials"):
        await node({"operation": "list_subscription_groups"}).execute({})


def test_invalid_date_ranges_and_empty_recipients_fail_before_http():
    for start,end in [(20260230,20260301),(20261210,20261201),(20261,20261201)]:
        with pytest.raises(ValidationError):
            native.ListCampaigns(from_date=start,to_date=end)
    with pytest.raises(ValidationError):
        native.Recipients()
    with pytest.raises(ValidationError):
        native.Recipients(Identity=[""])


@pytest.mark.asyncio
async def test_poll_baseline_repeat_and_documented_version_change(monkeypatch):
    cfg = {"operation": "on_subscription_group_changed"}
    poll = node(cfg)
    state = {}
    async def update(mutator, **kwargs):
        new,result = mutator(copy.deepcopy(state))
        if new is not None:
            state.clear()
            state.update(new)
        return result
    poll._update_node_state = update
    saved = json.loads(EXAMPLES[cfg["operation"]]["responses"][0]["body"])
    transport(monkeypatch, saved)
    assert (await poll.execute({}))["groups"] == []
    assert (await poll.execute({}))["groups"] == []
    # Mutate the documented timestamp field to simulate a second delivery/version.
    saved["list"][0]["updated_on"] += 1
    transport(monkeypatch, saved)
    output = await poll.execute({})
    assert output["changed_group_count"] == 1
    event = native.CleverTapNode.resolve_agent_event(output)
    assert "Newsletter" in event["text"] and "group key 1" in event["text"]
    assert (await poll.execute({}))["groups"] == []
    assert native.CleverTapNode.resolve_agent_event({"operation": cfg["operation"], "groups": []}) is None


@pytest.mark.asyncio
async def test_poll_with_empty_seen_set_emits_collection_payload(monkeypatch):
    poll = node({"operation": "on_subscription_group_changed"})
    state = {"seen_ids": []}
    async def update(mutator, **kwargs):
        new,result = mutator(state.copy())
        if new is not None:
            state.update(new)
        return result
    poll._update_node_state = update
    saved = EXAMPLES["on_subscription_group_changed"]["responses"][0]["body"]
    transport(monkeypatch, saved)
    output = await poll.execute({})
    assert output["groups"] == json.loads(saved)["list"]
    assert poll._poll_emitted_count == 1


@pytest.mark.asyncio
async def test_event_poll_collection_cursor_chain_repeat_protection_and_dedup(monkeypatch):
    poll = node({"operation": "on_new_event", "event_name": "App Launched", "account_timezone": "Asia/Kolkata"})
    state = {"seen_ids": []}
    async def update(mutator, **kwargs):
        new,result = mutator(state.copy())
        if new is not None:
            state.clear()
            state.update(new)
        return result
    poll._update_node_state = update
    opened = EXAMPLES["start_event_export"]["responses"][0]["body"]
    page = EXAMPLES["get_event_export_page"]["responses"][0]["body"]
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=opened if request.method == "POST" else page)
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))
    output = await poll.execute({})
    assert [r.method for r in requests] == ["POST", "GET", "GET"]
    assert json.loads(requests[0].content)["event_name"] == "App Launched"
    assert output["new_event_count"] == 1
    assert output["records"] == json.loads(page)["records"]
    assert not output["scan_complete"] and "repeated" in output["warning"]
    event = native.CleverTapNode.resolve_agent_event(output)
    assert "App Launched" in event["text"] and "20151023140416" in event["text"]
    assert "coverage" in event["text"]
    assert (await poll.execute({}))["records"] == []


@pytest.mark.asyncio
async def test_event_poll_documented_terminal_cursor_response(monkeypatch):
    poll = node({"operation": "on_new_event", "event_name": "App Launched"})
    async def update(mutator, **kwargs):
        _,result = mutator({"seen_ids": []})
        return result
    poll._update_node_state = update
    opened = EXAMPLES["start_event_export"]["responses"][0]["body"]
    # Exact terminal example from https://developer.clevertap.com/docs/get-events-api.
    terminal = {"status": "success"}
    def handler(request):
        return httpx.Response(200, content=opened if request.method == "POST" else json.dumps(terminal))
    monkeypatch.setattr(native, "guarded_async_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))
    output = await poll.execute({})
    assert output["records"] == [] and output["scan_complete"]
    assert native.CleverTapNode.resolve_agent_event(output) is None



def test_event_identity_ignores_mutable_profile_and_summary_enrichment():
    example = json.loads((Path(__file__).parent / "fixtures/clevertap/event_export_docs.json").read_text())["body"]["records"][0]
    key = native.CleverTapNode._event_key(example)
    enriched = copy.deepcopy(example)
    enriched["profile"]["email"] = "changed@example.test"
    enriched["profile"]["profileData"]["favoriteColor"] = "red"
    enriched["events"]["Test event"]["count"] += 1
    assert native.CleverTapNode._event_key(enriched) == key
    for field in ("ts", "event_props", "session_props"):
        changed = copy.deepcopy(example)
        changed[field] = example["ts"] + 1 if field == "ts" else {"value": "different"}
        assert native.CleverTapNode._event_key(changed) != key
    another_user = copy.deepcopy(example)
    another_user["profile"]["objectId"] = "different-user"
    assert native.CleverTapNode._event_key(another_user) != key

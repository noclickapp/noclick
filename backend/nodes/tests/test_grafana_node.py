"""Contract tests for Grafana route selection and request/response handling.

These tests do not count as live NoClick FlowCanvas verification.
"""

import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from nodes.grafana_node import OPERATIONS
from nodes.grafana_node import GrafanaNode, GrafanaNodeConfig, _MODELS, _origin


def _node(operation, **fields):
    config = GrafanaNodeConfig.model_validate(
        {
            "config": {"operation": operation, **fields},
            "credentials": {
                "url": "https://example.grafana.net",
                "token": "grafana-qa-token",
            },
        }
    )
    return GrafanaNode(
        node_id="grafana-test",
        node_type="automation-grafana",
        node_data={},
        config=config,
    )


@pytest.fixture
def alert_notification():
    # Unmodified default JSON example from Grafana's webhook-notifier docs;
    # the adjacent provenance file records the provider page.
    return json.loads((Path(__file__).parent / "fixtures/grafana/alert-notification.json").read_text())


@pytest.mark.asyncio
async def test_grafana_trigger_registers_signed_contact_point_and_removes_it():
    requests = []

    def capture(request):
        requests.append(request)
        return httpx.Response(202 if request.method == "POST" else 204)

    credential = _node("on_alert_notification").config.credentials.model_dump()
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(capture))

    with patch("nodes.grafana_node.guarded_async_client", side_effect=client):
        registration = await GrafanaNode._register_external_webhook(
            webhook_url="https://example.hooks.example.test", credential=credential,
            config={"operation": "on_alert_notification"}, node_id="grafana-trigger")
        await GrafanaNode._unregister_external_webhook(
            credential=credential, config=registration, node_id="grafana-trigger")
    posted = json.loads(requests[0].content)
    assert posted["uid"] == registration["external_webhook_id"]
    assert len(posted["uid"]) <= 40
    assert posted["name"].startswith("NoClick ")
    assert posted["type"] == "webhook"
    assert posted["disableResolveMessage"] is False
    assert posted["settings"] == {
        "url": "https://example.hooks.example.test", "httpMethod": "POST",
        "hmacConfig": {"secret": registration["signing_secret"],
                       "header": "X-Grafana-Alerting-Signature",
                       "timestampHeader": "X-Grafana-Alerting-Timestamp"},
    }
    assert len(registration["signing_secret"]) == 64
    assert requests[0].url.path == "/api/v1/provisioning/contact-points"
    assert requests[1].method == "DELETE"
    assert requests[1].url.path.endswith("/" + posted["uid"])
    assert all(r.headers["Authorization"] == "Bearer grafana-qa-token" for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [401, 403, 409, 500])
async def test_grafana_trigger_lifecycle_errors_are_not_hidden(code):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(code)))
    credential = _node("on_alert_notification").config.credentials.model_dump()
    with patch("nodes.grafana_node.guarded_async_client", side_effect=client):
        with pytest.raises(httpx.HTTPStatusError):
            await GrafanaNode._register_external_webhook(
                webhook_url="https://example.hooks.example.test", credential=credential, config={}, node_id="test")
        with pytest.raises(httpx.HTTPStatusError):
            await GrafanaNode._unregister_external_webhook(
                credential=credential, config={"external_webhook_id": "cp"}, node_id="test")


def test_grafana_timestamped_hmac_signature(alert_notification):
    body = json.dumps(alert_notification).encode()
    secret = "test-grafana-signing-secret"
    def headers(timestamp):
        return {"X-Grafana-Alerting-Timestamp": timestamp,
                "X-Grafana-Alerting-Signature": hmac.new(
                    secret.encode(), timestamp.encode() + b":" + body, hashlib.sha256).hexdigest()}
    now = str(int(time.time()))
    config = {"signing_secret": secret}
    assert GrafanaNode.verify_webhook_signature(body, headers(now), config)
    assert GrafanaNode.verify_webhook_signature(body, {k.lower(): v for k, v in headers(now).items()}, config)
    assert not GrafanaNode.verify_webhook_signature(body + b" ", headers(now), config)
    assert not GrafanaNode.verify_webhook_signature(body, headers(now), {"signing_secret": "wrong"})
    assert not GrafanaNode.verify_webhook_signature(body, headers(str(int(now) - 301)), config)
    assert not GrafanaNode.verify_webhook_signature(body, headers(str(int(now) + 301)), config)
    assert not GrafanaNode.verify_webhook_signature(body, headers("invalid"), config)
    assert not GrafanaNode.verify_webhook_signature(body, {}, config)
    assert not GrafanaNode.verify_webhook_signature(body, headers(now), {})


def test_grafana_notification_filters_and_agent_turn(alert_notification):
    config = {"operation": "on_alert_notification"}
    assert GrafanaNode.filter_trigger_payload(alert_notification, config)
    assert GrafanaNode.filter_trigger_payload(alert_notification, {**config, "notification_status": "firing"})
    assert not GrafanaNode.filter_trigger_payload(alert_notification, {**config, "notification_status": "resolved"})
    assert not GrafanaNode.filter_trigger_payload(alert_notification, {"operation": "list_folders"})
    assert not GrafanaNode.filter_trigger_payload({}, config)
    output = GrafanaNode.resolve_trigger_payload(alert_notification, config)
    event = GrafanaNode.resolve_agent_event(output)
    for value in ("High memory usage", "High CPU usage", "team=blue", "organization 1",
                  "My Super Webhook", "c6eadffa33fcdf37", "https://myrunbook.com/runbook/1234",
                  "https://play.grafana.org/alerting/1afz29v7z/edit"):
        assert value in event["text"]
    assert event["conversation_key"] == "https://play.grafana.org/:1:{}:{}"


@pytest.mark.asyncio
async def test_grafana_manual_trigger_run_does_not_fabricate_an_event():
    result = await _node("on_alert_notification").execute({})
    assert result["status"] == "no_event"


def test_grafana_trigger_registration_fingerprint_and_schema():
    assert GrafanaNode.registration_fingerprint_fields({"contact_point_name": "Operations"}) == {
        "contact_point_name": "Operations"}
    op = _node("on_alert_notification").config.config
    assert op.model_json_schema()["properties"]["operation"]["x-is-trigger"] is True
    assert op.model_json_schema()["x-requires-webhook"] is True
    assert op.model_validate({**op.model_dump(), "signing_secret": "secret"}).signing_secret == "secret"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create_alert_rule", "get_alert_rule", "update_alert_rule"])
async def test_grafana_documented_alert_rule_durations_and_nullable_response(operation):
    fixture = Path(__file__).parent / "fixtures/grafana/alert-rule.json"
    documented = json.loads(fixture.read_text())
    calls = []
    def capture(request):
        calls.append(request)
        return httpx.Response(201 if operation == "create_alert_rule" else 200, json=documented)
    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    fields = {"uid": documented["uid"]} if operation != "create_alert_rule" else {}
    if operation != "get_alert_rule":
        fields["body"] = json.dumps({k: documented[k] for k in (
            "orgID", "folderUID", "ruleGroup", "title", "condition", "data", "noDataState", "execErrState", "for")})
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await _node(operation, **fields).execute({})
    assert result["data"] == documented
    assert result["data"]["for"] == "5m"
    assert result["data"]["notification_settings"] is None
    assert result["data"]["record"] is None
    if operation != "get_alert_rule":
        assert json.loads(calls[0].content)["for"] == "5m"


@pytest.mark.asyncio
async def test_grafana_preserves_documented_nullable_data_source_json():
    documented = json.loads((Path(__file__).parent / "fixtures/grafana/update-data-source.json").read_text())
    calls = []
    def capture(request):
        calls.append(request)
        return httpx.Response(200, json={"message": "Datasource updated"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await _node("update_data_source", uid="kLtEtcRGk", body=json.dumps(documented)).execute({})
    assert result["status"] == "success"
    assert json.loads(calls[0].content) == documented
    assert documented["jsonData"] is None


def _fields_for(spec):
    result = {}
    for parameter in spec["parameters"]:
        if parameter["location"] == "path" or parameter["required"]:
            result[parameter["field"]] = (
                42 if parameter["type"] == "integer" else "resource uid"
            )
    if spec["name"] == "move_folder":
        result["parent_uid"] = "d80b18c0-266a-4aa4-ad5d-5537a00cb8e8"
    elif spec["body_required"]:
        result["body"] = '{"title":"QA","uid":"qa"}'
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", OPERATIONS, ids=lambda spec: spec["name"])
async def test_every_grafana_operation_uses_expected_method_route_and_auth(spec):
    calls = []

    def capture(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    node = _node(spec["name"], **_fields_for(spec))
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == spec["name"]
    assert result["data"] == {"ok": True}
    request = calls[0]
    assert request.method == spec["method"]
    assert request.url.host == "example.grafana.net"
    assert request.url.path.startswith("/api/")
    assert "{" not in request.url.path
    assert request.headers["Authorization"] == "Bearer grafana-qa-token"
    if spec["name"] == "move_folder":
        assert json.loads(request.content) == {"parentUid": "d80b18c0-266a-4aa4-ad5d-5537a00cb8e8"}
    elif spec["body_required"]:
        assert json.loads(request.content) == {"title": "QA", "uid": "qa"}
    else:
        assert not request.content


def test_catalog_and_schema_have_one_config_per_operation():
    assert len(OPERATIONS) == 62
    assert len(_MODELS) == len(OPERATIONS)
    assert len({spec["name"] for spec in OPERATIONS}) == len(OPERATIONS)
    schema = GrafanaNode.get_config_schema()
    assert schema["properties"]["credentials"]
    assert len(schema["properties"]["config"]["oneOf"]) == len(OPERATIONS) + 1


@pytest.mark.asyncio
async def test_path_is_encoded_and_query_array_repeats():
    captured = []

    def capture(request):
        captured.append(request)
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    node = _node("get_dashboard", uid="folder/secret")
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        await node.execute({})
    assert captured[0].url.raw_path == b"/api/dashboards/uid/folder%2Fsecret"

    captured.clear()
    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    node = _node("search_dashboards", tag="prod, api", limit=10)
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await node.execute({})
    assert captured[0].url.params.get_list("tag") == ["prod", "api"]
    assert captured[0].url.params["limit"] == "10"
    assert result["data"] == {"items": [], "count": 0}


@pytest.mark.asyncio
async def test_bad_json_does_not_send_request():
    node = _node("save_dashboard", body="{bad")
    with pytest.raises(ValueError, match="valid JSON"):
        await node.execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("code,message", [(401, "Unauthorized"), (403, "Forbidden"), (404, "Not found")])
async def test_provider_errors_are_visible(code, message):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(code, json={"message": message})
        )
    )
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await _node("list_folders").execute({})
    assert result["status"] == "error"
    assert result["status_code"] == code
    assert result["error"] == message


@pytest.mark.asyncio
async def test_empty_delete_response():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(204))
    )
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await _node("delete_folder", folder_uid="qa").execute({})
    assert result["status"] == "success"
    assert result["status_code"] == 204
    assert result["data"] == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.google.internal",
        "https://example.grafana.net/evil",
        "https://example.grafana.net?token=bad",
        "https://user:pass@example.grafana.net",
    ],
)
def test_credential_origin_rejects_unsafe_forms(url):
    with pytest.raises(ValueError):
        _origin(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [{}, {"parent_uid": ""}])
async def test_move_folder_can_move_under_root(fields):
    captured = []

    def capture(request):
        captured.append(request)
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    node = _node("move_folder", folder_uid="a5393ec3-5568-4e88-8809-b866968ae8a6", **fields)
    with patch("nodes.grafana_node.guarded_async_client", return_value=client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert captured[0].url.path == "/api/folders/a5393ec3-5568-4e88-8809-b866968ae8a6/move"
    assert json.loads(captured[0].content) == {"parentUid": ""}


def test_move_folder_parent_uid_rejects_non_string():
    with pytest.raises(ValueError, match="parent_uid"):
        _node("move_folder", folder_uid="a5393ec3-5568-4e88-8809-b866968ae8a6", parent_uid={"invalid": True})

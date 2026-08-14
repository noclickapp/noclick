"""`respond: last_node` HTTP response contract.

Before the contract, the terminal node's raw execution envelope WAS the
response body — a "REST API" returned {"type": "serverless_function",
"result": {"status": 200, "body": {"sum": 12}}, "stdout": "", ...} and an
HTML page served as escaped JSON (2026-08-14). These tests pin the shaping:
{status[, headers][, body]} from the terminal node (unwrapping the serverless
envelope) becomes a real HTTP response; everything else keeps the raw dump.
"""

import json

import pytest

from utils.webhook_routes import (
    _response_from_execution_result,
    _response_to_relay_payload,
    _shaped_response_from_output,
)
from wss.handlers.workflow_execution_handler import WorkflowExecutionResult


def _serverless_envelope(result):
    return {
        "type": "serverless_function",
        "status": "completed",
        "runtime": "javascript",
        "result": result,
        "stdout": "",
        "stderr": "",
        "error": None,
        "exit_code": 0,
        "execution_time_ms": 0.5,
    }


def test_contract_dict_becomes_json_body():
    resp = _shaped_response_from_output({"status": 200, "body": {"sum": 12}})
    assert resp is not None
    assert resp.status_code == 200
    assert json.loads(resp.body) == {"sum": 12}
    assert resp.headers["content-type"].startswith("application/json")


def test_serverless_envelope_unwraps_to_contract():
    # The REST-API case: the function returned {status, body} and the caller
    # got the whole envelope instead.
    resp = _shaped_response_from_output(
        _serverless_envelope({"status": 200, "body": {"sum": 12}})
    )
    assert resp is not None
    assert json.loads(resp.body) == {"sum": 12}


def test_serverless_bare_string_serves_as_html_page():
    html = "<!DOCTYPE html><html><body>calc</body></html>"
    resp = _shaped_response_from_output(_serverless_envelope(html))
    assert resp is not None
    assert resp.status_code == 200
    assert resp.body.decode() == html
    assert resp.headers["content-type"].startswith("text/html")


def test_explicit_content_type_header_wins():
    resp = _shaped_response_from_output(
        {"status": 201, "headers": {"Content-Type": "text/plain"}, "body": "ok"}
    )
    assert resp.status_code == 201
    assert resp.body.decode() == "ok"
    assert resp.headers["content-type"] == "text/plain"


def test_bodyless_status_with_headers_supports_redirects():
    resp = _shaped_response_from_output(
        {"status": 302, "headers": {"Location": "https://example.com"}}
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com"


@pytest.mark.parametrize(
    "output",
    [
        {"summary": "not a response"},                      # arbitrary dict
        {"status": "completed", "body": {}},                # non-int status
        {"status": True, "body": {}},                       # bool is not a status
        {"status": 200, "body": {}, "extra": 1},            # foreign key
        {"status": 9000, "body": {}},                       # out-of-range
        {"status": 200, "headers": "nope"},                 # malformed headers
        ["a", "b"],                                        # non-dict
        "bare top-level string",                            # only serverless unwrap serves strings
    ],
)
def test_non_contract_outputs_fall_through(output):
    assert _shaped_response_from_output(output) is None


def test_non_contract_serverless_result_keeps_envelope():
    # Existing consumers of arbitrary serverless outputs keep today's shape.
    assert _shaped_response_from_output(_serverless_envelope({"foo": 1})) is None


def _execution_result(output):
    return WorkflowExecutionResult(
        execution_id="ex-1",
        workflow_id="wf-1",
        success=True,
        nodes_executed=2,
        duration=0.1,
        error=None,
        node_outputs={"sum": output},
        last_output_node_id="sum",
    )


_LAST_NODE_TRIGGER = {"config": {"respond": "last_node"}}


def test_execution_result_serves_shaped_response():
    resp = _response_from_execution_result(
        _LAST_NODE_TRIGGER,
        _execution_result(_serverless_envelope({"status": 200, "body": {"sum": 12}})),
    )
    assert json.loads(resp.body) == {"sum": 12}


def test_execution_result_falls_back_to_raw_dump():
    envelope = _serverless_envelope({"foo": 1})
    resp = _response_from_execution_result(_LAST_NODE_TRIGGER, _execution_result(envelope))
    assert json.loads(resp.body) == envelope


def test_relay_payload_carries_shaped_html():
    # The *.hooks.example.test path serves through the Cloudflare relay — the shaped
    # response must survive _response_to_relay_payload with its content-type.
    html = "<!DOCTYPE html><html><body>calc</body></html>"
    resp = _response_from_execution_result(
        _LAST_NODE_TRIGGER, _execution_result(_serverless_envelope(html))
    )
    payload = _response_to_relay_payload(resp)
    assert payload["status"] == 200
    assert payload["body"] == html
    assert payload["headers"]["content-type"].startswith("text/html")

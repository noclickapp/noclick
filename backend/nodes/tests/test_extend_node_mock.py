"""
Contract tests for the Extend (extend.ai) node — full modern API surface.

Every operation is exercised through the node and the outgoing HTTP request it
builds (method, path, query params, JSON body) is captured and asserted against
the authoritative OpenAPI contract (api version 2026-02-09). No live calls.

Also covers: multipart file upload, webhook trigger register/deregister, native
Extend signature verification, dynamic-options dropdowns, and error handling.
"""

import hashlib
import hmac

import pytest
from unittest.mock import Mock, patch, AsyncMock

from nodes import extend_node as E
from nodes.extend_node import ExtendNode, ExtendNodeConfig, ExtendApiKeyCredential


# ── harness ──────────────────────────────────────────────────────────────────


def make_node(config):
    return ExtendNode(
        node_id="test-extend-node", node_type="automation-extend", node_data={},
        config=config, sio=Mock(), sid="sid", workflow_id="wf", user_id="user",
    )


def _cred():
    return ExtendApiKeyCredential(api_key="extend_test_key", workspace_id=None)


class Capture:
    """Replaces _extend_request to record the outgoing request and return success."""

    def __init__(self):
        self.calls = []

    async def __call__(self, api_key, method, endpoint, workspace_id=None, params=None,
                       json_body=None, action_name="request"):
        # mirror the real None-stripping so assertions see the wire shape
        body = {k: v for k, v in (json_body or {}).items() if v is not None} if json_body else json_body
        prm = {k: v for k, v in (params or {}).items() if v not in (None, "")} if params else params
        self.calls.append({"method": method, "endpoint": endpoint, "params": prm,
                           "body": body, "action": action_name})
        return {"status": "success", "action": action_name, "data": {"id": "result_1"}, "status_code": 200}


async def run_op(config_obj):
    cap = Capture()
    node = make_node(ExtendNodeConfig(config=config_obj, credentials=_cred()))
    with patch("nodes.extend_node._extend_request", cap):
        result = await node.execute({})
    assert result["status"] == "success"
    return cap.calls[-1]


# ── per-operation contract cases ─────────────────────────────────────────────
# (config class, kwargs, METHOD, path, body-subset, params-subset)

CASES = [
    # Files
    (E.ExtendGetFileConfig, dict(file_id="f1", raw_text="true", markdown="true"), "GET", "/files/f1", None, {"rawText": "true", "markdown": "true"}),
    (E.ExtendListFilesConfig, dict(name_contains="inv", max_page_size="10"), "GET", "/files", None, {"nameContains": "inv", "maxPageSize": "10"}),
    (E.ExtendDeleteFileConfig, dict(file_id="f1"), "DELETE", "/files/f1", None, None),
    # Sync
    (E.ExtendParseSyncConfig, dict(file_id="f1"), "POST", "/parse", {"file": {"id": "f1"}}, None),
    (E.ExtendParseSyncConfig, dict(file_url="https://x/y.pdf"), "POST", "/parse", {"file": {"url": "https://x/y.pdf"}}, None),
    (E.ExtendExtractSyncConfig, dict(extractor_id="ex1", file_id="f1"), "POST", "/extract", {"extractor": {"id": "ex1"}, "file": {"id": "f1"}}, None),
    (E.ExtendClassifySyncConfig, dict(classifier_id="cl1", file_id="f1"), "POST", "/classify", {"classifier": {"id": "cl1"}, "file": {"id": "f1"}}, None),
    (E.ExtendSplitSyncConfig, dict(splitter_id="sp1", file_id="f1"), "POST", "/split", {"splitter": {"id": "sp1"}, "file": {"id": "f1"}}, None),
    (E.ExtendEditSyncConfig, dict(file_id="f1"), "POST", "/edit", {"file": {"id": "f1"}}, None),
    # Parse runs
    (E.ExtendCreateParseRunConfig, dict(file_id="f1"), "POST", "/parse_runs", {"file": {"id": "f1"}}, None),
    (E.ExtendGetParseRunConfig, dict(run_id="r1", response_type="raw"), "GET", "/parse_runs/r1", None, {"responseType": "raw"}),
    (E.ExtendListParseRunsConfig, dict(status="PROCESSED"), "GET", "/parse_runs", None, {"status": "PROCESSED"}),
    (E.ExtendCancelParseRunConfig, dict(run_id="r1"), "POST", "/parse_runs/r1/cancel", None, None),
    (E.ExtendDeleteParseRunConfig, dict(run_id="r1"), "DELETE", "/parse_runs/r1", None, None),
    (E.ExtendBatchParseRunsConfig, dict(inputs='[{"file":{"id":"f1"}}]'), "POST", "/parse_runs/batch", {"inputs": [{"file": {"id": "f1"}}]}, None),
    # Extract runs
    (E.ExtendCreateExtractRunConfig, dict(extractor_id="ex1", file_id="f1"), "POST", "/extract_runs", {"extractor": {"id": "ex1"}, "file": {"id": "f1"}}, None),
    (E.ExtendGetExtractRunConfig, dict(run_id="r1"), "GET", "/extract_runs/r1", None, None),
    (E.ExtendListExtractRunsConfig, dict(extractor_id="ex1"), "GET", "/extract_runs", None, {"extractorId": "ex1"}),
    (E.ExtendCancelExtractRunConfig, dict(run_id="r1"), "POST", "/extract_runs/r1/cancel", None, None),
    (E.ExtendDeleteExtractRunConfig, dict(run_id="r1"), "DELETE", "/extract_runs/r1", None, None),
    (E.ExtendBatchExtractRunsConfig, dict(extractor_id="ex1", inputs='[{"file":{"id":"f1"}}]'), "POST", "/extract_runs/batch", {"extractor": {"id": "ex1"}, "inputs": [{"file": {"id": "f1"}}]}, None),
    # Extractors
    (E.ExtendCreateExtractorConfig, dict(name="Inv", config='{"schema":{}}'), "POST", "/extractors", {"name": "Inv", "config": {"schema": {}}}, None),
    (E.ExtendGetExtractorConfig, dict(extractor_id="ex1"), "GET", "/extractors/ex1", None, None),
    (E.ExtendUpdateExtractorConfig, dict(extractor_id="ex1", name="Inv2"), "POST", "/extractors/ex1", {"name": "Inv2"}, None),
    (E.ExtendListExtractorsConfig, dict(), "GET", "/extractors", None, None),
    (E.ExtendCreateExtractorVersionConfig, dict(extractor_id="ex1", release_type="minor"), "POST", "/extractors/ex1/versions", {"releaseType": "minor"}, None),
    (E.ExtendListExtractorVersionsConfig, dict(extractor_id="ex1"), "GET", "/extractors/ex1/versions", None, None),
    (E.ExtendGetExtractorVersionConfig, dict(extractor_id="ex1", version_id="v1"), "GET", "/extractors/ex1/versions/v1", None, None),
    # Classify runs
    (E.ExtendCreateClassifyRunConfig, dict(classifier_id="cl1", file_id="f1"), "POST", "/classify_runs", {"classifier": {"id": "cl1"}, "file": {"id": "f1"}}, None),
    (E.ExtendGetClassifyRunConfig, dict(run_id="r1"), "GET", "/classify_runs/r1", None, None),
    (E.ExtendListClassifyRunsConfig, dict(classifier_id="cl1"), "GET", "/classify_runs", None, {"classifierId": "cl1"}),
    (E.ExtendCancelClassifyRunConfig, dict(run_id="r1"), "POST", "/classify_runs/r1/cancel", None, None),
    (E.ExtendDeleteClassifyRunConfig, dict(run_id="r1"), "DELETE", "/classify_runs/r1", None, None),
    (E.ExtendBatchClassifyRunsConfig, dict(classifier_id="cl1", inputs='[]'), "POST", "/classify_runs/batch", {"classifier": {"id": "cl1"}, "inputs": []}, None),
    # Classifiers
    (E.ExtendCreateClassifierConfig, dict(name="Doc"), "POST", "/classifiers", {"name": "Doc"}, None),
    (E.ExtendGetClassifierConfig, dict(classifier_id="cl1"), "GET", "/classifiers/cl1", None, None),
    (E.ExtendUpdateClassifierConfig, dict(classifier_id="cl1", name="Doc2"), "POST", "/classifiers/cl1", {"name": "Doc2"}, None),
    (E.ExtendListClassifiersConfig, dict(), "GET", "/classifiers", None, None),
    (E.ExtendCreateClassifierVersionConfig, dict(classifier_id="cl1", release_type="major"), "POST", "/classifiers/cl1/versions", {"releaseType": "major"}, None),
    (E.ExtendListClassifierVersionsConfig, dict(classifier_id="cl1"), "GET", "/classifiers/cl1/versions", None, None),
    (E.ExtendGetClassifierVersionConfig, dict(classifier_id="cl1", version_id="v1"), "GET", "/classifiers/cl1/versions/v1", None, None),
    # Split runs
    (E.ExtendCreateSplitRunConfig, dict(splitter_id="sp1", file_id="f1"), "POST", "/split_runs", {"splitter": {"id": "sp1"}, "file": {"id": "f1"}}, None),
    (E.ExtendGetSplitRunConfig, dict(run_id="r1"), "GET", "/split_runs/r1", None, None),
    (E.ExtendListSplitRunsConfig, dict(splitter_id="sp1"), "GET", "/split_runs", None, {"splitterId": "sp1"}),
    (E.ExtendCancelSplitRunConfig, dict(run_id="r1"), "POST", "/split_runs/r1/cancel", None, None),
    (E.ExtendDeleteSplitRunConfig, dict(run_id="r1"), "DELETE", "/split_runs/r1", None, None),
    (E.ExtendBatchSplitRunsConfig, dict(splitter_id="sp1", inputs='[]'), "POST", "/split_runs/batch", {"splitter": {"id": "sp1"}, "inputs": []}, None),
    # Splitters
    (E.ExtendCreateSplitterConfig, dict(name="Split"), "POST", "/splitters", {"name": "Split"}, None),
    (E.ExtendGetSplitterConfig, dict(splitter_id="sp1"), "GET", "/splitters/sp1", None, None),
    (E.ExtendUpdateSplitterConfig, dict(splitter_id="sp1", name="S2"), "POST", "/splitters/sp1", {"name": "S2"}, None),
    (E.ExtendListSplittersConfig, dict(), "GET", "/splitters", None, None),
    (E.ExtendCreateSplitterVersionConfig, dict(splitter_id="sp1", release_type="patch"), "POST", "/splitters/sp1/versions", {"releaseType": "patch"}, None),
    (E.ExtendListSplitterVersionsConfig, dict(splitter_id="sp1"), "GET", "/splitters/sp1/versions", None, None),
    (E.ExtendGetSplitterVersionConfig, dict(splitter_id="sp1", version_id="v1"), "GET", "/splitters/sp1/versions/v1", None, None),
    # Edit
    (E.ExtendCreateEditRunConfig, dict(file_id="f1", config='{"instructions":"redact"}'), "POST", "/edit_runs", {"file": {"id": "f1"}, "config": {"instructions": "redact"}}, None),
    (E.ExtendGetEditRunConfig, dict(run_id="r1"), "GET", "/edit_runs/r1", None, None),
    (E.ExtendDeleteEditRunConfig, dict(run_id="r1"), "DELETE", "/edit_runs/r1", None, None),
    (E.ExtendGenerateEditSchemaConfig, dict(file_id="f1"), "POST", "/edit_schemas/generate", {"file": {"id": "f1"}}, None),
    (E.ExtendGetEditTemplateConfig, dict(template_id="t1"), "GET", "/edit_templates/t1", None, None),
    # Workflows
    (E.ExtendCreateWorkflowConfig, dict(name="WF", steps='[]'), "POST", "/workflows", {"name": "WF", "steps": []}, None),
    (E.ExtendGetWorkflowConfig, dict(workflow_id="wf1"), "GET", "/workflows/wf1", None, None),
    (E.ExtendUpdateWorkflowConfig, dict(workflow_id="wf1", name="WF2"), "POST", "/workflows/wf1", {"name": "WF2"}, None),
    (E.ExtendListWorkflowsConfig, dict(), "GET", "/workflows", None, None),
    (E.ExtendCreateWorkflowVersionConfig, dict(workflow_id="wf1", name="v"), "POST", "/workflows/wf1/versions", {"name": "v"}, None),
    (E.ExtendListWorkflowVersionsConfig, dict(workflow_id="wf1"), "GET", "/workflows/wf1/versions", None, None),
    (E.ExtendGetWorkflowVersionConfig, dict(workflow_id="wf1", version_id="v1"), "GET", "/workflows/wf1/versions/v1", None, None),
    # Workflow runs
    (E.ExtendCreateWorkflowRunConfig, dict(workflow_id="wf1", file_id="f1"), "POST", "/workflow_runs", {"workflow": {"id": "wf1"}, "file": {"id": "f1"}}, None),
    (E.ExtendCreateWorkflowRunConfig, dict(workflow_id="wf1", file_id="f1", version="draft"), "POST", "/workflow_runs", {"workflow": {"id": "wf1", "version": "draft"}, "file": {"id": "f1"}}, None),
    (E.ExtendGetWorkflowRunConfig, dict(run_id="r1"), "GET", "/workflow_runs/r1", None, None),
    (E.ExtendListWorkflowRunsConfig, dict(workflow_id="wf1"), "GET", "/workflow_runs", None, {"workflowId": "wf1"}),
    (E.ExtendUpdateWorkflowRunConfig, dict(run_id="r1", name="n"), "POST", "/workflow_runs/r1", {"name": "n"}, None),
    (E.ExtendCancelWorkflowRunConfig, dict(run_id="r1"), "POST", "/workflow_runs/r1/cancel", None, None),
    (E.ExtendDeleteWorkflowRunConfig, dict(run_id="r1"), "DELETE", "/workflow_runs/r1", None, None),
    (E.ExtendBatchWorkflowRunsConfig, dict(workflow_id="wf1", inputs='[]'), "POST", "/workflow_runs/batch", {"workflow": {"id": "wf1"}, "inputs": []}, None),
    # Webhook endpoints
    (E.ExtendCreateWebhookEndpointConfig, dict(url="https://x", name="n", enabled_events='["workflow_run.completed"]'), "POST", "/webhook_endpoints", {"url": "https://x", "name": "n", "apiVersion": E.EXTEND_API_VERSION, "enabledEvents": ["workflow_run.completed"]}, None),
    (E.ExtendListWebhookEndpointsConfig, dict(), "GET", "/webhook_endpoints", None, None),
    (E.ExtendGetWebhookEndpointConfig, dict(endpoint_id="we1"), "GET", "/webhook_endpoints/we1", None, None),
    (E.ExtendUpdateWebhookEndpointConfig, dict(endpoint_id="we1", name="n2"), "POST", "/webhook_endpoints/we1", {"name": "n2"}, None),
    (E.ExtendDeleteWebhookEndpointConfig, dict(endpoint_id="we1"), "DELETE", "/webhook_endpoints/we1", None, None),
    # Webhook subscriptions
    (E.ExtendCreateWebhookSubscriptionConfig, dict(webhook_endpoint_id="we1", resource_type="workflow", resource_id="wf1", enabled_events='["workflow_run.completed"]'), "POST", "/webhook_subscriptions", {"webhookEndpointId": "we1", "resourceType": "workflow", "resourceId": "wf1", "enabledEvents": ["workflow_run.completed"]}, None),
    (E.ExtendListWebhookSubscriptionsConfig, dict(webhook_endpoint_id="we1"), "GET", "/webhook_subscriptions", None, {"webhookEndpointId": "we1"}),
    (E.ExtendGetWebhookSubscriptionConfig, dict(subscription_id="ws1"), "GET", "/webhook_subscriptions/ws1", None, None),
    (E.ExtendUpdateWebhookSubscriptionConfig, dict(subscription_id="ws1", enabled_events='["parse_run.processed"]'), "POST", "/webhook_subscriptions/ws1", {"enabledEvents": ["parse_run.processed"]}, None),
    (E.ExtendDeleteWebhookSubscriptionConfig, dict(subscription_id="ws1"), "DELETE", "/webhook_subscriptions/ws1", None, None),
    # Evaluation
    (E.ExtendCreateEvaluationSetConfig, dict(name="Eval", entity_id="ex1"), "POST", "/evaluation_sets", {"name": "Eval", "entityId": "ex1"}, None),
    (E.ExtendListEvaluationSetsConfig, dict(entity_id="ex1"), "GET", "/evaluation_sets", None, {"entityId": "ex1"}),
    (E.ExtendGetEvaluationSetConfig, dict(evaluation_set_id="es1"), "GET", "/evaluation_sets/es1", None, None),
    (E.ExtendCreateEvaluationSetItemsConfig, dict(evaluation_set_id="es1", items='[]'), "POST", "/evaluation_sets/es1/items", {"items": []}, None),
    (E.ExtendListEvaluationSetItemsConfig, dict(evaluation_set_id="es1"), "GET", "/evaluation_sets/es1/items", None, None),
    (E.ExtendGetEvaluationSetItemConfig, dict(evaluation_set_id="es1", item_id="it1"), "GET", "/evaluation_sets/es1/items/it1", None, None),
    (E.ExtendUpdateEvaluationSetItemConfig, dict(evaluation_set_id="es1", item_id="it1", expected_output='{"total":9}'), "POST", "/evaluation_sets/es1/items/it1", {"expectedOutput": {"total": 9}}, None),
    (E.ExtendDeleteEvaluationSetItemConfig, dict(evaluation_set_id="es1", item_id="it1"), "DELETE", "/evaluation_sets/es1/items/it1", None, None),
    (E.ExtendCreateEvaluationSetRunConfig, dict(evaluation_set_id="es1"), "POST", "/evaluation_set_runs", {"evaluationSetId": "es1"}, None),
    (E.ExtendGetEvaluationSetRunConfig, dict(run_id="r1"), "GET", "/evaluation_set_runs/r1", None, None),
    # Batch status
    (E.ExtendGetBatchRunConfig, dict(batch_id="b1"), "GET", "/batch_runs/b1", None, None),
    (E.ExtendGetBatchProcessorRunConfig, dict(batch_id="b1"), "GET", "/batch_processor_runs/b1", None, None),
]


@pytest.mark.parametrize("cls,kw,method,path,body,params", CASES,
                         ids=[c[0].__name__ for c in CASES])
@pytest.mark.asyncio
async def test_operation_contract(cls, kw, method, path, body, params):
    call = await run_op(cls(**kw))
    assert call["method"] == method, f"method for {cls.__name__}"
    assert call["endpoint"] == path, f"path for {cls.__name__}"
    if body is not None:
        for k, v in body.items():
            assert call["body"].get(k) == v, f"body[{k}] for {cls.__name__}: {call['body']}"
    if params is not None:
        for k, v in params.items():
            assert (call["params"] or {}).get(k) == v, f"params[{k}] for {cls.__name__}: {call['params']}"


def test_every_operation_has_a_case():
    """Guard: every non-trigger operation is covered by a contract case."""
    import typing
    members = typing.get_args(typing.get_args(E.ExtendConfig)[0])
    all_ops = {typing.get_args(m.model_fields["operation"].annotation)[0] for m in members}
    covered = {c[0].model_fields["operation"].default for c in CASES}
    covered.add("upload_file")        # dedicated multipart test below
    covered.add("on_run_completed")   # dedicated trigger test below
    missing = all_ops - covered
    assert not missing, f"operations without a test: {sorted(missing)}"


# ── headers / auth ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_headers_include_version_and_workspace():
    captured = {}

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"data": {"ok": True}}

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, method, url, headers=None, params=None, json=None):
            captured.update(headers or {})
            return _Resp()

    cred = ExtendApiKeyCredential(api_key="k", workspace_id="ws_123")
    node = make_node(ExtendNodeConfig(config=E.ExtendListFilesConfig(), credentials=cred))
    with patch("nodes.extend_node.httpx.AsyncClient", _Client):
        await node.execute({})
    assert captured["Authorization"] == "Bearer k"
    assert captured["x-extend-api-version"] == E.EXTEND_API_VERSION
    assert captured["X-Extend-Workspace-Id"] == "ws_123"


# ── multipart upload ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_file_multipart_downloads_then_posts():
    posted = {}

    class _DL:
        status_code = 200
        content = b"PDFBYTES"
        def raise_for_status(self):
            return None

    class _Resp:
        status_code = 200
        text = ""
        def json(self):
            return {"data": {"id": "file_1", "name": "doc.pdf"}}

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, follow_redirects=True, timeout=None):
            posted["downloaded"] = url
            return _DL()
        async def post(self, url, headers=None, params=None, data=None, files=None):
            posted["url"] = url
            posted["files"] = files
            posted["headers"] = headers
            return _Resp()

    cfg = E.ExtendUploadFileConfig(file_url="https://x/doc.pdf", file_name="doc.pdf")
    node = make_node(ExtendNodeConfig(config=cfg, credentials=_cred()))
    with patch("nodes.extend_node.httpx.AsyncClient", _Client):
        result = await node.execute({})
    assert result["status"] == "success"
    assert result["data"]["id"] == "file_1"
    assert posted["downloaded"] == "https://x/doc.pdf"
    assert posted["url"].endswith("/files/upload")
    assert posted["files"]["file"][0] == "doc.pdf"
    assert posted["files"]["file"][1] == b"PDFBYTES"
    # multipart: Content-Type must NOT be forced to application/json
    assert "Content-Type" not in posted["headers"]


# ── trigger ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_passthrough():
    cfg = E.ExtendRunCompletedTriggerConfig(webhook_url="https://abc.hooks.example.test")
    node = make_node(ExtendNodeConfig(config=cfg, credentials=None))
    payload = {"eventType": "workflow_run.completed", "payload": {"id": "wr_x"}}
    result = await node.execute(payload)
    assert result["status"] == "success"
    assert result["action"] == "on_run_completed"
    assert result["data"]["eventType"] == "workflow_run.completed"
    assert result["data"]["webhook_url"] == "https://abc.hooks.example.test"


@pytest.mark.asyncio
async def test_register_external_webhook_uses_correct_body():
    captured = {}

    async def fake_req(api_key, method, endpoint, workspace_id=None, params=None, json_body=None, action_name="request"):
        captured.update({"method": method, "endpoint": endpoint, "body": json_body})
        return {"status": "success", "data": {"id": "we_99", "signingSecret": "whsec_abc"}}

    with patch("nodes.extend_node._extend_request", fake_req):
        extra = await ExtendNode._register_external_webhook(
            webhook_url="https://abc.hooks.example.test", credential={"api_key": "k"},
            config={}, node_id="node-1")
    assert captured["method"] == "POST"
    assert captured["endpoint"] == "/webhook_endpoints"
    assert captured["body"]["enabledEvents"] == E.RUN_COMPLETED_EVENTS
    assert captured["body"]["apiVersion"] == E.EXTEND_API_VERSION
    assert "name" in captured["body"]
    assert extra["external_webhook_id"] == "we_99"
    assert extra["signing_secret"] == "whsec_abc"


@pytest.mark.asyncio
async def test_register_replaces_stale_endpoint():
    calls = []

    async def fake_req(api_key, method, endpoint, workspace_id=None, params=None, json_body=None, action_name="request"):
        calls.append((method, endpoint))
        return {"status": "success", "data": {"id": "we_new", "signingSecret": "s"}}

    with patch("nodes.extend_node._extend_request", fake_req):
        await ExtendNode._register_external_webhook(
            webhook_url="https://x", credential={"api_key": "k"},
            config={"external_webhook_id": "we_old"}, node_id="n")
    assert ("DELETE", "/webhook_endpoints/we_old") in calls
    assert ("POST", "/webhook_endpoints") in calls


@pytest.mark.asyncio
async def test_unregister_external_webhook():
    calls = []

    async def fake_req(api_key, method, endpoint, workspace_id=None, params=None, json_body=None, action_name="request"):
        calls.append((method, endpoint))
        return {"status": "success", "data": {}}

    with patch("nodes.extend_node._extend_request", fake_req):
        await ExtendNode._unregister_external_webhook(
            credential={"api_key": "k"}, config={"external_webhook_id": "we_9"}, node_id="n")
    assert ("DELETE", "/webhook_endpoints/we_9") in calls


def test_verify_webhook_signature_native_scheme():
    secret = "whsec_extend_secret"
    body = b'{"eventType":"workflow_run.completed"}'
    ts = "1700000000"
    good = hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    cfg = {"signing_secret": secret}
    headers = {"x-extend-request-timestamp": ts, "x-extend-request-signature": good}
    assert ExtendNode.verify_webhook_signature(body, headers, cfg)
    # tamper rejected
    bad = {"x-extend-request-timestamp": ts, "x-extend-request-signature": "deadbeef"}
    assert not ExtendNode.verify_webhook_signature(body, bad, cfg)
    # tampered body rejected
    assert not ExtendNode.verify_webhook_signature(body + b"x", headers, cfg)
    # missing headers rejected
    assert not ExtendNode.verify_webhook_signature(body, {}, cfg)
    # no secret stored -> accept (not yet armed)
    assert ExtendNode.verify_webhook_signature(body, {}, {})


# ── dynamic options ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("field,endpoint", [
    ("extractor_id", "/extractors"), ("classifier_id", "/classifiers"),
    ("splitter_id", "/splitters"), ("workflow_id", "/workflows"),
])
@pytest.mark.asyncio
async def test_dynamic_options(field, endpoint):
    seen = {}

    async def fake_req(api_key, method, ep, workspace_id=None, params=None, json_body=None, action_name="request"):
        seen["endpoint"] = ep
        seen["params"] = params
        return {"status": "success", "data": [{"id": "x1", "name": "First"}]}

    with patch("nodes.extend_node._extend_request", fake_req):
        res = await ExtendNode.load_field_options(
            field,
            {"api_key": "k"},
            page_token="cursor-1",
            search="first",
        )
    assert seen["endpoint"] == endpoint
    assert seen["params"] == {"maxPageSize": "100", "pageToken": "cursor-1"}
    assert res["options"][0] == {"label": "First", "value": "x1"}
    assert res["next_page_token"] is None


@pytest.mark.asyncio
async def test_dynamic_options_unknown_field_returns_empty():
    res = await ExtendNode.load_field_options("nope", {"api_key": "k"})
    assert res == {"options": [], "next_page_token": None}


@pytest.mark.asyncio
async def test_dynamic_options_without_credential_returns_empty():
    res = await ExtendNode.load_field_options("workflow_id", {})
    assert res == {"options": [], "next_page_token": None}


# ── error handling ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_error_surfaced():
    class _Resp:
        status_code = 404
        text = ""
        def json(self):
            return {"error": {"message": "File not found"}}

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, method, url, headers=None, params=None, json=None):
            return _Resp()

    node = make_node(ExtendNodeConfig(config=E.ExtendGetFileConfig(file_id="missing"), credentials=_cred()))
    with patch("nodes.extend_node.httpx.AsyncClient", _Client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert result["status_code"] == 404
    assert "not found" in str(result["error"]).lower()


@pytest.mark.asyncio
async def test_extend_top_level_error_shape_surfaced():
    """Extend returns errors as {code, message, requestId} at the top level (not
    nested under 'error'). The message + requestId must reach the caller."""
    class _Resp:
        status_code = 400
        text = ""
        def json(self):
            return {"code": "INVALID_REQUEST", "message": "Invalid event types for global",
                    "requestId": "apireq_123", "retryable": False}

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def request(self, method, url, headers=None, params=None, json=None):
            return _Resp()

    node = make_node(ExtendNodeConfig(config=E.ExtendListFilesConfig(), credentials=_cred()))
    with patch("nodes.extend_node.httpx.AsyncClient", _Client):
        result = await node.execute({})
    assert result["status"] == "error"
    assert "Invalid event types" in result["error"]
    assert "apireq_123" in result["error"]  # requestId appended for debuggability


def test_trigger_events_are_valid_global_endpoint_events():
    """Global webhook endpoints reject workflow_run.* events (verified live);
    RUN_COMPLETED_EVENTS must only contain valid global run-completion events."""
    assert "workflow_run.completed" not in E.RUN_COMPLETED_EVENTS
    assert "workflow_run.failed" not in E.RUN_COMPLETED_EVENTS
    assert "parse_run.processed" in E.RUN_COMPLETED_EVENTS
    assert all(ev.endswith(".processed") or ev.endswith(".failed") for ev in E.RUN_COMPLETED_EVENTS)


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    node = make_node(ExtendNodeConfig(config=E.ExtendListFilesConfig(), credentials=None))
    with pytest.raises(ValueError, match="Credentials are required"):
        await node.execute({})

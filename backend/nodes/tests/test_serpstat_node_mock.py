"""Serpstat v4 native transport, parser and picker tests."""
import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nodes import serpstat_node as sn
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation, run_node_lookup

CREDS = {"credential_type": sn.FAMILIES[0], "api_token": "synthetic+/=token"}
STAMP = datetime(2026, 10, 6, tzinfo=timezone.utc)
STATS = {"data": {"max_lines": 1000, "used_lines": 3, "left_lines": 997,
          "user_info": {"user_id": "account-42", "ga_client_Id": "private", "plan_id": "private"},
          "plugin_limits": {"hasApiPlugin": True, "delayBetweenRequests": 1, "total": 1000, "used": 3, "left": 997}},
          "summary_info": {"left_lines": 997}}
PROJECT = {"project_id": "42", "project_name": "Owned", "domain": "example.com", "created_at": "2026-10-06T00:00:00", "type": "owner"}
RANK = {"id": "81", "projectName": "Owned rank", "domain": "example.com", "createdAt": "2026-10-06 00:00:00", "type": "owner", "status": 9, "enableTracking": True}
REPORT = {"reportId": 91, "date": "2026-10-06 00:00:00", "sdo": 80, "pagesLimit": 100, "pagesScanned": 20, "criticalCount": 1, "nonCriticalCount": 2, "virusesCount": 0, "progress": 100, "stoped": False, "hasDetailData": True}


def page(rows, current=1, pages=1, total=None):
    return {"data": rows, "summary_info": {"page": current, "page_total": pages, "count": 20, "total": len(rows) if total is None else total}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


class Response:
    def __init__(self, payload, *, status=200, raw=None, content_type="application/json"):
        self.status_code, self.headers = status, {"content-type": content_type}
        self.payload, self.raw = payload, raw
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def aiter_bytes(self, chunk_size):
        assert chunk_size == 65536
        yield self.raw if self.raw is not None else json.dumps(self.payload).encode()


@pytest.fixture
def wire(monkeypatch):
    calls, responses = [], []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            response = responses.pop(0)
            if callable(response):
                response = response(kwargs["json"]["id"])
            else:
                response = Response({"id": kwargs["json"]["id"], "result": response})
            logging.getLogger("httpx").info("HTTP Request: %s token=%s", url, kwargs["params"]["token"])
            logging.getLogger("httpcore.http2").debug("private query %s", kwargs["params"])
            return response
    def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(sn.httpx, "AsyncClient", client)
    return SimpleNamespace(calls=calls, responses=responses)


async def run(op, args=None, **context):
    return await run_node_operation(node_type=sn.NODE_TYPE, operation=op, arguments=args or {}, credential_data=CREDS, user_id="actor", **context)


def test_factory_credential_family_numeric_forms_and_method_allowlist():
    node = NodeFactory.create_node(node_id="native", node_type=sn.NODE_TYPE, user_id="actor", node_data={"config": {"operation": "list_projects", "page": "1", "size": "20"}, "credentials": CREDS})
    assert node.config.config.page == 1 and node.config.config.size == 20
    assert len(sn.SerpstatNode.get_config_schema()["properties"]["config"]["discriminator"]["mapping"]) == 20
    for family in (None, "http_bearer", "serpstat_oauth"):
        bad = {"credential_id": "saved", "config": {"operation": "test_connection"}, "credentials": {**CREDS, "credential_type": family}}
        assert sn.SerpstatNode.validate_config(bad)["valid"] is False
        with pytest.raises(ValueError, match="family"): sn.SerpstatNode.parse_config(bad)
    for cfg in ({"operation": "AuditSite.start"}, {"operation": "test_connection", "endpoint": "https://evil.test"}, {"operation": "list_projects", "page": True}, {"operation": "get_domain_overview", "domain": "https://evil.test"}, {"operation": "get_keyword_metrics", "keywords": [""]}):
        with pytest.raises(ValueError): sn.SerpstatNode.parse_config({"config": cfg, "credentials": CREDS})


@pytest.mark.asyncio
async def test_exact_query_token_wire_account_proof_closed_output_and_one_evidence_call(monkeypatch, wire, caplog):
    wire.responses.append(STATS)
    with caplog.at_level(logging.DEBUG): result = await run("test_connection")
    call = wire.calls[0]
    assert call["url"] == "https://api.serpstat.com/v4" and call["method"] == "POST"
    assert call["params"] == {"token": CREDS["api_token"]} and "Authorization" not in call["headers"]
    assert call["json"]["method"] == "SerpstatLimitsProcedure.getStats" and call["json"]["jsonrpc"] == "2.0"
    assert isinstance(call["json"]["id"], str) and "params" not in call["json"]
    assert CREDS["api_token"] not in caplog.text and "Serpstat private transport activity" in caplog.text
    assert sn._PRIVATE_REQUEST.get() is False
    assert result["data"]["account_id"] == "account-42" and result["data"]["account_identity_verified"] is True
    assert result["data"]["method_spends_api_credits"] is False and result["data"]["seo_rank_audit_permissions_verified"] is False
    assert "private" not in json.dumps(result)
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    probe = AsyncMock(return_value=result); monkeypatch.setattr(run_op, "run_node_operation", probe)
    evidence = await collect_evidence(node_type=sn.NODE_TYPE, credential_data=CREDS, user_id="actor")
    assert evidence.account_label == "account-42" and probe.await_count == 1


@pytest.mark.asyncio
async def test_log_privacy_is_context_local_and_resets_after_exception(wire, caplog):
    ready, release = asyncio.Event(), asyncio.Event()
    async def private_context():
        token = sn._PRIVATE_REQUEST.set(True)
        try:
            sn._protect_transport_logs(); ready.set(); await release.wait()
            logging.getLogger("httpx").warning("private=%s", CREDS["api_token"])
        finally: sn._PRIVATE_REQUEST.reset(token)
    with caplog.at_level(logging.DEBUG):
        task = asyncio.create_task(private_context()); await ready.wait()
        logging.getLogger("httpx").warning("unrelated concurrent transport")
        release.set(); await task
    assert "unrelated concurrent transport" in caplog.text and CREDS["api_token"] not in caplog.text
    wire.responses.append(lambda rid: Response(None, raw=b'not JSON'))
    with pytest.raises(sn.SerpstatAPIError): await run("test_connection")
    assert sn._PRIVATE_REQUEST.get() is False and len(wire.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["id", "version", "result_error", "rpc_error", "null_error", "html", "http401", "http429", "nan", "overflow", "deep", "rejected", "wrong_stats"])
async def test_unknown_rejected_and_malformed_results_never_echo_or_replay(wire, case):
    def response(rid):
        body = {"id": rid, "result": STATS}
        options = {}
        if case == "id": body["id"] = "another"
        if case == "version": body["jsonrpc"] = "1.0"
        if case == "result_error": body["error"] = {"code": -1, "message": CREDS["api_token"]}
        if case == "rpc_error": body = {"id": rid, "error": {"code": -1, "message": CREDS["api_token"], "data": {"token": CREDS["api_token"]}}}
        if case == "null_error": body["error"] = None
        if case == "html": options["content_type"] = "text/html"
        if case == "http401": options["status"] = 401
        if case == "http429": options["status"] = 429
        if case in ("nan", "overflow"): options["raw"] = ('{"id":"'+rid+'","result":{"x":'+("NaN" if case == "nan" else "1e309")+'}}').encode()
        if case == "deep": options["raw"] = ('{"id":"'+rid+'","result":'+ '['*40+'0'+']'*40+'}').encode()
        if case == "rejected": body["status"] = "rejected"
        if case == "wrong_stats": body["result"] = {"data": []}
        return Response(body, **options)
    wire.responses.append(response)
    with pytest.raises(sn.SerpstatAPIError) as error: await run("test_connection")
    assert CREDS["api_token"] not in str(error.value) and len(wire.calls) == 1
    assert error.value.authority_rejected is (case == "http401") and sn._PRIVATE_REQUEST.get() is False


@pytest.mark.asyncio
async def test_project_pages_and_bound_picker_continuations(wire):
    wire.responses.append(page([PROJECT], pages=2, total=21))
    result = await sn.SerpstatNode.load_field_options("project_id", CREDS, context={"_user_id": "actor"}, search="Owned")
    assert result["options"] == [{"value": "42", "label": "Owned"}] and result["next_page_token"]
    before = len(wire.calls)
    with pytest.raises(ValueError, match="another current"):
        await sn.SerpstatNode.load_field_options("rank_project_id", CREDS, context={"_user_id": "actor"}, search="Owned", page_token=result["next_page_token"])
    assert len(wire.calls) == before
    wire.responses.append(page([{**PROJECT, "project_id": "43"}], current=2, pages=2, total=21))
    last = await sn.SerpstatNode.load_field_options("project_id", CREDS, context={"_user_id": "actor"}, search="Owned", page_token=result["next_page_token"])
    assert last["next_page_token"] is None
    for i in range(1, 6): wire.responses.append(page([{**PROJECT, "project_id": str(i+100)}], current=i, pages=6, total=101))
    with pytest.raises(sn.SerpstatAPIError, match="bounded search"):
        await sn.SerpstatNode.load_field_options("project_id", CREDS, context={"_user_id": "actor"}, search="Unmatched")


@pytest.mark.asyncio
async def test_distinct_rank_project_region_and_audit_report_scope(wire):
    wire.responses.extend([page([RANK]), {"projectId": 81, "regions": [{"id": 82, "active": True, "country": "USA"}], "spent_limits": 0}, {"projectId": 81, "regionId": 82, "parsing": False}])
    status = await run("get_rank_status", {"rank_project_id": "81", "rank_region_id": "82"})
    assert status["data"]["parsing"] is False
    assert [c["json"]["method"] for c in wire.calls] == ["RtApiProjectProcedure.getProjects", "RtApiSearchEngineProcedure.getProjectRegions", "RtApiProjectProcedure.getProjectStatus"]
    wire.responses.extend([page([PROJECT]), [REPORT], [{"category": "meta_tags", "highCount": 1, "mediumCount": 2, "lowCount": 3, "informationCount": 4}]])
    result = await run("get_audit_categories", {"project_id": "42", "audit_report_id": "91"})
    assert result["data"]["parent_scope_source"] == "protected_project_and_report_membership"
    assert wire.calls[-2]["json"]["params"] == {"projectId": 42, "limit": 20, "offset": 0}
    assert wire.calls[-1]["json"]["params"] == {"reportId": 91}
    before = len(wire.calls); wire.responses.extend([page([PROJECT]), []])
    with pytest.raises(ValueError, match="not currently listed"):
        await run("get_audit_status", {"project_id": "42", "audit_report_id": "92"})
    assert len(wire.calls) == before + 2


@pytest.mark.asyncio
async def test_analytical_projection_paging_unknown_and_current_methods(wire):
    wire.responses.extend([
        {"data": [{"domain": "example.com", "keywords": 7, "traff": 99, "new_keywords": 1, "out_keywords": 0, "rised_keywords": 2, "down_keywords": 0, "ad_keywords": 0, "ads": 0, "prev_date": "2026-10-05"}], "summary_info": {"page": 1, "left_lines": 900}},
        {"data": [], "summary_info": {"page": 1, "left_lines": 900}},
        {"data": [{"domain_from": "source.test", "ref_pages": "4", "domainRank": "30", "secret": CREDS["api_token"]}], "summary_info": {"left_lines": 899, "page": 1, "count": 1, "total": 1, "sort": "domain_links", "order": "desc"}},
    ])
    overview = await run("get_domain_overview", {"domain": "example.com"})
    assert overview["data"]["data"][0]["keywords"] == 7
    unknown = await run("list_domain_competitors", {"domain": "example.com"})
    assert unknown["data"]["continuation_unknown"] is True and unknown["data"]["collection_exhausted"] is None
    backlinks = await run("list_referring_domains", {"domain": "example.com"})
    assert backlinks["data"]["collection_exhausted"] is True and "secret" not in json.dumps(backlinks)
    assert wire.calls[-1]["json"]["params"] == {"query": "example.com", "searchType": "domain", "page": 1, "size": 20}
    before = len(wire.calls)
    with pytest.raises(ValueError, match="Unsupported"):
        await sn._rpc(sn._shape(CREDS), {}, "AuditSite.start", {})
    assert len(wire.calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected"])
async def test_actual_saved_admission_precedes_credit_transport(monkeypatch, wire, status):
    from nodes.core import run_op
    from repositories.credential_approvals import CredentialApprovalRepo
    monkeypatch.setattr(run_op, "resolve_operation_credential", AsyncMock(return_value=CREDS))
    monkeypatch.setattr(CredentialApprovalRepo, "admit", AsyncMock(return_value={"status": status, "id": "approval", "new_request": False}))
    result = await run("test_connection", credential_id="saved", pool=object())
    lookup = await run_node_lookup(node_type=sn.NODE_TYPE, field_name="project_id", credential_id="saved", user_id="actor", pool=object())
    assert result["executed"] is False and lookup["status"] in ("pending_approval", "rejected") and wire.calls == []


@pytest.mark.asyncio
async def test_documented_nullable_keyword_trends_and_empty_metrics(wire):
    wire.responses.extend([
        {"data": [{"keyword": "seo tool", "current_volume": None, "yoy_change_pct": None, "trend": None, "peak_month": None, "trough_month": None, "monthly": []}], "spent_limits": 5, "left_limits": 995},
        {"data": [], "summary_info": {"page": 1, "left_lines": 990}, "not_found": ["missing keyword"]},
    ])
    trends = await run("get_keyword_trends", {"keywords": ["seo tool"]})
    assert trends["data"]["data"][0]["current_volume"] is None and trends["data"]["spent_limits"] == 5
    assert wire.calls[0]["json"]["params"] == {"se": "g_us", "keywords": ["seo tool"], "months": 12}
    metrics = await run("get_keyword_metrics", {"keywords": ["missing keyword"]})
    assert metrics["data"]["data"] == [] and metrics["data"]["not_found"] == ["missing keyword"]


@pytest.mark.asyncio
async def test_response_byte_bound_before_replay(monkeypatch, wire):
    monkeypatch.setattr(sn, "MAX_BYTES", 10)
    wire.responses.append(STATS)
    with pytest.raises(sn.SerpstatAPIError, match="byte bound"):
        await run("test_connection")
    assert len(wire.calls) == 1 and sn._PRIVATE_REQUEST.get() is False


from pathlib import Path

DOCUMENTED_RESPONSES = json.loads(
    (Path(__file__).parent / "fixtures/serpstat/documented_responses.json").read_text()
)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", DOCUMENTED_RESPONSES)
async def test_provider_authored_response_examples(wire, method):
    body = DOCUMENTED_RESPONSES[method]["body"]
    # The server echoes the request id; keep every result field verbatim.
    wire.responses.append(lambda rid: Response({**body, "id": rid}))
    result = await sn._rpc(sn._shape(CREDS), {}, method)
    assert result == sn._projected(body["result"], sn.CONTRACTS[method])
    if method == "SerpstatBacklinksProcedure.getRefDomains":
        assert result["data"][0]["ref_pages"] == 2
        assert result["data"][0]["domainRank"] == 47
        assert result["summary_info"]["order"] == "DESC"

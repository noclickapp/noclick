"""Native Analytics factory, discovery, transport and report regressions."""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from nodes import adobe_analytics_node as api
from nodes.adobe_analytics_node import AdobeAnalyticsNode, RunReport
from nodes.core import credential_connect, run_op
from nodes.core.registry import NodeFactory, NODE_REGISTRY

NODE = "automation-adobe-analytics"
USER = "00000000-0000-4000-8000-000000000001"
CID = "00000000-0000-4000-8000-000000000042"
OWNER = "00000000-0000-4000-8000-000000000002"
CREDS = {"credential_type": api.KIND, "access_token": "fixture-issued-token", "client_id": "fixture-client",
         "global_company_id": "fixtureco", "expires_at": "2099-01-01T00:00:00Z"}
DISCOVERY = {"imsUserId": "fixture-user@AdobeID", "imsOrgs": [{"companies": [{"globalCompanyId": "fixtureco", "companyName": "Fixture company"}]}]}
SUITE = {"rsid": "fixturesuite", "id": "fixturesuite", "name": "Fixture suite", "timezoneZoneinfo": "US/Pacific"}
METRICS = [{"id": "metrics/visits", "name": "Visits", "allowedForReporting": True}, {"id": "metrics/visitors", "name": "Visitors"}]
COMPONENT = {"id": "cm-fixture", "rsid": "fixturesuite", "name": "Owned ratio", "owner": {"id": 42}, "definition": {"secret": "omit"}}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def provider(monkeypatch):
    requests, replies = [], {}
    defaults = {"/discovery/me": DISCOVERY, "/api/fixtureco/reportsuites/collections/suites/fixturesuite": SUITE,
                "/api/fixtureco/metrics": METRICS, "/api/fixtureco/reportsuites/collections/suites": [SUITE]}
    def response(request):
        requests.append(request)
        path = request.url.path
        value = replies.get((request.method, path), replies.get(path, defaults.get(path, [])))
        if callable(value):
            value = value(request)
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json=deepcopy(value))
    @asynccontextmanager
    async def guarded(**kwargs):
        assert kwargs == {"trust_env": False, "follow_redirects": False, "timeout": 25.0}
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            yield client
    monkeypatch.setattr(api, "guarded_async_client", guarded)
    return SimpleNamespace(requests=requests, replies=replies)


async def native(operation, *, credentials=None, **arguments):
    return await run_op.run_node_operation(node_type=NODE, operation=operation, arguments=arguments,
        user_id=USER, credential_data=deepcopy(credentials or CREDS))


def test_actual_factory_schema_and_manual_shape():
    assert NODE_REGISTRY[NODE] is AdobeAnalyticsNode
    credential = AdobeAnalyticsNode.get_config_schema()["$defs"]["AdobeAnalyticsTokenCredential"]
    assert set(credential["required"]) == {"access_token", "client_id", "global_company_id"}
    assert credential["properties"]["credential_type"]["const"] == api.KIND
    assert credential["properties"]["access_token"]["ui:widget"] == "password"
    assert "x-oauth-provider" not in credential
    shaped, errors, resolved = credential_connect.shape_credential(api.KIND, {k: v for k, v in CREDS.items() if k != "credential_type"})
    assert not errors and shaped["credential_type"] == api.KIND and resolved[0] == NODE
    node = NodeFactory.create_node("fixture", NODE, {"config": {"operation": "list_metrics", "rsid": "fixturesuite", "label": "Saved canvas", "_settings": {"retryOnFail": "false"}}, "credentials": shaped}, user_id=USER)
    assert node.config.config.rsid == "fixturesuite"
    for key in ("access_token", "client_id", "global_company_id"):
        _, errors, _ = credential_connect.shape_credential(api.KIND, {k: v for k, v in CREDS.items() if k != key})
        assert key in errors


@pytest.mark.parametrize("credential", [{**CREDS, "credential_type": "adobe_campaign_token"}, {**CREDS, "access_token": "fixture-secret\r\n"}, {**CREDS, "client_id": "fixture-secret\x00"}])
def test_foreign_type_and_header_shape_refuse_without_input_echo(credential):
    with pytest.raises(ValueError) as error:
        AdobeAnalyticsNode.parse_config({"config": {"operation": "discover_companies"}, "credentials": credential})
    assert "fixture-secret" not in str(error.value)


@pytest.mark.parametrize("value", ["../other", "a/b", "x?key=fixture-secret", "https://other.test", "x%2Fz", "."])
def test_company_and_suite_identifiers_are_paths_not_urls(value):
    with pytest.raises(ValueError):
        api.shape({**CREDS, "global_company_id": value})
    with pytest.raises(ValueError):
        AdobeAnalyticsNode.parse_config({"config": {"operation": "get_report_suite", "rsid": value}, "credentials": CREDS})


async def test_native_connect_uses_real_collector_and_discovered_company(provider, monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type=api.KIND, credential_data=CREDS, user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert AdobeAnalyticsNode.connection_evidence.proves == "account"
    assert verdict.evidence.samples[0].label == "Fixture suite"
    request = provider.requests[0]
    assert str(request.url) == "https://analytics.adobe.io/discovery/me"
    assert request.headers["Authorization"] == "Bearer fixture-issued-token" and request.headers["x-api-key"] == "fixture-client"


async def test_company_mismatch_never_reaches_resource(provider):
    with pytest.raises(ValueError, match="not authorized"):
        await native("get_report_suite", credentials={**CREDS, "global_company_id": "otherco"}, rsid="fixturesuite")
    assert [r.url.path for r in provider.requests] == ["/discovery/me"]


@pytest.mark.parametrize("payload", [{}, {"imsUserId": "", "imsOrgs": []}, {"imsUserId": "fixture", "imsOrgs": [{"companies": [SUITE]}]}])
async def test_malformed_discovery_never_claims_working_connection(provider, payload):
    provider.replies["/discovery/me"] = payload
    from nodes.core.connection_evidence import collect_evidence
    result = await collect_evidence(node_type=NODE, credential_data=CREDS, user_id=USER)
    assert result.reachable is not True


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_transport_errors_do_not_echo_provider_tokens(provider, status):
    provider.replies["/api/fixtureco/segments"] = httpx.Response(status, json={"error": "fixture-issued-token"}, headers={"Retry-After": "60"})
    with pytest.raises(ValueError) as error:
        await native("list_segments", rsid="fixturesuite")
    assert f"HTTP {status}" in str(error.value) and "fixture-issued-token" not in str(error.value)
    if status == 429:
        assert "60 seconds" in str(error.value)


@pytest.mark.parametrize("response", [httpx.Response(200, json={"errorCode": "fixture-issued-token"}), httpx.Response(200, content=b"<html>fixture-issued-token</html>", headers={"Content-Type": "text/html"}), httpx.Response(200, content=b"{bad", headers={"Content-Type": "application/json"}), httpx.Response(200, content=b"x" * (api.MAX_BYTES + 1), headers={"Content-Type": "application/json"})])
async def test_media_error_envelope_and_body_bounds(provider, response):
    provider.replies["/api/fixtureco/segments"] = response
    with pytest.raises(ValueError) as error:
        await native("list_segments", rsid="fixturesuite")
    assert "fixture-issued-token" not in str(error.value)


async def test_array_paging_has_candidate_without_fabricated_total(provider):
    provider.replies["/api/fixtureco/reportsuites/collections/suites"] = [SUITE]
    output = await native("list_report_suites", limit=1)
    assert output["next_page"] == 1 and output["continuation_confirmed"] is False
    assert "totalElements" not in output


async def test_totals_and_partial_dimension_reports(provider):
    provider.replies["/api/fixtureco/reports"] = {"columns": {"columnIds": ["0"]}, "summaryData": {"totals": [42]}}
    args = {"rsid": "fixturesuite", "metric_ids": ["metrics/visits"], "start": "2026-01-01T00:00:00", "end": "2026-01-02T00:00:00"}
    totals = await native("run_report", **args)
    assert totals["rows"] == [] and totals["dimension"] is None and totals["summaryData"]["totals"] == [42]
    assert "dimension" not in json.loads(provider.requests[-1].content)
    provider.replies["/api/fixtureco/dimensions"] = [{"id": "variables/page", "name": "Page"}]
    provider.replies["/api/fixtureco/reports"] = httpx.Response(206, json={"number": 0, "lastPage": False,
        "columns": {"columnIds": ["0"], "columnErrors": [{"columnId": "0", "errorCode": "not_enabled_metric", "errorDescription": "fixture-issued-token"}]},
        "rows": [{"itemId": "fixture-item", "value": "Fixture page", "data": [None]}], "summaryData": {"totals": [None]}, "request": {"secret": "omit"}})
    partial = await native("run_report", **args, dimension_id="variables/page")
    assert partial["partial"] is True and partial["next_page"] == 1 and partial["rows"][0]["data"] == [None]
    assert partial["column_errors"] == [{"columnId": "0", "errorCode": "not_enabled_metric"}]
    assert "fixture-issued-token" not in json.dumps(partial) and "request" not in partial


async def test_report_mismatched_columns_refuse(provider):
    provider.replies["/api/fixtureco/reports"] = {"columns": {"columnIds": ["other"]}, "summaryData": {"totals": [42]}}
    with pytest.raises(ValueError, match="columns"):
        await native("run_report", rsid="fixturesuite", metric_ids=["metrics/visits"], start="2026-01-01T00:00:00", end="2026-01-02T00:00:00")


@pytest.mark.parametrize("change", [{"end": "2026-01-01T00:00:00"}, {"start": "2026-01-01T00:00:00Z"}, {"metric_ids": ["metrics/visits"] * 11}, {"page": 1}, {"metric_ids": ["metrics/visits", "metrics/visits"]}])
def test_report_date_metric_and_totals_page_bounds(change):
    with pytest.raises(ValueError):
        RunReport.model_validate({"rsid": "fixturesuite", "metric_ids": ["metrics/visits"], "start": "2026-01-01T00:00:00", "end": "2026-01-02T00:00:00", **change})


def metric_replies(provider, *, shared=False, owner=42):
    component = {**COMPONENT, "owner": {"id": owner}}
    provider.replies["/api/fixtureco/calculatedmetrics"] = [component]
    provider.replies["/api/fixtureco/calculatedmetrics/cm-fixture"] = component
    provider.replies["/api/fixtureco/users/me"] = {"loginId": 42}
    provider.replies["/api/fixtureco/componentmetadata/shares/component/search"] = {"number": 0, "lastPage": True,
        "content": [{"componentType": "calculatedMetric", "componentId": "cm-fixture", "shares": [{"shareId": 3}] if shared else []}]}
    return component


@pytest.mark.parametrize("shared,owner", [(True, 42), (False, 7)])
async def test_shared_or_other_owned_metric_is_never_mutated(provider, shared, owner):
    metric_replies(provider, shared=shared, owner=owner)
    with pytest.raises(ValueError):
        await native("update_calculated_metric", rsid="fixturesuite", calculated_metric_id="cm-fixture", name="New", confirm_component_update=True)
    assert not any(request.method in {"PUT", "DELETE"} for request in provider.requests)


async def test_actual_ratio_create_body_and_owned_readback(provider):
    component = metric_replies(provider)
    def validate(request):
        body = json.loads(request.content)
        assert body["definition"]["formula"] == {"func": "divide", "col1": {"func": "metric", "name": "metrics/visits"}, "col2": {"func": "metric", "name": "metrics/visitors"}}
        assert not {"owner", "shares", "approved", "published"} & body.keys()
        return {"valid": True}
    provider.replies["/api/fixtureco/calculatedmetrics/validate"] = validate
    provider.replies[("POST", "/api/fixtureco/calculatedmetrics")] = component
    output = await native("create_calculated_metric", rsid="fixturesuite", name="Owned ratio", numerator_metric_id="metrics/visits", denominator_metric_id="metrics/visitors", confirm_component_creation=True)
    assert output["created"]["id"] == "cm-fixture" and output["atomic_visibility_guarantee"] is False
    assert "definition" not in output["created"]


async def test_delete_opaque_documented_result_uses_owned_list_readback(provider):
    metric_replies(provider)
    def delete(_request):
        provider.replies["/api/fixtureco/calculatedmetrics"] = []
        return {"result": "provider-documented-string", "message": "fixture-issued-token"}
    provider.replies[("DELETE", "/api/fixtureco/calculatedmetrics/cm-fixture")] = delete
    output = await native("delete_calculated_metric", rsid="fixturesuite", calculated_metric_id="cm-fixture", confirm_component_deletion=True)
    assert output["deleted_from_owned_list"] is True and output["hard_erasure_verified"] is False
    assert "fixture-issued-token" not in json.dumps(output)


async def test_native_picker_parent_cursor_and_property_projection(provider):
    data = await AdobeAnalyticsNode.freshen_credential(CREDS)
    provider.replies["/api/fixtureco/dimensions"] = [{"id": "variables/page", "name": "Page", "secret": "omit"}]
    output = await AdobeAnalyticsNode.load_field_options("dimension_id", data, context={"rsid": "fixturesuite"})
    assert output == {"options": [{"value": "variables/page", "label": "Page"}], "next_page_token": None}
    before = len(provider.requests)
    with pytest.raises(ValueError):
        await AdobeAnalyticsNode.load_field_options("dimension_id", data, context={"rsid": "other-suite"}, page_token=api.cursor({"company": "fixtureco", "field": "dimension_id", "rsid": "fixturesuite", "search": ""}, 1))
    assert len(provider.requests) == before



async def test_adobe_analytics_expired_issued_token_never_reaches_transport(provider):
    expired = {**CREDS, "expires_at": "2000-01-01T00:00:00Z"}
    with pytest.raises(ValueError, match="expired"):
        await AdobeAnalyticsNode.freshen_credential(expired)
    with pytest.raises(ValueError, match="expired"):
        await native("discover_companies", credentials=expired)
    assert provider.requests == []

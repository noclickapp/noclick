"""Gender-API request contract, documented responses and connection regressions.

All HTTP is intercepted; no account signup or provider credential is used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import gender_api_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-gender-api-token-42"
FIXTURES = json.loads((Path(__file__).parent / "fixtures/gender-api/responses.json").read_text())["examples"]


def node(config, credentials=True):
    return NodeFactory.create_node(node_id="gender-api-fixture", node_type="automation-gender-api",
        node_data={"config": config, "credentials": {"credential_type": "gender_api_token", "api_token": TOKEN} if credentials else None})


def transport(monkeypatch, response):
    calls = []
    def handler(request):
        calls.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field,value,path", [
    ("query_first_name", "first_name", "Sandra", "/gender/by-first-name"),
    ("query_full_name", "full_name", "Sandra Miller", "/gender/by-full-name"),
    ("query_email", "email", "sandra.miller14@gmail.com", "/gender/by-email-address"),
    ("query_origin_first_name", "first_name", "Johanna", "/country-of-origin"),
    ("query_origin_full_name", "full_name", "Theresa Miller", "/country-of-origin"),
    ("query_origin_email", "email", "sophia5342@gmail.com", "/country-of-origin"),
])
async def test_exact_single_routes_json_and_bearer(monkeypatch, operation, field, value, path):
    example = FIXTURES["CountryOfOriginResultModel" if "origin" in operation else {"first_name": "FirstNameResultModel", "full_name": "FullNameResultModel", "email": "EmailResultModel"}[field]]
    calls = transport(monkeypatch, example)
    config = {"operation": operation, field: value}
    if "origin" not in operation:
        config.update(country="US", locale="en_US", ip="54.201.16.177")
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == example
    assert len(calls) == 1 and calls[0].method == "POST"
    assert str(calls[0].url) == native.API_BASE + path
    assert calls[0].headers["Authorization"] == "Bearer " + TOKEN
    assert calls[0].headers["Content-Type"] == "application/json"
    assert json.loads(calls[0].content) == {k: v for k, v in config.items() if k != "operation"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,field,values,path,fixture", [
    ("query_first_names_batch", "first_name", ["sandra", "mike"], "/gender/by-first-name-multiple", "FirstNameResultModelMultiple"),
    ("query_full_names_batch", "full_name", ["sandra miller", "mike meyers"], "/gender/by-full-name-multiple", "FullNameResultModelMultiple"),
    ("query_emails_batch", "email", ["sandra.miller14@gmail.com", "mark.meyer@gmail.com"], "/gender/by-email-address-multiple", "EmailResultModelMultiple"),
])
async def test_batch_is_top_level_array_preserves_ids_and_results(monkeypatch, operation, field, values, path, fixture):
    rows = [{field: value, "id": str(i + 1), **({"country": "US"} if i == 0 else {})} for i, value in enumerate(values)]
    calls = transport(monkeypatch, FIXTURES[fixture])
    result = await node({"operation": operation, "entries_json": json.dumps(rows)}).execute({})
    assert result["status"] == "success" and result["data"] == FIXTURES[fixture]
    assert len(calls) == 1 and calls[0].url.path == "/v2" + path
    assert json.loads(calls[0].content) == rows


@pytest.mark.asyncio
async def test_statistics_connection_read_costs_no_query_and_handles_exhausted_account(monkeypatch):
    example = {**FIXTURES["StatisticResultModel"], "remaining_credits": 0, "is_limit_reached": True}
    calls = transport(monkeypatch, example)
    result = await node({"operation": "get_statistics"}).execute({})
    assert result["status"] == "success" and result["name"] == "0 credits remaining"
    assert calls[0].method == "GET" and calls[0].url.path == "/v2/statistic"
    assert calls[0].content == b"" and calls[0].url.query == b""
    spec = native.GenderApiNode.connection_evidence
    assert spec.operation == "get_statistics" and spec.proves == "account"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,title", [(400,"invalid-country-code"),(401,"invalid-auth-token"),(401,"limit-exceeded"),(429,"rate-limited"),(500,"server-error")])
async def test_provider_failure_is_not_success_and_redacts_token(monkeypatch, code, title):
    calls = transport(monkeypatch, lambda _: httpx.Response(code,json={"status":code,"title":title,"detail":"provider says " + TOKEN},headers={"Retry-After":"60"}))
    result = await node({"operation":"get_statistics"}).execute({})
    assert result["status"] == "error" and result["status_code"] == code
    assert result["error"]["title"] == title and TOKEN not in str(result)
    assert len(calls) == 1
    if code == 429: assert result["retry_after"] == "60"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302,headers={"location":"https://example.com"}),httpx.Response(200,text="<html>bad</html>"),httpx.Response(200,content=b"{",headers={"content-type":"application/json"}),httpx.Response(200,json={}),httpx.Response(200,json={"title":"invalid-auth-token"})])
async def test_redirect_html_invalid_json_and_incomplete_response_fail(monkeypatch,response):
    calls=transport(monkeypatch,lambda _:response)
    assert (await node({"operation":"get_statistics"}).execute({}))["status"] == "error"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_not_found_is_valid_enrichment_result_and_partial_batch_fails(monkeypatch):
    transport(monkeypatch,{"result_found":False,"gender":"unknown"})
    assert (await node({"operation":"query_first_name","first_name":"Sandra"}).execute({}))["status"] == "success"
    transport(monkeypatch,[{"result_found":False}])
    result=await node({"operation":"query_first_names_batch","entries_json":json.dumps([{"first_name":"Sandra"},{"first_name":"Mike"}])}).execute({})
    assert result["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("entries", ['{}','[]','not json','[1]','[{"first_name":"Sandra","url":"https://evil.test"}]','[{"first_name":"Sandra","id":true}]',json.dumps([{"first_name":"Sandra"}]*101)])
async def test_bad_batch_never_sends_a_request(monkeypatch,entries):
    calls=transport(monkeypatch,{})
    with pytest.raises((ValueError,ValidationError)):
        await node({"operation":"query_first_names_batch","entries_json":entries}).execute({})
    assert calls == []


@pytest.mark.asyncio
async def test_missing_credentials_refused_before_network(monkeypatch):
    calls=transport(monkeypatch,{})
    with pytest.raises(ValueError,match="Connect"):
        await node({"operation":"get_statistics"},credentials=False).execute({})
    assert calls == []


@pytest.mark.parametrize("config", [{"operation":"query_email","email":"not-an-email"},{"operation":"query_first_name","first_name":"Sandra","ip":"invalid"},{"operation":"query_origin_first_name","first_name":"Sandra","full_name":"Sandra Miller"},{"operation":"get_statistics","url":"https://evil.test"}])
def test_invalid_fields_are_rejected(config):
    assert native.GenderApiNode.validate_config({"config":config})["valid"] is False


@pytest.mark.parametrize("token", ["Bearer some-token","https://example.com/key","<token>"])
def test_token_shape_rejected(token):
    with pytest.raises(ValueError):
        native.GenderApiTokenCredential(api_token=token)


@pytest.mark.asyncio
async def test_unsaved_credential_evidence_shows_account_credits(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    # Exercise the real operation through the evidence seam with only the runner
    # replaced; no saved credential or database is needed for a manual connect.
    async def run(**kwargs):
        assert kwargs["operation"] == "get_statistics" and kwargs["arguments"] == {}
        assert kwargs["credential_data"]["api_token"] == TOKEN
        return await node({"operation": kwargs["operation"]}).execute({})
    monkeypatch.setattr(run_op, "run_node_operation", run)
    calls = transport(monkeypatch, FIXTURES["StatisticResultModel"])
    result = await collect_evidence(node_type="automation-gender-api", user_id="fixture-user",
        credential_data={"credential_type": "gender_api_token", "api_token": TOKEN})
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == ["24999 credits remaining"]
    assert len(calls) == 1

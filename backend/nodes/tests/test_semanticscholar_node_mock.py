"""Offline wire tests using provider examples and adversarial boundaries."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import semanticscholar_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-semanticscholar-key"
PAPER = "649def34f8be52c8b66281af98ae884c09aef38b"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="s2-test", node_type="automation-semanticscholar",
        node_data={"config": config, "credentials": {"credential_type": "semanticscholar_api_key", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,body", [
    ({"operation": "search_papers", "query": "graph"}, "/paper/search", {"total": 2, "offset": 0, "next": 1, "data": [{"paperId": PAPER, "title": "Construction of the Literature Graph in Semantic Scholar"}]}),
    ({"operation": "search_papers_bulk", "query": "graph", "token": "opaque-next", "sort": "citationCount:desc"}, "/paper/search/bulk", {"total": 1, "token": "opaque-final", "data": [{"paperId": PAPER}]}),
    ({"operation": "match_paper", "query": "Construction of the Literature Graph in Semantic Scholar"}, "/paper/search/match", {"data": [{"paperId": PAPER, "matchScore": 1.0}]}),
    ({"operation": "autocomplete_papers", "query": "semanti"}, "/paper/autocomplete", {"matches": [{"id": PAPER, "title": "Semantic Scholar"}]}),
    ({"operation": "get_paper", "paper_id": PAPER}, "/paper/" + PAPER, {"paperId": PAPER}),
    ({"operation": "get_paper_authors", "paper_id": PAPER}, "/paper/" + PAPER + "/authors", {"offset": 0, "data": [{"authorId": "1741101", "name": "Oren Etzioni"}]}),
    ({"operation": "get_paper_citations", "paper_id": PAPER}, "/paper/" + PAPER + "/citations", {"offset": 0, "data": [{"citingPaper": {"paperId": PAPER}, "contexts": ["context"]}]}),
    ({"operation": "get_paper_references", "paper_id": PAPER}, "/paper/" + PAPER + "/references", {"offset": 0, "data": [{"citedPaper": {"paperId": PAPER}}]}),
    ({"operation": "search_authors", "query": "Oren Etzioni"}, "/author/search", {"total": 1, "offset": 0, "data": [{"authorId": "1741101", "name": "Oren Etzioni"}]}),
    ({"operation": "get_author", "author_id": "1741101"}, "/author/1741101", {"authorId": "1741101", "name": "Oren Etzioni"}),
    ({"operation": "get_author_papers", "author_id": "1741101"}, "/author/1741101/papers", {"offset": 0, "data": [{"paperId": PAPER}]}),
])
async def test_semanticscholar_reads_preserve_provider_envelope(monkeypatch, config, path, body):
    requests = transport(monkeypatch, body)
    out = await node(config).execute({})
    assert out == {"status": "success", "data": body}
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "GET"
    assert req.url.host == "api.semanticscholar.org"
    assert req.url.path == "/graph/v1" + path
    assert req.headers["x-api-key"] == TOKEN
    assert TOKEN not in str(out)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,ids", [("papers", [PAPER, "ARXIV:2106.15928"]), ("authors", ["1741101", "1780531"])])
async def test_semanticscholar_documented_batch_arrays(monkeypatch, kind, ids):
    body = json.loads((Path(__file__).parent / "fixtures/semanticscholar" / (kind + "_batch.json")).read_text())
    requests = transport(monkeypatch, body)
    out = await node({"operation": "batch_get_" + kind, "ids": ids, "fields": "title" if kind == "papers" else "name"}).execute({})
    req = requests[0]
    assert out["data"] == body
    assert req.method == "POST"
    assert req.url.path.endswith("/paper/batch" if kind == "papers" else "/author/batch")
    assert json.loads(req.content) == {"ids": ids}
    assert dict(req.url.params) == {"fields": "title" if kind == "papers" else "name"}


@pytest.mark.asyncio
async def test_semanticscholar_filters_and_path_encoding(monkeypatch):
    requests = transport(monkeypatch, {"data": [], "total": 0, "offset": 0})
    await node({"operation": "search_papers", "query": "graph", "openAccessPdf": True, "minCitationCount": 200,
        "fieldsOfStudy": "Computer Science", "year": "2016-2020", "limit": 5, "offset": 10}).execute({})
    assert dict(requests[0].url.params) == {"query": "graph", "openAccessPdf": "", "minCitationCount": "200", "fieldsOfStudy": "Computer Science", "year": "2016-2020", "limit": "5", "offset": "10"}
    requests = transport(monkeypatch, {"paperId": PAPER})
    await node({"operation": "get_paper", "paper_id": "DOI:10.1038/nrn3241?x=y#z"}).execute({})
    assert b"DOI%3A10.1038%2Fnrn3241%3Fx%3Dy%23z" in requests[0].url.raw_path
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
async def test_semanticscholar_errors_are_not_success(monkeypatch, status):
    transport(monkeypatch, {"message": "Rejected " + TOKEN}, status)
    out = await node({"operation": "get_author", "author_id": "1741101"}).execute({})
    assert out == {"status": "error", "status_code": status, "error": "Rejected [redacted]"}


@pytest.mark.asyncio
async def test_semanticscholar_batch_null_and_bad_envelope(monkeypatch):
    transport(monkeypatch, [None])
    assert (await node({"operation": "batch_get_papers", "ids": [PAPER]}).execute({}))["data"] == [None]
    transport(monkeypatch, {"paperId": PAPER})
    with pytest.raises(ValueError, match="batch array"):
        await node({"operation": "batch_get_papers", "ids": [PAPER]}).execute({})
    transport(monkeypatch, {"data": "invalid"})
    with pytest.raises(ValueError, match="result list"):
        await node({"operation": "search_papers", "query": "graph"}).execute({})


def test_semanticscholar_credential_can_be_filled_manually():
    credential = native.SemanticScholarAPIKeyCredential(api_key=" " + TOKEN + " ")
    assert credential.credential_type == "semanticscholar_api_key"
    assert credential.api_key == TOKEN
    for value in ("https://example.com/key", "Bearer abc def", "abc\nkey"):
        with pytest.raises(ValidationError):
            native.SemanticScholarAPIKeyCredential(api_key=value)


@pytest.mark.parametrize("model,config", [
    (native.SearchPapers, {"query": "x", "limit": 101}),
    (native.GetPaperAuthors, {"paper_id": PAPER, "limit": 1001}),
    (native.BatchGetPapers, {"ids": []}),
    (native.BatchGetPapers, {"ids": [PAPER] * 501}),
    (native.BatchGetAuthors, {"ids": ["abc"]}),
    (native.GetAuthor, {"author_id": "../paper/search"}),
    (native.GetPaper, {"paper_id": "\n"}),
    (native.GetPaper, {"paper_id": ".."}),
])
def test_semanticscholar_rejects_invalid_inputs(model, config):
    with pytest.raises(ValidationError):
        model(**config)

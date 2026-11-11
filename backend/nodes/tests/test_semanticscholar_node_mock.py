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


@pytest.mark.asyncio
async def test_semanticscholar_poll_baseline_new_ids_and_scope(monkeypatch):
    # Provider batch examples supply the records; the bulk-search contract
    # defines the data envelope and guarantees paperId on every record.
    from nodes.core.poll_trigger import poll_scope
    from copy import deepcopy
    papers = json.loads((Path(__file__).parent / 'fixtures/semanticscholar/papers_batch.json').read_text())
    body = {'data': papers[:1]}
    requests = transport(monkeypatch, body)
    watcher = node({'operation': 'on_new_matching_paper', 'query': 'fish ladder',
                    'publicationDateOrYear': '2015:2020', 'fields': 'title',
                    'openAccessPdf': True, 'minCitationCount': 200})
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        next_state, result = mutator(deepcopy(state))
        if next_state is not None:
            state = next_state
        return result

    monkeypatch.setattr(watcher, '_update_node_state', update)
    first = await watcher.execute({})
    assert first == {'papers': [], 'new_paper_count': 0}
    assert watcher.trigger_produced_no_event(first)
    assert native.SemanticScholarNode.resolve_agent_event(first) is None
    assert dict(requests[0].url.params) == {
        'query': 'fish ladder', 'publicationDateOrYear': '2015:2020',
        'fields': 'title,url', 'sort': 'publicationDate:desc',
        'openAccessPdf': '', 'minCitationCount': '200',
    }
    assert requests[0].url.path == '/graph/v1/paper/search/bulk'
    body['data'] = papers
    fresh = await watcher.execute({})
    assert fresh == {'papers': papers[1:], 'new_paper_count': 1}
    assert watcher.trigger_emitted_event(fresh)
    event = native.SemanticScholarNode.resolve_agent_event(fresh)
    assert papers[1]['title'] in event['text']
    assert papers[1]['paperId'] in event['text']
    assert 'get_paper' in event['text']
    assert (await watcher.execute({}))['papers'] == []
    config = watcher.config.config.model_dump()
    original_scope = poll_scope(native.SemanticScholarNode, config)
    assert original_scope == poll_scope(native.SemanticScholarNode, {**config, 'webhook_url': 'https://example.test/tick'})
    assert original_scope != poll_scope(native.SemanticScholarNode, {**config, 'query': 'covid'})
    watcher.config.config.query = 'covid'
    assert (await watcher.execute({}))['papers'] == []


@pytest.mark.asyncio
async def test_semanticscholar_poll_rejects_malformed_records_without_advancing_state(monkeypatch):
    from unittest.mock import AsyncMock
    transport(monkeypatch, {'data': [{'title': 'missing ID'}]})
    watcher = node({'operation': 'on_new_matching_paper', 'query': 'fish ladder'})
    update = AsyncMock()
    monkeypatch.setattr(watcher, '_update_node_state', update)
    with pytest.raises(ValueError, match='paperId'):
        await watcher.execute({})
    update.assert_not_awaited()


def test_semanticscholar_poll_is_discoverable():
    from nodes.core.poll_trigger import PollTriggerConfigBase
    config = native.OnNewMatchingPaper(query='fish ladder')
    assert isinstance(config, PollTriggerConfigBase)
    assert config.model_json_schema()['properties']['operation']['x-is-trigger'] is True

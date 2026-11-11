"""Check WeGA routes, parameter serialization, paging and error handling.

Mock bodies follow the pinned OpenAPI shapes; these tests do not contact an
account and do not claim that generated IDs create documents.
"""
import json

import httpx
import pytest

from nodes import weber_gesamtausgabe_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="wega-test", node_type="automation-weber-gesamtausgabe", node_data={"config": config})


def transport(monkeypatch, body, status=200, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "search_entities", "q": "Weber", "docType": ["persons", "works"]}, "GET", "/search/entity", {"q": "Weber", "docType": "persons,works", "offset": "1", "limit": "10"}, []),
    ({"operation": "list_documents", "offset": 21, "limit": 20}, "GET", "/documents", {"offset": "21", "limit": "20"}, []),
    ({"operation": "get_documents", "docID": "A002068"}, "GET", "/documents/A002068", {}, []),
    ({"operation": "find_documents_by_author", "authorID": "A002068"}, "GET", "/documents/findByAuthor/A002068", {"offset": "1", "limit": "10"}, []),
    ({"operation": "find_documents_by_mention", "docID": "A002068", "docType": ["letters"]}, "GET", "/documents/findByMention/A002068", {"offset": "1", "limit": "10", "docType": "letters"}, []),
    ({"operation": "find_documents_by_date", "fromDate": "1786-11-18", "toDate": "1826-06-05"}, "GET", "/documents/findByDate", {"offset": "1", "limit": "10", "fromDate": "1786-11-18", "toDate": "1826-06-05"}, []),
    ({"operation": "find_on_this_day", "date": "2024-12-18"}, "GET", "/documents/otd", {"offset": "1", "limit": "10", "date": "2024-12-18"}, []),
    ({"operation": "list_repositories", "city": "A130002"}, "GET", "/repositories", {"offset": "1", "limit": "10", "city": "A130002"}, []),
    ({"operation": "list_repository_items", "siglum": "D-B", "term": "Weber", "orderby": "sortdate", "orderdir": "desc"}, "GET", "/repositories/items", {"offset": "1", "limit": "10", "siglum": "D-B", "term": "Weber", "orderby": "sortdate", "orderdir": "desc"}, []),
    ({"operation": "find_code_by_element", "element": "persName"}, "GET", "/code/findByElement/persName", {"offset": "1", "limit": "10", "namespace": "http://www.tei-c.org/ns/1.0"}, []),
    ({"operation": "get_facets", "facet": "authors", "scope": "indices", "docType": ["letters"], "term": "Weber"}, "GET", "/facets/authors", {"offset": "1", "limit": "10", "scope": "indices", "docType": "letters", "term": "Weber"}, []),
    ({"operation": "get_application_status"}, "GET", "/application/status", {}, {"status": "healthy", "version": "3.2.0"}),
    ({"operation": "create_document_id", "docType": ["persons", "letters"]}, "GET", "/application/newID", {"docType": ["persons", "letters"]}, {"docID": "A123456", "docType": "letters"}),
    ({"operation": "get_preferences"}, "GET", "/application/preferences", {}, {"limit": 10, "line-wrap": True}),
    ({"operation": "set_preferences", "limit": 25, "line-wrap": False, "thematicCommentaries-marker": True, "rdg-marker": False, "textConst-marker": True, "supplied-marker": False, "note-marker": True}, "POST", "/application/preferences", {"limit": 25, "line-wrap": False, "thematicCommentaries-marker": True, "rdg-marker": False, "textConst-marker": True, "supplied-marker": False, "note-marker": True}, {"limit": 25, "line-wrap": False}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,params,body", CASES)
async def test_contract_operations(monkeypatch, config, method, path, params, body):
    requests = transport(monkeypatch, body)
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == body
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split("?")[0] == native.BASE + path
    assert request.headers["Accept"] == "application/json"
    assert "authorization" not in request.headers
    if method == "POST":
        assert not request.url.query
        assert json.loads(request.content) == params
    else:
        assert set(request.url.params) == set(params)
        for key, value in params.items():
            assert request.url.params.get_list(key) == (value if isinstance(value, list) else [value])
        assert not request.content


def test_operations_public_evidence_and_discovery():
    assert {case[0]["operation"] for case in CASES} == set(native.ROUTES)
    assert NODE_REGISTRY["automation-weber-gesamtausgabe"] is native.WeberGesamtausgabeNode
    assert native.WeberGesamtausgabeNode.connection_evidence.proves == "reachability"
    assert native.WegaFullConfig(config={"operation": "get_application_status"}, credentials={}).credentials is None


@pytest.mark.asyncio
async def test_external_identifier_is_one_encoded_path_value(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({"operation": "get_documents", "docID": "http://www.wikidata.org/entity/Q154812"}).execute({})
    assert requests[0].url.host == "weber-gesamtausgabe.de"
    assert requests[0].url.raw_path == b"/api/v1/documents/http%3A%2F%2Fwww.wikidata.org%2Fentity%2FQ154812"


@pytest.mark.asyncio
@pytest.mark.parametrize("total,count,offset,limit,next_offset", [
    ("25", 10, 1, 10, 11), ("25", 5, 21, 10, None),
    (None, 10, 1, 10, 11), (None, 3, 1, 10, None), ("25", 0, 26, 10, None),
])
async def test_one_based_pagination(monkeypatch, total, count, offset, limit, next_offset):
    transport(monkeypatch, [{} for _ in range(count)], headers={"totalrecordcount": total} if total else {})
    result = await node({"operation": "list_documents", "offset": offset, "limit": limit}).execute({})
    assert result["next_offset"] == next_offset
    if total:
        assert result["total_record_count"] == int(total)


@pytest.mark.parametrize("config", [
    {"operation": "list_documents", "limit": 201}, {"operation": "list_documents", "offset": 0},
    {"operation": "list_documents", "docType": ["invented"]}, {"operation": "get_documents"},
    {"operation": "create_document_id"}, {"operation": "get_facets", "facet": "authors", "scope": "indices"},
    {"operation": "get_facets", "facet": "authors", "scope": "indices-suffix", "docType": ["letters"]},
    {"operation": "find_documents_by_date", "fromDate": "not-a-date"},
    {"operation": "find_documents_by_date", "fromDate": "1826-06-05", "toDate": "1786-11-18"},
    {"operation": "set_preferences", "limit": 20}, {"operation": "list_repository_items", "orderby": "updated_at"},
    {"operation": "list_documents", "unexpected": "value"},
])
def test_invalid_config(config):
    assert native.WeberGesamtausgabeNode.validate_config({"config": config})["valid"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,body,status", [
    ("list_documents", {"code": 500, "message": "Provider error"}, 200),
    ("list_documents", ["invalid record"], 200), ("get_preferences", [], 200),
    ("get_application_status", {"error": "Provider error"}, 200),
    ("list_documents", [], 302), ("list_documents", [], 429), ("set_preferences", {}, 500),
])
async def test_errors_are_not_success(monkeypatch, operation, body, status):
    transport(monkeypatch, body, status)
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await node({"operation": operation}).execute({})

"""BC Laws wire and parser tests use examples copied from its official API docs.

Exercise real node construction, metadata preservation, document markup,
paging limits and provider failures without an account or network calls.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import bclaws_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / "fixtures" / "bclaws"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def example(name):
    return (FIXTURES / name).read_text()


def node(config):
    return NodeFactory.create_node(node_id="bclaws-docs", node_type="automation-bclaws", node_data={"config": config})


def transport(monkeypatch, body, *, status=200, headers=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, text=body, headers=headers or {"Content-Type": "application/xml"})
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,aspect", [
    ("list_content", "complete"), ("list_statutes_and_regulations", "complete"),
    ("list_orders_in_council", "oic"), ("list_corporate_registry", "corpreg"),
])
async def test_public_collection_reads_publishers_xml(monkeypatch, operation, aspect):
    requests = transport(monkeypatch, example("content.xml"))
    result = await node({"operation": operation}).execute({})
    assert len(requests) == 1 and requests[0].method == "GET"
    assert str(requests[0].url) == native.BASE + "/content/" + aspect
    assert "authorization" not in requests[0].headers
    fields = result["items"][0]["fields"]
    assert fields["CIVIX_DOCUMENT_TITLE"] == "Statutes and Regulations"
    assert fields["CIVIX_DOCUMENT_ID"] == "statreg"
    assert len(fields["CIVIX_INDEX_FIELDS"]) == 12
    assert result["content"] == example("content.xml")


@pytest.mark.asyncio
async def test_directory_navigation_preserves_ids_and_booleans_as_published(monkeypatch):
    requests = transport(monkeypatch, example("directory.xml"))
    result = await node({"operation": "list_directory", "directory_id": "statreg"}).execute({})
    assert requests[0].url.path == "/civix/content/complete/statreg"
    assert len(result["items"]) == 2
    fields = result["items"][0]["fields"]
    assert fields["CIVIX_DOCUMENT_ID"] == "524872423"
    assert fields["CIVIX_DOCUMENT_VISIBLE"] == "true"


@pytest.mark.asyncio
async def test_search_required_parameters_and_documented_nested_snippet(monkeypatch):
    requests = transport(monkeypatch, example("search.xml"))
    result = await node({"operation": "search_documents", "query": "water"}).execute({})
    assert dict(requests[0].url.params) == {"q": "water", "s": "0", "e": "20", "nFrag": "5", "lFrag": "100"}
    assert requests[0].url.path == "/civix/search/complete/fullsearch"
    fields = result["items"][0]["fields"]
    assert fields["CIVIX_DOCUMENT_ID"] == "tlc96484"
    assert fields["CIVIX_DOCUMENT_ANCESTORS"] == ["tlc96484_f", "96484", "901199259", "statreg"]
    assert '<b loc="1">Water</b>' in fields["frag"]
    assert result["items"][0]["attributes"]["hits"] == "1"
    assert result["content"] == example("search.xml")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,suffix", [
    ("get_document_html", ""), ("get_document_xml", "/xml"),
    ("get_highlighted_document_html", '/search/%22protection%20plan%22'),
    ("get_highlighted_document_xml", '/xml/search/%22protection%20plan%22'),
])
async def test_document_routes_and_verbatim_publisher_excerpt(monkeypatch, operation, suffix):
    body = example("document-excerpt.xml")
    requests = transport(monkeypatch, body)
    config = {"operation": operation, "index_id": "statreg", "document_id": "01009_01"}
    if "highlighted" in operation:
        config["search_text"] = '"protection plan"'
    result = await node(config).execute({})
    assert str(requests[0].url) == native.BASE + "/document/id/complete/statreg/01009_01" + suffix
    assert result["content"] == body
    assert "items" not in result


@pytest.mark.asyncio
async def test_provider_migration_redirect_is_followed(monkeypatch):
    requests = []
    def reply(request):
        requests.append(request)
        if request.url.host == "www.bclaws.ca":
            return httpx.Response(301, headers={"Location": "https://www.bclaws.gov.bc.ca/civix/content/complete"})
        return httpx.Response(200, text=example("content.xml"))
    monkeypatch.setattr(native, "guarded_async_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply), **kw))
    result = await node({"operation": "list_content"}).execute({})
    assert len(requests) == 2
    assert result["url"] == "https://www.bclaws.gov.bc.ca/civix/content/complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404, 429, 500])
async def test_provider_errors_are_not_documents(monkeypatch, status):
    transport(monkeypatch, "Unavailable", status=status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({"operation": "list_content"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", "<html>Service unavailable</html>", "<root>", '<!DOCTYPE root [<!ENTITY x "boom">]><root>&x;</root>'])
async def test_reject_invalid_metadata_without_silent_empty_results(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({"operation": "list_content"}).execute({})


@pytest.mark.parametrize("changes", [{"start": 20, "end": 20}, {"end": 101}, {"fragment_count": 10}, {"fragment_length": 200}, {"query": "  "}])
def test_search_window_matches_provider_performance_limits(changes):
    with pytest.raises(ValidationError):
        native.SearchDocuments.model_validate({"query": "water", **changes})


@pytest.mark.parametrize("identifier", ["..", "a/b", "a?x=1", "a#b", "https://example.org", "a%2fb"])
def test_identifier_cannot_change_route(identifier):
    with pytest.raises(ValidationError):
        native.ListDirectory(directory_id=identifier)


def test_schema_is_credential_free_and_evidence_is_public():
    config = native.BCLawsConfig.model_validate({"config": {"operation": "list_content"}, "credentials": {}})
    assert config.credentials is None
    assert native.BCLawsNode.connection_evidence.proves == "reachability"
    assert len(native.Operation.__args__[0].__args__) == 10
    assert len(json.loads((FIXTURES / "sources.json").read_text())) == 5

"""Contract tests for Meilisearch request shaping and credential boundaries.

The transport is a recording fake; no account or external server is required.
"""

from contextlib import asynccontextmanager
import httpx
import pytest

from nodes import meilisearch_node as module


URL = "https://search.example.com"
KEY = "private-key"


class RecordingClient:
    def __init__(self, payload=None, status=200):
        self.calls = []
        self.payload = payload if payload is not None else {"taskUid": 42}
        self.status = status

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return httpx.Response(self.status, json=self.payload, request=httpx.Request(method, url))

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)


def install_client(monkeypatch, client):
    @asynccontextmanager
    async def fake_guarded_client(**_kwargs):
        yield client

    monkeypatch.setattr(module, "guarded_async_client", fake_guarded_client)


def make_node(config):
    return module.MeilisearchNode(
        node_id="test-meili",
        node_type="automation-meilisearch",
        node_data={},
        config=module.MeilisearchNodeConfig(
            config=config,
            credentials=module.MeilisearchCredential(url=URL, api_key=KEY),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "method", "path", "body", "params"),
    [
        (module.ListIndexes(limit=4, offset=2), "GET", "/indexes", None, {"limit": 4, "offset": 2}),
        (module.GetIndex(index_uid="books"), "GET", "/indexes/books", None, {}),
        (module.CreateIndex(index_uid="books", primary_key="id"), "POST", "/indexes", {"uid": "books", "primaryKey": "id"}, {}),
        (module.UpdateIndex(index_uid="books", primary_key="id"), "PATCH", "/indexes/books", {"primaryKey": "id"}, {}),
        (module.DeleteIndex(index_uid="books"), "DELETE", "/indexes/books", None, {}),
        (module.SwapIndexes(swaps_json='[{"indexes":["books","books_new"]}]'), "POST", "/swap-indexes", [{"indexes": ["books", "books_new"]}], {}),
        (module.ListDocuments(index_uid="books", limit=5, offset=10, fields="id,title"), "GET", "/indexes/books/documents", None, {"limit": 5, "offset": 10, "fields": "id,title"}),
        (module.GetDocument(index_uid="books", document_id="a/b +"), "GET", "/indexes/books/documents/a%2Fb%20%2B", None, {}),
        (module.AddDocuments(index_uid="books", documents_json='[{"id":1,"title":"A"}]', primary_key="id"), "POST", "/indexes/books/documents", [{"id": 1, "title": "A"}], {"primaryKey": "id"}),
        (module.UpdateDocuments(index_uid="books", documents_json='[{"id":1,"title":"B"}]'), "PUT", "/indexes/books/documents", [{"id": 1, "title": "B"}], {}),
        (module.DeleteDocument(index_uid="books", document_id="1"), "DELETE", "/indexes/books/documents/1", None, {}),
        (module.DeleteDocumentsBatch(index_uid="books", ids_json='[1,"2"]'), "POST", "/indexes/books/documents/delete-batch", [1, "2"], {}),
        (module.DeleteDocumentsByFilter(index_uid="books", filter_json='"genre = Horror"'), "POST", "/indexes/books/documents/delete", {"filter": "genre = Horror"}, {}),
        (module.DeleteAllDocuments(index_uid="books"), "DELETE", "/indexes/books/documents", None, {}),
        (module.Search(index_uid="books", query="space", filter_json='"genre = SciFi"', sort="year:desc", limit=3), "POST", "/indexes/books/search", {"q": "space", "filter": "genre = SciFi", "sort": ["year:desc"], "limit": 3, "offset": 0}, {}),
        (module.MultiSearch(queries_json='[{"indexUid":"books","q":"space"}]', federation_json='{"limit":10}'), "POST", "/multi-search", {"queries": [{"indexUid": "books", "q": "space"}], "federation": {"limit": 10}}, {}),
        (module.GetSettings(index_uid="books"), "GET", "/indexes/books/settings", None, {}),
        (module.UpdateSettings(index_uid="books", settings_json='{"filterableAttributes":["genre"]}'), "PATCH", "/indexes/books/settings", {"filterableAttributes": ["genre"]}, {}),
        (module.ResetSettings(index_uid="books"), "DELETE", "/indexes/books/settings", None, {}),
        (module.GetIndexStats(index_uid="books"), "GET", "/indexes/books/stats", None, {}),
        (module.GetTask(task_uid=42), "GET", "/tasks/42", None, {}),
        (module.ListTasks(limit=5, from_uid=30, statuses="enqueued,succeeded", index_uids="books"), "GET", "/tasks", None, {"limit": 5, "from": 30, "statuses": "enqueued,succeeded", "indexUids": "books"}),
    ],
    ids=lambda case: case.operation if isinstance(case, module.BaseModel) else None,
)
async def test_each_operation_shapes_request(monkeypatch, config, method, path, body, params):
    client = RecordingClient()
    install_client(monkeypatch, client)
    result = await make_node(config).execute({})
    assert result["status"] == "success"
    assert result["task_uid"] == 42
    assert client.calls == [(method, f"{URL}{path}", {
        "headers": {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        "params": params,
        "json": body,
    })]


@pytest.mark.asyncio
async def test_index_picker_uses_own_instance_and_filters(monkeypatch):
    client = RecordingClient({"results": [{"uid": "books"}, {"uid": "orders"}]})
    install_client(monkeypatch, client)
    options = await module.MeilisearchNode.load_field_options(
        "index_uid", {"url": URL, "api_key": KEY}, search="boo"
    )
    assert options == [{"value": "books", "label": "books"}]
    assert client.calls[0][1] == f"{URL}/indexes"
    assert client.calls[0][2]["headers"]["Authorization"] == f"Bearer {KEY}"


@pytest.mark.asyncio
async def test_api_errors_do_not_expose_key(monkeypatch):
    client = RecordingClient({"message": "Index not found", "code": "index_not_found"}, 404)
    install_client(monkeypatch, client)
    result = await make_node(module.GetIndex(index_uid="missing")).execute({})
    assert result == {
        "status": "error", "operation": "get_index", "status_code": 404, "error": "Index not found"
    }
    assert KEY not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        module.AddDocuments(index_uid="books", documents_json="{}"),
        module.DeleteDocumentsBatch(index_uid="books", ids_json="[]"),
        module.UpdateSettings(index_uid="books", settings_json="[]"),
        module.MultiSearch(queries_json='[{"q":"space"}]'),
        module.SwapIndexes(swaps_json='[{"indexes":["only_one"]}]'),
        module.Search(index_uid="books", filter_json="not json"),
    ],
)
async def test_invalid_structured_input_rejected_before_request(monkeypatch, config):
    client = RecordingClient()
    install_client(monkeypatch, client)
    with pytest.raises(ValueError):
        await make_node(config).execute({})
    assert not client.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://localhost:7700", "https://user:pass@example.com", "https://example.com/path"])
async def test_non_exact_https_origin_rejected(monkeypatch, url):
    client = RecordingClient()
    install_client(monkeypatch, client)
    node = make_node(module.ListIndexes())
    node.config.credentials.url = url
    with pytest.raises(ValueError):
        await node.execute({})
    assert not client.calls

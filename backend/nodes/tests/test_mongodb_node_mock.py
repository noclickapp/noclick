"""
Mock tests for MongoDBNode — covers all 38 operations without requiring
a live MongoDB connection. Motor's AsyncIOMotorClient is patched throughout.
"""

import importlib
import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# ---------------------------------------------------------------------------
# Stub motor and pymongo so the node's local imports don't fail at call time.
# Must be in sys.modules BEFORE the node module is imported below.
# ---------------------------------------------------------------------------
_motor_stub = MagicMock()
sys.modules.setdefault("motor", _motor_stub)
sys.modules.setdefault("motor.motor_asyncio", _motor_stub.motor_asyncio)

try:
    _pymongo_stub = importlib.import_module("pymongo")
except ImportError:
    _pymongo_stub = MagicMock()
    # real pymongo: ReturnDocument.BEFORE/AFTER are False/True
    _pymongo_stub.ReturnDocument.BEFORE = False
    _pymongo_stub.ReturnDocument.AFTER = True
    sys.modules.setdefault("pymongo", _pymongo_stub)
    sys.modules.setdefault("pymongo.operations", MagicMock())

from nodes.mongodb_node import (  # noqa: E402 - stubs must exist before import
    MongoDBNode,
    MongoDBNodeConfig,
    MongoDBCredential,
    # Documents
    MongoDBFindConfig,
    MongoDBFindOneConfig,
    MongoDBInsertOneConfig,
    MongoDBInsertManyConfig,
    MongoDBUpdateOneConfig,
    MongoDBUpdateManyConfig,
    MongoDBReplaceOneConfig,
    MongoDBDeleteOneConfig,
    MongoDBDeleteManyConfig,
    MongoDBCountDocumentsConfig,
    MongoDBEstimatedDocumentCountConfig,
    MongoDBDistinctConfig,
    MongoDBBulkWriteConfig,
    MongoDBFindOneAndUpdateConfig,
    MongoDBFindOneAndDeleteConfig,
    MongoDBFindOneAndReplaceConfig,
    # Aggregation
    MongoDBAggregatConfig,
    # Collections
    MongoDBListCollectionsConfig,
    MongoDBCreateCollectionConfig,
    MongoDBDropCollectionConfig,
    MongoDBRenameCollectionConfig,
    # Indexes
    MongoDBCreateIndexConfig,
    MongoDBListIndexesConfig,
    MongoDBDropIndexConfig,
    MongoDBDropIndexesConfig,
    # Atlas Vector Search
    MongoDBVectorSearchConfig,
    MongoDBCreateVectorSearchIndexConfig,
    MongoDBListSearchIndexesConfig,
    MongoDBUpdateSearchIndexConfig,
    MongoDBDeleteSearchIndexConfig,
    # Atlas Search
    MongoDBAtlasTextSearchConfig,
    MongoDBCreateAtlasSearchIndexConfig,
    # Database
    MongoDBListDatabasesConfig,
    MongoDBDropDatabaseConfig,
    MongoDBCommandConfig,
    # Upload & Index
    MongoDBUploadAndIndexConfig,
    # New 38-op additions
    MongoDBAtlasFacetSearchConfig,
    MongoDBCreateIndexesConfig,
)
from utils.ssrf import SSRFError  # noqa: E402 - same import-order constraint

CONN_STR = "mongodb://user:pass@localhost:27017/"


@pytest.fixture(autouse=True)
def allow_mock_private_database(monkeypatch):
    """Mock credentials intentionally point at localhost."""
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")


@pytest.fixture
def credentials():
    return MongoDBCredential(connection_string=CONN_STR)


def create_node(config):
    return MongoDBNode(
        node_id="test-mongodb-node",
        node_type="automation-mongodb",
        node_data={},
        config=config,
    )


def make_motor_mocks():
    """Return (mock_client, mock_db, mock_collection) wired with __getitem__."""
    mock_collection = MagicMock()
    mock_db = MagicMock()
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    mock_client.close = MagicMock()
    return mock_client, mock_db, mock_collection


def make_cursor(docs):
    """Cursor mock supporting sort/skip/limit chaining and async to_list."""
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=docs)
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    return cursor


class AsyncIterator:
    """Async iterable that yields items from a list — used for list_indexes cursor."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def patch_motor(mock_client):
    """Patch _get_client (the motor-client factory) to return mock_client."""
    return patch.object(MongoDBNode, "_get_client", return_value=mock_client)


# ---------------------------------------------------------------------------
# Documents — find
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_basic(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindConfig(database="mydb", collection="users"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    docs = [{"_id": "1", "name": "Alice"}, {"_id": "2", "name": "Bob"}]
    mock_collection.find.return_value = make_cursor(docs)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "find"
    assert result["count"] == 2
    assert result["documents"][0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_find_with_sort_skip_limit(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindConfig(
            database="mydb", collection="users",
            filter='{"status": "active"}',
            sort='{"createdAt": -1}',
            skip=5, limit=10,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    cursor = make_cursor([{"_id": "3", "status": "active"}])
    mock_collection.find.return_value = cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["count"] == 1
    cursor.sort.assert_called_once()
    cursor.skip.assert_called_once_with(5)
    cursor.limit.assert_called_once_with(10)


@pytest.mark.asyncio
async def test_find_empty_results(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindConfig(database="mydb", collection="users"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find.return_value = make_cursor([])

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["documents"] == []
    assert result["count"] == 0


# ---------------------------------------------------------------------------
# Documents — find_one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_one_found(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneConfig(
            database="mydb", collection="users",
            filter='{"_id": "abc"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one = AsyncMock(return_value={"_id": "abc", "name": "Alice"})

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "find_one"
    assert result["found"] is True
    assert result["document"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_find_one_not_found(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneConfig(
            database="mydb", collection="users",
            filter='{"_id": "missing"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one = AsyncMock(return_value=None)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["found"] is False
    assert result["document"] is None


# ---------------------------------------------------------------------------
# Documents — insert_one / insert_many
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_one(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBInsertOneConfig(
            database="mydb", collection="users",
            document='{"name": "Alice", "age": 30}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.inserted_id = "abc123"
    mock_collection.insert_one = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "insert_one"
    assert result["inserted_id"] == "abc123"
    mock_collection.insert_one.assert_called_once_with({"name": "Alice", "age": 30})


@pytest.mark.asyncio
async def test_insert_many(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBInsertManyConfig(
            database="mydb", collection="users",
            documents='[{"name": "Alice"}, {"name": "Bob"}]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.inserted_ids = ["id1", "id2"]
    mock_collection.insert_many = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "insert_many"
    assert result["inserted_count"] == 2
    assert result["inserted_ids"] == ["id1", "id2"]


# ---------------------------------------------------------------------------
# Documents — update_one / update_many
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_one_basic(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBUpdateOneConfig(
            database="mydb", collection="users",
            filter='{"_id": "abc"}',
            update='{"$set": {"status": "active"}}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.matched_count = 1
    mock_result.modified_count = 1
    mock_result.upserted_id = None
    mock_collection.update_one = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "update_one"
    assert result["matched_count"] == 1
    assert result["modified_count"] == 1
    assert result["upserted_id"] is None
    mock_collection.update_one.assert_called_once_with(
        {"_id": "abc"}, {"$set": {"status": "active"}}, upsert=False
    )


@pytest.mark.asyncio
async def test_update_one_upsert(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBUpdateOneConfig(
            database="mydb", collection="users",
            filter='{"email": "new@example.com"}',
            update='{"$setOnInsert": {"email": "new@example.com"}}',
            upsert="true",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.matched_count = 0
    mock_result.modified_count = 0
    mock_result.upserted_id = "new_id"
    mock_collection.update_one = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["upserted_id"] == "new_id"
    mock_collection.update_one.assert_called_once_with(
        {"email": "new@example.com"},
        {"$setOnInsert": {"email": "new@example.com"}},
        upsert=True,
    )


@pytest.mark.asyncio
async def test_update_many(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBUpdateManyConfig(
            database="mydb", collection="users",
            filter='{"status": "pending"}',
            update='{"$set": {"status": "archived"}}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.matched_count = 5
    mock_result.modified_count = 5
    mock_result.upserted_id = None
    mock_collection.update_many = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "update_many"
    assert result["matched_count"] == 5
    assert result["modified_count"] == 5


# ---------------------------------------------------------------------------
# Documents — replace_one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_one(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBReplaceOneConfig(
            database="mydb", collection="users",
            filter='{"_id": "abc"}',
            replacement='{"name": "Alice Updated", "age": 31}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.matched_count = 1
    mock_result.modified_count = 1
    mock_result.upserted_id = None
    mock_collection.replace_one = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "replace_one"
    assert result["matched_count"] == 1
    mock_collection.replace_one.assert_called_once_with(
        {"_id": "abc"}, {"name": "Alice Updated", "age": 31}, upsert=False
    )


# ---------------------------------------------------------------------------
# Documents — delete_one / delete_many
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_one(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDeleteOneConfig(
            database="mydb", collection="users",
            filter='{"_id": "abc"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.deleted_count = 1
    mock_collection.delete_one = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "delete_one"
    assert result["deleted_count"] == 1
    mock_collection.delete_one.assert_called_once_with({"_id": "abc"})


@pytest.mark.asyncio
async def test_delete_many(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDeleteManyConfig(
            database="mydb", collection="users",
            filter='{"status": "inactive"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.deleted_count = 7
    mock_collection.delete_many = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "delete_many"
    assert result["deleted_count"] == 7


# ---------------------------------------------------------------------------
# Documents — count_documents / estimated_document_count / distinct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_documents_no_filter(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCountDocumentsConfig(database="mydb", collection="users"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.count_documents = AsyncMock(return_value=42)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "count_documents"
    assert result["count"] == 42
    mock_collection.count_documents.assert_called_once_with({})


@pytest.mark.asyncio
async def test_count_documents_with_filter(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCountDocumentsConfig(
            database="mydb", collection="users",
            filter='{"status": "active"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.count_documents = AsyncMock(return_value=10)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["count"] == 10
    mock_collection.count_documents.assert_called_once_with({"status": "active"})


@pytest.mark.asyncio
async def test_estimated_document_count(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBEstimatedDocumentCountConfig(database="mydb", collection="users"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.estimated_document_count = AsyncMock(return_value=1000)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "estimated_document_count"
    assert result["count"] == 1000


@pytest.mark.asyncio
async def test_distinct_with_filter(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDistinctConfig(
            database="mydb", collection="users",
            field="status",
            filter='{"verified": true}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.distinct = AsyncMock(return_value=["active", "inactive", "pending"])

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "distinct"
    assert result["field"] == "status"
    assert result["count"] == 3
    assert "active" in result["values"]
    mock_collection.distinct.assert_called_once_with("status", filter={"verified": True})


@pytest.mark.asyncio
async def test_distinct_no_filter(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDistinctConfig(
            database="mydb", collection="orders",
            field="category",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.distinct = AsyncMock(return_value=["electronics", "clothing"])

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["count"] == 2
    mock_collection.distinct.assert_called_once_with("category", filter=None)


# ---------------------------------------------------------------------------
# Documents — bulk_write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_write(credentials):
    ops_json = (
        '[{"insertOne": {"document": {"x": 1}}}, '
        '{"updateOne": {"filter": {"x": 1}, "update": {"$set": {"y": 2}}}}, '
        '{"deleteOne": {"filter": {"x": 99}}}]'
    )
    config = MongoDBNodeConfig(
        config=MongoDBBulkWriteConfig(
            database="mydb", collection="items",
            operations=ops_json,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.inserted_count = 1
    mock_result.matched_count = 1
    mock_result.modified_count = 1
    mock_result.deleted_count = 1
    mock_result.upserted_count = 0
    mock_collection.bulk_write = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "bulk_write"
    assert result["inserted_count"] == 1
    assert result["deleted_count"] == 1
    mock_collection.bulk_write.assert_called_once()
    ops_passed = mock_collection.bulk_write.call_args[0][0]
    assert len(ops_passed) == 3


# ---------------------------------------------------------------------------
# Documents — find_one_and_update / find_one_and_delete / find_one_and_replace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_one_and_update_return_after(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneAndUpdateConfig(
            database="mydb", collection="tasks",
            filter='{"_id": "t1"}',
            update='{"$set": {"status": "done"}}',
            return_document="after",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one_and_update = AsyncMock(return_value={"_id": "t1", "status": "done"})

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "find_one_and_update"
    assert result["found"] is True
    assert result["document"]["status"] == "done"
    call_kwargs = mock_collection.find_one_and_update.call_args[1]
    # ReturnDocument.AFTER == True
    assert call_kwargs["return_document"] is True


@pytest.mark.asyncio
async def test_find_one_and_update_return_before(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneAndUpdateConfig(
            database="mydb", collection="tasks",
            filter='{"_id": "t1"}',
            update='{"$set": {"status": "done"}}',
            return_document="before",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one_and_update = AsyncMock(return_value={"_id": "t1", "status": "pending"})

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["document"]["status"] == "pending"
    call_kwargs = mock_collection.find_one_and_update.call_args[1]
    # ReturnDocument.BEFORE == False
    assert call_kwargs["return_document"] is False


@pytest.mark.asyncio
async def test_find_one_and_delete(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneAndDeleteConfig(
            database="mydb", collection="tokens",
            filter='{"token": "xyz"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one_and_delete = AsyncMock(return_value={"_id": "1", "token": "xyz"})

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "find_one_and_delete"
    assert result["found"] is True
    mock_collection.find_one_and_delete.assert_called_once_with({"token": "xyz"}, projection=None)


@pytest.mark.asyncio
async def test_find_one_and_delete_not_found(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneAndDeleteConfig(
            database="mydb", collection="tokens",
            filter='{"token": "nonexistent"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one_and_delete = AsyncMock(return_value=None)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["found"] is False
    assert result["document"] is None


@pytest.mark.asyncio
async def test_find_one_and_replace(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneAndReplaceConfig(
            database="mydb", collection="products",
            filter='{"sku": "ABC"}',
            replacement='{"sku": "ABC", "price": 99.99}',
            return_document="after",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one_and_replace = AsyncMock(
        return_value={"sku": "ABC", "price": 99.99}
    )

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "find_one_and_replace"
    assert result["document"]["price"] == 99.99


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate(credentials):
    pipeline_json = (
        '[{"$match": {"active": true}}, '
        '{"$group": {"_id": "$category", "count": {"$sum": 1}}}]'
    )
    config = MongoDBNodeConfig(
        config=MongoDBAggregatConfig(
            database="mydb", collection="orders",
            pipeline=pipeline_json,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    agg_cursor = MagicMock()
    agg_cursor.to_list = AsyncMock(return_value=[{"_id": "electronics", "count": 5}])
    mock_collection.aggregate.return_value = agg_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "aggregate"
    assert result["count"] == 1
    assert result["documents"][0]["_id"] == "electronics"
    called_pipeline = mock_collection.aggregate.call_args[0][0]
    assert called_pipeline[0]["$match"] == {"active": True}
    assert called_pipeline[1]["$group"]["_id"] == "$category"


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_collections_no_filter(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBListCollectionsConfig(database="mydb"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.list_collection_names = AsyncMock(return_value=["users", "orders", "products"])

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "list_collections"
    assert result["count"] == 3
    assert "users" in result["collections"]
    mock_db.list_collection_names.assert_called_once_with()


@pytest.mark.asyncio
async def test_list_collections_with_filter(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBListCollectionsConfig(
            database="mydb",
            filter='{"name": {"$regex": "^user"}}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.list_collection_names = AsyncMock(return_value=["users"])

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["count"] == 1
    mock_db.list_collection_names.assert_called_once_with(
        filter={"name": {"$regex": "^user"}}
    )


@pytest.mark.asyncio
async def test_create_collection_plain(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateCollectionConfig(database="mydb", name="events"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.create_collection = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "create_collection"
    assert result["collection"] == "events"
    mock_db.create_collection.assert_called_once_with("events")


@pytest.mark.asyncio
async def test_create_collection_capped(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateCollectionConfig(
            database="mydb", name="logs",
            capped="true", size=10485760, max=1000,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.create_collection = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    mock_db.create_collection.assert_called_once_with(
        "logs", capped=True, size=10485760, max=1000
    )


@pytest.mark.asyncio
async def test_drop_collection(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDropCollectionConfig(database="mydb", collection="old_data"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.drop_collection = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "drop_collection"
    assert result["collection"] == "old_data"
    mock_db.drop_collection.assert_called_once_with("old_data")


@pytest.mark.asyncio
async def test_rename_collection(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBRenameCollectionConfig(
            database="mydb", collection="users",
            new_name="members",
            drop_target="false",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.rename = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "rename_collection"
    assert result["old_name"] == "users"
    assert result["new_name"] == "members"
    mock_collection.rename.assert_called_once_with("members", dropTarget=False)


# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_index_basic(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateIndexConfig(
            database="mydb", collection="users",
            keys='{"email": 1}',
            unique="true",
            name="email_unique_idx",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.create_index = AsyncMock(return_value="email_unique_idx")

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "create_index"
    assert result["index_name"] == "email_unique_idx"
    mock_collection.create_index.assert_called_once_with(
        [("email", 1)],
        unique=True,
        sparse=False,
        hidden=False,
        name="email_unique_idx",
    )


@pytest.mark.asyncio
async def test_create_index_ttl(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateIndexConfig(
            database="mydb", collection="sessions",
            keys='{"expiredAt": 1}',
            expire_after_seconds=3600,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.create_index = AsyncMock(return_value="expiredAt_1")

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    call_kwargs = mock_collection.create_index.call_args[1]
    assert call_kwargs["expireAfterSeconds"] == 3600


@pytest.mark.asyncio
async def test_create_index_compound(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateIndexConfig(
            database="mydb", collection="orders",
            keys='{"userId": 1, "createdAt": -1}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.create_index = AsyncMock(return_value="userId_1_createdAt_-1")

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    keys_arg = mock_collection.create_index.call_args[0][0]
    assert ("userId", 1) in keys_arg
    assert ("createdAt", -1) in keys_arg


@pytest.mark.asyncio
async def test_list_indexes(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBListIndexesConfig(database="mydb", collection="users"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    index_info = {
        "_id_": {"key": [("_id", 1)], "ns": "mydb.users"},
        "email_1": {"key": [("email", 1)], "ns": "mydb.users", "unique": True},
    }
    mock_collection.index_information = AsyncMock(return_value=index_info)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "list_indexes"
    assert result["count"] == 2
    assert "_id_" in result["indexes"]
    assert "email_1" in result["indexes"]


@pytest.mark.asyncio
async def test_drop_index(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDropIndexConfig(
            database="mydb", collection="users",
            index_name="email_1",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.drop_index = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "drop_index"
    assert result["index_name"] == "email_1"
    mock_collection.drop_index.assert_called_once_with("email_1")


@pytest.mark.asyncio
async def test_drop_indexes(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDropIndexesConfig(database="mydb", collection="users"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.drop_indexes = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "drop_indexes"
    assert result["collection"] == "users"
    assert "All non-_id" in result["note"]
    mock_collection.drop_indexes.assert_called_once()


# ---------------------------------------------------------------------------
# Atlas Vector Search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vector_search_ann(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBVectorSearchConfig(
            database="mydb", collection="embeddings",
            index_name="vector_idx",
            path="embedding",
            query_vector="[0.1, 0.2, 0.3]",
            num_candidates=100,
            limit=5,
            exact="false",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    agg_cursor = MagicMock()
    agg_cursor.to_list = AsyncMock(return_value=[{"_id": "doc1", "text": "hello"}])
    mock_collection.aggregate.return_value = agg_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "vector_search"
    assert result["count"] == 1
    pipeline = mock_collection.aggregate.call_args[0][0]
    vs = pipeline[0]["$vectorSearch"]
    assert vs["numCandidates"] == 100
    assert "exact" not in vs
    assert vs["queryVector"] == [0.1, 0.2, 0.3]
    assert vs["index"] == "vector_idx"
    assert vs["path"] == "embedding"
    assert vs["limit"] == 5


@pytest.mark.asyncio
async def test_vector_search_exact(credentials):
    """exact=true uses ENN — must have `exact: True` and NO `numCandidates`."""
    config = MongoDBNodeConfig(
        config=MongoDBVectorSearchConfig(
            database="mydb", collection="embeddings",
            index_name="vector_idx",
            path="embedding",
            query_vector="[0.5, 0.6]",
            limit=3,
            exact="true",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    agg_cursor = MagicMock()
    agg_cursor.to_list = AsyncMock(return_value=[])
    mock_collection.aggregate.return_value = agg_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    pipeline = mock_collection.aggregate.call_args[0][0]
    vs = pipeline[0]["$vectorSearch"]
    assert vs["exact"] is True
    assert "numCandidates" not in vs


@pytest.mark.asyncio
async def test_vector_search_with_filter_and_projection(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBVectorSearchConfig(
            database="mydb", collection="embeddings",
            index_name="vector_idx",
            path="embedding",
            query_vector="[0.1]",
            limit=5,
            exact="false",
            filter='{"category": "news"}',
            project='{"title": 1, "score": {"$meta": "vectorSearchScore"}}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    agg_cursor = MagicMock()
    agg_cursor.to_list = AsyncMock(return_value=[{"title": "Breaking News"}])
    mock_collection.aggregate.return_value = agg_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    pipeline = mock_collection.aggregate.call_args[0][0]
    assert len(pipeline) == 2  # $vectorSearch + $project
    vs = pipeline[0]["$vectorSearch"]
    assert vs["filter"] == {"category": "news"}
    assert pipeline[1]["$project"]["title"] == 1


@pytest.mark.asyncio
async def test_create_vector_search_index(credentials):
    """SearchIndexModel must be called with type='vectorSearch' and correct fields."""
    config = MongoDBNodeConfig(
        config=MongoDBCreateVectorSearchIndexConfig(
            database="mydb", collection="embeddings",
            index_name="my_index",
            path="embedding",
            num_dimensions=1536,
            similarity="cosine",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.create_search_index = AsyncMock()

    with patch("pymongo.operations.SearchIndexModel") as MockModel, \
         patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "create_vector_search_index"
    assert result["index_name"] == "my_index"
    assert result["num_dimensions"] == 1536
    assert result["similarity"] == "cosine"
    MockModel.assert_called_once_with(
        definition={"fields": [
            {"type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine"}
        ]},
        name="my_index",
        type="vectorSearch",
    )
    mock_collection.create_search_index.assert_called_once_with(model=MockModel.return_value)


@pytest.mark.asyncio
async def test_create_vector_search_index_with_filter_fields(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateVectorSearchIndexConfig(
            database="mydb", collection="embeddings",
            index_name="vs_idx",
            path="embedding",
            num_dimensions=768,
            similarity="dotProduct",
            filter_fields="category, user_id",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.create_search_index = AsyncMock()

    with patch("pymongo.operations.SearchIndexModel") as MockModel, \
         patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["filter_fields"] == ["category", "user_id"]
    fields = MockModel.call_args[1]["definition"]["fields"]
    assert len(fields) == 3  # 1 vector + 2 filter
    assert fields[1] == {"type": "filter", "path": "category"}
    assert fields[2] == {"type": "filter", "path": "user_id"}


@pytest.mark.asyncio
async def test_list_search_indexes(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBListSearchIndexesConfig(database="mydb", collection="embeddings"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_search_cursor = MagicMock()
    mock_search_cursor.to_list = AsyncMock(
        return_value=[{"name": "myindex", "status": "READY", "type": "vectorSearch"}]
    )
    mock_collection.list_search_indexes.return_value = mock_search_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "list_search_indexes"
    assert result["count"] == 1
    assert result["indexes"][0]["name"] == "myindex"
    assert result["indexes"][0]["status"] == "READY"


@pytest.mark.asyncio
async def test_update_search_index(credentials):
    new_def = '{"fields": [{"type": "vector", "path": "embedding", "numDimensions": 3072, "similarity": "cosine"}]}'
    config = MongoDBNodeConfig(
        config=MongoDBUpdateSearchIndexConfig(
            database="mydb", collection="embeddings",
            index_name="vector_idx",
            definition=new_def,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.update_search_index = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "update_search_index"
    assert result["index_name"] == "vector_idx"
    mock_collection.update_search_index.assert_called_once_with(
        "vector_idx",
        {"fields": [{"type": "vector", "path": "embedding", "numDimensions": 3072, "similarity": "cosine"}]},
    )


@pytest.mark.asyncio
async def test_delete_search_index(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDeleteSearchIndexConfig(
            database="mydb", collection="embeddings",
            index_name="vector_idx",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.drop_search_index = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "delete_search_index"
    assert result["index_name"] == "vector_idx"
    mock_collection.drop_search_index.assert_called_once_with("vector_idx")


# ---------------------------------------------------------------------------
# Atlas Search (full-text)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atlas_text_search_all_fields(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBAtlasTextSearchConfig(
            database="mydb", collection="articles",
            index_name="default",
            query="machine learning",
            limit=5,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    agg_cursor = MagicMock()
    agg_cursor.to_list = AsyncMock(return_value=[{"title": "Intro to ML"}, {"title": "Deep Learning"}])
    mock_collection.aggregate.return_value = agg_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "atlas_text_search"
    assert result["count"] == 2
    pipeline = mock_collection.aggregate.call_args[0][0]
    search_stage = pipeline[0]["$search"]
    assert search_stage["index"] == "default"
    assert search_stage["text"]["query"] == "machine learning"
    # no search_fields set → wildcard path
    assert search_stage["text"]["path"] == {"wildcard": "*"}
    assert pipeline[1] == {"$limit": 5}


@pytest.mark.asyncio
async def test_atlas_text_search_fuzzy_specific_fields(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBAtlasTextSearchConfig(
            database="mydb", collection="articles",
            index_name="default",
            query="machien lerning",
            search_fields="title,description",
            fuzzy="true",
            limit=3,
            projection='{"title": 1, "score": {"$meta": "searchScore"}}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    agg_cursor = MagicMock()
    agg_cursor.to_list = AsyncMock(return_value=[{"title": "Machine Learning"}])
    mock_collection.aggregate.return_value = agg_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    pipeline = mock_collection.aggregate.call_args[0][0]
    assert len(pipeline) == 3  # $search + $limit + $project
    text_query = pipeline[0]["$search"]["text"]
    assert text_query["path"] == ["title", "description"]
    assert text_query["fuzzy"] == {}


@pytest.mark.asyncio
async def test_atlas_text_search_single_field(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBAtlasTextSearchConfig(
            database="mydb", collection="articles",
            index_name="default",
            query="python",
            search_fields="title",
            limit=10,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    agg_cursor = MagicMock()
    agg_cursor.to_list = AsyncMock(return_value=[])
    mock_collection.aggregate.return_value = agg_cursor

    with patch_motor(mock_client):
        await node.execute({})

    pipeline = mock_collection.aggregate.call_args[0][0]
    # single field → scalar path, not list
    assert pipeline[0]["$search"]["text"]["path"] == "title"


@pytest.mark.asyncio
async def test_create_atlas_search_index_dynamic(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateAtlasSearchIndexConfig(
            database="mydb", collection="articles",
            index_name="default",
            dynamic="true",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.create_search_index = AsyncMock()

    with patch("pymongo.operations.SearchIndexModel") as MockModel, \
         patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "create_atlas_search_index"
    assert result["dynamic"] is True
    MockModel.assert_called_once_with(
        definition={"mappings": {"dynamic": True}},
        name="default",
        type="search",
    )
    mock_collection.create_search_index.assert_called_once_with(model=MockModel.return_value)


@pytest.mark.asyncio
async def test_create_atlas_search_index_static_with_analyzer(credentials):
    field_mappings = '{"title": [{"type": "string", "analyzer": "lucene.standard"}]}'
    config = MongoDBNodeConfig(
        config=MongoDBCreateAtlasSearchIndexConfig(
            database="mydb", collection="articles",
            index_name="custom_idx",
            dynamic="false",
            field_mappings=field_mappings,
            analyzer="lucene.english",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.create_search_index = AsyncMock()

    with patch("pymongo.operations.SearchIndexModel") as MockModel, \
         patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    definition = MockModel.call_args[1]["definition"]
    assert definition["mappings"]["dynamic"] is False
    assert "fields" in definition["mappings"]
    assert definition["analyzer"] == "lucene.english"
    assert MockModel.call_args[1]["type"] == "search"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_databases(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBListDatabasesConfig(),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()
    mock_client.list_database_names = AsyncMock(return_value=["admin", "mydb", "test"])

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "list_databases"
    assert result["count"] == 3
    assert "mydb" in result["databases"]
    mock_client.list_database_names.assert_called_once()


@pytest.mark.asyncio
async def test_drop_database(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBDropDatabaseConfig(database="mydb"),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()
    mock_client.drop_database = AsyncMock()

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "drop_database"
    assert result["database"] == "mydb"
    mock_client.drop_database.assert_called_once_with("mydb")


@pytest.mark.asyncio
async def test_command_ping(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCommandConfig(
            database="admin",
            command='{"ping": 1}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.command = AsyncMock(return_value={"ok": 1.0})

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "command"
    assert result["result"]["ok"] == 1.0
    mock_db.command.assert_called_once_with({"ping": 1})


@pytest.mark.asyncio
async def test_command_server_status(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCommandConfig(
            database="admin",
            command='{"serverStatus": 1}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.command = AsyncMock(return_value={"ok": 1.0, "version": "7.0.0"})

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["result"]["version"] == "7.0.0"
    mock_db.command.assert_called_once_with({"serverStatus": 1})


# ---------------------------------------------------------------------------
# Upload & Index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_and_index(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBUploadAndIndexConfig(
            database="mydb", collection="docs",
            document="res-12345",
            vector_field="embedding",
            text_field="text",
            metadata_field="metadata",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    fake_records = [
        {
            "id": "doc-chunk-0",
            "values": [0.1, 0.2, 0.3],
            "metadata": {"text": "Hello world", "source": "test.pdf", "chunk_index": 0},
        },
        {
            "id": "doc-chunk-1",
            "values": [0.4, 0.5, 0.6],
            "metadata": {"text": "Goodbye world", "source": "test.pdf", "chunk_index": 1},
        },
    ]
    mock_result = MagicMock()
    mock_result.inserted_ids = ["doc-chunk-0", "doc-chunk-1"]
    mock_collection.insert_many = AsyncMock(return_value=mock_result)

    with patch("nodes.mongodb_node.ingest_document",
               new=AsyncMock(return_value=(fake_records, {"filename": "test.pdf"}))), \
         patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "upload_and_index"
    assert result["chunks_indexed"] == 2
    assert result["source"] == "test.pdf"
    assert result["collection"] == "docs"
    assert result["database"] == "mydb"

    inserted_docs = mock_collection.insert_many.call_args[0][0]
    assert inserted_docs[0]["_id"] == "doc-chunk-0"
    assert inserted_docs[0]["embedding"] == [0.1, 0.2, 0.3]
    assert inserted_docs[0]["text"] == "Hello world"
    mock_collection.insert_many.assert_called_once_with(inserted_docs, ordered=False)


@pytest.mark.asyncio
async def test_upload_and_index_no_records(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBUploadAndIndexConfig(
            database="mydb", collection="docs",
            document="res-empty",
        ),
        credentials=credentials,
    )
    node = create_node(config)

    with patch("nodes.mongodb_node.ingest_document",
               new=AsyncMock(return_value=([], {"filename": "empty.txt"}))):
        result = await node.execute({})

    assert result["status"] == "error"
    assert "No text" in result["error"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_credentials_raises():
    config = MongoDBNodeConfig(
        config=MongoDBListDatabasesConfig(),
        credentials=None,
    )
    node = create_node(config)
    with pytest.raises(ValueError, match="[Cc]redentials"):
        await node.execute({})


def test_get_client_empty_connection_string_raises():
    """_get_client itself raises when the credential dict has no connection string."""
    # motor.motor_asyncio is stubbed in sys.modules so the local import succeeds.
    with pytest.raises(ValueError, match="connection string"):
        MongoDBNode._get_client({})


@pytest.mark.asyncio
async def test_find_invalid_filter_json(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindConfig(
            database="mydb", collection="users",
            filter="not-valid-json{{{",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        with pytest.raises(ValueError, match="filter"):
            await node.execute({})


@pytest.mark.asyncio
async def test_insert_one_invalid_document_json(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBInsertOneConfig(
            database="mydb", collection="users",
            document="[this is not json]",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        with pytest.raises(ValueError, match="document"):
            await node.execute({})


@pytest.mark.asyncio
async def test_insert_many_not_array_raises(credentials):
    """insert_many requires a JSON array, not an object."""
    config = MongoDBNodeConfig(
        config=MongoDBInsertManyConfig(
            database="mydb", collection="users",
            documents='{"name": "Alice"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        with pytest.raises(ValueError, match="JSON array"):
            await node.execute({})


@pytest.mark.asyncio
async def test_aggregate_not_array_pipeline_raises(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBAggregatConfig(
            database="mydb", collection="orders",
            pipeline='{"$match": {"active": true}}',  # object, not array
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.aggregate.return_value = MagicMock()

    with patch_motor(mock_client):
        with pytest.raises(ValueError, match="JSON array"):
            await node.execute({})


@pytest.mark.asyncio
async def test_vector_search_query_vector_not_array_raises(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBVectorSearchConfig(
            database="mydb", collection="embeddings",
            index_name="vector_idx",
            path="embedding",
            query_vector='{"not": "an-array"}',
            limit=5,
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        with pytest.raises(ValueError, match="query_vector"):
            await node.execute({})


@pytest.mark.asyncio
async def test_bulk_write_invalid_json_raises(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBBulkWriteConfig(
            database="mydb", collection="items",
            operations="not json at all",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        with pytest.raises(ValueError, match="operations"):
            await node.execute({})


@pytest.mark.asyncio
async def test_bulk_write_unknown_op_type_raises(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBBulkWriteConfig(
            database="mydb", collection="items",
            operations='[{"unknownOp": {"document": {"x": 1}}}]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        with pytest.raises(ValueError, match="Unknown bulk write operation"):
            await node.execute({})


@pytest.mark.asyncio
async def test_command_not_object_raises(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCommandConfig(
            database="admin",
            command='"just a string"',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        with pytest.raises(ValueError, match="JSON object"):
            await node.execute({})


# ---------------------------------------------------------------------------
# load_field_options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_field_options_database():
    mock_client, _, _ = make_motor_mocks()
    mock_client.list_database_names = AsyncMock(return_value=["admin", "mydb", "test"])

    with patch_motor(mock_client):
        options = await MongoDBNode.load_field_options(
            field_name="database",
            credential_data={"connection_string": CONN_STR},
        )

    assert len(options) == 3
    values = {o["value"] for o in options}
    assert "mydb" in values
    assert all(o["label"] == o["value"] for o in options)


@pytest.mark.asyncio
async def test_load_field_options_collection():
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.list_collection_names = AsyncMock(return_value=["users", "orders"])

    with patch_motor(mock_client):
        options = await MongoDBNode.load_field_options(
            field_name="collection",
            credential_data={"connection_string": CONN_STR},
            context={"database": "mydb"},
        )

    assert len(options) == 2
    assert {o["value"] for o in options} == {"users", "orders"}


@pytest.mark.asyncio
async def test_load_field_options_collection_no_db_returns_empty():
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        options = await MongoDBNode.load_field_options(
            field_name="collection",
            credential_data={"connection_string": CONN_STR},
            context={},
        )

    assert options == []


@pytest.mark.asyncio
async def test_load_field_options_index_name():
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.list_indexes.return_value = AsyncIterator([
        {"name": "_id_"},
        {"name": "email_1"},
        {"name": "status_1"},
    ])

    with patch_motor(mock_client):
        options = await MongoDBNode.load_field_options(
            field_name="index_name",
            credential_data={"connection_string": CONN_STR},
            context={"database": "mydb", "collection": "users"},
        )

    assert len(options) == 3
    values = {o["value"] for o in options}
    assert "email_1" in values
    assert "_id_" in values


@pytest.mark.asyncio
async def test_load_field_options_index_name_missing_db_returns_empty():
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        options = await MongoDBNode.load_field_options(
            field_name="index_name",
            credential_data={"connection_string": CONN_STR},
            context={"collection": "users"},  # no database
        )

    assert options == []


@pytest.mark.asyncio
async def test_load_field_options_index_name_missing_collection_returns_empty():
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        options = await MongoDBNode.load_field_options(
            field_name="index_name",
            credential_data={"connection_string": CONN_STR},
            context={"database": "mydb"},  # no collection
        )

    assert options == []


@pytest.mark.asyncio
async def test_load_field_options_unknown_field_returns_empty():
    mock_client, _, _ = make_motor_mocks()

    with patch_motor(mock_client):
        options = await MongoDBNode.load_field_options(
            field_name="unknown_field",
            credential_data={"connection_string": CONN_STR},
        )

    assert options == []


@pytest.mark.asyncio
async def test_load_field_options_search_filter():
    mock_client, _, _ = make_motor_mocks()
    mock_client.list_database_names = AsyncMock(
        return_value=["admin", "mydb", "production", "mytest"]
    )

    with patch_motor(mock_client):
        options = await MongoDBNode.load_field_options(
            field_name="database",
            credential_data={"connection_string": CONN_STR},
            search="my",
        )

    assert len(options) == 2
    values = {o["value"] for o in options}
    assert values == {"mydb", "mytest"}


@pytest.mark.asyncio
async def test_load_field_options_returns_empty_on_exception():
    """Any error inside load_field_options is caught and returns []."""
    with patch.object(MongoDBNode, "_get_client", side_effect=Exception("connection refused")):
        options = await MongoDBNode.load_field_options(
            field_name="database",
            credential_data={"connection_string": CONN_STR},
        )

    assert options == []


# ---------------------------------------------------------------------------
# New parameter tests (38-op additions)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_one_and_update_with_sort(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneAndUpdateConfig(
            database="mydb",
            collection="orders",
            filter='{"status": "pending"}',
            update='{"$set": {"status": "processing"}}',
            sort='{"createdAt": 1}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one_and_update = AsyncMock(return_value={"_id": "1", "status": "pending"})

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    call_kwargs = mock_collection.find_one_and_update.call_args
    # sort should be passed as list of tuples
    assert call_kwargs.kwargs.get("sort") == [("createdAt", 1)]


@pytest.mark.asyncio
async def test_find_one_and_delete_with_sort(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindOneAndDeleteConfig(
            database="mydb",
            collection="logs",
            filter='{"level": "debug"}',
            sort='{"timestamp": 1}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.find_one_and_delete = AsyncMock(return_value={"_id": "x"})

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert mock_collection.find_one_and_delete.call_args.kwargs.get("sort") == [("timestamp", 1)]


@pytest.mark.asyncio
async def test_update_one_with_array_filters(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBUpdateOneConfig(
            database="mydb",
            collection="grades",
            filter='{"_id": "student1"}',
            update='{"$set": {"scores.$[elem].grade": "A"}}',
            array_filters='[{"elem.score": {"$gte": 90}}]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.matched_count = 1
    mock_result.modified_count = 1
    mock_result.upserted_id = None
    mock_collection.update_one = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    call_kwargs = mock_collection.update_one.call_args.kwargs
    assert call_kwargs.get("array_filters") == [{"elem.score": {"$gte": 90}}]


@pytest.mark.asyncio
async def test_insert_many_ordered_false(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBInsertManyConfig(
            database="mydb",
            collection="items",
            documents='[{"a": 1}, {"b": 2}]',
            ordered="false",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.inserted_ids = ["id1", "id2"]
    mock_collection.insert_many = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert mock_collection.insert_many.call_args.kwargs.get("ordered") is False


@pytest.mark.asyncio
async def test_insert_many_ordered_true(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBInsertManyConfig(
            database="mydb",
            collection="items",
            documents='[{"a": 1}]',
            ordered="true",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.inserted_ids = ["id1"]
    mock_collection.insert_many = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        await node.execute({})

    assert mock_collection.insert_many.call_args.kwargs.get("ordered") is True


@pytest.mark.asyncio
async def test_aggregate_allow_disk_use(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBAggregatConfig(
            database="mydb",
            collection="sales",
            pipeline='[{"$group": {"_id": "$region", "total": {"$sum": "$amount"}}}]',
            allow_disk_use="true",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[{"_id": "east", "total": 100}])
    mock_collection.aggregate.return_value = mock_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert mock_collection.aggregate.call_args.kwargs.get("allowDiskUse") is True


@pytest.mark.asyncio
async def test_atlas_text_search_with_search_operator(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBAtlasTextSearchConfig(
            database="mydb",
            collection="products",
            index_name="default",
            query="coffee",
            search_operator='{"compound": {"must": [{"text": {"query": "coffee", "path": "name"}}]}}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[{"name": "Coffee Blend"}])
    mock_collection.aggregate.return_value = mock_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    pipeline = mock_collection.aggregate.call_args.args[0]
    search_stage = pipeline[0]["$search"]
    # compound operator should be injected directly
    assert "compound" in search_stage


@pytest.mark.asyncio
async def test_vector_search_with_score_details(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBVectorSearchConfig(
            database="mydb",
            collection="docs",
            index_name="vector_idx",
            query_vector="[0.1, 0.2, 0.3]",
            path="embedding",
            num_candidates=50,
            limit=5,
            score_details="true",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_collection.aggregate.return_value = mock_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    pipeline = mock_collection.aggregate.call_args.args[0]
    vector_stage = pipeline[0]["$vectorSearch"]
    assert vector_stage.get("scoreDetails") is True


@pytest.mark.asyncio
async def test_atlas_facet_search(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBAtlasFacetSearchConfig(
            database="mydb",
            collection="products",
            index_name="default",
            query="electronics",
            facets='{"category": {"type": "string", "path": "category"}}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    facet_result = [{"count": {"lowerBound": 100}, "facet": {"category": {"buckets": []}}}]
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=facet_result)
    mock_collection.aggregate.return_value = mock_cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "atlas_facet_search"
    pipeline = mock_collection.aggregate.call_args.args[0]
    assert "$searchMeta" in pipeline[0]
    search_meta = pipeline[0]["$searchMeta"]
    assert search_meta["index"] == "default"
    assert "facet" in search_meta


@pytest.mark.asyncio
async def test_create_indexes_batch(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateIndexesConfig(
            database="mydb",
            collection="users",
            indexes='[{"keys": {"email": 1}, "unique": true}, {"keys": {"createdAt": 1}, "expireAfterSeconds": 3600}]',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_collection.create_indexes = AsyncMock(return_value=["email_1", "createdAt_1"])

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == "create_indexes"
    assert mock_collection.create_indexes.called


@pytest.mark.asyncio
async def test_find_with_hint_and_collation(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBFindConfig(
            database="mydb",
            collection="products",
            hint='{"price": 1}',
            collation='{"locale": "en", "strength": 2}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    cursor = make_cursor([])
    # hint and collation return the same cursor (chaining)
    cursor.hint.return_value = cursor
    cursor.collation.return_value = cursor
    mock_collection.find.return_value = cursor

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    cursor.hint.assert_called_once_with({"price": 1})
    cursor.collation.assert_called_once_with({"locale": "en", "strength": 2})


@pytest.mark.asyncio
async def test_create_collection_with_validator(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateCollectionConfig(
            database="mydb",
            name="validated_users",
            validator='{"$jsonSchema": {"bsonType": "object", "required": ["email"]}}',
            validation_level="strict",
            validation_action="error",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.create_collection = AsyncMock(return_value=MagicMock())

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    call_kwargs = mock_db.create_collection.call_args.kwargs
    assert "validator" in call_kwargs
    assert call_kwargs["validationLevel"] == "strict"
    assert call_kwargs["validationAction"] == "error"


@pytest.mark.asyncio
async def test_create_collection_timeseries(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBCreateCollectionConfig(
            database="mydb",
            name="sensor_data",
            time_field="timestamp",
            meta_field="sensorId",
            granularity="minutes",
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, mock_db, _ = make_motor_mocks()
    mock_db.create_collection = AsyncMock(return_value=MagicMock())

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    call_kwargs = mock_db.create_collection.call_args.kwargs
    assert "timeseries" in call_kwargs
    ts = call_kwargs["timeseries"]
    assert ts["timeField"] == "timestamp"
    assert ts["metaField"] == "sensorId"
    assert ts["granularity"] == "minutes"


@pytest.mark.asyncio
async def test_update_many_with_hint_and_collation(credentials):
    config = MongoDBNodeConfig(
        config=MongoDBUpdateManyConfig(
            database="mydb",
            collection="products",
            filter='{"category": "books"}',
            update='{"$inc": {"viewCount": 1}}',
            hint='{"category": 1}',
            collation='{"locale": "en"}',
        ),
        credentials=credentials,
    )
    node = create_node(config)
    mock_client, _, mock_collection = make_motor_mocks()
    mock_result = MagicMock()
    mock_result.matched_count = 5
    mock_result.modified_count = 5
    mock_result.upserted_id = None
    mock_collection.update_many = AsyncMock(return_value=mock_result)

    with patch_motor(mock_client):
        result = await node.execute({})

    assert result["status"] == "success"
    call_kwargs = mock_collection.update_many.call_args.kwargs
    assert call_kwargs.get("hint") == {"category": 1}
    assert call_kwargs.get("collation") == {"locale": "en"}


@pytest.mark.parametrize(
    "unsafe_option",
    [
        "authMechanism=MONGODB-OIDC",
        "authMechanism=MONGODB-AWS",
        "authMechanism=GSSAPI",
        "authMechanism=MONGODB-X509",
        "authMechanism=PLAIN",
        "AuThMeChAnIsM=MONGODB%2DOIDC",
        "auth%4Dechanism=MONGODB%2DAWS",
        "authMechanismProperties=ENVIRONMENT:azure",
        "AuThMeChAnIsMpRoPeRtIeS=SERVICE_NAME:mongodb",
        "authMechanism%50roperties=AWS_SESSION_TOKEN:token",
        "tlsCertificateKeyFile=%2Fetc%2Fssl%2Fprivate%2Fclient.pem",
        "tLsCeRtIfIcAtEkEyFiLePaSsWoRd=secret",
        "tlsCAFile=%2Fetc%2Fssl%2Fcerts%2Fca.pem",
        "tls%43RLFile=%2Fetc%2Fssl%2Fcrl.pem",
        "proxyHost=127.0.0.1",
        "PrOxYpOrT=1080",
        "proxyUsername=runtime-user",
        "pro%78yPassword=runtime-secret",
    ],
)
def test_client_rejects_ambient_credential_options_before_motor_or_file_access(
    monkeypatch, unsafe_option
):
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    uri = f"mongodb://user:pass@db.public.example:27017/app?tls=true&{unsafe_option}"

    with (
        patch("motor.motor_asyncio.AsyncIOMotorClient") as constructor,
        patch("builtins.open") as local_file,
        pytest.raises(SSRFError),
    ):
        MongoDBNode._get_client({"connection_string": uri})

    constructor.assert_not_called()
    local_file.assert_not_called()


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://user:pass@db.public.example:27017/app"
        "#?authMechanism=MONGODB-OIDC",
        "mongodb://user:pass@db.public.example:27017/app"
        "#?tlsCertificateKeyFile=%2Fetc%2Fssl%2Fprivate%2Fclient.pem",
    ],
)
def test_client_uses_pymongo_query_delimiter_grammar(monkeypatch, uri):
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)

    with (
        patch("motor.motor_asyncio.AsyncIOMotorClient") as constructor,
        patch("builtins.open") as local_file,
        pytest.raises(SSRFError),
    ):
        MongoDBNode._get_client({"connection_string": uri})

    constructor.assert_not_called()
    local_file.assert_not_called()


@pytest.mark.parametrize(
    ("uri", "expected_kwargs"),
    [
        (
            "mongodb+srv://user:pass@cluster.abc.mongodb.net/app"
            "?authMechanism=SCRAM-SHA-256",
            {"serverSelectionTimeoutMS": 10000},
        ),
        (
            "mongodb://user:pass@db.public.example:27017/app"
            "?tls=true&authMechanism=SCRAM-SHA-1",
            {"serverSelectionTimeoutMS": 10000, "directConnection": True},
        ),
        (
            "mongodb://user:pass@db.public.example:27017/app?tls=true",
            {"serverSelectionTimeoutMS": 10000, "directConnection": True},
        ),
        (
            "mongodb://user:pass@db.public.example:27017/app"
            "?tls=true&authMechanism=DEFAULT",
            {"serverSelectionTimeoutMS": 10000, "directConnection": True},
        ),
    ],
)
def test_client_preserves_scram_and_default_auth(monkeypatch, uri, expected_kwargs):
    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    client = object()

    with patch(
        "motor.motor_asyncio.AsyncIOMotorClient", return_value=client
    ) as constructor:
        assert MongoDBNode._get_client({"connection_string": uri}) is client

    constructor.assert_called_once_with(uri, **expected_kwargs)


def test_private_network_opt_out_preserves_ambient_auth_options(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    uri = (
        "mongodb://internal-db:27017/app?authMechanism=MONGODB-OIDC"
        "&tlsCAFile=/trusted/internal-ca.pem"
    )

    with patch("motor.motor_asyncio.AsyncIOMotorClient") as constructor:
        MongoDBNode._get_client({"connection_string": uri})

    constructor.assert_called_once_with(uri, serverSelectionTimeoutMS=10000)

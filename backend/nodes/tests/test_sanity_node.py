"""Contract tests for the Sanity Content Lake node.

These assert the documented endpoint, method, and payload for each operation,
then verify local input validation and safe handling of provider failures.
"""

import json
from unittest.mock import Mock

import httpx
import pytest

from nodes.sanity_node import SanityNode, SanityNodeConfig, SanityRobotTokenCredential


def make_node(operation: str, **fields):
    credential = SanityRobotTokenCredential(project_id="rfdvp4hs", api_token="secret-test-token")
    config = SanityNodeConfig.model_validate({
        "config": {"operation": operation, **fields},
        "credentials": credential.model_dump(),
    })
    return SanityNode(
        node_id="sanity-test", node_type="automation-sanity", node_data={},
        config=config, sio=Mock(), sid="test", workflow_id="test", user_id="test",
    )


@pytest.fixture
def requests(monkeypatch):
    seen = []

    async def fake_request(token, method, url, *, params=None, body=None, timeout=30.0):
        seen.append({"token": token, "method": method, "url": url,
                     "params": params, "body": body, "timeout": timeout})
        return {"results": [{"documentId": "doc-1"}], "result": [{"_id": "doc-1"}]}

    monkeypatch.setattr("nodes.sanity_node._request", fake_request)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,method,path,body", [
    ("list_datasets", {}, "GET", "/projects/rfdvp4hs/datasets", None),
    ("create_dataset", {"name": "staging", "visibility": "private"}, "PUT",
     "/projects/rfdvp4hs/datasets/staging", {"aclMode": "private"}),
    ("delete_dataset", {"name": "staging"}, "DELETE", "/projects/rfdvp4hs/datasets/staging", None),
    ("query_documents", {"query": '*[_type==$kind]', "params_json": '{"kind":"post"}'},
     "POST", "/data/query/production", {"query": '*[_type==$kind]', "params": {"kind": "post"}}),
    ("get_document", {"document_id": "post-1"}, "GET", "/data/doc/production/post-1", None),
    ("create_document", {"document_json": '{"_type":"post","title":"Hi"}'}, "POST",
     "/data/mutate/production", {"mutations": [{"create": {"_type": "post", "title": "Hi"}}]}),
    ("replace_document", {"document_json": '{"_id":"post-1","_type":"post"}'}, "POST",
     "/data/mutate/production", {"mutations": [{"createOrReplace": {"_id": "post-1", "_type": "post"}}]}),
    ("patch_document", {"document_id": "post-1", "set_json": '{"title":"Updated"}', "unset_json": '["old"]'},
     "POST", "/data/mutate/production", {"mutations": [{"patch": {"id": "post-1", "set": {"title": "Updated"}, "unset": ["old"]}}]}),
    ("delete_document", {"document_id": "post-1"}, "POST", "/data/mutate/production",
     {"mutations": [{"delete": {"id": "post-1"}}]}),
    ("list_assets", {"asset_type": "images", "limit": 10}, "POST", "/data/query/production",
     {"query": '*[_type in ["sanity.imageAsset"]] | order(_createdAt desc)[0...10]'}),
    ("upload_image_url", {"url": "https://example.com/image.png", "filename": "image.png"}, "POST",
     "/assets/images/production/from-url", {"url": "https://example.com/image.png", "filename": "image.png"}),
    ("upload_file_url", {"url": "https://example.com/data.pdf"}, "POST",
     "/assets/files/production/from-url", {"url": "https://example.com/data.pdf"}),
])
async def test_operation_contracts(requests, operation, fields, method, path, body):
    result = await make_node(operation, **fields).execute({})
    assert result["status"] == "success"
    assert result["action"] == operation
    assert len(requests) == 1
    sent = requests[0]
    assert sent["token"] == "secret-test-token"
    assert sent["method"] == method
    assert sent["url"].endswith(path)
    assert sent["body"] == body
    if operation.endswith("document") and operation != "get_document":
        assert sent["params"] == {"returnIds": "true", "visibility": "sync"}
    if operation == "query_documents":
        assert sent["params"] == {"perspective": "published"}
    if operation.startswith("upload_"):
        assert sent["timeout"] == 330.0


@pytest.mark.asyncio
async def test_dataset_options_are_authenticated_and_searchable(requests):
    async def list_datasets(token, method, url, **kwargs):
        assert token == "secret-test-token"
        return [{"name": "production"}, {"name": "staging"}]

    from unittest.mock import patch
    with patch("nodes.sanity_node._request", list_datasets):
        result = await SanityNode.load_field_options(
            "dataset", {"project_id": "rfdvp4hs", "api_token": "secret-test-token"},
            search="prod",
        )
    assert result["options"] == [{"value": "production", "label": "production"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fields,error", [
    ("create_document", {"document_json": '{"title":"Missing type"}'}, "_type"),
    ("create_document", {"document_json": "{"}, "invalid JSON"),
    ("replace_document", {"document_json": '{"_type":"post"}'}, "_id"),
    ("patch_document", {"document_id": "post-1"}, "requires fields"),
    ("patch_document", {"document_id": "post-1", "unset_json": "[1]"}, "only strings"),
    ("upload_image_url", {"url": "http://example.com/image.png"}, "public HTTPS"),
    ("upload_file_url", {"url": "https://user:pass@example.com/data.pdf"}, "embedded credentials"),
    ("get_document", {"document_id": "post-1", "dataset": "bad/path"}, "dataset name"),
])
async def test_invalid_inputs_never_call_sanity(requests, operation, fields, error):
    with pytest.raises(ValueError, match=error):
        await make_node(operation, **fields).execute({})
    assert requests == []


@pytest.mark.asyncio
async def test_provider_failure_does_not_echo_content_or_token(monkeypatch):
    from nodes.sanity_node import _request

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def request(self, method, url, **kwargs):
            return httpx.Response(403, json={"message": "private customer content"},
                                  request=httpx.Request(method, url))

    monkeypatch.setattr("nodes.sanity_node.httpx.AsyncClient", lambda **_: Client())
    with pytest.raises(ValueError) as exc:
        await _request("secret-test-token", "GET", "https://api.sanity.io/v2025-02-19/projects/rfdvp4hs/datasets")
    assert "HTTP 403" in str(exc.value)
    assert "secret-test-token" not in str(exc.value)
    assert "private customer content" not in str(exc.value)


def test_generated_schema_has_credential_and_all_operations():
    schema = SanityNode.get_config_schema()
    dumped = json.dumps(schema)
    assert "SanityRobotTokenCredential" in dumped
    assert "sanity_robot_token" in dumped
    assert all(name in dumped for name in (
        "query_documents", "create_document", "patch_document", "delete_document",
        "upload_image_url", "create_dataset", "delete_dataset",
    ))


def test_dataset_creation_tracks_the_actual_management_api_resource_id():
    schema = SanityNode.get_config_schema()
    create = schema["$defs"]["SanityCreateDatasetConfig"]["properties"]
    assert create["operation"]["x-resource-id-path"] == "data.datasetName"
    assert create["visibility"]["default"] == "private"
    assert create["visibility"]["enum"][0] == "private"

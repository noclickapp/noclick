"""Directus node contracts, credential handling, and response safety."""

import base64
import json
from pathlib import Path

import httpx
import pytest

from nodes import directus_node as directus


@pytest.fixture
def credential():
    return directus.DirectusStaticTokenCredential(
        instance_url="https://cms.example.com",
        static_token="private-test-token",
    )


def _values(fields):
    defaults = {
        "collection": "articles",
        "collection_name": "articles",
        "item_id": "a/b",
        "field_name": "title",
        "field_type": "string",
        "file_id": "file-1",
        "folder_id": "folder-1",
        "folder_name": "NoClick QA",
        "file_name": "qa.txt",
        "content_base64": base64.b64encode(b"hello directus").decode(),
        "payload_json": '{"title":"NoClick QA"}',
    }
    return {field: defaults[field] for field in fields if field in defaults}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,label,category,method,path,fields", directus._SPECS)
async def test_each_operation_uses_its_documented_method_and_path(
    monkeypatch, credential, name, label, category, method, path, fields
):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer private-test-token"
        return httpx.Response(200, json={"data": {"id": "created"}})

    monkeypatch.setattr(
        directus,
        "guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    config = directus._MODELS[name](**_values(fields))
    node = directus.DirectusNode(
        node_id="qa",
        node_type="automation-directus",
        node_data={},
        config=directus.DirectusNodeConfig(config=config, credentials=credential),
    )
    result = await node.execute({})

    assert result["status"] == "success"
    assert result["action"] == name
    assert len(seen) == 1
    assert seen[0].method == method
    expected = path.format(
        collection="articles",
        item_id="a%2Fb",
        field_name="title",
        file_id="file-1",
        folder_id="folder-1",
    )
    assert seen[0].url.raw_path.decode().split("?", 1)[0] == expected
    assert "private-test-token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_content_filter_and_write_body(monkeypatch, credential):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": 1, "title": "Draft"}]})

    monkeypatch.setattr(
        directus,
        "guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    listed = directus._MODELS["list_items"](
        collection="articles", limit="5", filter_json='{"status":{"_eq":"draft"}}'
    )
    result = await directus._call(credential, "list_items", listed)
    assert result["data"][0]["title"] == "Draft"
    assert seen[0].url.params["limit"] == "5"
    assert json.loads(seen[0].url.params["filter"]) == {"status": {"_eq": "draft"}}

    created = directus._MODELS["create_item"](
        collection="articles", payload_json='{"title":"New"}'
    )
    await directus._call(credential, "create_item", created)
    assert json.loads(seen[1].content) == {"title": "New"}


@pytest.mark.asyncio
async def test_user_read_cannot_expose_authentication_fields(monkeypatch, credential):
    def handler(request):
        assert (
            request.url.params["fields"] == "id,email,first_name,last_name,role,status"
        )
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "user-1",
                    "email": "qa@example.com",
                    "token": "server-secret",
                    "password": "hash",
                    "auth_data": {"secret": "bad"},
                }
            },
        )

    monkeypatch.setattr(
        directus,
        "guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await directus._call(
        credential, "get_current_user", directus._MODELS["get_current_user"]()
    )
    assert result["data"] == {"id": "user-1", "email": "qa@example.com"}
    assert "server-secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_upload_is_multipart_and_invalid_base64_is_rejected(
    monkeypatch, credential
):
    seen = []
    # Provider-authored Upload a File response: https://directus.com/docs/api/files
    payload = json.loads(
        (Path(__file__).parent / "fixtures/directus/upload_file.json").read_text()
    )

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(
        directus,
        "guarded_async_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    config = directus._MODELS["upload_file"](
        file_name="qa.txt",
        mime_type="text/plain",
        content_base64=base64.b64encode(b"hello").decode(),
    )
    result = await directus._call(credential, "upload_file", config)
    assert result["data"] == payload["data"]
    assert "multipart/form-data" in seen[0].headers["content-type"]
    assert b"hello" in seen[0].content

    with pytest.raises(ValueError, match="valid base64"):
        await directus._call(
            credential,
            "upload_file",
            directus._MODELS["upload_file"](
                file_name="bad.txt", content_base64="not-base64!"
            ),
        )


def test_rejects_system_collection_and_bad_json():
    with pytest.raises(ValueError, match="user collection"):
        directus._request_parts(
            "list_items", directus._MODELS["list_items"](collection="directus_users")
        )
    with pytest.raises(ValueError, match="valid JSON"):
        directus._request_parts(
            "create_item",
            directus._MODELS["create_item"](collection="articles", payload_json="{bad"),
        )


def test_item_writes_require_json_in_the_config_form():
    for operation in ("create_item", "update_item"):
        model = directus._MODELS[operation]
        assert model.model_fields["payload_json"].is_required()
    assert (
        not directus._MODELS["create_collection"]
        .model_fields["payload_json"]
        .is_required()
    )


def test_url_rejects_embedded_credentials_and_fragments():
    for url in (
        "https://user:password@cms.example.com",
        "https://cms.example.com/#secret",
    ):
        credential = directus.DirectusStaticTokenCredential(
            instance_url=url, static_token="private-test-token"
        )
        with pytest.raises(ValueError, match="cannot contain"):
            directus._url(credential)

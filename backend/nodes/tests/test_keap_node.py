"""Keap catalog and request contracts; live FlowCanvas verification is separate."""

import base64
import json
import re

import httpx
import pytest
from pydantic import ValidationError

from nodes.core.binary_output import BinaryOutput
from nodes.keap_node import CONFIG_MODELS, OPERATIONS, KeapNode, KeapNodeConfig


_ORIGINAL_CLIENT = httpx.AsyncClient


def _config(operation: str, **fields):
    return KeapNodeConfig.model_validate(
        {
            "config": {"operation": operation, **fields},
            "credentials": {
                "credential_type": "keap_pat",
                "personal_access_token": "test-token",
            },
        }
    )


def _node(config: KeapNodeConfig):
    return KeapNode("keap-1", "automation-keap", {}, config, user_id="user-1")


def _transport(monkeypatch, callback):
    monkeypatch.setattr(
        "nodes.keap_node.httpx.AsyncClient",
        lambda *args, **kwargs: _ORIGINAL_CLIENT(
            transport=httpx.MockTransport(callback)
        ),
    )


def test_pinned_sdk_catalog_has_exactly_one_config_per_action():
    assert len(OPERATIONS) == len(CONFIG_MODELS) == 402
    assert {op["method"] for op in OPERATIONS.values()} == {
        "GET",
        "POST",
        "PATCH",
        "PUT",
        "DELETE",
    }
    for name, operation in OPERATIONS.items():
        assert name == operation["name"]
        assert operation["path"].startswith("/rest/v2/")
        assert set(operation["path_params"]) == set(
            re.findall(r"\{([^{}]+)\}", operation["path"])
        )
        assert CONFIG_MODELS[name].model_fields["operation"].default == name
    assert KeapNode.connection_evidence.operation == "get_user_info"
    assert KeapNode.scope_registry.keys_declared == frozenset(OPERATIONS)


def test_required_fields_are_in_schema():
    with pytest.raises(ValidationError):
        _config("get_contact")
    with pytest.raises(ValidationError):
        _config("create_contact")
    with pytest.raises(ValidationError):
        _config("create_file", file_base64="aGVsbG8=")
    assert _config("list_contacts")


@pytest.mark.asyncio
async def test_list_contacts_uses_bearer_token_and_filters(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(
            200, json={"contacts": [{"id": "42", "given_name": "Ada"}]}
        )

    _transport(monkeypatch, callback)
    output = await _node(
        _config("list_contacts", query_json='{"page_size": 2}')
    ).execute({})
    assert output["data"]["contacts"][0]["given_name"] == "Ada"
    assert str(seen[0].url) == "https://api.keap.com/crm/rest/v2/contacts?page_size=2"
    assert seen[0].headers["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_create_contact_sends_json_and_rejects_invalid_json(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "42"})

    _transport(monkeypatch, callback)
    body = {"email_addresses": [{"email": "ada@example.com"}]}
    output = await _node(_config("create_contact", body_json=json.dumps(body))).execute(
        {}
    )
    assert output["data"]["id"] == "42"
    assert json.loads(seen[0].content) == body
    assert seen[0].method == "POST"
    with pytest.raises(ValueError, match="valid JSON"):
        await _node(_config("create_contact", body_json="{")).execute({})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_path_encoding_error_and_binary_response(monkeypatch):
    seen = []

    def not_found(request):
        seen.append(request)
        return httpx.Response(404, json={"message": "No such contact"})

    _transport(monkeypatch, not_found)
    with pytest.raises(ValueError, match="Keap API error 404: No such contact"):
        await _node(_config("get_contact", path_contact_id="a/b")).execute({})
    assert seen[0].url.raw_path.endswith(b"/contacts/a%2Fb")

    def binary(request):
        return httpx.Response(
            200,
            content=b"\x00\xff",
            headers={"content-type": "application/octet-stream"},
        )

    _transport(monkeypatch, binary)
    result = await _node(_config("get_file_data1", path_file_id="f1")).execute({})
    assert isinstance(result["data"], BinaryOutput)
    assert result["data"].data == b"\x00\xff"


@pytest.mark.asyncio
async def test_multipart_upload_preserves_bytes_and_required_fields(monkeypatch):
    seen = []

    def callback(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "file-1"})

    _transport(monkeypatch, callback)
    output = await _node(
        _config(
            "create_file",
            file_base64=base64.b64encode(b"hello\x00world").decode(),
            form_file_name="demo.txt",
            form_file_association="CONTACT",
        )
    ).execute({})
    assert output["data"]["id"] == "file-1"
    assert b"hello\x00world" in seen[0].content
    assert b"demo.txt" in seen[0].content
    assert seen[0].headers["content-type"].startswith("multipart/form-data")
    with pytest.raises(ValidationError, match="file_association"):
        await _node(
            _config(
                "create_file", file_base64="aGVsbG8=", form_file_name="x"
            )
        ).execute({})
    assert len(seen) == 1

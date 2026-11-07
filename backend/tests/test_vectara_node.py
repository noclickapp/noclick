"""Native factory/dispatcher/transport regressions; all data is synthetic."""
import json
from contextlib import asynccontextmanager

import pytest

from nodes import vectara_node as v
from nodes.core.registry import NodeFactory

KEY = "native-fixture-vectara-key"
CORPUS = {"id": "crp_1", "key": "owned", "name": "Owned fixture"}
DOCUMENT = {"id": "fixture/a", "metadata": {"label": "owned", "api_key": "withheld", "url": "https://private.example.test"}, "document_parts": [{"text": "private full body"}]}


def make(operation, **arguments):
    return NodeFactory.create_node("native", "automation-vectara", {
        "config": {"operation": operation, **arguments},
        "credentials": {"credential_type": v.FAMILY, "api_key": KEY, "corpus_key": "owned"},
    }, user_id="fixture-user")


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    class Response:
        def __init__(self, status, value): self.status_code, self.value = status, value
        async def aiter_bytes(self):
            yield b"" if self.value is None else json.dumps(self.value).encode()
    class Client:
        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            assert replies, "Unexpected native request"
            yield Response(*replies.pop(0))
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        yield Client()
    monkeypatch.setattr(v, "guarded_async_client", client)
    return calls, replies


@pytest.mark.parametrize("field,value", [("document_id", 1), ("limit", True), ("corpus_key", 1), ("metadata_keys", [1])])
def test_factory_refuses_raw_coercion(field, value):
    args = {"document_id": "fixture/a", field: value}
    with pytest.raises(ValueError): make("get_document", **args)


def test_factory_accepts_pending_native_id_but_execution_remains_guarded():
    node = make("get_document", document_id="{{node.output.id}}")
    assert node.config.config.document_id == "{{node.output.id}}"
    job = make("get_corpus_job", job_id="{{node.output.id}}")
    assert job.config.config.job_id == "{{node.output.id}}"


async def test_parent_and_unresolved_refusal_before_transport(transport):
    for args in ({"corpus_key": "other"}, {"document_id": "{{node.output.id}}"}):
        node = make("get_document", **({"document_id": "fixture/a"} | args))
        with pytest.raises(v.VectaraError): await node.run({})
    assert transport[0] == []


async def test_search_explicitly_disables_generation_history_and_rewriting(transport):
    calls, replies = transport
    replies.extend([(200, CORPUS), (200, {"search_results": [{"document_id": "fixture/a", "text": "selected matching text", "score": 0.8, "corpus_key": "owned", "document_metadata": {"token": "hidden"}}], "summary": "never output"})])
    result = await make("search_corpus", query="fixture").run({})
    method, url, request = calls[-1]
    assert (method, url) == ("POST", v.API + "/corpora/owned/query")
    assert request["headers"]["x-api-key"] == KEY
    assert request["json"]["generation"] == {"enabled": False}
    assert request["json"]["save_history"] is request["json"]["intelligent_query_rewriting"] is False
    assert result["data"]["items"] == [{"document_id": "fixture/a", "score": 0.8, "text": "selected matching text"}]
    assert "summary" not in json.dumps(result) and KEY not in json.dumps(result)


@pytest.mark.parametrize("wait,ready", [("indexed", False), ("searchable", True)])
async def test_index_exact_201_wait_contract_and_encoded_document_route(transport, wait, ready):
    calls, replies = transport
    replies.extend([(200, CORPUS), (201, DOCUMENT)])
    result = await make("index_document", document_id="fixture/a", text="owned fixture", wait_for=wait).run({})
    assert calls[-1][2]["params"] == {"wait_for": wait}
    assert calls[-1][2]["json"]["document_parts"] == [{"text": "owned fixture"}]
    assert result["data"]["searchable_acknowledged"] is ready
    assert result["data"]["readback_required"] is True
    assert "job_id" not in result["data"]


@pytest.mark.parametrize("operation,method,suffix", [("merge_document_metadata", "PATCH", ""), ("replace_document_metadata", "PUT", "/metadata")])
async def test_merge_vs_replace_and_private_projection(transport, operation, method, suffix):
    calls, replies = transport
    replies.extend([(200, CORPUS), (200, DOCUMENT), (200, DOCUMENT)])
    result = await make(operation, document_id="fixture/a", metadata={}, metadata_keys=["label", "api_key", "url"]).run({})
    assert calls[-1][:2] == (method, v.API + "/corpora/owned/documents/fixture%2Fa" + suffix)
    assert calls[-1][2]["json"] == {"metadata": {}}
    assert result["data"]["metadata"] == {"label": "owned"}
    assert "document_parts" not in result["data"]


async def test_delete_empty_204_is_acknowledgement_not_verified_absence(transport):
    calls, replies = transport
    replies.extend([(200, CORPUS), (200, DOCUMENT), (204, None)])
    result = await make("delete_document", document_id="fixture/a").run({})
    assert calls[-1][0] == "DELETE" and len(calls) == 3
    assert result["data"]["delete_acknowledged"] is True
    assert result["data"]["deletion_verified"] is False


@pytest.mark.parametrize("status,body", [(202, {"id": "job_1"}), (201, {"id": "different"}), (503, {})])
async def test_unknown_write_outcome_never_retries(transport, status, body):
    calls, replies = transport
    replies.extend([(200, CORPUS), (status, body)])
    with pytest.raises(v.VectaraError) as exc:
        await make("index_document", document_id="fixture/a", text="owned fixture").run({})
    assert exc.value.uncertain is True and len(calls) == 2


@pytest.mark.parametrize("cursor", ["https://other.example.test/page", "{{node.output}}"])
async def test_opaque_cursor_cannot_become_a_next_url(transport, cursor):
    transport[1].extend([(200, CORPUS), (200, {"documents": [], "metadata": {"page_key": cursor}})])
    with pytest.raises(v.VectaraError): await make("list_documents").run({})
    assert len(transport[0]) == 2


@pytest.mark.parametrize("state,status", [("queued", "pending"), ("started", "pending"), ("failed_will_retry", "pending"), ("completed", "success"), ("failed", "error"), ("aborted", "error")])
async def test_existing_job_states(transport, state, status):
    job={"id": "job_fixture", "corpus_keys": ["owned"], "state": state, "created_by_username": "private"}
    transport[1].extend([(200, CORPUS), (200, {"jobs": [job]}), (200, job)])
    result = await make("get_corpus_job", job_id="job_fixture").run({})
    assert result["status"] == status and "created_by_username" not in result["data"]


async def test_job_and_search_results_cannot_escape_parent(transport):
    transport[1].extend([(200, CORPUS), (200, {"jobs": [{"id": "job_fixture", "corpus_keys": ["owned", "other"], "state": "completed"}]} )])
    with pytest.raises(v.VectaraError): await make("get_corpus_job", job_id="job_fixture").run({})
    transport[1].extend([(200, CORPUS), (200, {"search_results": [{"document_id": "x", "text": "x", "score": 1, "corpus_key": "other"}]})])
    with pytest.raises(v.VectaraError): await make("search_corpus", query="x").run({})


async def test_reflected_key_is_withheld_and_sparse_corpus_update(transport):
    transport[1].extend([(200, CORPUS), (200, {**CORPUS, "description": KEY})])
    with pytest.raises(v.VectaraError) as exc: await make("update_corpus", name="Renamed").run({})
    assert exc.value.uncertain is True and KEY not in str(exc.value)
    assert transport[0][-1][2]["json"] == {"name": "Renamed"}


def test_native_metadata_preserves_null_false_zero_and_empty_text_through_factory():
    node = make("replace_document_metadata", document_id="fixture/a", metadata={"null": None, "flag": False, "count": 0, "empty": ""})
    assert node.config.config.metadata == {"null": None, "flag": False, "count": 0, "empty": ""}


async def test_foreign_job_id_refused_before_global_detail_and_bound_cursor_supported(transport):
    transport[1].extend([(200,CORPUS),(200,{"jobs":[]})])
    with pytest.raises(v.VectaraError): await make("get_corpus_job",job_id="job_foreign",page_key="opaque-page").run({})
    assert len(transport[0])==2 and transport[0][-1][1]==v.API+"/jobs"
    assert transport[0][-1][2]["params"]=={"corpus_key":["owned"],"limit":100,"page_key":"opaque-page"}

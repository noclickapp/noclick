"""Exercise native discovery and the real request boundary with offline HTTP."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import rosette_text_analytics_node as rosette
from nodes.core.registry import NodeFactory
from utils import ssrf

TYPE = "automation-rosette-text-analytics"
KEY = "fixture-rosette-key-not-live"
AUTH = {"credential_type": rosette.CREDENTIAL_TYPE, "api_key": KEY}
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/rosette-text-analytics/published_requests.json").read_text())["examples"]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.rosette.com"
        assert request.headers["X-RosetteAPI-Key"] == KEY
        assert KEY not in str(request.url)
        status, payload, *headers = replies.pop(0)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload, headers=headers[0] if headers else {"Content-Type": "application/json"})
        return httpx.Response(status, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(rosette, "guarded_async_client", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return requests, replies


def make(operation, **arguments):
    return NodeFactory.create_node(node_id="rosette-test", node_type=TYPE,
        node_data={"config": {"operation": operation, **arguments}, "credentials": AUTH.copy()})


DOCUMENT_OPERATIONS = [name for name, (method, _) in rosette.ROUTES.items() if method == "POST" and name not in {"compare_names", "deduplicate_names", "translate_name", "compare_addresses"}]


@pytest.mark.parametrize("operation", DOCUMENT_OPERATIONS)
@pytest.mark.asyncio
async def test_document_actions_use_one_exact_request(transport, operation):
    requests, replies = transport
    route = rosette.ROUTES[operation][1]
    example = EXAMPLES[route]
    args = {"content": example["content"]}
    expected = args.copy()
    if operation == "analyze_morphology":
        args["morpho_feature"] = "lemmas"
        route = "/morphology/lemmas"
    if operation == "find_similar_terms":
        args.update(result_languages=["eng", "spa"], count=4)
        expected["options"] = {"resultLanguages": ["eng", "spa"], "count": 4}
    payload = {"tokens": ["hello"], "providerExtra": {"preserved": True}}
    replies.append((200, payload))
    result = await make(operation, **args).execute({})
    assert result == {"status": "success", "operation": operation, "data": payload}
    assert len(requests) == 1 and requests[0].method == "POST"
    assert requests[0].url.path == "/rest/v1" + route
    assert json.loads(requests[0].content) == expected


@pytest.mark.parametrize("operation,args,expected", [
    ("compare_names", {"name1": {"text": "Michael Jackson", "entityType": "PERSON"}, "name2": {"text": "迈克尔·杰克逊"}}, {"name1": {"text": "Michael Jackson", "entityType": "PERSON"}, "name2": {"text": "迈克尔·杰克逊"}}),
    ("deduplicate_names", {"names": [{"text": "Joe Smith"}, {"text": "Joe Smidge"}], "threshold": 0.8}, {"names": [{"text": "Joe Smith"}, {"text": "Joe Smidge"}], "threshold": 0.8}),
    ("translate_name", {"name": "معمر محمد أبو منيار القذافي", "target_language": "eng", "maximum_results": 10}, {"name": "معمر محمد أبو منيار القذافي", "targetLanguage": "eng", "maximumResults": 10}),
    ("compare_addresses", {"address1": "1600 Pennsylvania Ave NW", "address2": "160 Pennsylvania Avenue"}, {"address1": "1600 Pennsylvania Ave NW", "address2": "160 Pennsylvania Avenue"}),
])
@pytest.mark.asyncio
async def test_name_and_address_request_shapes(transport, operation, args, expected):
    requests, replies = transport
    replies.append((200, {"score": 0.8}))
    assert (await make(operation, **args).execute({}))["status"] == "success"
    assert len(requests) == 1
    assert requests[0].url.path == "/rest/v1" + rosette.ROUTES[operation][1]
    assert json.loads(requests[0].content) == expected


@pytest.mark.parametrize("operation", ["get_service_info", "get_entity_types", "get_event_schemas", "list_supported_languages"])
@pytest.mark.asyncio
async def test_reads_and_credential_only_evidence(transport, operation):
    requests, replies = transport
    replies.append((200, {"supportedLanguages": [{"language": "eng", "script": "Latn", "licensed": True}]}))
    assert (await make(operation).execute({}))["status"] == "success"
    assert len(requests) == 1 and requests[0].method == "GET" and requests[0].content == b""
    assert rosette.RosetteTextAnalyticsNode.connection_evidence.proves == "reachability"


@pytest.mark.asyncio
async def test_query_and_language_are_serialized(transport):
    requests, replies = transport
    replies.append((200, {}))
    await make("get_entity_types", per_subsource_supported_entity_types=True).execute({})
    assert dict(requests[-1].url.params) == {"perSubsourceSupportedEntityTypes": "true"}
    replies.append((200, {}))
    await make("tokenize_text", content="Bonjour", language="fra").execute({})
    assert json.loads(requests[-1].content) == {"content": "Bonjour", "language": "fra"}


@pytest.mark.parametrize("status,payload", [(401, {"message": "Invalid API key"}), (429, {"message": "Quota exceeded"}), (500, {"message": "Service unavailable"}), (302, b""), (200, b"not json"), (200, []), (200, {"code": "badRequest", "message": "Rejected"})])
@pytest.mark.asyncio
async def test_errors_never_look_like_success_or_retry(transport, status, payload):
    requests, replies = transport
    replies.append((status, payload))
    result = await make("list_supported_languages").execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert len(requests) == 1 and "data" not in result
    if status == 401:
        assert result["error"] == "Invalid API key"


@pytest.mark.asyncio
async def test_does_not_follow_redirect_or_echo_key(transport):
    requests, replies = transport
    replies.append((302, b"", {"Location": "https://attacker.example/steal"}))
    assert (await make("get_service_info").execute({}))["status"] == "error"
    replies.append((401, {"message": "Rejected " + KEY}))
    assert KEY not in json.dumps(await make("get_service_info").execute({}))
    assert len(requests) == 2


@pytest.mark.parametrize("key", ["https://example.com/key", "your_api_key", "one\ntwo", "one two", "🔑"])
def test_bad_keys_cannot_connect(key):
    with pytest.raises((ValidationError, ValueError)):
        rosette.RosetteTextAnalyticsApiKeyCredential(api_key=key)


def test_manual_credential_has_default_tag_and_cleans_key():
    credential = rosette.RosetteTextAnalyticsApiKeyCredential(api_key="  " + KEY + "  ")
    assert credential.credential_type == rosette.CREDENTIAL_TYPE and credential.api_key == KEY
    assert KEY not in repr(credential)


@pytest.mark.parametrize("operation,args", [
    ("tokenize_text", {"content": "x" * 50001}),
    ("tokenize_text", {"content": "hello", "language": "english"}),
    ("analyze_morphology", {"content": "hello", "morpho_feature": "../info"}),
    ("translate_name", {"name": "x" * 501, "target_language": "eng"}),
    ("compare_names", {"name1": {"text": "a", "unknown": True}, "name2": {"text": "b"}}),
    ("find_similar_terms", {"content": "spy", "result_languages": ["../eng"]}),
])
def test_input_boundaries(operation, args):
    with pytest.raises(ValueError):
        make(operation, **args)

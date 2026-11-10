"""Native operation execution against LanguageTool's published v2 wire shapes."""
import json
from urllib.parse import parse_qs

import httpx
import pytest

from nodes import languagetool_node as lt
from nodes.core.run_op import run_node_operation

AUTH = {"credential_type": "languagetool_api_key", "username": "writer@example.test", "api_key": "test-api-key-123"}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def api(monkeypatch):
    calls, responses = [], []
    async def send(request):
        calls.append(request)
        code, content = responses.pop(0)
        return httpx.Response(code, content=content, request=request)
    native = httpx.AsyncClient
    monkeypatch.setattr(lt.httpx, "AsyncClient", lambda **kwargs: native(**kwargs, transport=httpx.MockTransport(send)))
    return calls, responses


async def run(operation, **arguments):
    return await run_node_operation(node_type="automation-languagetool", operation=operation,
                                    arguments=arguments, credential_data=AUTH,
                                    user_id="00000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("operation,arguments,method,path,body", [
    ("check_text", {"text": "This is an test.", "language": "auto"}, "POST", "/v2/check", {"matches": []}),
    ("list_languages", {}, "GET", "/v2/languages", [{"name": "English (US)", "code": "en", "longCode": "en-US"}]),
    ("list_words", {"offset": 10, "limit": 20, "dicts": "technical,medical"}, "GET", "/v2/words", {"words": ["NoClick"]}),
    ("add_word", {"word": "NoClick", "dictionary": "technical"}, "POST", "/v2/words/add", {"added": True}),
    ("delete_word", {"word": "NoClick", "dictionary": "technical"}, "POST", "/v2/words/delete", {"deleted": False}),
])
@pytest.mark.asyncio
async def test_native_wire_contract(api, operation, arguments, method, path, body):
    calls, responses = api
    responses.append((200, json.dumps(body).encode()))
    result = await run(operation, **arguments)
    assert result == ({"languages": body} if operation == "list_languages" else body)
    request, = calls
    assert request.method == method and request.url.path == path
    assert request.url.host == "api.languagetoolplus.com"
    values = dict(request.url.params) if method == "GET" else {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    if operation == "list_languages":
        assert values == {}
    else:
        assert values["username"] == AUTH["username"] and values["apiKey"] == AUTH["api_key"]
    if method == "POST":
        assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
        assert "apiKey" not in str(request.url)
    if operation == "list_words":
        assert values["offset"] == "10" and values["limit"] == "20" and values["dicts"] == "technical,medical"
    if operation in {"add_word", "delete_word"}:
        assert values["dict"] == "technical" and values["word"] == "NoClick" and "dictionary" not in values


@pytest.mark.asyncio
async def test_all_check_options_and_annotated_markup(api):
    calls, responses = api
    body = {"software": {"name": "LanguageTool", "version": "3.3", "buildDate": "2016-05-25", "apiVersion": 1},
            "language": {"name": "English (US)", "code": "en-US", "detectedLanguage": {"name": "English", "code": "en"}}, "matches": []}
    responses.append((200, json.dumps(body).encode()))
    annotation = json.dumps({"annotation": [{"text": "A "}, {"markup": "<b>"}, {"text": "test"}, {"markup": "</b>"}]})
    assert await run("check_text", data=annotation, language="auto", preferred_variants="en-GB,de-AT", mother_tongue="de",
                     enabled_rules="RULE", disabled_rules="OTHER", enabled_categories="TYPOGRAPHY", disabled_categories="CASING",
                     enabled_only=False, level="picky", dicts="technical") == body
    values = parse_qs(calls[0].content.decode())
    assert values == {"data": [annotation], "language": ["auto"], "preferredVariants": ["en-GB,de-AT"], "motherTongue": ["de"],
                      "enabledRules": ["RULE"], "disabledRules": ["OTHER"], "enabledCategories": ["TYPOGRAPHY"],
                      "disabledCategories": ["CASING"], "enabledOnly": ["false"], "level": ["picky"], "dicts": ["technical"],
                      "username": [AUTH["username"]], "apiKey": [AUTH["api_key"]]}


@pytest.mark.parametrize("code", [401, 403, 429, 500, 302])
@pytest.mark.asyncio
async def test_provider_errors_and_redirects_never_echo_secrets(api, code):
    calls, responses = api
    responses.append((code, f"Rejected {AUTH['api_key']} {AUTH['username']}".encode()))
    output = await run("list_words")
    assert output["status"] == "error" and output["http_status"] == code
    assert AUTH["api_key"] not in str(output) and AUTH["username"] not in str(output)
    assert len(calls) == 1


@pytest.mark.parametrize("operation,args,payload", [
    ("list_words", {}, b'{"words":[1]}'),
    ("list_languages", {}, b'{}'),
    ("check_text", {"text": "A test"}, b'{"matches":null}'),
    ("add_word", {"word": "test"}, b'{"added":"true"}'),
    ("delete_word", {"word": "test"}, b'{"deleted":null}'),
    ("list_words", {}, b'<html>Oops</html>'),
])
@pytest.mark.asyncio
async def test_invalid_responses_do_not_claim_success(api, operation, args, payload):
    _, responses = api
    responses.append((200, payload))
    with pytest.raises(ValueError, match="LanguageTool"):
        await run(operation, **args)


def test_input_requirements_and_manual_credential_default():
    assert lt.LanguageToolAPIKey(username="me@example.test", api_key="real-shaped-api-key").credential_type == "languagetool_api_key"
    for data in [{}, {"text": "A", "data": '{}'}, {"data": "not json"}, {"data": '{}'}]:
        with pytest.raises(ValueError):
            lt.CheckTextConfig(**data)
    with pytest.raises(ValueError):
        lt.AddWordConfig(word="two words")
    with pytest.raises(ValueError):
        lt.ListWordsConfig(offset=-1)
    assert lt.LanguageToolNode.connection_evidence.operation == "list_words"

import json

import httpx
import pytest

import noclick as nc
from platform_helpers import body

ANTHROPIC_TOOLS = [{"name": "search", "description": "Search the web", "input_schema": {"type": "object"}},
                   {"name": "gmail__send_email", "description": "Send", "input_schema": {"type": "object"}}]


def _call_responder(request):
    payload = body(request)
    name = payload["name"]
    if name == "gmail__send_email":
        return httpx.Response(200, json={
            "object": "tool_result", "name": name, "content": "Connect Gmail first.", "is_error": True,
            "needs_connection": {"integration": "gmail", "connect_url": "https://noclick.com/c/1"},
        })
    return httpx.Response(200, json={
        "object": "tool_result", "name": name,
        "content": [{"type": "text", "text": f"results for {payload['arguments'].get('query')}"}],
        "is_error": False,
    })


@pytest.fixture
def tools_api(api):
    api.post("/v1/toolkits/definitions").mock(side_effect=lambda request: httpx.Response(200, json={
        "object": "tool_definitions", "format": body(request)["format"], "tools": ANTHROPIC_TOOLS,
    }))
    api.post("/v1/toolkits/call").mock(side_effect=_call_responder)
    return api


def test_definitions_are_cached_per_format(tools_api, client):
    route = tools_api.routes[0]
    toolkit = nc.Toolkit(["search", "gmail.send_email"])
    assert toolkit.definitions() == ANTHROPIC_TOOLS
    assert toolkit.definitions() == ANTHROPIC_TOOLS
    assert route.call_count == 1
    assert body(route.calls.last.request) == {"tools": ["search", "gmail.send_email"], "format": "anthropic"}
    toolkit.definitions("openai")
    assert route.call_count == 2 and body(route.calls.last.request)["format"] == "openai"


def test_call_returns_tool_result_with_needs_connection(tools_api, client):
    toolkit = nc.Toolkit("gmail")
    result = toolkit.call("gmail__send_email", {"to": "a@b.c"})
    assert result.is_error and result.connect_url == "https://noclick.com/c/1"
    ok = toolkit.call("search", {"query": "cake"})
    assert ok.text == "results for cake" and ok.needs_connection is None


def test_shared_toolkit_follows_the_current_user(tools_api, client):
    route = tools_api.routes[1]
    toolkit = nc.Toolkit(["search"])  # e.g. built once at import time
    for user in ("user_1", "user_2"):
        with nc.as_user(user):
            toolkit.call("search", {"query": "x"})
        assert route.calls.last.request.headers["NoClick-User"] == user
    toolkit.call("search", {"query": "x"}, user="user_9")
    assert route.calls.last.request.headers["NoClick-User"] == "user_9"


def test_toolkit_pinned_to_a_user(tools_api, client):
    toolkit = nc.Toolkit(["search"], user="user_42")
    with nc.as_user("someone_else"):
        toolkit.call("search", {"query": "x"})
    assert tools_api.routes[1].calls.last.request.headers["NoClick-User"] == "user_42"


def test_handle_anthropic_dict_blocks(tools_api, client):
    content = [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "toolu_1", "name": "search", "input": {"query": "cake"}},
        {"type": "tool_use", "id": "toolu_2", "name": "gmail__send_email", "input": {"to": "a@b.c"}},
    ]
    results = nc.Toolkit(["search", "gmail"]).handle({"role": "assistant", "content": content})
    assert results == [
        {"type": "tool_result", "tool_use_id": "toolu_1",
         "content": [{"type": "text", "text": "results for cake"}], "is_error": False},
        {"type": "tool_result", "tool_use_id": "toolu_2", "content": "Connect Gmail first.", "is_error": True},
    ]
    assert nc.Toolkit(["search"]).handle(content) == results  # a bare content list works too


def test_handle_anthropic_sdk_message(tools_api, client):
    anthropic_types = pytest.importorskip("anthropic.types")
    message = anthropic_types.Message(
        id="msg_1", type="message", role="assistant", model="claude-x", stop_reason="tool_use",
        stop_sequence=None, usage=anthropic_types.Usage(input_tokens=1, output_tokens=1),
        content=[
            anthropic_types.TextBlock(type="text", text="Searching."),
            anthropic_types.ToolUseBlock(type="tool_use", id="toolu_9", name="search", input={"query": "pie"}),
        ],
    )
    toolkit = nc.Toolkit(["search"])
    [result] = toolkit.handle(message)
    assert result["tool_use_id"] == "toolu_9" and result["content"][0]["text"] == "results for pie"
    assert toolkit.handle(message.content) == [result]


async def test_handle_aio_runs_calls_concurrently(tools_api, client):
    content = [{"type": "tool_use", "id": f"t{i}", "name": "search", "input": {"query": str(i)}} for i in range(5)]
    results = await nc.Toolkit(["search"]).handle.aio(content)
    assert [r["tool_use_id"] for r in results] == [f"t{i}" for i in range(5)]
    assert tools_api.routes[1].call_count == 5


def test_handle_openai_chat_tool_calls(tools_api, client):
    calls = [
        {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": json.dumps({"query": "tea"})}},
        {"id": "call_2", "type": "function", "function": {"name": "search", "arguments": "{not json"}},
    ]
    messages = nc.Toolkit(["search"]).handle_openai({"role": "assistant", "tool_calls": calls})
    assert messages[0] == {"role": "tool", "tool_call_id": "call_1", "content": "results for tea"}
    assert messages[1]["tool_call_id"] == "call_2" and "not valid JSON" in messages[1]["content"]
    assert tools_api.routes[1].call_count == 1  # the malformed call never reached the API


def test_handle_openai_sdk_objects_and_responses_items(tools_api, client):
    chat = pytest.importorskip("openai.types.chat")
    completion = chat.ChatCompletion(
        id="c1", object="chat.completion", created=0, model="gpt-x",
        choices=[{"index": 0, "finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "call_7", "type": "function",
                            "function": {"name": "search", "arguments": "{\"query\": \"jam\"}"}}],
        }}],
    )
    toolkit = nc.Toolkit(["search"])
    assert toolkit.handle_openai(completion) == [{"role": "tool", "tool_call_id": "call_7", "content": "results for jam"}]
    items = [{"type": "function_call", "call_id": "fc_1", "name": "search", "arguments": "{\"query\": \"figs\"}"}]
    assert toolkit.handle_openai(items) == [{"type": "function_call_output", "call_id": "fc_1", "output": "results for figs"}]

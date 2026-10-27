"""JS runtime: a result with no JSON form fails the run instead of reaching the next step as its repr.

A value too large to serialise within the sandbox's memory, a function, a symbol or a cycle came back as the
string "<_quickjs.Object object at 0x…>", so a step "succeeded" and the steps after it acted on nothing
(2026-10-27)."""

from utils.js_executor import execute_js


def test_a_result_too_large_to_serialise_fails_saying_why():
    pages = [{"text": "on site at 9 😊 " * 20, "n": i} for i in range(16000)]
    result = execute_js("return inputs.pages;", {"pages": pages})
    assert result["success"] is False and result["result"] is None
    assert "too large for the JavaScript sandbox's memory" in result["error"]


def test_a_result_with_no_json_form_fails_saying_why():
    for code, said in (("return () => 1;", "it's a function or a symbol"),
                       ("const o = {}; o.self = o; return o;", "circular reference")):
        result = execute_js(code, {})
        assert result["success"] is False, code
        assert "can't be turned into JSON" in result["error"] and said in result["error"], result["error"]


def test_ordinary_results_still_come_back():
    assert execute_js("return {when: new Date(0), list: [1, undefined]};", {})["result"] == {
        "when": "1970-01-01T00:00:00.000Z", "list": [1, None]}

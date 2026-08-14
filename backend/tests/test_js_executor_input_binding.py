"""JS serverless runtime: function_inputs bind as bare variables.

The Python runtime passes function_inputs as real parameters, and the config
schema calls them "named input parameters" — but the JS runtime only exposed
them via `inputs.<name>`, so code written against the documented contract died
with `ReferenceError: 'x' is not defined` (11 consecutive failed runs,
2026-08-14). These tests pin the parity fix: bare names resolve, user
redeclarations shadow instead of throwing, and sandbox globals survive.
"""

from utils.js_executor import execute_js


def test_inputs_available_as_bare_names():
    result = execute_js("return x + y;", {"x": 7, "y": 5})
    assert result["success"], result.get("error")
    assert result["result"] == 12


def test_inputs_object_still_works():
    result = execute_js("return inputs.x + x;", {"x": 3})
    assert result["success"], result.get("error")
    assert result["result"] == 6


def test_user_redeclaration_shadows_instead_of_throwing():
    # Pre-fix working code often did `const x = inputs.x` — a lexical
    # declaration must shadow the property binding, never SyntaxError.
    result = execute_js("const x = 1; return x;", {"x": 9})
    assert result["success"], result.get("error")
    assert result["result"] == 1


def test_non_identifier_keys_reachable_via_inputs_only():
    result = execute_js("return inputs['weird-key'] + x;", {"weird-key": 10, "x": 2})
    assert result["success"], result.get("error")
    assert result["result"] == 12


def test_existing_globals_never_clobbered():
    # An input named after a sandbox/builtin global must not break it.
    result = execute_js(
        "return JSON.stringify({n: Math.max(1, 2)});",
        {"JSON": 5, "Math": 6},
    )
    assert result["success"], result.get("error")
    assert result["result"] == '{"n":2}'


def test_state_vars_still_let_bound_and_captured():
    result = execute_js(
        "st.counter = (st.counter || 0) + 1; return st.counter;",
        {"st": {"counter": 4}, "x": 1},
        state_var_names=["st"],
    )
    assert result["success"], result.get("error")
    assert result["result"] == 5
    assert result["__mutated_state__"] == {"counter": 5}

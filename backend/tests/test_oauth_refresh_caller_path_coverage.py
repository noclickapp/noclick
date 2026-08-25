"""AST regression test: every call site of ``ensure_fresh_oauth_token`` must
be reachable only through a known caller_path source.

There are two legitimate patterns:

1. **Explicit kwarg** — ``ensure_fresh_oauth_token(..., caller_path="...")``.
   Used by direct entry points.

2. **Trusted indirection** — the call site lives inside a function whose
   callers are wrapped in ``caller_path_scope(...)``:
   - ``WorkflowNode._ensure_fresh_token`` instance methods (~30 nodes) —
     called from ``node.execute()`` which is wrapped in
     ``caller_path_scope("execute")`` by the workflow execution handler.
   - The ``freshen_oauth_credential`` wrapper in
     ``backend/nodes/core/oauth_refresh.py`` — forwards a ``caller_path``
     kwarg it received from ``freshen_credential`` callers.

This test fails if someone adds a new call site that doesn't fit either
pattern — e.g. a new entry point that forgets to pass ``caller_path=`` and
isn't wrapped in a scope. Without this guard, the new path silently
defaults to ``caller_path='unknown'`` and we'd only catch it by grepping
WARNING logs in production.

The audit complements the runtime WARNING by failing CI deterministically.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Files we don't scan — third-party vendored code, tests, generated.
_EXCLUDE_DIRS = (
    "tests",
    "__pycache__",
    ".venv",
    "node_modules",
)

# Function names whose body is a TRUSTED indirection: a call to
# ensure_fresh_oauth_token inside one of these is fine because the caller is
# expected to be a scoped entry point (or to forward an explicit caller_path).
_TRUSTED_FUNCTION_NAMES = frozenset({
    # Per-node execute-path refresh — callers (node.execute) are scoped to "execute"
    # by WorkflowExecutionHandler / SetupExecutionHandler.
    "_ensure_fresh_token",
    "_get_access_token",
    "_get_auth_headers",
    "_resolve_trigger_credential",
    # Per-node freshen_credential overrides — callers wrap the call in
    # caller_path_scope (dropdown / mcp / trigger_register / manual_refresh).
    "freshen_credential",
    # Shared OAuth refresh wrappers that forward kwargs / default caller_path.
    "freshen_oauth_credential",
    "ensure_fresh_google_token",
    "_force_refresh_oauth_credentials",
    "_ensure_fresh_oauth_token",
})


_TRUSTED_FILES = frozenset()


def _iter_backend_py_files() -> Iterable[Path]:
    for path in BACKEND_ROOT.rglob("*.py"):
        if any(part in _EXCLUDE_DIRS for part in path.parts):
            continue
        yield path


def _enclosing_function(stack: list[ast.AST]) -> ast.AST | None:
    for node in reversed(stack):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


def _call_has_caller_path_kwarg(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "caller_path":
            return True
    return False


def _is_direct_call_to(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == name:
        return True
    if isinstance(func, ast.Attribute) and func.attr == name:
        return True
    return False


def _find_violations(path: Path) -> list[str]:
    """Return a list of human-readable violation strings for this file."""
    try:
        source = path.read_text()
    except (UnicodeDecodeError, OSError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    rel = path.relative_to(BACKEND_ROOT).as_posix()
    if rel in _TRUSTED_FILES:
        return []

    violations: list[str] = []

    def _walk(node: ast.AST, stack: list[ast.AST]) -> None:
        stack.append(node)
        try:
            if _is_direct_call_to(node, "ensure_fresh_oauth_token"):
                enclosing = _enclosing_function(stack)
                enclosing_name = enclosing.name if enclosing else "<module>"
                if enclosing_name not in _TRUSTED_FUNCTION_NAMES and not _call_has_caller_path_kwarg(node):
                    violations.append(
                        f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}: "
                        f"ensure_fresh_oauth_token(...) inside `{enclosing_name}` "
                        "neither passes caller_path= nor is in a trusted "
                        "indirection — refresh will tag caller_path='unknown'. "
                        "Either pass caller_path= explicitly, wrap the entry "
                        "point in caller_path_scope(...), or add this function "
                        "to _TRUSTED_FUNCTION_NAMES if it forwards a kwarg."
                    )
            for child in ast.iter_child_nodes(node):
                _walk(child, stack)
        finally:
            stack.pop()

    _walk(tree, [])
    return violations


def test_every_ensure_fresh_oauth_token_call_has_a_caller_path_source():
    """Fail if any direct call to ``ensure_fresh_oauth_token`` is missing both
    an explicit ``caller_path=`` kwarg AND is not inside one of the trusted
    forwarding helpers."""
    all_violations: list[str] = []
    for path in _iter_backend_py_files():
        all_violations.extend(_find_violations(path))

    if all_violations:
        msg = (
            "Found ensure_fresh_oauth_token call sites that would tag "
            "caller_path='unknown':\n  "
            + "\n  ".join(all_violations)
        )
        raise AssertionError(msg)


def test_known_scoped_entry_points_actually_call_caller_path_scope():
    """Sanity check: files we expect to set the ambient caller_path actually
    import and use ``caller_path_scope``."""
    expected_scoped_files = [
        "wss/handlers/workflow_execution_handler.py",
        "wss/handlers/workflow_handler.py",
        "wss/handlers/workflow_mcp_handler.py",
        "wss/handlers/oauth/slack_oauth_handler.py",
        "mcp_server.py",
        "nodes/core/watch_channels.py",
        "nodes/core/webhook_trigger.py",
        "nodes/core/webhook_subscriptions.py",
    ]
    missing: list[str] = []
    for rel in expected_scoped_files:
        text = (BACKEND_ROOT / rel).read_text()
        if "caller_path_scope" not in text:
            missing.append(rel)
    if missing:
        raise AssertionError(
            "These entry-point files were expected to wrap their refresh "
            "callers in `caller_path_scope(...)` but do not:\n  "
            + "\n  ".join(missing)
        )



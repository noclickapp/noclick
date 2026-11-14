"""No request path walks every integration's class.

``NODE_REGISTRY.items()``/``.values()`` import every integration (~25 s of CPU and ~1 GB), on the event loop of
whatever request did it: a search, a builder turn, a socket event any signed-in browser could send
(``workflow:mcp:search_nodes``, removed: no client sent it). A lookup about every type reads the node catalog
(``nodes/core/catalog.py``) instead. The allowlist only shrinks."""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
# Each walk left, and why it never runs on a request's event loop.
ALLOWED = {
    "utils/startup_warmup.py": "the boot warmup, in a thread before the process serves",
    "nodes/core/credential_connect.py": "credential_type_owners and _class_index, which only the suite calls",
}


def _walks(path: Path) -> bool:
    source = path.read_text()
    if "NODE_REGISTRY" not in source:
        return False
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("items", "values") and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "NODE_REGISTRY"):
            return True
    return False


def test_only_the_allowed_modules_walk_every_integration():
    walking = {
        str(path.relative_to(BACKEND)) for path in BACKEND.rglob("*.py")
        if not {"tests", "scripts", "evals", "node_modules"} & set(path.relative_to(BACKEND).parts) and _walks(path)
    }
    assert walking <= set(ALLOWED), f"walks every integration: {sorted(walking - set(ALLOWED))}"
    # One that stopped comes off the list (the open edition ships without some of them).
    assert {path for path in ALLOWED if (BACKEND / path).exists()} <= walking

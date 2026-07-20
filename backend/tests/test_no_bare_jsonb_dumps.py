"""Source-scan pin: never feed json.dumps output to a bare ``$N::jsonb`` param.

Runtime pools register a jsonb codec (dict-encoding), so a pre-dumped string
double-encodes into a jsonb STRING SCALAR — and Postgres ``object || scalar``
is jsonb ARRAY concatenation, which silently rewrites an object into a list.
That corrupted a trigger node's config blob on every reconciler-driven
registration (2026-07-20: the corrupt list crashed the save's config-change
hooks, so a PostHog event_name edit never re-registered provider-side).

Correct forms:
- pass the dict and let the codec encode it (repositories on runtime pools), or
- ``json.dumps`` + ``($N::text)::jsonb`` — pool-agnostic (utils/notifications.py),
  required for code reachable from BOTH codec'd runtime pools and plain cron pools.
"""
import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

SCAN_ROOTS = ["utils", "repositories", "wss", "nodes", "billing", "coder", "mcp_server.py", "api.py"]
DB_CALLS = {"execute", "executemany", "fetch", "fetchrow", "fetchval", "execute_async", "fetch_async"}
BARE_JSONB = re.compile(r"\$\d+::jsonb")
DUMPS = re.compile(r"\bjson\.dumps\(|\b_json\.dumps\(")


def _py_files():
    for root in SCAN_ROOTS:
        path = BACKEND / root
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from (
                p for p in path.rglob("*.py")
                if "tests" not in p.parts and not p.name.startswith(("test_", "debug_"))
            )


def test_no_json_dumps_into_bare_jsonb_param():
    violations = []
    for path in _py_files():
        source = path.read_text()
        if "::jsonb" not in source or "json.dumps" not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in DB_CALLS):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if BARE_JSONB.search(segment) and DUMPS.search(segment):
                violations.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    assert not violations, (
        "json.dumps fed to a bare $N::jsonb param (double-encodes on codec'd "
        "pools; object||scalar concat corrupts the object into a LIST). Pass "
        "the dict, or use ($N::text)::jsonb for pool-agnostic call sites:\n  "
        + "\n  ".join(violations)
    )

"""What billing does when nobody has registered a platform.

The engine meters work and asks permission through `billing.*`. An installation
that charges nobody — and every test in this repository, which registers
nothing — gets the defaults: gates pass, balances read unlimited, markup is
neutral, prices are zero. This pins both halves of that.

1. Surface: for EVERY `billing.*` import in non-billing backend code (AST scan,
   same resolution rules as the boundary ratchet), the module exists and
   exports the symbol. A call site that imports something the engine does not
   define is a self-hosted install that crashes on a code path nobody here
   walks.
2. Semantics: the defaults are permissive and free. The failure this guards is
   silent in the other direction — a default that refused, or that charged,
   would break an installation with no billing at all.

Run in a subprocess so registering nothing is guaranteed: another test in the
same session may have installed the hosted implementations.
"""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

from tests.judged_nodes import files_narrowed, judged_files

BACKEND = Path(__file__).parent.parent

SKIP_ROOTS = ("tests", "scripts", "viteapp", "node_modules", "sandbox", "public", "__pycache__")


# A line that imports billing, or anything with it (`import os, billing.markup`): a file without one is never parsed.
_IMPORTS_BILLING = re.compile(r"^[ \t]*(?:from[ \t]+billing\b|import[ \t][^\n]*\bbilling\b)", re.MULTILINE)


def _statements(tree: ast.AST):
    """Every statement in ``tree``: an import is one, so this finds each without visiting every expression."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        for block in ("body", "orelse", "finalbody", "handlers", "cases"):
            stack.extend(getattr(node, block, ()))


def _imported_billing_symbols() -> dict:
    """module name ('billing', 'billing.markup', …) → set of imported names.
    '<module>' marks a plain `import billing.x` (module itself must resolve)."""
    symbols: dict = {}
    for p in judged_files(sorted(BACKEND.rglob("*.py"))):
        rel = p.relative_to(BACKEND)
        if any(part in SKIP_ROOTS for part in rel.parts):
            continue
        if rel.parts[0] == "billing":
            continue
        source = p.read_text()
        if "billing" not in source or not _IMPORTS_BILLING.search(source):
            continue  # imports nothing from it, so no need to parse it
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in _statements(tree):
            # level>0 = relative import (e.g. coder/openai_agent's `.billing`) — not ours
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module \
                    and (node.module == "billing" or node.module.startswith("billing.")):
                symbols.setdefault(node.module, set()).update(a.name for a in node.names)
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "billing" or a.name.startswith("billing."):
                        symbols.setdefault(a.name, set()).add("<module>")
    return symbols


_PROBE = r"""
import asyncio, importlib, json, sys
from decimal import Decimal

surface = json.loads(sys.argv[1])
_UID = "00000000-0000-4000-8000-000000000001"
_ORG = "00000000-0000-4000-8000-000000000002"
missing = []
for module_name, names in surface.items():
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        missing.append(f"{module_name}: import failed: {e}")
        continue
    for name in names:
        if name != "<module>" and not hasattr(mod, name):
            missing.append(f"{module_name}.{name}")
if missing:
    print("MISSING:" + json.dumps(sorted(missing)))
    sys.exit(1)

# Semantics
from billing.usage_tracker import usage_tracker, MIN_CREDITS
from billing.schema import UsageEventData
from billing import markup

async def checks():
    assert await usage_tracker.check_credit_balance(_UID) is None          # unlimited
    assert await usage_tracker.fetch_credit_remaining(_UID) is None
    assert await usage_tracker.enforce_credit_gate(_UID) is None           # always passes
    assert await usage_tracker.resolve_billing_user_id(_UID, _ORG) == _UID
    event = UsageEventData(
        user_id=_UID, total_cost=Decimal("0.01"), usage_type="ai_usage",
        usage_subtype="model", quantity=Decimal("100"), unit_type="tokens",
        metadata={"actual_user_id": _UID}, organization_id=None,
    )
    await usage_tracker.track_usage_event(event)                          # no-op, no raise

asyncio.run(checks())
assert markup.apply_platform_markup(Decimal("2"), False, "m") == Decimal("2")
assert markup.PLATFORM_MIN_MARKUP == Decimal("1")
print("OK:" + str(markup.CREDITS_PER_DOLLAR))
"""


def _run_probe(surface: dict) -> str:
    payload = json.dumps({m: sorted(s) for m, s in surface.items()})
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, payload],
        capture_output=True, text=True,
        cwd=str(BACKEND),
        # A bare environment: no PLATFORM_MARKUP, no PRICE_* — the defaults
        # are what an installation with no billing configuration gets.
        env={"PYTHONPATH": str(BACKEND), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, (
        f"shim probe failed:\n{result.stdout}\n{result.stderr}"
    )
    return result.stdout.strip()


def test_every_billing_import_resolves_and_the_defaults_are_free():
    surface = _imported_billing_symbols()
    if files_narrowed() and not surface:
        return  # none of the judged files imports billing
    assert surface, "scan found no billing imports — scanner broken?"
    out = _run_probe(surface)
    assert out.startswith("OK:")

    # Unconfigured, the engine counts dollars; the hosted registration
    # publishes its own conversion (CREDITS_PER_DOLLAR) before importing it.
    assert out == "OK:1"

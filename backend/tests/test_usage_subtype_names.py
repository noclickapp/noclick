"""Every charge the backend can record has a name a person reads.

The usage page, its drill-down and its CSV name a charge by its ``usage_subtype``
through one table, ``frontend/app/lib/usage/usageNames.json`` (``charges`` for
exact subtypes, ``families`` for ``prefix/*`` and ``*_suffix`` patterns; model ids
are named by the model rule in ``lib/usage/display.ts``). This test reads the
code for every subtype it can record: each ``usage_subtype=`` passed anywhere,
followed back through constants, dicts, imports, f-strings and the arguments
each writer's callers pass. A subtype the table doesn't name fails here rather
than reach a person as ``apps/build_cache``. A writer whose subtype can't be
followed to strings must say what it records (``DYNAMIC``). These are the
engine's writers; a deployment checks its own (``cloud/``) with the same
``recorded``, ``check_followed`` and ``check_named``."""

from __future__ import annotations

import ast
import fnmatch
import functools
import json
import pathlib
from typing import Dict, Iterator, List, Optional, Set, Tuple

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
NAMES = BACKEND.parent / "frontend" / "app" / "lib" / "usage" / "usageNames.json"

# Writers whose subtype is decided at run time, by what it is (path, enclosing function): reason.
DYNAMIC: Dict[Tuple[str, str], str] = {
    ("coder/openai_agent/billing.py", "*"): "model",  # each edition records its model calls in its own hook
    ("nodes/agent/handlers/kling.py", "*"): "model",
    ("nodes/agent/handlers/imagen.py", "*"): "model",
    ("utils/media_generation.py", "*"): "model",
    ("nodes/core/document_ingest.py", "*"): "model",  # embedding/<model>: the families name it
    ("nodes/core/apify_runner.py", "*"): "passthrough",  # each node's usage_subtype=, read where it passes it
    ("repositories/usage.py", "*"): "passthrough",  # rows read back
}

# The kinds a recurring charge can be, recorded as its subtype from its row.
RECURRING_KINDS = {"whatsapp_connection", "phone_number", "phone_number_setup"}

# Seen in production in the 90 days to 2026-10-17 (models aside), so rows recorded before a writer changed keep
# their names.
SEEN_IN_PRODUCTION = {
    "noclick/builder-1", "noclick/testing-1", "apps/build", "apps/build_cache", "apps/build_outputs", "apps/hosting",
    "apps/releases", "browser/minutes", "database/compute", "database/history", "database/rows_read",
    "database/rows_written", "database/storage", "email/agent_reply", "email/agent_update", "email/coordinator",
    "email/platform_app", "email/platform_human", "email/platform_inbox_reply", "email/send_node", "exa/search_api",
    "extraction/ai_transcription", "extraction/ai_video_digest", "instagram/scrape_profile",
    "linkedin/scrape_profile", "linkedin/search_posts", "linkedin/search_profiles", "noclick/transcribe-1",
    "perplexity/api", "reddit_scraping", "storage/repo", "storage/repo_clone", "storage/repo_push",
    "twitter/x_api", "voice/call", "agent/sandbox", "serverless/cpu", "phone_number", "whatsapp_connection",
}

Value = Tuple[str, str]  # ("exact" | "pattern" | "dynamic", text)


class Code:
    """The backend's modules, each parsed the first time something in it is read: the writers (files that pass
    ``usage_subtype=``), the modules their names come from, and the files that call a function whose parameter a
    subtype comes from (found by the function's name in their text)."""

    def __init__(self) -> None:
        self.sources: Dict[str, str] = {}
        for path in BACKEND.rglob("*.py"):
            rel = path.relative_to(BACKEND).as_posix()
            if rel.startswith(("tests/", "scripts/")) or "/tests/" in rel or path.name.startswith("debug_"):
                continue
            try:
                self.sources[rel] = path.read_text()
            except UnicodeDecodeError:
                continue
        self.module_of = {rel[:-3].replace("/", ".").removesuffix(".__init__"): rel for rel in self.sources}
        self.trees: Dict[str, ast.Module] = {}
        self.assigns: Dict[str, Dict[str, ast.AST]] = {}
        self.imports: Dict[str, Dict[str, Tuple[str, str]]] = {}
        self.module_aliases: Dict[str, Dict[str, str]] = {}
        self.parents: Dict[str, Dict[ast.AST, ast.AST]] = {}
        self.by_name: Dict[str, Dict[str, List[ast.Call]]] = {}

    def tree(self, rel: str) -> Optional[ast.Module]:
        if rel not in self.trees:
            try:
                tree = ast.parse(self.sources[rel])
            except SyntaxError:
                return None
            self.trees[rel] = tree
            assigns, imports, aliases, by_name = {}, {}, {}, {}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            assigns[target.id] = node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
                    assigns[node.target.id] = node.value
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    called = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
                    if called:
                        by_name.setdefault(called, []).append(node)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        source = self.module_of.get(f"{node.module}.{alias.name}")
                        if source:  # `from pkg import module`
                            aliases[alias.asname or alias.name] = source
                        else:
                            imports[alias.asname or alias.name] = (node.module, alias.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        source = self.module_of.get(alias.name)
                        if source:
                            aliases[alias.asname or alias.name.split(".")[-1]] = source
            self.assigns[rel], self.imports[rel], self.module_aliases[rel], self.by_name[rel] = assigns, imports, aliases, by_name
        return self.trees[rel]

    def enclosing(self, rel: str, node: ast.AST) -> Optional[ast.AST]:
        if rel not in self.parents:
            self.parents[rel] = {child: parent for parent in ast.walk(self.trees[rel])
                                 for child in ast.iter_child_nodes(parent)}
        parents = self.parents[rel]
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def writes(self) -> Iterator[Tuple[str, ast.Call]]:
        """Every call that passes ``usage_subtype=``."""
        for rel, text in self.sources.items():
            if "usage_subtype" in text and self.tree(rel) is not None:
                for calls in self.by_name[rel].values():
                    for call in calls:
                        if any(k.arg == "usage_subtype" for k in call.keywords):
                            yield rel, call

    def callers(self, rel: str, function: ast.AST) -> Iterator[Tuple[str, ast.Call, bool]]:
        """Calls of ``function`` (defined in ``rel``): by name in its own module, by attribute through a module alias
        or ``self``, or by an imported name. The bool says the call passes ``self`` implicitly."""
        name = function.name
        method = bool(function.args.args) and function.args.args[0].arg in ("self", "cls")
        for caller, text in self.sources.items():
            if f"{name}(" not in text or self.tree(caller) is None:
                continue
            for call in self.by_name[caller].get(name, ()):
                f = call.func
                if isinstance(f, ast.Name):
                    imported = self.imports[caller].get(name)
                    if caller == rel or (imported and imported[1] == name and self.module_of.get(imported[0]) == rel):
                        yield caller, call, method
                elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    if f.value.id in ("self", "cls") and caller == rel:
                        yield caller, call, method
                    elif self.module_aliases[caller].get(f.value.id) == rel:
                        yield caller, call, False

    def resolve(self, rel: str, expr: ast.AST, scope: Optional[ast.AST], seen: frozenset = frozenset()) -> Set[Value]:
        key = (rel, id(expr))
        if key in seen or len(seen) > 40:
            return {("dynamic", ast.unparse(expr))}
        seen = seen | {key}
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {("exact", expr.value)}
        if isinstance(expr, ast.JoinedStr):
            parts: List[Set[str]] = []
            for piece in expr.values:
                if isinstance(piece, ast.Constant):
                    parts.append({str(piece.value)})
                else:
                    inner = self.resolve(rel, piece.value, scope, seen)
                    parts.append({v for k, v in inner if k == "exact"} if all(k == "exact" for k, _ in inner) else {"*"})
            return _join(parts)
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
            left, right = (self.resolve(rel, side, scope, seen) for side in (expr.left, expr.right))
            return _join([_texts(left), _texts(right)])
        if isinstance(expr, ast.IfExp):
            return self.resolve(rel, expr.body, scope, seen) | self.resolve(rel, expr.orelse, scope, seen)
        if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
            table = self._lookup(rel, expr.value.id)
            if table and isinstance(table[1], ast.Dict):
                out: Set[Value] = set()
                for value in table[1].values:
                    out |= self.resolve(table[0], value, None, seen)
                return out
        if isinstance(expr, ast.Name):
            if scope is not None and expr.id in _params(scope):
                return self._from_callers(rel, scope, expr.id, seen)
            found = self._lookup(rel, expr.id)
            if found:
                return self.resolve(found[0], found[1], None, seen)
        return {("dynamic", ast.unparse(expr))}

    def _lookup(self, rel: str, name: str) -> Optional[Tuple[str, ast.AST]]:
        self.tree(rel)
        if name in self.assigns[rel]:
            return rel, self.assigns[rel][name]
        if name in self.imports[rel]:
            module, original = self.imports[rel][name]
            source = self.module_of.get(module)
            if source and self.tree(source) is not None and original in self.assigns[source]:
                return source, self.assigns[source][original]
        return None

    def _from_callers(self, rel: str, function: ast.AST, param: str, seen: frozenset) -> Set[Value]:
        names = _params(function)
        index = names.index(param)
        out: Set[Value] = set()
        default = _default(function, param)
        for caller, call, implicit_self in self.callers(rel, function):
            arg = next((k.value for k in call.keywords if k.arg == param), None)
            position = index - (1 if implicit_self else 0)
            if arg is None and 0 <= position < len(call.args) and not isinstance(call.args[position], ast.Starred):
                arg = call.args[position]
            if arg is not None:
                out |= self.resolve(caller, arg, self.enclosing(caller, call), seen)
            elif default is not None:
                out |= self.resolve(rel, default, None, seen)
        return out or {("dynamic", f"{function.name}({param})")}


def _params(function: ast.AST) -> List[str]:
    args = function.args
    return [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]


def _default(function: ast.AST, param: str) -> Optional[ast.AST]:
    args = function.args
    positional = args.posonlyargs + args.args
    for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
        if arg.arg == param:
            return default
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if arg.arg == param:
            return default
    return None


def _texts(values: Set[Value]) -> Set[str]:
    return {v if kind != "dynamic" else "*" for kind, v in values}


def _join(parts: List[Set[str]]) -> Set[Value]:
    out = {""}
    for options in parts:
        out = {a + b for a in out for b in options}
    return {("pattern" if "*" in text else "exact", text) for text in out}


@functools.lru_cache(maxsize=1)
def _code() -> Code:
    return Code()


@functools.lru_cache(maxsize=2)
def recorded(dynamic: frozenset = frozenset(DYNAMIC), hosted: bool = False) -> Dict[Value, List[str]]:
    """Every subtype the engine's writers (``hosted``: a deployment's, under ``cloud/``) can record, with where,
    leaving out the writers ``dynamic`` names."""
    code = _code()
    found: Dict[Value, List[str]] = {}
    for rel, call in code.writes():
        if rel.startswith("cloud/") != hosted:
            continue
        for keyword in call.keywords:
            if keyword.arg != "usage_subtype":
                continue
            function = code.enclosing(rel, call)
            where = f"{rel}:{call.lineno}"
            if (rel, function.name if function else "") in dynamic or (rel, "*") in dynamic:
                continue
            for value in code.resolve(rel, keyword.value, function):
                found.setdefault(value, []).append(where)
    return found


def names() -> dict:
    return json.loads(NAMES.read_text())


def named(subtype: str, table: dict) -> bool:
    if subtype in table["charges"]:
        return True
    return any(fnmatch.fnmatchcase(subtype, pattern) for pattern in table["families"])


def exact(found: Dict[Value, List[str]]) -> Set[str]:
    return {v for kind, v in found if kind == "exact"}


def check_followed(found: Dict[Value, List[str]]) -> None:
    dynamic = sorted(f"{v} at {', '.join(w)}" for (kind, v), w in found.items() if kind == "dynamic")
    assert not dynamic, (
        "A writer records a subtype this test can't follow to strings. Say what it records in DYNAMIC, or pass a "
        "constant:\n  " + "\n  ".join(dynamic))


def check_named(found: Dict[Value, List[str]]) -> None:
    table = names()
    missing = sorted(f"{v}  ({', '.join(sorted(set(w))[:3])})" for (kind, v), w in found.items()
                     if kind == "exact" and not named(v, table))
    assert not missing, "Name these in frontend/app/lib/usage/usageNames.json:\n  " + "\n  ".join(missing)
    patterns = sorted(f"{v}  ({', '.join(sorted(set(w))[:3])})" for (kind, v), w in found.items()
                      if kind == "pattern" and v not in table["families"])
    assert not patterns, ("A writer records a family of subtypes; name the family (the same pattern) in "
                          "usageNames.json `families`:\n  " + "\n  ".join(patterns))


def test_the_code_records_subtypes_this_test_can_read():
    found = recorded()
    check_followed(found)
    # The resolver reaches through dicts, imports and callers' arguments: a few it must find.
    assert {"email/agent_update", "noclick/builder-1"} <= exact(found)


def test_every_subtype_the_code_records_has_a_name():
    check_named(recorded())


@pytest.mark.parametrize("subtype", sorted(RECURRING_KINDS | SEEN_IN_PRODUCTION))
def test_what_production_and_recurring_charges_hold_is_named(subtype):
    assert named(subtype, names()), f"{subtype} has no name in usageNames.json"


def test_names_read_as_english():
    table = names()
    for subtype, name in {**table["charges"], **table["families"]}.items():
        assert "/" not in name and "_" not in name, f"{subtype} is named {name!r}: write it out in words"
        assert name[:1].isupper() or name.startswith("{}"), f"{subtype} is named {name!r}: start it with a capital"

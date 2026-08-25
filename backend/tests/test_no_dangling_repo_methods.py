"""Every repository method a handler calls must exist on that repository.

The community edition is produced by pruning the full tree, and a pruner that
removes an unreferenced method is right until the reference it missed is a
`repo.method(...)` attribute — which no import check and no linter follows. The
result is an `AttributeError` at the moment a user does the thing, with a green
test suite behind it: `ConversationRepo.list_recent_for_workflow` shipped
missing, and the builder chat raised on every workflow open.

This walks the call sites instead of the imports. It resolves a local to a
repository class through the nearest preceding assignment in the same function,
which is how the handlers actually bind them (`repo = ConversationRepo(pool)`),
and skips anything it cannot resolve — a missed call is a gap in coverage, a
wrong one would be a false failure nobody could act on.
"""

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND / "repositories"


def _repository_members() -> dict[str, set[str]]:
    members: dict[str, set[str]] = {}
    for path in sorted(REPO_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names = set()
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(item.name)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    names.add(item.target.id)
                elif isinstance(item, ast.Assign):
                    names.update(t.id for t in item.targets if isinstance(t, ast.Name))
            # A subclass inherits its base's surface; resolve what we can see.
            for base in node.bases:
                base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
                if base_name in members:
                    names |= members[base_name]
            members.setdefault(node.name, set()).update(names)
    return members


def _constructed_class(value: ast.expr, known: dict) -> str | None:
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    return name if name in known else None


def _scan(tree: ast.AST, path: str, known: dict) -> list[str]:
    """Attribute accesses on locals bound to a repository, in statement order."""
    problems: list[str] = []

    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            continue
        # (line, name) -> class, so a later rebinding of the same name wins for
        # accesses below it. Handlers reuse `repo` for two repositories in one
        # function; whole-function maps report the other one's methods missing.
        bindings: list[tuple[int, str, str | None]] = []
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                cls = _constructed_class(node.value, known)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bindings.append((node.lineno, target.id, cls))
        if not any(cls for _, _, cls in bindings):
            continue

        for node in ast.walk(scope):
            if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)):
                continue
            candidates = [
                (line, cls) for line, name, cls in bindings
                if name == node.value.id and line <= node.lineno
            ]
            if not candidates:
                continue
            cls = max(candidates, key=lambda c: c[0])[1]
            if cls and node.attr not in known[cls] and not node.attr.startswith("__"):
                problems.append(f"{path}:{node.lineno}  {cls}.{node.attr}")
    return problems


def test_every_called_repository_method_exists():
    known = _repository_members()
    assert "ConversationRepo" in known, "repository package did not parse"

    problems: list[str] = []
    for path in sorted(BACKEND.rglob("*.py")):
        if any(p in {"__pycache__", ".venv", "tests"} for p in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue
        problems += _scan(tree, str(path.relative_to(BACKEND)), known)

    assert not problems, (
        "These repository methods are called and not defined:\n  "
        + "\n  ".join(sorted(set(problems)))
        + "\n\nPort the method rather than deleting the call: the caller is the "
        "feature, and the missing method is the pruner's mistake."
    )

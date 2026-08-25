"""Every unguarded first-party import must resolve in the shipped tree.

Static resolution covers deferred imports that a boot check cannot exercise.
"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

SKIP_DIR_NAMES = {
    "__pycache__", ".venv", "node_modules", ".git", "build", "dist",
    ".noclick", ".noclick-home", "logs",
}

# Top-level packages that belong to this codebase (resolved against BACKEND).
FIRST_PARTY = {
    p.name
    for p in BACKEND.iterdir()
    if p.is_dir() and not p.name.startswith(".") and p.name not in SKIP_DIR_NAMES
}


def _module_exists(dotted: str) -> bool:
    """True if `dotted` resolves to a module or package under backend/."""
    rel = Path(*dotted.split("."))
    return (BACKEND / rel).with_suffix(".py").is_file() or (BACKEND / rel / "__init__.py").is_file()


def _is_first_party(dotted: str) -> bool:
    return dotted.split(".")[0] in FIRST_PARTY


def _iter_python_files():
    for path in BACKEND.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        yield path


def _guarded_import_lines(tree: ast.AST) -> set:
    """Line numbers of imports inside a try/except that catches ImportError.

    That shape is a deliberate optional dependency — the module is allowed to be
    absent and the code has a path for it. Only UNguarded imports of a missing
    module are latent crashes.
    """
    guarded = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches_import_error = any(
            handler.type is None
            or (isinstance(handler.type, ast.Name)
                and handler.type.id in {"ImportError", "ModuleNotFoundError", "Exception"})
            or (isinstance(handler.type, ast.Tuple)
                and any(isinstance(e, ast.Name)
                        and e.id in {"ImportError", "ModuleNotFoundError", "Exception"}
                        for e in handler.type.elts))
            for handler in node.handlers
        )
        if not catches_import_error:
            continue
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    guarded.add(sub.lineno)
    return guarded


def _imported_modules(tree: ast.AST):
    """Yield (dotted_name, lineno) for unguarded absolute imports naming a module."""
    guarded = _guarded_import_lines(tree)
    for node in ast.walk(tree):
        if node.lineno in guarded if hasattr(node, "lineno") else False:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import: resolved against the package, not
            # the repo root, so it is out of scope here.
            if node.level == 0 and node.module:
                yield node.module, node.lineno


def test_no_imports_of_missing_first_party_modules():
    dangling = []
    for path in _iter_python_files():
        try:
            tree = ast.parse(path.read_text(errors="ignore"), filename=str(path))
        except SyntaxError:
            continue  # not our concern here
        rel = path.relative_to(BACKEND).as_posix()
        for dotted, lineno in _imported_modules(tree):
            if _is_first_party(dotted) and not _module_exists(dotted):
                dangling.append(f"backend/{rel}:{lineno}: imports missing module '{dotted}'")

    assert not dangling, (
        "These imports name first-party modules that do not exist in this tree. "
        "If a module was stripped from the export, its importers must be stripped "
        "or adapted too — otherwise the failure only surfaces when a user reaches "
        "the code path:\n  " + "\n  ".join(sorted(set(dangling)))
    )

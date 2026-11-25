"""Keep ``noclick/__init__.py``'s imports and ``__all__`` one name per line.

    python scripts/export_list.py            # rewrite the file in its one form
    python scripts/export_list.py --check    # exit 1 when it isn't in that form

Each module's names are imported in one block, the blocks ordered by module and the names in each sorted;
``__all__`` keeps the order it's written in, which is the order the reference lists a page's names in, one name a
line. Two changes that each add a name touch different lines, so they rarely conflict. Nothing else is in the file
but its docstring.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, List

INIT = Path(__file__).resolve().parents[1] / "noclick" / "__init__.py"


def canonical(source: str) -> str:
    tree = ast.parse(source)
    docstring = tree.body[0]
    if not (isinstance(docstring, ast.Expr) and isinstance(docstring.value, ast.Constant)):
        raise ValueError("noclick/__init__.py must open with its docstring")
    imports: Dict[str, List[str]] = {}
    exported: List[str] = []
    for node in tree.body[1:]:
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            for alias in node.names:
                if alias.asname:
                    raise ValueError(f"import {alias.name} as {alias.asname}: export it by its own name")
                imports.setdefault(node.module or "", []).append(alias.name)
        elif isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["__all__"]:
            exported = [ast.literal_eval(e) for e in node.value.elts]
        else:
            raise ValueError(f"line {node.lineno}: only relative imports and __all__ may follow the docstring")
    if len(set(exported)) != len(exported):
        raise ValueError(f"__all__ names {sorted({n for n in exported if exported.count(n) > 1})} twice")
    head = "\n".join(source.splitlines()[: docstring.end_lineno])
    parts = [head, ""]
    for module in sorted(imports):
        names = sorted(set(imports[module]))
        parts.append(f"from .{module} import (\n" + "".join(f"    {n},\n" for n in names) + ")")
    parts.append("\n__all__ = [\n" + "".join(f'    "{n}",\n' for n in exported) + "]")
    return "\n".join(parts) + "\n"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the file isn't in its one form")
    args = parser.parse_args(argv)
    source = INIT.read_text()
    want = canonical(source)
    if args.check:
        if source != want:
            print(f"{INIT.name} isn't one name per line in order: run python scripts/export_list.py", file=sys.stderr)
            return 1
        return 0
    INIT.write_text(want)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""noclick/__init__.py is one name per line, in order (scripts/export_list.py), so two changes adding names merge
cleanly; and every name it exports is one the package has."""

import importlib.util
from pathlib import Path

import noclick

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_list.py"


def test_the_export_list_is_one_name_per_line_in_order_and_every_name_resolves():
    spec = importlib.util.spec_from_file_location("export_list", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--check"]) == 0, "run: python scripts/export_list.py"
    assert [n for n in noclick.__all__ if not hasattr(noclick, n)] == []

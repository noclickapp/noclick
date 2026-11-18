"""The version the client reports is the one it's published as: ``noclick.__version__`` (sent in the User-Agent)
is written by hand in ``noclick/_version.py``, so a release that raises pyproject.toml must raise it too."""

import re
from pathlib import Path

import noclick


def test_version_is_pyprojects():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    [declared] = re.findall(r'^version = "([^"]+)"$', pyproject, flags=re.MULTILINE)
    assert noclick.__version__ == declared

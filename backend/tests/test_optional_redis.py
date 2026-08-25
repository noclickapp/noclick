"""Redis is optional in this edition, so "no Redis" must be a configuration, not
an error.

Two modules used to read `os.getenv("REDIS_URL", "redis://localhost:6379")`.
On a host that never ran Redis — which is the default self-hosted install —
that default produced a refused connection logged at ERROR on every start,
and an empty `REDIS_URL=` in a compose file or PaaS dashboard produced the
same, because an empty string beats a getenv default.

`redis_url_or_none` is the one place that decides. These tests pin the answer
and the absence of a second one.
"""

import ast
import os
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_absent_or_blank_redis_url_is_none(value, monkeypatch):
    from utils.redis_client import redis_url_or_none

    if value is None:
        monkeypatch.delenv("REDIS_URL", raising=False)
    else:
        monkeypatch.setenv("REDIS_URL", value)
    assert redis_url_or_none() is None, f"REDIS_URL={value!r} must read as no Redis"


def test_configured_redis_url_passes_through(monkeypatch):
    from utils.redis_client import redis_url_or_none

    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/2")
    assert redis_url_or_none() == "redis://cache:6379/2"


def _shipped_backend_modules():
    """Every non-test Python module present in this shipped backend tree."""
    return [
        candidate
        for candidate in BACKEND.rglob("*.py")
        if not any(part in {"__pycache__", "tests", ".venv"} for part in candidate.parts)
    ]


def test_no_module_defaults_redis_url_to_localhost():
    """A default URL is worse than no URL: it converts "Redis is not part of
    this deployment" into a connection error, once per process, for a service
    that is meant to degrade silently."""
    offenders = []
    for path in _shipped_backend_modules():
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) != 2:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in ("getenv", "get"):
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value == "REDIS_URL":
                offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    assert not offenders, (
        "REDIS_URL read with a fallback value at:\n  " + "\n  ".join(offenders)
        + "\nUse utils.redis_client.redis_url_or_none() instead."
    )

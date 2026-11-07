"""Test names that stay short, whatever a test is parametrized with.

A parameter is printed whole as part of its test's name: a 2 MB body made two
2 MB log lines and froze GitHub's log reader, and the job with it (every
open-edition run of the integration trains that carried one, 2026-11-07).
Imported into each conftest the editions use (the open edition ships no
backend/conftest.py), so every suite registers the hook.
"""


def pytest_make_parametrize_id(config, val, argname):
    if isinstance(val, (str, bytes)) and len(val) > 200:
        return f"{argname}-{type(val).__name__}-{len(val)}"
    return None

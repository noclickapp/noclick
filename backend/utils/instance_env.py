"""Instance settings applied to the process environment (self-hosted only).

Two stores use this — OAuth apps and model-provider keys — and share one rule:
a value that came from the real environment is never overwritten, and a value
this process applied from the database is tagged so it can be replaced when
the stored value changes or taken back when it is deleted, without a restart.
"""

import os


def applied_by_store(name: str, tag_prefix: str) -> bool:
    return os.environ.get(f"{tag_prefix}{name}") == "1"


def apply_value(name: str, value: str, tag_prefix: str) -> bool:
    """Set ``name`` unless the real environment defines it. A value this process
    applied earlier is replaced — a rotated key must take effect. Returns whether
    the environment changed."""
    if not value:
        return False
    if os.environ.get(name) and not applied_by_store(name, tag_prefix):
        return False
    if os.environ.get(name) == value:
        return False
    os.environ[name] = value
    os.environ[f"{tag_prefix}{name}"] = "1"
    return True


def release_value(name: str, tag_prefix: str) -> None:
    """Drop ``name`` if this process applied it; a real environment value stays."""
    if applied_by_store(name, tag_prefix):
        os.environ.pop(name, None)
        os.environ.pop(f"{tag_prefix}{name}", None)

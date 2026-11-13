"""Keep what a test worker has imported out of the garbage collector's walks, as a warmed server does.

A worker that has imported every integration tracks millions of long-lived objects (modules,
classes, schemas). A full collection walks them all while holding the GIL, about five seconds
on CI's runners, inside whatever test is running: an automatic one, or the one the workflow
runner makes after each node once the process passes 3 GB. A test with a deadline then fails
for nothing it did. A server freezes its heap once it has warmed up for the same reason; a
worker imports as its tests ask, so it collects and freezes after any test that brought in a
large batch of modules, and later collections walk only what tests make.
"""
import gc
import sys

import pytest

# Loading every integration adds about 3,800 modules; a test file's own imports, a few dozen.
NEW_MODULES = 1000

_modules_at_freeze = 0


@pytest.hookimpl(trylast=True)
def pytest_runtest_logfinish(nodeid, location):
    global _modules_at_freeze
    if len(sys.modules) - _modules_at_freeze >= NEW_MODULES:
        gc.collect()
        gc.freeze()
        _modules_at_freeze = len(sys.modules)

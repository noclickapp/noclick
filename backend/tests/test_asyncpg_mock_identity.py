"""
asyncpg class-identity invariant across the suite's mock/restore cycle.

tests/mocks/mock_asyncpg.py swaps sys.modules['asyncpg'] for a mock (imported
transitively by every handler test via base_handler_test), and
tests/fixtures/postgres_fixtures.py restores the real module for
testcontainers tests. `except` matches on class IDENTITY: if the restore
re-imports asyncpg instead of restoring the ORIGINAL module object (or the
mock aliases exception classes to bare Exception), app modules bound on one
side of the swap can't catch exceptions raised from the other — an
order-dependent flake that hit test_email_trigger's unique-violation test in
CI whenever collection order moved email_reservation_manager's import.

Runs in a subprocess so the sys.modules surgery can't leak into this process.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

SCRIPT = """
import sys

# 1. An app module binds the real asyncpg (like nodes/core/registry pulling in
#    email_reservation_manager early during collection).
import utils.email_reservation_manager as manager

# 2. A handler test installs the global mock (the base_handler_test path).
import tests.mocks.mock_asyncpg

# While mocked, the exception classes must still BE the real ones so app code
# bound to either module object catches consistently.
import asyncpg as mocked_binding
assert mocked_binding.UniqueViolationError is manager.asyncpg.UniqueViolationError, (
    "mock_asyncpg must reuse the real exception classes"
)

# 3. A postgres-fixture file restores the real module.
from tests.fixtures.postgres_fixtures import restore_real_asyncpg
restore_real_asyncpg()

# 4. A later test module binds asyncpg fresh — must be the SAME module object.
import asyncpg
assert asyncpg is manager.asyncpg, "asyncpg module identity diverged across mock/restore"
assert asyncpg.UniqueViolationError is manager.asyncpg.UniqueViolationError

# The original failure shape: a test-side raise must be caught app-side.
try:
    raise asyncpg.UniqueViolationError("dup")
except manager.asyncpg.UniqueViolationError:
    pass

print("IDENTITY_OK")
"""


def test_asyncpg_identity_survives_mock_and_restore():
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        capture_output=True,
        text=True,
        cwd=BACKEND_DIR,
        env={
            "PYTHONPATH": f"{BACKEND_DIR}:{BACKEND_DIR.parent}",
            "PATH": "/usr/bin:/bin",
        },
    )
    assert proc.returncode == 0, f"identity check failed:\n{proc.stderr}"
    assert "IDENTITY_OK" in proc.stdout

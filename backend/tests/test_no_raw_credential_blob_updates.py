"""Structural regression: no raw SQL writes to the credentials blob.

The encrypted ``credentials.credential`` column must only be written through
``utils/credentials.py`` (``update_credential_data_detailed`` — clears
``revoked_at`` so reconnect un-bricks auto-revoked credentials, strips
row-level bookkeeping keys, and supports the ``token_version`` CAS guard).

History this pins against:
- 20 OAuth handlers hand-rolled ``UPDATE credentials SET credential = $1``
  in their manual-refresh paths — unlocked, unaudited, racing the execute-path
  refresh (fixed 2026-06-10 by routing through ``manual_refresh_credential``).
- The Supabase handler wrote to ``encrypted_data``, a column that does not
  exist, consuming a rotated single-use refresh token and then failing the
  persist — bricking the credential deterministically.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# The one sanctioned writer of the encrypted blob.
ALLOWED = {BACKEND / "utils" / "credentials.py"}

# Each UPDATE statement is inspected in a bounded window so the match can't
# bridge across unrelated statements or docstrings in the same file.
_UPDATE_STMT = re.compile(r"UPDATE\s+(?:public\.)?credentials\b", re.IGNORECASE)
_BLOB_ASSIGN = re.compile(
    r"\bSET\b[^\"]{0,200}?\b(credential|encrypted_data)\s*=",
    re.IGNORECASE | re.DOTALL,
)


def _python_sources():
    for path in BACKEND.rglob("*.py"):
        parts = path.relative_to(BACKEND).parts
        if "__pycache__" in parts or parts[0] in ("tests",) or "tests" in parts:
            continue
        yield path


def test_no_raw_credential_blob_updates():
    violations = []
    for path in _python_sources():
        if path in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for stmt in _UPDATE_STMT.finditer(text):
            window = text[stmt.end():stmt.end() + 250]
            assign = _BLOB_ASSIGN.search(window)
            if assign:
                line = text.count("\n", 0, stmt.start()) + 1
                violations.append(
                    f"{path.relative_to(BACKEND)}:{line} writes credentials.{assign.group(1)}"
                )
    assert not violations, (
        "Raw SQL writes to the credentials blob found — route them through "
        "utils.credentials.update_credential_data(_detailed) instead:\n  "
        + "\n  ".join(violations)
    )


def test_no_encrypted_data_column_references():
    """``encrypted_data`` is not a column on credentials — any SQL mentioning
    it is writing into the void (the Supabase handler bug)."""
    violations = []
    for path in _python_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"SET\s+encrypted_data\s*=", text, re.IGNORECASE):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(BACKEND)}:{line}")
    assert not violations, f"SQL writes to nonexistent encrypted_data column: {violations}"

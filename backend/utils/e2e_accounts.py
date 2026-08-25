"""Community installs do not reserve managed-service test identities."""

from __future__ import annotations

from typing import Optional


def is_e2e_test_email(email: Optional[str]) -> bool:
    del email
    return False

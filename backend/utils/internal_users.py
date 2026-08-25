"""Internal-user configuration for self-hosted installations.

The hosted service has its own staff identities. They are deliberately absent
from this edition: an operator can build an admin policy appropriate for their
installation without inheriting NoClick staff privileges or personal data.
"""

INTERNAL_USER_EMAILS = frozenset()


def is_internal_user(email: str) -> bool:
    """No hosted staff identity is privileged in a self-hosted installation."""
    return False

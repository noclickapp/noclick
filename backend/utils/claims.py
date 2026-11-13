"""Claims a deployment narrows (``utils.capabilities.CLAIM_FILTER``).

A worker claiming rows from a shared queue adds ``claimable(owner_sql, since_sql)``
to its WHERE clause. With no filter registered that is the empty string, so the
claim's SQL is exactly what it would be without this module.
"""

from utils.capabilities import CLAIM_FILTER, capability


def claimable(owner_sql: str, since_sql: str) -> str:
    """`` AND (predicate)`` narrowing a claim to the rows this process takes, or "" when it takes any.
    ``owner_sql`` is the SQL naming whose row it is, ``since_sql`` when it became ready to take."""
    narrow = capability(CLAIM_FILTER)
    return f" AND ({narrow(owner_sql, since_sql)})" if narrow is not None else ""

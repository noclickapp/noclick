"""Canonical read-only authority for supplied 123FormBuilder v2 tokens."""
from datetime import datetime
from repositories.oauth_refresh_authority import OAuthRefreshAuthorityRepo


class FormBuilder123AuthorityRepo(OAuthRefreshAuthorityRepo):
    async def load(self, *args, **kwargs):
        row, org = await super().load(*args, **kwargs)
        if row is not None:
            stamp = row["updated_at"]
            if not isinstance(stamp, datetime) or stamp.tzinfo is None:
                raise ValueError("123FormBuilder saved credential timestamp is invalid")
        return row, org

    async def persist(self, *args, **kwargs):
        raise RuntimeError("123FormBuilder supplied tokens are not rotated by the node")

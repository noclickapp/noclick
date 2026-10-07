"""Read-only canonical saved-key authority for native OpenStatus.
The common repository supplies access/owner/team/workflow guards; this native
adapter requires a real version timestamp and refuses all token persistence.
"""
from datetime import datetime
from repositories.oauth_refresh_authority import OAuthRefreshAuthorityRepo


class OpenStatusAuthorityRepo(OAuthRefreshAuthorityRepo):
    async def load(self, *args, **kwargs):
        row, org = await super().load(*args, **kwargs)
        if row is not None and (not isinstance(row["updated_at"], datetime) or row["updated_at"].tzinfo is None):
            raise ValueError("OpenStatus saved credential timestamp is invalid")
        return row, org

    async def persist(self, *args, **kwargs):
        raise RuntimeError("OpenStatus supplied keys are not refreshed or persisted")

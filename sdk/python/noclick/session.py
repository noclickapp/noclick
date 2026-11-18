"""User sessions: a short-lived token for one user, safe to hand to a browser.

    session = user.session(scopes=["agents", "humans"], ttl_s=3600)
    token = session.token                       # your frontend uses it as its API key

    client = noclick.Client.for_session(session)     # or act as that user from Python
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SESSION_TOKEN_PREFIX = "nk_sess_"


@dataclass(frozen=True)
class Session:
    """A token pinned to one user with a subset of the minting key's scopes.
    Its ``repr`` never shows the token."""

    token: str = dc_field(repr=False)
    id: Optional[str]
    user_id: Optional[str]
    scopes: List[str]
    expires_at: Any
    raw: Dict[str, Any] = dc_field(repr=False)
    base_url: Optional[str] = dc_field(default=None, repr=False)

    @property
    def expired(self) -> bool:
        """Whether ``expires_at`` has passed (by this machine's clock)."""
        if not isinstance(self.expires_at, datetime):
            return False
        expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        return expires <= datetime.now(timezone.utc)

    def client(self, **kwargs: Any) -> Any:
        """A client that acts as this session: ``noclick.Agent.list(client=session.client())``.

        Returns:
            A client holding the session's token, pointed at the API the session came from. Every
            call it makes acts as the session's user, with the session's scopes.

        Usage::

            user = noclick.User.from_id("user_42")
            session = user.session(["agents"], ttl_s=600)
            as_ana = session.client()
            noclick.Agent.list(client=as_ana)   # Ana's agents and the shared ones, nothing else
        """
        from ._client import Client

        return Client.for_session(self, **kwargs)

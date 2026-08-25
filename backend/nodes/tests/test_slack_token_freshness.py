"""Tests for Slack credential freshening (the load-time refresh choke point).

``SlackNode.freshen_credential`` is the single place every NON-execute path
(channel dropdown, trigger registration, trigger tests) renews expiring Slack
rotation tokens. These tests pin that contract so a future read path can't
regress into consuming a stale token.

Run: pytest nodes/tests/test_slack_token_freshness.py -v
"""

from datetime import datetime, timedelta, timezone

from unittest.mock import AsyncMock, patch

from nodes.core.base import WorkflowNode
from nodes.slack_node import SlackNode
from nodes.oauth.slack_oauth import SlackTokens


def _iso(delta_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _slack_tokens(access_token: str, refresh_token: str, token_type: str = "bot") -> SlackTokens:
    return SlackTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=_iso(43200),
        scope="chat:write",
        token_type=token_type,
    )


class TestSlackFreshenCredential:
    async def test_refreshes_expired_bot_token(self):
        cred = {"access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600)}
        with patch(
            "nodes.oauth.slack_oauth.refresh_access_token",
            new=AsyncMock(return_value=_slack_tokens("fresh-bot", "r2")),
        ) as refresh, patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "stale", "refresh_token": "r1", "expires_at": _iso(-3600),
            }),
        ), patch(
            "utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))
        ):
            out = await SlackNode.freshen_credential(
                cred, pool=object(), user_id="uid", credential_id="cid"
            )
        refresh.assert_awaited_once()
        assert out["access_token"] == "fresh-bot"
        assert out["refresh_token"] == "r2"  # rotated token adopted

    async def test_noop_for_nonexpiring_bot_token_credential(self):
        # A manual bot token (xoxb-, no rotation): no refresh_token, no expiry.
        cred = {"access_token": "xoxb-permanent", "expires_at": None}
        with patch("nodes.oauth.slack_oauth.refresh_access_token", new=AsyncMock()) as refresh:
            out = await SlackNode.freshen_credential(cred, pool=object())
        refresh.assert_not_awaited()
        assert out["access_token"] == "xoxb-permanent"

    async def test_noop_when_bot_token_still_valid(self):
        cred = {"access_token": "good", "refresh_token": "r1", "expires_at": _iso(3600)}
        with patch("nodes.oauth.slack_oauth.refresh_access_token", new=AsyncMock()) as refresh:
            out = await SlackNode.freshen_credential(
                cred, pool=object(), user_id=None, credential_id=None
            )
        refresh.assert_not_awaited()
        assert out["access_token"] == "good"

    async def test_force_refreshes_future_expiry_token_that_slack_rejects(self):
        cred = {"access_token": "revoked", "refresh_token": "r1", "expires_at": _iso(3600)}
        with patch(
            "nodes.oauth.slack_oauth.validate_token",
            new=AsyncMock(return_value=(False, None)),
        ), patch(
            "nodes.oauth.slack_oauth.refresh_access_token",
            new=AsyncMock(return_value=_slack_tokens("fresh-bot", "r2")),
        ) as refresh, patch(
            "utils.credential_loader.load_credential",
            new=AsyncMock(return_value={
                "access_token": "revoked", "refresh_token": "r1", "expires_at": _iso(3600),
            }),
        ), patch(
            "utils.credentials.update_credential_data_detailed", new=AsyncMock(return_value=(1, None))
        ):
            out = await SlackNode.freshen_credential(
                cred, pool=object(), user_id="uid", credential_id="cid"
            )
        refresh.assert_awaited_once_with("r1", None, None)
        assert out["access_token"] == "fresh-bot"
        assert out["refresh_token"] == "r2"

    async def test_does_not_refresh_user_token_on_bot_only_paths(self):
        # freshen_credential is bot-only: dropdown / trigger paths use the bot
        # token, so an expired user (xoxp-) token is left for the execute path
        # (_ensure_fresh_token, send_as=user) rather than burning a single-use
        # user rotation here.
        cred = {
            "access_token": "bot",
            "refresh_token": "br",
            "expires_at": _iso(3600),  # bot still valid
            "user_access_token": "stale-user",
            "user_refresh_token": "ur1",
            "user_expires_at": _iso(-3600),  # user expired — must be left alone
        }
        with patch("nodes.oauth.slack_oauth.refresh_access_token", new=AsyncMock()) as refresh:
            out = await SlackNode.freshen_credential(
                cred, pool=object(), user_id=None, credential_id=None
            )
        refresh.assert_not_awaited()
        assert out["access_token"] == "bot"
        assert out["user_access_token"] == "stale-user"  # untouched

    async def test_empty_credential_passthrough(self):
        assert await SlackNode.freshen_credential({}) == {}

    async def test_base_hook_is_noop(self):
        data = {"access_token": "x"}
        assert await WorkflowNode.freshen_credential(data) is data


def _node_has_rotating_oauth_credential(cls) -> bool:
    """True if any of the node's credential models has a ``refresh_token`` field
    (i.e. a rotating OAuth credential whose access token expires)."""
    import typing

    from pydantic import BaseModel as _BaseModel

    config_model = cls.get_config_model()
    if config_model is None or not hasattr(config_model, "model_fields"):
        return False
    cred_field = config_model.model_fields.get("credentials")
    if cred_field is None:
        return False
    members = typing.get_args(cred_field.annotation) or (cred_field.annotation,)
    return any(
        isinstance(m, type)
        and issubclass(m, _BaseModel)
        and "refresh_token" in m.model_fields
        for m in members
    )


def test_rotating_oauth_nodes_freshen_on_load():
    """Structural guard: every node with a rotating OAuth credential (a
    credential model exposing ``refresh_token``) MUST override freshen_credential,
    or its dropdown / trigger-registration paths silently serve a stale token.
    Iterates the live registry so a newly-added OAuth node that forgets the
    override fails loudly at CI rather than silently in prod."""
    from nodes.core.registry import NODE_REGISTRY

    base_freshen = WorkflowNode.freshen_credential.__func__
    offenders = []
    for key, cls in NODE_REGISTRY.items():
        if not _node_has_rotating_oauth_credential(cls):
            continue
        # A correct override is a @classmethod (bound method with __func__ that
        # differs from the base). A plain-function/instance-method override has
        # no __func__ and binds credential_data to cls/self — broken at the
        # freshen-at-load callers, so flag it here rather than crash.
        func = getattr(cls.freshen_credential, "__func__", None)
        if func is None or func is base_freshen:
            offenders.append(key)
    assert not offenders, (
        "Rotating-OAuth nodes missing a proper @classmethod freshen_credential "
        f"override (dropdowns/triggers would serve stale tokens): {sorted(offenders)}"
    )

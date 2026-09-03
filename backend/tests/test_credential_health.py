"""Credential provider-session health seam (utils/credential_health.py).

Every surface that reasons about credentials (picker, validation, builder,
describe_workflow) reads this one seam, so its contract is pinned here:
verdicts only for definitively-known sessions, unknown is NEVER dead.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from utils.credential_health import CredentialHealth, get_credential_health


def _qr_row(cred_id, conn_id):
    return {
        "id": cred_id,
        "credential_type": "whatsapp_qr",
        "metadata": {"connection_id": conn_id} if conn_id else {},
    }


@pytest.mark.asyncio
async def test_statuses_map_to_health_verdicts():
    rows = [_qr_row("cred-live", "c1"), _qr_row("cred-dead", "c2"), _qr_row("cred-gone", "c3")]
    with patch("utils.whatsapp_qr.get_connection_statuses", return_value={"c1": "connected", "c2": "failed"}):
        health = await get_credential_health(rows)

    assert health["cred-live"] == CredentialHealth(status="connected", healthy=True, hint=None)
    assert health["cred-dead"].healthy is False
    assert health["cred-dead"].status == "failed"
    # The hint must steer recovery toward re-scan of the SAME credential.
    assert "do not create a new credential" in health["cred-dead"].hint
    # Absent from WAHooks = definitively gone.
    assert health["cred-gone"].status == "missing"
    assert health["cred-gone"].healthy is False


@pytest.mark.asyncio
async def test_unknown_is_never_dead():
    rows = [_qr_row("cred-1", "c1")]
    # Provider unreachable → no verdicts at all, not "dead".
    with patch("utils.whatsapp_qr.get_connection_statuses", return_value=None):
        assert await get_credential_health(rows) == {}


@pytest.mark.asyncio
async def test_checker_exception_yields_no_verdicts():
    rows = [_qr_row("cred-1", "c1")]
    with patch("utils.whatsapp_qr.get_connection_statuses", side_effect=RuntimeError("boom")):
        assert await get_credential_health(rows) == {}


@pytest.mark.asyncio
async def test_rows_without_checker_or_binding_are_skipped():
    rows = [
        {"id": "cred-oauth", "credential_type": "google_oauth", "metadata": {}},
        _qr_row("cred-legacy", None),  # whatsapp_qr without connection_id
    ]
    with patch("utils.whatsapp_qr.get_connection_statuses", return_value={}):
        assert await get_credential_health(rows) == {}


@pytest.mark.asyncio
async def test_accepts_attribute_rows():
    row = SimpleNamespace(id="cred-1", credential_type="whatsapp_qr", metadata={"connection_id": "c1"})
    with patch("utils.whatsapp_qr.get_connection_statuses", return_value={"c1": "scan_qr"}):
        health = await get_credential_health([row])
    assert health["cred-1"].healthy is False
    assert health["cred-1"].status == "scan_qr"


# ---------------------------------------------------------------------------
# AI-surface consumption: the brain/agent-facing status line and the workflow
# snapshot must flag attached-but-dead credentials instead of rendering ✓.
# An attached-but-dead session must not render as healthy to either AI surface.
# ---------------------------------------------------------------------------

_WA_CONFIG = {"operation": "receive_message", "credentialIds": {"whatsapp_qr": "cred-1"}}


def test_status_line_unchanged_when_healthy_or_unknown():
    from coder.workflow.operation_catalog import credential_status_line

    assert credential_status_line(
        "automation-whatsapp", "receive_message", _WA_CONFIG, "n1"
    ) == "[credentials: whatsapp ✓]"
    assert credential_status_line(
        "automation-whatsapp", "receive_message", _WA_CONFIG, "n1",
        health={"cred-1": CredentialHealth("connected", True, None)},
    ) == "[credentials: whatsapp ✓]"
    # Verdict for a different credential id — still unknown for this one.
    assert credential_status_line(
        "automation-whatsapp", "receive_message", _WA_CONFIG, "n1",
        health={"other": CredentialHealth("failed", False, "x")},
    ) == "[credentials: whatsapp ✓]"


def test_status_line_flags_attached_but_dead():
    from coder.workflow.operation_catalog import credential_status_line

    line = credential_status_line(
        "automation-whatsapp", "receive_message", _WA_CONFIG, "n1",
        health={"cred-1": CredentialHealth("failed", False, "Re-scan THIS credential.")},
    )
    assert "✗ attached but DISCONNECTED" in line
    assert "session failed" in line
    assert "Re-scan THIS credential." in line
    assert "✓" not in line


def test_graph_snapshot_renders_dead_credential():
    from coder.workflow.graph_state import GraphState

    # A real UUID: the id extractor deliberately drops {{vars.X}} refs and
    # marker values so they never reach a uuid[] cast.
    cred_id = "0b129266-59d2-4ab8-9e19-6e6342d67270"
    workflow = {
        "nodes": [{
            "id": "wa1",
            "type": "automation-whatsapp",
            "config": {"operation": "receive_message", "credentialIds": {"whatsapp_qr": cred_id}},
        }],
        "edges": [],
    }
    gs = GraphState.from_dict(workflow)
    assert gs.attached_credential_ids() == [cred_id]

    assert "✓" in gs.to_xml()  # no health verdicts → today's rendering
    gs._credential_health = {cred_id: CredentialHealth("missing", False, "Re-scan.")}
    xml = gs.to_xml()
    assert "✗ attached but DISCONNECTED" in xml
    assert "session missing" in xml


def test_id_extractor_drops_refs_and_unchecked_types():
    from utils.credential_health import health_relevant_credential_ids

    config = {
        "credentialIds": {
            "whatsapp_qr": "0b129266-59d2-4ab8-9e19-6e6342d67270",
            "google_oauth": "1c23a377-59d2-4ab8-9e19-6e6342d67271",  # no health checker
            "slack": "{{vars.slack_cred}}",                          # template ref
            "credential_type": "whatsapp_qr",                        # marker, not an id
        }
    }
    assert health_relevant_credential_ids(config) == ["0b129266-59d2-4ab8-9e19-6e6342d67270"]
    assert health_relevant_credential_ids({}) == []
    assert health_relevant_credential_ids(None) == []


async def test_discord_install_health_marks_a_removed_bot_and_never_guesses(monkeypatch):
    """403/404 from Discord for the installed guild is definitive (the bot was
    removed); a probe that cannot be judged leaves the row unknown — and with
    no platform token nothing is asked at all."""
    from utils import credential_health as ch

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "platform-token")
    answers = {"g-ok": 200, "g-gone": 404, "g-forbidden": 403, "g-limited": 429, "g-down": None}

    async def probe(client, guild_id):
        return answers[guild_id]

    monkeypatch.setattr(ch, "_probe_discord_guild", probe)
    rows = [
        {"id": "c-ok", "credential_type": "discord_bot_install", "metadata": {"guild_id": "g-ok", "guild_name": "Acme"}},
        {"id": "c-gone", "credential_type": "discord_bot_install", "metadata": {"guild_id": "g-gone", "guild_name": "Old Server"}},
        {"id": "c-forbidden", "credential_type": "discord_bot_install", "metadata": {"guild_id": "g-forbidden"}},
        {"id": "c-limited", "credential_type": "discord_bot_install", "metadata": {"guild_id": "g-limited"}},
        {"id": "c-down", "credential_type": "discord_bot_install", "metadata": {"guild_id": "g-down"}},
        {"id": "c-legacy", "credential_type": "discord_bot_install", "metadata": {}},
    ]
    health = await ch.get_credential_health(rows)
    assert health["c-ok"].healthy is True and health["c-ok"].status == "installed"
    assert health["c-gone"].healthy is False and "Old Server" in health["c-gone"].hint
    assert health["c-forbidden"].healthy is False and "Install bot" in health["c-forbidden"].hint
    assert "c-limited" not in health and "c-down" not in health and "c-legacy" not in health

    monkeypatch.delenv("DISCORD_BOT_TOKEN")
    assert await ch.get_credential_health(rows) == {}

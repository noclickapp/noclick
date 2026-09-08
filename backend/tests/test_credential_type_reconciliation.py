"""A stamped credential row type that the node does not declare is reconciled.

Rows are typed by where they were minted, not by every node they serve, and
`get_credential` now stamps that row type onto the blob. Without this seam a
Gmail node on the shared Google row, a Slack node on a pre-2026 row or an
agent on a provider-typed row all die at parse (2026-09-07). All values are
synthetic.
"""
import pytest

from nodes.core.base import credential_type_literals, reconcile_credential_type
from nodes.core.registry import NODE_REGISTRY

GOOGLE_BLOB = {"access_token": "synthetic", "refresh_token": "synthetic", "expires_at": "2099-01-01T00:00:00+00:00", "email": "fixture@example.test"}


def _parse(node_type, config, credentials, credential_ids=None):
    payload = {"config": config, "credentials": credentials}
    if credential_ids:
        payload["credentialIds"] = credential_ids
        payload["credential_id"] = next(iter(credential_ids.values()))
    return NODE_REGISTRY[node_type].parse_config(payload)


def test_shared_google_row_parses_on_gmail_under_its_attachment_key():
    parsed = _parse(
        "automation-gmail",
        {"operation": "send_email_message", "to": "a@example.test", "subject": "s", "body": "b"},
        {**GOOGLE_BLOB, "credential_type": "google_sheets_oauth"},
        {"google_gmail_oauth": "row-fixture"},
    )
    assert parsed.credentials.credential_type == "google_gmail_oauth"
    assert parsed.credentials.access_token == "synthetic"


def test_legacy_row_type_with_no_usable_key_lets_the_union_choose_by_shape():
    parsed = _parse(
        "automation-slack",
        {"operation": "send_message_to_channel", "channel": "C1", "text": "hi"},
        {"credential_type": "bottokencredential", "bot_token": "xoxb-synthetic"},
        {"bottokencredential": "row-fixture"},
    )
    assert parsed.credentials.credential_type == "slack_bot_token"
    assert parsed.credentials.bot_token == "xoxb-synthetic"


def test_an_accepted_row_type_beats_the_attachment_key():
    # Instagram Login and Instagram OAuth share one node; the row decides the model.
    parsed = _parse(
        "automation-instagram",
        {"operation": "get_user_profile", "fields": "user_id,username"},
        {"access_token": "synthetic", "expires_at": "2099-01-01T00:00:00+00:00", "instagram_user_id": "1", "instagram_username": "f", "credential_type": "instagram_login"},
        {"instagram_oauth": "row-fixture"},
    )
    assert parsed.credentials.credential_type == "instagram_login"


def test_agent_rows_are_accepted_as_stamped():
    parsed = _parse("agent", {"model": "codex", "message": "hi"}, {"credential_type": "agent_codex_oauth", "access_token": "synthetic"})
    assert parsed.credentials.credential_type == "agent_codex_oauth"


def test_an_undeclared_row_type_never_selects_a_model_by_itself():
    # With the tag gone the union judges the shape alone: a blob that fits no
    # member still fails, exactly as an untagged blob always has.
    with pytest.raises(Exception, match="Invalid configuration"):
        _parse(
            "automation-slack",
            {"operation": "send_message_to_channel", "channel": "C1", "text": "hi"},
            {"credential_type": "github_oauth", "token": "synthetic"},
            {"github_oauth": "row-fixture"},
        )


def test_reconcile_is_pure_and_prefers_the_chosen_credential_key():
    model = NODE_REGISTRY["automation-gmail"].get_config_model()
    assert credential_type_literals(model) == frozenset({"google_gmail_oauth"})
    payload = {
        "config": {}, "credentials": {"credential_type": "google_sheets_oauth", "x": "y"},
        "credentialIds": {"unrelated": "other", "google_gmail_oauth": "chosen"}, "credential_id": "chosen",
    }
    out = reconcile_credential_type(payload, model)
    assert out["credentials"]["credential_type"] == "google_gmail_oauth"
    assert payload["credentials"]["credential_type"] == "google_sheets_oauth"  # input untouched

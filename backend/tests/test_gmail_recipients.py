"""Gmail recipient handling (2026-07-05 incident follow-up).

Two behaviors pinned here:
1. Recipients that template to empty/None are DROPPED before hitting the API —
   an untouched optional Cc must never produce "Invalid Cc header".
2. All malformed recipients across to/cc/bcc are reported in ONE error —
   Gmail's serial header rejection (To, then Cc, then Bcc) cost a user three
   test cycles.
"""

import pytest
from pydantic import ValidationError

from nodes.gmail_node import (
    GmailNode,
    GmailSendConfig,
    GmailCreateDraftConfig,
    _normalize_recipient_list,
)


class TestNormalizeRecipientList:
    def test_comma_string_split(self):
        assert _normalize_recipient_list("a@b.com, c@d.com") == ["a@b.com", "c@d.com"]

    def test_drops_none_and_empty_entries(self):
        assert _normalize_recipient_list(["a@b.com", "", None, "  "]) == ["a@b.com"]

    def test_trims_whitespace(self):
        assert _normalize_recipient_list([" a@b.com "]) == ["a@b.com"]

    def test_non_string_junk_kept_for_pydantic(self):
        # A dict entry must surface as a Pydantic type error, not be coerced.
        assert _normalize_recipient_list([{"x": 1}]) == [{"x": 1}]


class TestSendConfigRecipients:
    def _base(self, **overrides):
        cfg = {"to": ["a@b.com"], "subject": "s", "body": "b"}
        cfg.update(overrides)
        return cfg

    def test_empty_templated_cc_dropped(self):
        parsed = GmailSendConfig(**self._base(cc=["", None], bcc=[""]))
        assert parsed.cc == []
        assert parsed.bcc == []

    def test_empty_entries_in_to_dropped_but_valid_kept(self):
        parsed = GmailSendConfig(**self._base(to=["", "a@b.com", None]))
        assert parsed.to == ["a@b.com"]

    def test_all_empty_to_rejected(self):
        with pytest.raises(ValidationError):
            GmailSendConfig(**self._base(to=["", None]))

    def test_draft_config_same_behavior(self):
        parsed = GmailCreateDraftConfig(
            to=["a@b.com", ""], subject="s", body="b", cc=[None],
        )
        assert parsed.to == ["a@b.com"]
        assert parsed.cc == []


class TestValidateRecipients:
    def test_valid_addresses_pass(self):
        GmailNode._validate_recipients(
            to=["a@b.com", "Name Person <n@d.org>"], cc=[], bcc=None,
        )

    def test_all_bad_entries_reported_in_one_error(self):
        with pytest.raises(ValueError) as exc:
            GmailNode._validate_recipients(
                to=["not-an-email"], cc=["also bad"], bcc=["fine@ok.com", "@nolocal"],
            )
        msg = str(exc.value)
        assert "to: 'not-an-email'" in msg
        assert "cc: 'also bad'" in msg
        assert "bcc: '@nolocal'" in msg
        assert "fine@ok.com" not in msg

    def test_unresolved_template_rejected(self):
        with pytest.raises(ValueError) as exc:
            GmailNode._validate_recipients(to=["{{ $('webhook').lead_email }}"])
        assert "webhook" in str(exc.value)

    def test_display_name_format_accepted(self):
        GmailNode._validate_recipients(to=["Jane Doe <jane@example.com>"])

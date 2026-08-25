"""Build-time validation must judge the exact config the runtime parses.

The execution path cleans empty-string config values to None before Pydantic
parsing; validation layers used to judge the RAW config, so the two could
disagree — the Gmail validation regression: node drafter filled cc=""/bcc="" (valid
raw via the coercing validator), the runtime cleanup turned them into None,
and the run died with "Input should be a valid list". These tests pin the
shared cleanup (`clean_config_empty_strings`) into both validators plus the
gmail normalizer's whole-value-None handling.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from coder.workflow.operation_catalog import validate_node_config
from nodes.core.base import WorkflowNode, clean_config_empty_strings, runtime_config_view
from nodes.gmail_node import GmailSendConfig, _normalize_recipient_list


# ── the shared cleanup ───────────────────────────────────────────────────────


def test_clean_config_empty_strings():
    assert clean_config_empty_strings({"a": "", "b": "x", "c": 0, "d": []}) == {
        "a": None, "b": "x", "c": 0, "d": [],
    }
    assert clean_config_empty_strings({}) == {}


# ── gmail normalizer (fix for the incident's runtime failure) ────────────────


def test_normalize_recipient_list_whole_value_none_is_empty():
    assert _normalize_recipient_list(None) == []


def test_incident_config_now_parses_at_runtime():
    # The exact saved config from run example-run: cc/bcc filled as "", cleaned
    # to None by the execution path — must parse, not brick the send.
    raw = {
        "operation": "send_email_message",
        "to": "user@example.com",
        "subject": "Daily Competitor Analysis Report",
        "body": "Hello",
        "cc": "",
        "bcc": "",
    }
    parsed = GmailSendConfig.model_validate(clean_config_empty_strings(raw))
    assert parsed.cc == [] and parsed.bcc == []


# ── builder validation sees the runtime view ─────────────────────────────────


def test_incident_config_valid_at_build_time_too():
    # Both layers now agree the incident config is fine.
    assert validate_node_config(
        "automation-gmail",
        "send_email_message",
        {
            "operation": "send_email_message",
            "to": "user@example.com",
            "subject": "s",
            "body": "b",
            "cc": "",
            "bcc": "",
        },
    ) is None


def test_required_str_empty_matches_runtime_acceptance():
    # subject="" cleans to None, but the runtime str-coercion restores "" for
    # str-typed fields before parsing — the run proceeds, so validation must
    # accept too (the full pipeline is the alignment target, not just the
    # cleanup step).
    config = {
        "operation": "send_email_message",
        "to": "user@example.com",
        "subject": "",
        "body": "b",
    }
    assert validate_node_config("automation-gmail", "send_email_message", config) is None
    parsed = GmailSendConfig.model_validate(runtime_config_view(config, GmailSendConfig))
    assert parsed.subject == ""


def test_empty_optional_int_no_longer_false_alarms():
    # page_size="" cleans to None at runtime → valid; the old raw validation
    # nagged node drafter with an int-parse error the runtime never saw.
    assert validate_node_config(
        "automation-airtable",
        "list_table_records",
        {
            "operation": "list_table_records",
            "base_id": "app123",
            "table_id_or_name": "tbl123",
            "page_size": "",
        },
    ) is None


# ── WorkflowNode.validate_config (canvas/socket validation) ──────────────────


class _Cfg(BaseModel):
    items: List[str] = []
    req_items: List[str]
    limit: Optional[int] = None


class _FakeNode(WorkflowNode):
    __abstractmethods__ = frozenset()

    @classmethod
    def get_config_model(cls):
        return _Cfg


def test_validate_config_judges_runtime_view():
    # "" on an Optional[int] is what runtime sees as None → valid.
    assert _FakeNode.validate_config({"limit": "", "req_items": ["x"]})["valid"] is True
    # "" on a DEFAULTED naked list is a rejected unset marker → dropped to
    # its default at runtime, so it validates instead of run-crashing.
    assert _FakeNode.validate_config({"items": "", "req_items": ["x"]})["valid"] is True
    parsed = _FakeNode.parse_config({"items": "", "req_items": ["x"]})
    assert parsed.items == []
    # "" on a REQUIRED list has no default to fall back to — invalid at both
    # layers, surfaced up front instead of at the run.
    assert _FakeNode.validate_config({"req_items": ""})["valid"] is False


def test_runtime_view_drops_only_rejected_markers():
    # A value the field accepts survives byte-for-byte — the coercion can
    # only turn a guaranteed parse error into the default.
    viewed = runtime_config_view({"items": ["a"], "limit": None, "req_items": ""}, _Cfg)
    assert viewed["items"] == ["a"]
    assert viewed["limit"] is None       # Optional accepts None → kept
    assert viewed["req_items"] is None   # required: cleaned, NOT dropped


def test_zoom_defaulted_field_census_offender():
    # Top census offender (624 landmine fields): empty user_id on a Zoom op
    # must validate to its default instead of run-crashing.
    assert validate_node_config(
        "automation-zoom", "list_meetings", {"operation": "list_meetings", "user_id": ""}
    ) is None

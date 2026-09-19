"""The connect-time contract for manual credentials (nodes/core/credential_connect.py).

What it pins:
- shaping runs the credential CLASS: strip, secret fields refuse URLs and
  placeholders, missing/invalid fields come back per field, extras survive,
  and a class's own normalisers are written back (Tableau smart paste);
- the probe policy: a definitive provider refusal blocks the save with the
  provider's words + a hint, "cannot judge" saves as unverified, an answer
  saves with verification and stamps verified_at/verified_as;
- harness (agent*) credentials still route to key_validation;
- the hint classifier and the evidence seam's web-page summariser.
"""

from __future__ import annotations

import pytest

from nodes.core import connection_evidence as ce
from nodes.core import credential_connect as cc
from nodes.core.connection_evidence import ConnectionEvidence, EvidenceResult, EvidenceSample
from nodes.core.credential_fields import clean_secret, https_origin, segment_after


# ------------------------------------------------------------------ fields


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://us-east-1.online.tableau.com/#/site/acme/home", "https://us-east-1.online.tableau.com"),
        (" acme.example.com/ ", "https://acme.example.com"),
        ("http://tableau.internal:8443/api", "http://tableau.internal:8443"),
        ("", ""),
    ],
)
def test_https_origin_keeps_only_the_origin(raw, expected):
    assert https_origin(raw) == expected


@pytest.mark.parametrize("raw", ["ftp://x.com", "https://user:pw@x.com", "nohost"])
def test_https_origin_rejects_what_cannot_be_a_host(raw):
    with pytest.raises(ValueError):
        https_origin(raw, field_name="Server URL")


def test_segment_after_reads_fragment_and_path():
    assert segment_after("https://x.online.tableau.com/#/site/acme/home", "site") == "acme"
    assert segment_after("https://x.com/site/acme", "site") == "acme"
    assert segment_after("https://x.com/site/", "site") is None
    assert segment_after("acme", "site") is None


@pytest.mark.parametrize(
    "raw", ["https://x.com/#/site/a", "www.x.com", "<your key>", "your_api_key", "xxxxxxxx", "{PLACEHOLDER}"]
)
def test_clean_secret_refuses_addresses_and_placeholders(raw):
    with pytest.raises(ValueError):
        clean_secret(raw, field_name="Token")


def test_clean_secret_keeps_real_values_including_json_key_files():
    assert clean_secret(" sk-live-abc\n") == "sk-live-abc"
    blob = '{"type": "service_account", "private_key": "-----BEGIN"}'
    assert clean_secret(blob) == blob


# ----------------------------------------------------------------- shaping


def test_credential_types_are_unique_per_node():
    """The lookup is a bijection, which is what lets a type name its class."""
    index = cc._class_index()
    assert index["tableau_pat"][0] == "automation-tableau"
    assert len(index) > 150


def test_shape_strips_and_writes_back_the_class_normalisation():
    data, errors, resolved = cc.shape_credential(
        "tableau_pat",
        {
            "server_url": " https://us-east-1.online.tableau.com/#/site/acme/home ",
            "site_content_url": "",
            "pat_name": " noclick ",
            "pat_secret": "s3cret\n",
            "surface_extra": "kept",
        },
    )
    assert errors == {}
    assert resolved[0] == "automation-tableau"
    assert data["server_url"] == "https://us-east-1.online.tableau.com"
    assert data["site_content_url"] == "acme"  # smart paste filled the site
    assert data["pat_secret"] == "s3cret"
    assert data["surface_extra"] == "kept"


def test_shape_reports_url_shaped_secrets_per_field():
    site = "https://us-east-1.online.tableau.com/#/site/acme"
    _, errors, _ = cc.shape_credential(
        "tableau_pat",
        {"server_url": site, "pat_name": site + "/home", "pat_secret": site},
    )
    assert set(errors) == {"pat_name", "pat_secret"}
    assert "web address" in errors["pat_secret"]


def test_shape_refuses_the_cloud_manager_console_host():
    _, errors, _ = cc.shape_credential(
        "tableau_pat",
        {"server_url": "https://acme.cloudmanager.tableau.com", "pat_name": "n", "pat_secret": "s"},
    )
    assert list(errors) == ["server_url"]
    assert "Cloud Manager" in errors["server_url"]
    assert "online.tableau.com" in errors["server_url"]


def test_shape_reports_missing_required_fields_by_title():
    _, errors, _ = cc.shape_credential("firecrawl_api_key", {})
    assert errors == {"api_key": "API Key is required."}


def test_shape_refuses_placeholder_secrets():
    _, errors, _ = cc.shape_credential("firecrawl_api_key", {"api_key": "<your key>"})
    assert "placeholder" in errors["api_key"]


def test_unknown_types_pass_through_stripped():
    data, errors, resolved = cc.shape_credential("not_a_node_type", {"k": " v "})
    assert (data, errors, resolved) == ({"k": "v"}, {}, None)


@pytest.mark.parametrize("credential_type", sorted(cc._class_index()))
def test_every_credential_class_refuses_an_address_in_its_secret_fields(credential_type):
    """The generic layer, not per-node code, covers every manual credential:
    a URL pasted into any password/key/token/secret field is refused."""
    _, cls = cc._class_index()[credential_type]
    secrets = cc._secret_fields(cls)
    if not secrets:
        pytest.skip("no secret-shaped field")
    blob = {name: "https://example.com/settings/tokens" for name in secrets}
    _, errors, _ = cc.shape_credential(credential_type, blob)
    for name in secrets:
        assert "web address" in errors.get(name, ""), (credential_type, name, errors)


# ------------------------------------------------------------------- probe


class _Node:
    connection_evidence = ConnectionEvidence(operation="list_things", noun="things")

    @classmethod
    def get_config_model(cls):
        return None


@pytest.fixture
def probe_registry(monkeypatch):
    """A resolvable type on a node that declares evidence, with the probe faked."""
    from nodes.core import registry as reg

    monkeypatch.setitem(reg.NODE_REGISTRY, "automation-probe", _Node)
    monkeypatch.setattr(
        cc, "resolve_credential_class", lambda t: ("automation-probe", _Cred) if t == "probe_key" else None
    )
    calls = {}

    def fake(result):
        async def _collect(**kwargs):
            calls.update(kwargs)
            return result

        monkeypatch.setattr(cc, "_collect_evidence", _collect)
        return calls

    return fake


from pydantic import BaseModel, Field  # noqa: E402
from typing import Literal  # noqa: E402


class _Cred(BaseModel):
    credential_type: Literal["probe_key"] = Field("probe_key")
    api_key: str


async def test_rejection_blocks_with_provider_words_and_hint(probe_registry):
    calls = probe_registry(
        EvidenceResult(reachable=False, noun="things", error="invalid_auth (HTTP 401)", hint="The key or token was rejected.")
    )
    verdict = await cc.validate_for_connect(
        credential_type="probe_key", credential_data={"api_key": "k"}, user_id="u"
    )
    assert not verdict.ok
    assert verdict.rejection == "invalid_auth (HTTP 401)"
    assert verdict.hint.startswith("The key")
    # Shaped blob, not the raw one; unset defaults are not invented into it.
    assert calls["credential_data"] == {"api_key": "k"}
    assert verdict.verified_metadata() == {}


async def test_cannot_judge_saves_as_unverified(probe_registry):
    probe_registry(EvidenceResult(reachable=None, noun="things"))
    verdict = await cc.validate_for_connect(
        credential_type="probe_key", credential_data={"api_key": "k"}, user_id="u"
    )
    assert verdict.ok and verdict.rejection is None
    assert verdict.evidence.reachable is None
    assert verdict.verified_metadata() == {}


async def test_answer_saves_with_verification_and_stamps_the_row(probe_registry):
    probe_registry(
        EvidenceResult(reachable=True, noun="things", samples=[EvidenceSample(label="Sales"), EvidenceSample(label="Ops")])
    )
    verdict = await cc.validate_for_connect(
        credential_type="probe_key", credential_data={"api_key": " k "}, user_id="u"
    )
    assert verdict.ok
    assert verdict.credential_data["api_key"] == "k"
    meta = verdict.verified_metadata()
    assert meta["verified_as"] == "Sales" and meta["verified_at"]


async def test_shape_errors_short_circuit_the_probe(probe_registry):
    calls = probe_registry(EvidenceResult(reachable=True, noun="things"))
    verdict = await cc.validate_for_connect(
        credential_type="probe_key", credential_data={"api_key": "https://x.com"}, user_id="u"
    )
    assert "api_key" in verdict.field_errors and calls == {}


async def test_probe_false_only_shapes(probe_registry):
    calls = probe_registry(EvidenceResult(reachable=True, noun="things"))
    verdict = await cc.validate_for_connect(
        credential_type="probe_key", credential_data={"api_key": "k"}, user_id="u", probe=False
    )
    assert verdict.ok and verdict.evidence is None and calls == {}


async def test_node_without_evidence_saves_unverified(monkeypatch):
    class _Bare(_Node):
        connection_evidence = None

    from nodes.core import registry as reg

    monkeypatch.setitem(reg.NODE_REGISTRY, "automation-bare", _Bare)
    monkeypatch.setattr(cc, "resolve_credential_class", lambda t: ("automation-bare", _Cred))
    verdict = await cc.validate_for_connect(
        credential_type="probe_key", credential_data={"api_key": "k"}, user_id="u"
    )
    assert verdict.ok and verdict.evidence is None


async def test_agent_types_route_to_key_validation(monkeypatch):
    seen = {}

    async def fake(credential_type, credential_data):
        seen["type"] = credential_type
        return "Anthropic rejected this key"

    monkeypatch.setattr(cc, "_validate_agent_api_key", fake)
    verdict = await cc.validate_for_connect(
        credential_type="agent_api_key",
        credential_data={"credentials": {"ANTHROPIC_API_KEY": "bad"}},
        user_id="u",
    )
    assert seen["type"] == "agent_api_key"
    assert verdict.rejection == "Anthropic rejected this key"
    # The bundle is stored as-is: key_validation owns its shape.
    assert verdict.credential_data == {"credentials": {"ANTHROPIC_API_KEY": "bad"}}


# ------------------------------------------------------ evidence additions


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("<html><body>HTTP Status 403 – Forbidden</body></html>", "web page"),
        ("The server answered HTTP 403 with a web page instead of an API response", "web page"),
        ("Not Found (HTTP 404)", "Nothing answered"),
        ("invalid_auth (HTTP 401)", "rejected"),
        ("missing_scope (HTTP 403)", "permissions"),
    ],
)
def test_hint_for_rejection_reads_the_shape(text, fragment):
    assert fragment in ce.hint_for_rejection(text)


def test_hint_for_rejection_stays_quiet_on_unknown_shapes():
    assert ce.hint_for_rejection("something odd happened") is None
    assert ce.hint_for_rejection("") is None


def test_redact_secrets_strips_keys_quoted_in_urls():
    text = "Client error '403 Forbidden' for url 'https://api.semrush.com/?type=rank&key=abc123&display_limit=1'"
    assert "abc123" not in ce.redact_secrets(text)
    assert "key=***" in ce.redact_secrets(text)
    assert ce.redact_secrets("invalid_auth") == "invalid_auth"


def test_error_envelope_summarises_web_pages():
    with pytest.raises(ce._ProviderRefused) as exc:
        ce._raise_if_error_envelope(
            {"status": "error", "error": "<!doctype html><html><body>HTTP Status 403</body></html>", "status_code": 403}
        )
    assert "web page instead of an API response" in str(exc.value)
    assert "<html" not in str(exc.value)


def test_identity_label_finds_nested_names():
    keys = ConnectionEvidence(noun="x", identity_operation="get").identity_keys
    assert ce._identity_label({"session": {"site": {"id": "1", "name": "Acme"}, "user": {"name": "P"}}}, keys) == "Acme"
    assert ce._identity_label({"team": "Acme"}, keys) == "Acme"
    assert ce._identity_label({"nothing": {"here": {"deep": {"name": "x"}}}}, keys, depth=2) is None


def test_rows_from_options_accepts_both_loader_shapes():
    assert ce._rows_from_options({"options": [{"label": "a"}]}) == [{"label": "a"}]
    assert ce._rows_from_options([{"label": "a"}]) == [{"label": "a"}]
    assert ce._rows_from_options({"nope": 1}) == [] and ce._rows_from_options(None) == []


def test_rows_from_operation_finds_nested_collections():
    rows = ce._rows_from_operation(
        {"status": "success", "data": {"pagination": {"n": 2}, "workbooks": {"workbook": [{"name": "A"}, {"name": "B"}]}}}
    )
    assert [r["name"] for r in rows] == ["A", "B"]


async def test_collect_evidence_probes_raw_credential_data(monkeypatch):
    """The connect flow proves an UNSAVED blob: no resolver, the blob goes to the op."""
    from nodes.core import registry as reg, run_op

    monkeypatch.setitem(reg.NODE_REGISTRY, "automation-probe", _Node)
    seen = {}

    async def fake_run(**kwargs):
        seen.update(kwargs)
        return {"status": "success", "data": {"things": [{"name": "One"}]}}

    monkeypatch.setattr(run_op, "run_node_operation", fake_run)
    result = await ce.collect_evidence(
        node_type="automation-probe", credential_data={"api_key": "k"}, user_id="u"
    )
    assert result.reachable is True and result.samples[0].label == "One"
    assert seen["credential_data"] == {"api_key": "k"} and seen["credential_id"] is None


async def test_collect_evidence_requires_an_id_or_data():
    with pytest.raises(ValueError):
        await ce.collect_evidence(node_type="automation-tableau", user_id="u")

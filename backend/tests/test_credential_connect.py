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
        EvidenceResult(reachable=False, noun="things", error="invalid_auth (HTTP 401)", hint="The API key was rejected.")
    )
    verdict = await cc.validate_for_connect(
        credential_type="probe_key", credential_data={"api_key": "k"}, user_id="u"
    )
    assert not verdict.ok
    assert verdict.rejection == "invalid_auth (HTTP 401)"
    # The probe is told the form's labels, so its hint (read once, from the raw words) names the field to fix.
    assert calls["labels"] == ce.FieldLabels(secret="API key", address=None)
    assert verdict.hint == "The API key was rejected."
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
    # A board it can read is what it reached, not who it is.
    assert meta["verified_with"] == "Sales" and meta["verified_at"]
    assert "verified_as" not in meta


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


@pytest.mark.parametrize("credential_type,env_var", [
    ("agent_claude_code", "ANTHROPIC_API_KEY"), ("agent_anthropic", "ANTHROPIC_API_KEY"),
    ("agent_codex", "OPENAI_API_KEY"), ("agent_openai", "OPENAI_API_KEY"),
])
async def test_a_vendor_key_is_probed_alike_under_its_harness_or_model_type(monkeypatch, credential_type, env_var):
    """A vendor key serves its CLI harness and its models under either type
    (providers.AGENT_VENDOR_KEY_ALIASES), so connecting it under either runs the
    same provider probe on the same variable and refuses it the same way."""
    from nodes.agent import key_validation

    probed = []

    async def probe(var, key):
        if key:
            probed.append((var, key))
        return key_validation.Rejection("anthropic" if "ANTHROPIC" in var else "openai", "invalid_key",
                                        "invalid x-api-key") if key else None

    monkeypatch.setattr(key_validation, "validate_provider_key", probe)
    monkeypatch.setattr(cc, "_validate_agent_api_key", key_validation.validate_agent_api_key)
    verdict = await cc.validate_for_connect(
        credential_type=credential_type, credential_data={"credentials": {env_var: "sk-dead"}}, user_id="u")
    assert probed == [(env_var, "sk-dead")]
    assert verdict.rejection and "invalid x-api-key" in verdict.rejection


# ----------------------------------------------------------- linked fields
#
# Some fields name a resource NoClick's own provider account acts on: a WhatsApp session on its WAHooks account, a
# number it bought, the server its bot was installed into, a workspace's Slack installation, a HubSpot portal's app
# events. Only NoClick's linking flow writes them, so nothing typed in may name one, under any credential type.


def test_the_linked_fields_are_declared_by_their_credential_classes():
    assert cc.linked_field_names() == {"connection_id", "number_sid", "guild_id", "team_id", "hub_id"}
    assert {t for t in cc._class_index() if cc.linked_only(t)} == {"whatsapp_qr", "phone_number", "discord_bot_install"}


@pytest.mark.parametrize("credential_type,blob,field", [
    ("whatsapp_qr", {"connection_id": "another-users-session"}, "connection_id"),
    ("whatsapp_qr", {}, "connection_id"),
    ("phone_number", {"phone_number": "+15550001111", "number_sid": "PN0123"}, "number_sid"),
    ("discord_bot_install", {"guild_id": "1", "access_token": "a", "refresh_token": "r",
                             "expires_at": "2099-01-01T00:00:00Z"}, "guild_id"),
    ("slack_oauth", {"access_token": "xoxb-own", "team_id": "T0OTHER"}, "team_id"),
    ("hubspot_oauth", {"access_token": "own", "hub_id": "12345"}, "hub_id"),
    # Keys a class doesn't declare survive shaping, so a sibling or unknown type could carry one into a dict read.
    ("whatsapp_access_token", {"access_token": "t", "phone_number_id": "1", "connection_id": "x"}, "connection_id"),
    ("slack_bot_token", {"bot_token": "xoxb-own", "team_id": "T0OTHER"}, "team_id"),
    ("hubspot_pat", {"access_token": "pat-own", "hub_id": "12345"}, "hub_id"),
    ("mcp_api_key", {"api_key": "k", "connection_id": "x"}, "connection_id"),
    ("agent_api_key", {"credentials": {"ANTHROPIC_API_KEY": "k"}, "connection_id": "x"}, "connection_id"),
])
async def test_a_typed_blob_never_names_what_only_noclick_links(credential_type, blob, field):
    verdict = await cc.validate_for_connect(credential_type=credential_type, credential_data=blob, user_id="u")
    assert not verdict.ok and verdict.evidence is None
    assert list(verdict.field_errors) == [field]
    assert "can't be entered" in verdict.message


async def test_client_metadata_never_names_one_either():
    verdict = await cc.validate_for_connect(
        credential_type="discord_bot_token", credential_data={"bot_token": "own"}, user_id="u",
        metadata={"guild_id": "someone-elses-server"})
    assert list(verdict.field_errors) == ["guild_id"]


async def test_the_refusal_says_how_noclick_links_it():
    verdict = await cc.validate_for_connect(
        credential_type="whatsapp_qr", credential_data={"connection_id": "x"}, user_id="u")
    assert verdict.message == "Connection ID is set by NoClick when you scan the QR code; it can't be entered."
    verdict = await cc.validate_for_connect(
        credential_type="slack_oauth", credential_data={"access_token": "xoxb-own", "team_id": "T0"}, user_id="u")
    assert verdict.message == "Team ID is set by NoClick when you sign in; it can't be entered."


async def test_a_key_of_ones_own_is_still_judged_as_before():
    verdict = await cc.validate_for_connect(
        credential_type="slack_oauth", credential_data={"access_token": "xoxb-own"}, user_id="u")
    assert verdict.ok
    verdict = await cc.validate_for_connect(
        credential_type="whatsapp_access_token", credential_data={"access_token": "t", "phone_number_id": "1"},
        user_id="u", metadata={"provider": "meta"})
    assert verdict.ok


async def test_a_deployments_test_account_may_hold_a_made_up_link(monkeypatch):
    """The one way past it: a value the deployment says its own test account may hold (hosted: a QA account and a
    prefix no provider mints), asked with the account and the value."""
    from utils import capabilities

    asked = []

    async def test_link(pool, *, user_id, value):
        asked.append((user_id, value))
        return user_id == "qa" and value.startswith("test-")

    monkeypatch.setitem(capabilities._providers, capabilities.LINKED_TEST_VALUE, test_link)
    ok = await cc.validate_for_connect(
        credential_type="whatsapp_qr", credential_data={"connection_id": "test-1"}, user_id="qa")
    assert ok.ok and ok.credential_data["connection_id"] == "test-1"
    assert asked == [("qa", "test-1")]
    for user_id, value in (("someone", "test-1"), ("qa", "real-session")):
        refused = await cc.validate_for_connect(
            credential_type="whatsapp_qr", credential_data={"connection_id": value}, user_id=user_id)
        assert list(refused.field_errors) == ["connection_id"]


async def test_metadata_carried_over_a_replace_is_only_the_linked_part():
    assert cc.linked_metadata({"connection_id": "c", "phone_number": "+1", "provider": "wahooks"}) == {
        "connection_id": "c"}
    assert cc.linked_metadata(None) == {}


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


def test_hint_for_rejection_names_the_field_by_its_label():
    labels = ce.FieldLabels(secret="token secret", address="server URL")
    assert ce.hint_for_rejection("invalid_auth (HTTP 401)", labels).startswith("The token secret was rejected.")
    assert "check the server URL" in ce.hint_for_rejection("<html><body>Sign in</body></html>", labels)
    assert ce.hint_for_rejection("Not Found (HTTP 404)", labels) == "Nothing answered at that address. Check the server URL for typos."
    # A form with no address field never sends the person looking for one.
    keyonly = ce.FieldLabels(secret="secret key", address=None)
    assert ce.hint_for_rejection("Not Found (HTTP 404)", keyonly) is None
    assert ce.hint_for_rejection("missing_scope (HTTP 403)", keyonly).startswith("The secret key was recognised")


def test_field_labels_read_the_credential_class():
    class Site(BaseModel):
        server_url: str = Field(..., title="Server URL")
        pat_secret: str = Field(..., title="Token Secret", json_schema_extra={"ui:widget": "password"})

    class Keys(BaseModel):
        api_key: str
        app_secret: str = Field(..., title="App Secret")

    class Tableau(Site):
        pat_name: str = Field(..., title="Token Name")

    assert cc._field_labels(Site) == ce.FieldLabels(secret="token secret", address="server URL")
    # Two secrets: the hint says "credential" rather than pick one; no address field: none is named.
    assert cc._field_labels(Keys) == ce.FieldLabels(secret="credential", address=None)
    # A masked field outranks a name that only looks secret.
    assert cc._field_labels(Tableau).secret == "token secret"
    assert cc._as_phrase("Api key") == "API key"

    class Keyfile(BaseModel):
        private_key: str = Field(..., title="Private Key", json_schema_extra={"ui:widget": "password"})
        token_uri: str = Field("https://oauth2.googleapis.com/token", title="Token URI")

    # An optional override (a token URI, a self-hosted base URL) is never the address a hint points at.
    assert cc._field_labels(Keyfile).address is None
    assert cc._as_phrase("Jira Domain", frozenset({"jira"})) == "Jira domain"


def test_redact_secrets_strips_keys_quoted_in_urls():
    text = "Client error '403 Forbidden' for url 'https://api.semrush.com/?type=rank&key=abc123&display_limit=1'"
    assert "abc123" not in ce.redact_secrets(text)
    assert "key=***" in ce.redact_secrets(text)
    assert ce.redact_secrets("invalid_auth") == "invalid_auth"


NOTION_401 = (
    'Notion API error: {"object":"error","status":401,"code":"unauthorized","message":"API token is invalid.",'
    '"additional_data":{"reason":"token_invalid"},"request_id":"0c6b7c0e-d4ac-4144-a008-dc0deb1fcddc"}'
)


def test_provider_message_reads_a_json_error_body():
    # Notion's real 401: the provider's own sentence and its status, not the envelope.
    assert ce.provider_message(NOTION_401) == "API token is invalid. (HTTP 401)"
    # Each shape a provider answers in; a status already written beside the body is kept.
    assert ce.provider_message('{"error":{"code":401,"message":"Request had invalid authentication credentials."}}') == (
        "Request had invalid authentication credentials. (HTTP 401)"
    )
    assert ce.provider_message('{"error":"invalid_grant","error_description":"Token has been expired or revoked.","status":400}') == (
        "Token has been expired or revoked. (invalid_grant, HTTP 400)"
    )
    assert ce.provider_message('{"ok":false,"error":"invalid_auth"} (HTTP 401)') == "invalid_auth (HTTP 401)"
    assert ce.provider_message('GitHub API error 401: {"message":"Bad credentials"}') == "Bad credentials (HTTP 401)"


def test_provider_message_keeps_the_code_and_reads_the_last_body():
    # An error code beside a different sentence is kept: it is the provider's word too.
    assert ce.provider_message('{"error":"invalid_grant","error_description":"Token has been expired or revoked."}') == (
        "Token has been expired or revoked. (invalid_grant)"
    )
    assert ce.provider_message('HTTP error: {"error":"Forbidden","message":"Your plan does not include API access"}') == (
        "Your plan does not include API access (Forbidden)"
    )
    # A node can quote the request it sent; the provider's answer is the last body.
    assert ce.provider_message('… payload {"message":"hello world"} -> {"message":"Unauthorized"}') == "Unauthorized"
    # The status is the one written just before that body, not before the first one.
    assert ce.provider_message('{"ok":true,"message":"queued"} then 401 {"error":"invalid_auth"}') == "invalid_auth (HTTP 401)"
    # ...and never a number inside a quoted body.
    assert ce.provider_message('sent {"amount":404} got {"message":"Unauthorized"}') == "Unauthorized"


def test_the_hint_comes_from_the_providers_raw_words():
    raw = 'HTTP error: {"error":"Forbidden","message":"Your plan does not include API access"}'
    assert "permissions" in ce.hint_for_rejection(raw)


async def test_a_refused_key_keeps_the_hint_its_raw_words_gave(monkeypatch):
    """The connect seam takes the evidence's hint as it is: read once, from the raw text, with the form's labels."""
    from nodes.core import registry as reg, run_op

    monkeypatch.setitem(reg.NODE_REGISTRY, "automation-probe", _Node)

    async def refused(**kwargs):
        raise ValueError('HTTP error: {"error":"Forbidden","message":"Your plan does not include API access"}')

    monkeypatch.setattr(run_op, "run_node_operation", refused)
    result = await ce.collect_evidence(
        node_type="automation-probe", credential_data={"api_key": "k"}, user_id="u", labels=ce.FieldLabels(secret="API key", address=None)
    )
    assert result.error == "Your plan does not include API access (Forbidden)"
    assert result.hint == "The API key was recognised but refused. Check its permissions or scopes."


def test_provider_message_leaves_other_text_as_it_is():
    assert ce.provider_message("Slack API error: account_inactive") == "Slack API error: account_inactive"
    assert ce.provider_message("Invalid API Key provided: sk_test_****0000 (HTTP 401)") == (
        "Invalid API Key provided: sk_test_****0000 (HTTP 401)"
    )
    # JSON with no message to read keeps the whole body.
    assert ce.provider_message('{"ok":false,"code":42}') == '{"ok":false,"code":42}'


async def test_a_rejection_reads_the_providers_own_message(monkeypatch):
    from nodes.core import registry as reg, run_op

    monkeypatch.setitem(reg.NODE_REGISTRY, "automation-probe", _Node)

    async def refused(**kwargs):
        raise ValueError(NOTION_401)

    monkeypatch.setattr(run_op, "run_node_operation", refused)
    result = await ce.collect_evidence(node_type="automation-probe", credential_data={"api_key": "k"}, user_id="u")
    assert result.reachable is False
    assert result.error == "API token is invalid. (HTTP 401)"
    assert result.hint and "rejected" in result.hint


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

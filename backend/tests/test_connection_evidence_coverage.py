"""Connection evidence coverage: every credentialed node must be able to prove itself.

The bug this pins: a credential could be attached, pass ``validate_workflow``
with ``config_valid: true``, and be completely dead — a Slack bot token returned
``invalid_auth`` on every call while every surface showed green, and nobody found
out until runs silently delivered nothing. The fix is that connecting an account
shows the user something only a working credential could produce (their own
channel names, their own bases), and that is only reliable if EVERY credentialed
node can do it.

Three layers, weakest to strongest — the same shape as
``test_oauth_scope_coverage.py``, which took its own gap from 131 broken
operations to ``_UNVERIFIED = frozenset()``:

1. **Ratchet** — every credentialed node declares ``connection_evidence`` or
   sits on ``_NO_EVIDENCE_YET``. That list may only shrink; a NEW credentialed
   node without evidence fails here. This is the layer that makes future nodes
   get an evidence layer by default rather than by remembering.
2. **Resolvable** — what a declaration points at must actually exist: the
   operation must be a real operation on that node, and the field must be one
   the node's own ``load_field_options`` handles.
3. **Read-only** — the declared operation must be non-mutating. Evidence runs
   the moment someone connects an account, so a declaration naming a write is a
   loaded gun pointed at the user's workspace.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nodes.core.connection_evidence import ConnectionEvidence, EvidenceSample
from nodes.core.registry import NODE_REGISTRY

BACKEND = Path(__file__).resolve().parents[1]


# Credentialed nodes that cannot yet prove themselves to a user. Each one is a
# provider where connecting gives no visible confirmation, so the user is asked
# to trust a green tick.
#
# This list may ONLY shrink. Adding an entry means shipping a node whose
# credential can be dead without anyone noticing; declare evidence instead —
# see nodes/core/connection_evidence.py for the three shapes available, one of
# which (identity-only) works even for stateless API keys.
_NO_EVIDENCE_YET: frozenset[str] = frozenset(
    {
        # --- has a listing operation; needs a zero-argument one picked ---
        "automation-affinity",
        "automation-apify",
        "automation-instantly",
        "automation-postgres",
        "automation-reducto",
        "automation-rss",
        "automation-voyage",
        # --- no listing at all; needs an identity/verification probe ---
        "automation-appsheet",
        "automation-bluesky",
        "automation-brandfetch",
        "automation-fellow",
        "automation-gohighlevel",
        "automation-google-maps",
        "automation-pagespeed",
        "automation-resend",
        "automation-semrush",
        "automation-telegram",
        # --- unbounded keyspace: wants a summary, not a listing ---
        "automation-redis",
        "automation-upstash-vector",
        # --- every listing is scoped to a project picked after connect, and
        #     there is no zero-argument read. Unblocked by teaching evidence to
        #     read project_id off the service-account credential itself. ---
        "automation-firestore",
    }
)

# Nodes with a credential field that is not a provider account: no external
# service exists to prove anything against.
_NO_PROVIDER: frozenset[str] = frozenset({"automation-http-request"})

# An operation is treated as mutating unless it is provably a read. Fail closed:
# wrongly skipping a read costs a thinner evidence panel, wrongly running a write
# costs a message in someone's workspace.
_READ_ONLY_PREFIXES = (
    "list_",
    "get_",
    "fetch_",
    "search_",
    "describe_",
    "test_",
    "check_",
    "read_",
    "query_",
    "count_",
    "validate_",
    "verify_",
    "resolve_",
    "lookup_",
    "download_",
    "export_",
    "poll_",
)


def _credentialed_nodes() -> dict[str, type]:
    """Registered nodes whose config model carries a credential.

    Detected from the generated schema rather than a hand-list so a new node is
    picked up the moment it is registered.
    """
    found: dict[str, type] = {}
    for node_type, node_cls in NODE_REGISTRY.items():
        if node_type in _NO_PROVIDER:
            continue
        try:
            schema = node_cls.get_config_schema()
        except Exception:  # a broken schema fails its own test, not this one
            continue
        defs = schema.get("$defs", {}) or {}
        has_cred = any(
            isinstance(v, dict) and v.get("x-credential-type") for v in defs.values()
        )
        if has_cred:
            found[node_type] = node_cls
    return found


def _operations(node_cls: type) -> dict[str, list[str]]:
    """Operation const -> the config fields it requires (excluding `operation`)."""
    ops: dict[str, list[str]] = {}
    try:
        schema = node_cls.get_config_schema()
    except Exception:
        return ops
    for defn in (schema.get("$defs", {}) or {}).values():
        if not isinstance(defn, dict):
            continue
        op = (defn.get("properties", {}) or {}).get("operation", {}) or {}
        const = op.get("const") or (op.get("enum") or [None])[0]
        if isinstance(const, str):
            ops[const] = [
                r for r in (defn.get("required") or []) if r != "operation"
            ]
    return ops


def _loader_fields(node_cls: type) -> dict[str, bool]:
    """Dynamic-option loader key -> whether it depends on another field.

    The key is ``x-dynamic-options.field_name``, which is what the loader is
    actually called with — it differs from the property name wherever one loader
    backs several fields (``destination_spreadsheet_id`` -> ``spreadsheet_id``).
    """
    fields: dict[str, bool] = {}
    try:
        schema = node_cls.get_config_schema()
    except Exception:
        return fields
    for defn in (schema.get("$defs", {}) or {}).values():
        if not isinstance(defn, dict):
            continue
        for prop, spec in (defn.get("properties", {}) or {}).items():
            dyn = spec.get("x-dynamic-options") if isinstance(spec, dict) else None
            if not isinstance(dyn, dict):
                continue
            key = dyn.get("field_name", prop)
            fields[key] = fields.get(key, False) or bool(dyn.get("depends_on"))
    return fields


# ---------------------------------------------------------------- 1. ratchet


def test_every_credentialed_node_can_prove_itself():
    """A new credentialed node must declare evidence, or the build fails."""
    missing = sorted(
        node_type
        for node_type, node_cls in _credentialed_nodes().items()
        if getattr(node_cls, "connection_evidence", None) is None
        and node_type not in _NO_EVIDENCE_YET
    )
    assert not missing, (
        "These credentialed nodes cannot show a user that their connection works:\n  "
        + "\n  ".join(missing)
        + "\n\nDeclare `connection_evidence` on the node class — see "
        "nodes/core/connection_evidence.py. If the provider genuinely has "
        "nothing a user would recognise, an identity-only declaration "
        "(identity_operation=...) is still far better than a green tick."
    )


def test_no_evidence_allowlist_only_shrinks():
    """Entries must name real nodes, so the list cannot rot into permanence."""
    stale = sorted(_NO_EVIDENCE_YET - set(NODE_REGISTRY))
    assert not stale, (
        f"_NO_EVIDENCE_YET names nodes that no longer exist: {stale}. "
        "Remove them — a stale allowlist hides how much is left to do."
    )

    covered = sorted(
        n
        for n in _NO_EVIDENCE_YET
        if getattr(NODE_REGISTRY.get(n), "connection_evidence", None) is not None
    )
    assert not covered, (
        f"These now declare evidence and must come OFF _NO_EVIDENCE_YET: {covered}. "
        "The list may only shrink, and it only shrinks if we take entries out."
    )


# ------------------------------------------------------------ 2. resolvable


@pytest.mark.parametrize(
    "node_type,node_cls",
    sorted(
        (t, c)
        for t, c in NODE_REGISTRY.items()
        if getattr(c, "connection_evidence", None) is not None
    ),
)
def test_declared_evidence_points_at_something_real(node_type, node_cls):
    """A declaration that names a nonexistent operation proves nothing at runtime."""
    spec: ConnectionEvidence = node_cls.connection_evidence
    ops = _operations(node_cls)

    for attr in ("operation", "identity_operation"):
        name = getattr(spec, attr)
        if name and ops:
            assert name in ops, (
                f"{node_type}.connection_evidence.{attr}={name!r} is not an "
                f"operation this node declares. Evidence would fail at runtime "
                f"and the user would be told their credential is broken."
            )

    if spec.field:
        assert hasattr(node_cls, "load_field_options"), (
            f"{node_type} declares evidence field={spec.field!r} but implements no "
            f"load_field_options, so nothing would be fetched. Either implement "
            f"the loader (preferred — it makes the field a picker too) or declare "
            f"an `operation` instead."
        )
        loaders = _loader_fields(node_cls)
        if loaders:
            assert spec.field in loaders, (
                f"{node_type}.connection_evidence.field={spec.field!r} is not a "
                f"dynamic-options field on this node. Use the loader key "
                f"(x-dynamic-options.field_name), which is not always the property "
                f"name. Available: {sorted(loaders)}"
            )

    assert spec.noun and spec.noun.strip(), (
        f"{node_type} must name what it lists ('channels', 'bases') — the noun is "
        f"shown to the user, so it has to read the way they would say it."
    )


@pytest.mark.parametrize(
    "node_type,node_cls",
    sorted(
        (t, c)
        for t, c in NODE_REGISTRY.items()
        if getattr(c, "connection_evidence", None) is not None
    ),
)
def test_evidence_needs_nothing_but_the_credential(node_type, node_cls):
    """Evidence runs with a credential and nothing else — no config exists yet.

    Two ways to get this wrong, both of which look fine until someone connects an
    account and is told their working credential is broken: naming a loader field
    that only resolves once ANOTHER field is filled in (a Sheets tab needs the
    spreadsheet picked first), or naming an operation with required arguments.
    """
    spec: ConnectionEvidence = node_cls.connection_evidence

    if spec.field:
        loaders = _loader_fields(node_cls)
        if spec.field in loaders:
            assert not loaders[spec.field], (
                f"{node_type}.connection_evidence.field={spec.field!r} depends on "
                f"another config field, so it cannot resolve at connect time when "
                f"nothing is configured yet. Pick a top-level field."
            )

    ops = _operations(node_cls)
    for attr in ("operation", "identity_operation"):
        name = getattr(spec, attr)
        if not name or name not in ops:
            continue
        unmet = [r for r in ops[name] if r not in spec.operation_arguments]
        assert not unmet, (
            f"{node_type}.connection_evidence.{attr}={name!r} requires {unmet}, "
            f"which nobody has filled in when evidence runs. Either choose an "
            f"operation that needs no arguments, or supply them via "
            f"operation_arguments={{...}}."
        )


# --------------------------------------------------------- 3. not generic

# Catalogues that are byte-identical for every account with that provider.
# Gmail shipped `label_ids` as evidence and showed the user INBOX, SENT, SPAM,
# DRAFT, TRASH and six CATEGORY_* entries — fourteen rows, not one of which
# could differ between two accounts. It read as proof and proved nothing.
#
# The test any declaration has to pass: WOULD TWO ACCOUNTS SHOW DIFFERENT
# THINGS? If not, it is verification, not evidence, and must say so via
# proves="reachability".
_STATIC_CATALOGUE_PATTERNS = (
    "label_ids",          # Gmail: system labels
    "mail_folder",        # Outlook: Inbox/Sent/Drafts
    "_language",          # translation targets
    "_timezone",
    "_currency",
    "export_format",
    "available_sobjects",  # Salesforce: Account/Contact/Lead in every org
    "api_versions",
)


@pytest.mark.parametrize(
    "node_type,node_cls",
    sorted(
        (t, c)
        for t, c in NODE_REGISTRY.items()
        if getattr(c, "connection_evidence", None) is not None
    ),
)
def test_evidence_is_not_a_static_catalogue(node_type, node_cls):
    """Evidence must be the user's OWN data, or admit that it is not."""
    spec: ConnectionEvidence = node_cls.connection_evidence
    if spec.proves == "reachability":
        return  # honestly declared as "the key works", nothing more

    probe = spec.field or spec.operation or ""
    hit = next((p for p in _STATIC_CATALOGUE_PATTERNS if p in probe), None)
    assert hit is None, (
        f"{node_type} shows {probe!r}, which is the same for every account with "
        f"this provider ({hit!r}) — it looks like proof and proves nothing.\n"
        f"Pick something only THIS account would have (their channels, their "
        f"repos, who emailed them), or, if the provider genuinely has no "
        f"per-account data, declare proves=\"reachability\" so the UI says the "
        f"key was accepted instead of parading a catalogue as evidence."
    )


def test_proves_is_a_known_value():
    """A typo here would silently disable the generic-evidence guard."""
    for node_type, node_cls in NODE_REGISTRY.items():
        spec = getattr(node_cls, "connection_evidence", None)
        if spec is None:
            continue
        assert spec.proves in ("account", "reachability"), (
            f"{node_type}.connection_evidence.proves={spec.proves!r} is not a "
            f"known value; use 'account' or 'reachability'."
        )


# ------------------------------------------------------------- 4. read-only


@pytest.mark.parametrize(
    "node_type,node_cls",
    sorted(
        (t, c)
        for t, c in NODE_REGISTRY.items()
        if getattr(c, "connection_evidence", None) is not None
    ),
)
def test_evidence_operations_are_read_only(node_type, node_cls):
    """Evidence runs on connect, so it must never be able to change anything."""
    spec: ConnectionEvidence = node_cls.connection_evidence
    for attr in ("operation", "identity_operation"):
        name = getattr(spec, attr)
        if not name:
            continue
        assert name.startswith(_READ_ONLY_PREFIXES), (
            f"{node_type}.connection_evidence.{attr}={name!r} is not provably "
            f"read-only. Evidence runs the moment a user connects an account; "
            f"name a listing or lookup operation instead."
        )


# --------------------------------------------------------- 4. the seam runs

# The layers above are all static. They cannot catch the seam itself breaking —
# `collect_evidence` called a credential resolver that did not exist under that
# name, and the broad except turned the ImportError into a silent "cannot judge"
# for every field-based node. These execute the real function.


@pytest.mark.asyncio
async def test_field_path_resolves_credential_and_returns_samples(monkeypatch):
    """The load_field_options path must actually run end to end."""
    from nodes.core import connection_evidence as ce

    class FakeNode(_FakeNodeBase):
        connection_evidence = ConnectionEvidence(field="channel", noun="channels")

        @classmethod
        async def load_field_options(cls, field_name, credential_data, **kw):
            assert field_name == "channel"
            assert credential_data == {"token": "xoxb-real"}
            return {"options": [{"name": "#sales"}, {"name": "#gtm"}]}

    monkeypatch.setitem(ce_registry(), "fake-node", FakeNode)
    monkeypatch.setattr(
        "utils.credentials.resolve_credential_with_owner_fallback",
        _async_return({"token": "xoxb-real"}),
    )

    res = await ce.collect_evidence(
        node_type="fake-node", credential_id="c1", user_id="u1"
    )
    assert res.reachable is True
    assert [s.label for s in res.samples] == ["#sales", "#gtm"]
    assert res.noun == "channels"


@pytest.mark.asyncio
async def test_broken_declaration_is_logged_not_silently_swallowed(monkeypatch, caplog):
    """A declaration pointing at nothing must be loud, not a quiet blank panel."""
    import logging

    from nodes.core import connection_evidence as ce

    class FakeNode(_FakeNodeBase):
        connection_evidence = ConnectionEvidence(field="nope", noun="things")

        @classmethod
        async def load_field_options(cls, field_name, credential_data, **kw):
            raise AttributeError("no loader for 'nope'")

    monkeypatch.setitem(ce_registry(), "fake-broken", FakeNode)
    monkeypatch.setattr(
        "utils.credentials.resolve_credential_with_owner_fallback",
        _async_return({"token": "t"}),
    )

    with caplog.at_level(logging.ERROR):
        res = await ce.collect_evidence(
            node_type="fake-broken", credential_id="c1", user_id="u1"
        )
    assert res.reachable is None, "our bug must not read as a rejected credential"
    assert any(
        "declaration is broken" in r.getMessage() for r in caplog.records
    ), "a broken declaration must be logged at ERROR so it is alertable"


@pytest.mark.asyncio
async def test_provider_rejection_is_reported_as_rejection(monkeypatch):
    """invalid_auth is a verdict about the credential, and must survive as one."""
    from nodes.core import connection_evidence as ce

    class FakeNode(_FakeNodeBase):
        connection_evidence = ConnectionEvidence(field="channel", noun="channels")

        @classmethod
        async def load_field_options(cls, field_name, credential_data, **kw):
            raise ValueError("slack api error: invalid_auth")

    monkeypatch.setitem(ce_registry(), "fake-dead", FakeNode)
    monkeypatch.setattr(
        "utils.credentials.resolve_credential_with_owner_fallback",
        _async_return({"token": "t"}),
    )

    res = await ce.collect_evidence(
        node_type="fake-dead", credential_id="c1", user_id="u1"
    )
    assert res.reachable is False
    assert "invalid_auth" in (res.error or ""), "the provider's own words must survive"



class _FakeNodeBase:
    """Minimum of the WorkflowNode contract that collect_evidence relies on.

    Real nodes inherit `freshen_credential` from WorkflowNode; evidence calls it
    so a merely-expired token is refreshed rather than reported as a dead
    credential. Fakes have to honour the same contract or they test a path the
    product does not have.
    """

    @classmethod
    async def freshen_credential(cls, credential_data, **kwargs):
        return credential_data


def ce_registry():
    from nodes.core.registry import NODE_REGISTRY

    return NODE_REGISTRY


def _async_return(value):
    async def _f(*a, **kw):
        return value

    return _f


@pytest.mark.asyncio
async def test_error_shaped_result_is_not_reported_as_connected(monkeypatch):
    """Nodes report failure in the RESULT, not by raising — a 403 is not a green.

    Twitter returned ``{"status": "error", "status_code": 403, ...}`` and the
    first cut of this layer called that connected, which is the false green the
    whole feature exists to remove.
    """
    from nodes.core import connection_evidence as ce

    class FakeNode(_FakeNodeBase):
        connection_evidence = ConnectionEvidence(
            operation="list_things", noun="things"
        )

    monkeypatch.setitem(ce_registry(), "fake-envelope", FakeNode)
    monkeypatch.setattr(
        "nodes.core.run_op.run_node_operation",
        _async_return(
            {
                "status": "error",
                "error": "Authenticating with OAuth 2.0 Application-Only is forbidden",
                "status_code": 403,
                "data": None,
            }
        ),
    )

    res = await ce.collect_evidence(
        node_type="fake-envelope", credential_id="c1", user_id="u1"
    )
    assert res.reachable is not True, "an error envelope must never read as connected"
    assert res.reachable is False, "a 403 is a definitive rejection"
    assert "forbidden" in (res.error or "").lower()


# --------------------------------------------- 5. the proof answers the question

# Every question asked before an agent runs lowers the odds it ever does. The
# probe has ALREADY fetched the user's channels to prove the credential works, so
# asking them to pick one a step later is a question we already paid for. These
# pin when the samples may be reused as the answer — and, more importantly, when
# they may not.


@pytest.mark.asyncio
async def test_field_evidence_can_answer_the_field_it_came_from(monkeypatch):
    """Samples from a field's own loader are legal values for that field."""
    from nodes.core import connection_evidence as ce

    class FakeNode(_FakeNodeBase):
        connection_evidence = ConnectionEvidence(field="channel", noun="channels")

        @classmethod
        async def load_field_options(cls, field_name, credential_data, **kw):
            return {
                "options": [
                    {"label": "#sales", "value": "C01"},
                    {"label": "#gtm", "value": "C02"},
                ]
            }

    monkeypatch.setitem(ce_registry(), "fake-picker", FakeNode)
    monkeypatch.setattr(
        "utils.credentials.resolve_credential_with_owner_fallback",
        _async_return({"token": "t"}),
    )

    res = await ce.collect_evidence(
        node_type="fake-picker", credential_id="c1", user_id="u1"
    )
    assert res.answers_field == "channel"
    assert res.samples == [
        EvidenceSample(label="#sales", value="C01"),
        EvidenceSample(label="#gtm", value="C02"),
    ], "the id must ride along, or the sample cannot be tapped to answer anything"


@pytest.mark.asyncio
async def test_operation_evidence_answers_nothing(monkeypatch):
    """Read-operation rows prove the account works but are not field options.

    Gmail's evidence is who recently emailed you. Those are not mailbox labels,
    and offering them as an answer to "which label do you want watched?" would
    write a sender's name into a label field.
    """
    from nodes.core import connection_evidence as ce

    class FakeNode(_FakeNodeBase):
        connection_evidence = ConnectionEvidence(
            operation="list_recent", noun="recent senders", label_keys=("from",)
        )

    monkeypatch.setitem(ce_registry(), "fake-op-evidence", FakeNode)
    monkeypatch.setattr(
        "nodes.core.run_op.run_node_operation",
        _async_return({"emails": [{"from": "Casey Example <casey@sender.example>"}]}),
    )

    res = await ce.collect_evidence(
        node_type="fake-op-evidence", credential_id="c1", user_id="u1"
    )
    assert res.reachable is True
    assert [s.label for s in res.samples] == ["Casey Example"]
    assert res.answers_field is None, (
        "operation rows are not options for any field; offering them as answers "
        "would write the wrong kind of value into a config field"
    )
    assert all(s.value is None for s in res.samples)


# Verbatim refusals from real providers, captured against genuinely dead
# credentials. Google's is the one that motivated this test: "invalid
# authentication credentials" does NOT contain the substring "invalid
# credentials" — the word "authentication" sits between them — so every expired
# Google credential was classified "cannot judge" and shown as unverified rather
# than as something to reconnect. A dead credential reading as merely unknown is
# the exact failure this whole module exists to remove.
_REAL_PROVIDER_REFUSALS = [
    "Google Drive API error: Request had invalid authentication credentials. "
    "Expected OAuth 2 access token, login cookie or other valid authentication credential.",
    "Google Drive API error (401): {'error': {'code': 401}}",
    "Client error '401 Unauthorized' for url 'https://api.github.com/user/repos'",
    "Slack API error: invalid_auth",
    'Notion API error: {"status":401,"code":"unauthorized","message":"API token is invalid."}',
    "Authenticating with OAuth 2.0 Application-Only is forbidden for this endpoint.",
    "Token has been expired or revoked.",
]


@pytest.mark.parametrize("message", _REAL_PROVIDER_REFUSALS)
def test_real_provider_refusals_are_recognised(message):
    from nodes.core.connection_evidence import _looks_like_auth_rejection

    assert _looks_like_auth_rejection(message), (
        f"{message[:60]!r} is a provider refusing the credential, but it would be "
        f"classified 'cannot judge' and shown as unverified instead of prompting "
        f"a reconnect."
    )


@pytest.mark.parametrize(
    "message",
    [
        "connection timed out",
        "502 Bad Gateway",
        "rate limit exceeded, retry after 30s",
        "spreadsheet not found",
        "internal server error",
    ],
)
def test_ordinary_failures_are_not_blamed_on_the_credential(message):
    """The marker list must stay narrow.

    A false positive tells someone to reconnect a perfectly good account, which
    is worse than showing nothing at all.
    """
    from nodes.core.connection_evidence import _looks_like_auth_rejection

    assert not _looks_like_auth_rejection(message), (
        f"{message!r} is not the provider rejecting the credential, but it would "
        f"be reported as one."
    )

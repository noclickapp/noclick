"""Tests for the system-notification email choke point (utils/notifications.py)
and its hooks: category opt-outs, the Postgres-backed dedupe windows +
per-category daily caps (user_notifications doubles as the in-app feed),
unsubscribe links, the credit-gate email, and the headless-only run-failure
predicate."""

import asyncio
import time
from types import SimpleNamespace

import pytest

import utils.notifications as notifications
from utils.notifications import (
    ALERT_DAILY_CAPS,
    CATEGORIES,
    build_unsubscribe_url,
    low_balance_state,
    mint_unsubscribe_sig,
    send_run_failure_alert,
    send_system_alert,
    verify_unsubscribe_sig,
)


@pytest.fixture(autouse=True)
def _relay_secret(monkeypatch):
    monkeypatch.setenv("EMAIL_RELAY_SECRET", "test-secret")
    notifications._LOCAL_WINDOWS.clear()


# ── Fake backend: routes the module's SQL onto an in-memory notification log ─

class _FakeBackend:
    """Implements the exact queries notifications.py issues, against an
    in-memory user_notifications list — so window/cap/record semantics are
    exercised end-to-end without Postgres."""

    def __init__(self, prefs_enabled=True, email="user@example.com", tier="pro"):
        self.prefs_enabled = prefs_enabled
        self.email = email
        self.tier = tier
        self.sends = []
        self.rows = []  # user_notifications
        self._next_id = 0
        self.claim_lock = asyncio.Lock()  # emulates pg_advisory_xact_lock
        self.credential_row = {
            "owner_id": "owner-1",
            "name": "credential@example.com",
            "credential_type": "google_gmail_oauth",
        }

    def install(self, monkeypatch):
        monkeypatch.setattr(notifications, "_fetch_row", self.fetch_row)
        monkeypatch.setattr(notifications, "_execute", self.execute)
        monkeypatch.setattr(notifications, "_send_email", self.send_email)
        # The window claim runs its own transaction on a real conn; hand it a
        # fake pool whose conn routes SQL back into this backend.
        monkeypatch.setattr(notifications, "_resolve_pool", lambda pool: _FakePool(self))
        return self

    async def fetch_row(self, pool, query, *args):
        if "auth.users" in query:
            return {"email": self.email} if self.email else None
        if "user_notification_preferences" in query:
            return {"value": "true" if self.prefs_enabled else "false"}
        if "user_billing" in query:
            return {"subscription_tier": self.tier}
        if "FROM workflows" in query:
            return {"name": "My Flow"}
        if "FROM credentials" in query:
            return self.credential_row
        if "INSERT INTO user_notifications" in query and "RETURNING id" in query:
            # The window claim: row inserted at acquire time, email_sent=false.
            user_id, category, dedupe_key, title, body, cta_text, cta_url, metadata = args
            self._next_id += 1
            self.rows.append({
                "id": self._next_id,
                "user_id": user_id, "category": category, "dedupe_key": dedupe_key,
                "title": title, "body": body, "cta_text": cta_text, "cta_url": cta_url,
                "metadata": metadata, "email_sent": False,
                "suppressed_count": 0, "created_at": time.time(),
            })
            return {"id": self._next_id}
        if "UPDATE user_notifications" in query:  # window bump CTE
            user_id, key, ttl = args
            recent = [
                r for r in self.rows
                if r["user_id"] == user_id and r["dedupe_key"] == key
                and r["created_at"] > time.time() - ttl
            ]
            if recent:
                recent[-1]["suppressed_count"] += 1
                return {"id": "bumped"}
            return None
        if "SELECT suppressed_count" in query:
            user_id, key = args
            matching = [r for r in self.rows if r["user_id"] == user_id and r["dedupe_key"] == key]
            return {"suppressed_count": matching[-1]["suppressed_count"]} if matching else None
        if "SELECT COUNT(*)" in query:
            user_id, category = args
            n = sum(
                1 for r in self.rows
                if r["user_id"] == user_id and r["email_sent"] and r["category"] == category
            )
            return {"n": n}
        raise AssertionError(f"unexpected query: {query}")

    async def execute(self, pool, query, *args):
        if "UPDATE user_notifications" in query and "SET title" in query:
            # _record_notification filling in a claimed row after the send.
            claim_id, title, body, cta_text, cta_url, metadata, email_sent = args
            for r in self.rows:
                if r.get("id") == claim_id:
                    r.update(title=title, body=body, cta_text=cta_text,
                             cta_url=cta_url, metadata=metadata, email_sent=email_sent)
            return
        assert "INSERT INTO user_notifications" in query, f"unexpected execute: {query}"
        user_id, category, dedupe_key, title, body, cta_text, cta_url, metadata, email_sent = args
        self._next_id += 1
        self.rows.append({
            "id": self._next_id,
            "user_id": user_id, "category": category, "dedupe_key": dedupe_key,
            "title": title, "body": body, "cta_text": cta_text, "cta_url": cta_url,
            "metadata": metadata, "email_sent": email_sent,
            "suppressed_count": 0, "created_at": time.time(),
        })

    def send_email(self, to_email, subject, html, text, headers=None):
        self.sends.append({
            "to": to_email, "subject": subject, "html": html,
            "text": text, "headers": headers or {},
        })
        return True


class _FakeConn:
    """conn-level API the window claim uses: fetchrow/execute routed into the
    backend, with the advisory xact lock emulated as an asyncio.Lock held
    until transaction exit."""

    def __init__(self, backend):
        self.b = backend
        self._held = False

    async def execute(self, query, *args):
        if "pg_advisory_xact_lock" in query:
            await self.b.claim_lock.acquire()
            self._held = True
            return None
        return await self.b.execute(None, query, *args)

    async def fetchrow(self, query, *args):
        return await self.b.fetch_row(None, query, *args)

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                if conn._held:
                    conn.b.claim_lock.release()
                    conn._held = False
                return False

        return _Tx()


class _FakePool:
    def __init__(self, backend):
        self.b = backend

    async def fetchrow(self, query, *args):
        # The credit CTA reads the tier through the pool it is handed.
        return await self.b.fetch_row(self, query, *args)

    def acquire(self):
        backend = self.b

        class _Acq:
            async def __aenter__(self):
                return _FakeConn(backend)

            async def __aexit__(self, *exc):
                return False

        return _Acq()


ALERT_KWARGS = dict(
    subject="Test", heading="Test", eyebrow="Test", blocks_html="<p>Hello</p>",
    text_body="Hello", cta_text="Go", cta_url="https://noclick.com",
)


# ── Unsubscribe signatures ───────────────────────────────────────────────────

def test_unsubscribe_sig_roundtrip():
    sig = mint_unsubscribe_sig("user-1", "credits")
    assert verify_unsubscribe_sig("user-1", "credits", sig)


def test_unsubscribe_sig_rejects_tamper():
    sig = mint_unsubscribe_sig("user-1", "credits")
    assert not verify_unsubscribe_sig("user-2", "credits", sig)
    assert not verify_unsubscribe_sig("user-1", "run_failure", sig)
    assert not verify_unsubscribe_sig("user-1", "credits", sig[:-1] + "0")


def test_unsubscribe_sig_rejects_unknown_category():
    # Category outside the vocabulary never verifies — the route can't be used
    # to write arbitrary prefs keys.
    sig = mint_unsubscribe_sig("user-1", "anything")
    assert not verify_unsubscribe_sig("user-1", "anything", sig)


def test_unsubscribe_url_contains_signed_params():
    url = build_unsubscribe_url("user-1", "digest")
    assert "uid=user-1" in url and "cat=digest" in url and "sig=" in url
    assert "/email/notifications/unsubscribe" in url


# ── Low-balance math ─────────────────────────────────────────────────────────

def test_low_balance_state_thresholds():
    crossed, frac = low_balance_state(100, 85, 0, 0)
    assert crossed and frac == pytest.approx(0.85)
    crossed, _ = low_balance_state(100, 79.9, 0, 0)
    assert not crossed
    # Topup quota widens the pool: 50/150 used is not low.
    crossed, frac = low_balance_state(100, 50, 50, 0)
    assert not crossed and frac == pytest.approx(1 / 3)
    crossed, _ = low_balance_state(100, 50, 50, 70)
    assert crossed
    # Degenerate pool never crosses (enterprise handled upstream as None base).
    assert low_balance_state(0, 0, 0, 0) == (False, 0.0)


# ── send_system_alert choke point ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_system_alert_sends_records_and_unsubscribes(monkeypatch):
    be = _FakeBackend().install(monkeypatch)
    ok = await send_system_alert("user-1", "credits", **ALERT_KWARGS)
    assert ok and len(be.sends) == 1
    sent = be.sends[0]
    assert sent["to"] == "user@example.com"
    unsubscribe_url = build_unsubscribe_url("user-1", "credits")
    assert unsubscribe_url in sent["html"]
    assert unsubscribe_url in sent["text"]
    assert sent["headers"]["List-Unsubscribe"] == f"<{unsubscribe_url}>"
    assert sent["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    # Recorded in the notification log for the future in-app feed.
    assert len(be.rows) == 1
    assert be.rows[0]["category"] == "credits" and be.rows[0]["email_sent"] is True


@pytest.mark.asyncio
async def test_send_system_alert_respects_optout(monkeypatch):
    be = _FakeBackend(prefs_enabled=False).install(monkeypatch)
    ok = await send_system_alert("user-1", "credits", **ALERT_KWARGS)
    assert not ok and be.sends == [] and be.rows == []


@pytest.mark.asyncio
async def test_send_system_alert_records_without_email_address(monkeypatch):
    be = _FakeBackend(email=None).install(monkeypatch)
    ok = await send_system_alert("user-1", "digest", **ALERT_KWARGS)
    assert not ok and be.sends == []
    assert len(be.rows) == 1 and be.rows[0]["email_sent"] is False


@pytest.mark.asyncio
async def test_send_system_alert_dedupe_window(monkeypatch):
    be = _FakeBackend().install(monkeypatch)
    kwargs = dict(ALERT_KWARGS, dedupe_key="test:user-1", dedupe_ttl_s=3600)
    assert await send_system_alert("user-1", "credits", **kwargs)
    assert not await send_system_alert("user-1", "credits", **kwargs)
    assert len(be.sends) == 1
    # The repeat bumped the existing row instead of inserting a second one.
    assert len(be.rows) == 1 and be.rows[0]["suppressed_count"] == 1


@pytest.mark.asyncio
async def test_send_system_alert_local_backstop_on_db_error(monkeypatch):
    """If the window claim errors (DB blip), the in-process window must still
    bound repeats — otherwise an every-minute cron failure emails every
    minute for as long as the blip lasts."""
    be = _FakeBackend().install(monkeypatch)

    class _BlippingPool(_FakePool):
        def acquire(self):
            raise RuntimeError("db blip")

    monkeypatch.setattr(notifications, "_resolve_pool", lambda pool: _BlippingPool(be))
    kwargs = dict(ALERT_KWARGS, dedupe_key="test:blip", dedupe_ttl_s=3600)
    assert await send_system_alert("user-1", "credits", **kwargs)
    assert not await send_system_alert("user-1", "credits", **kwargs)
    assert len(be.sends) == 1


@pytest.mark.asyncio
async def test_concurrent_same_key_alerts_send_once(monkeypatch):
    """The 2026-08-21 dupe: one WAHooks session.status FAILED event, delivered
    to two webhooks on the same connection, produced two identical
    channel_disconnected emails 184ms apart — the second alert passed the
    window check before the first had recorded its row (record ran after the
    send). The claim now INSERTs the window's row inside the acquire
    transaction, so a same-key alert folds even while the first is still
    rendering/sending, and even from another container (no local window)."""
    import threading

    be = _FakeBackend().install(monkeypatch)
    release = threading.Event()
    original_send = be.send_email

    def slow_send(*args, **kwargs):
        release.wait(timeout=5)
        return original_send(*args, **kwargs)

    monkeypatch.setattr(notifications, "_send_email", slow_send)
    kwargs = dict(ALERT_KWARGS, dedupe_key="disc:cred-1", dedupe_ttl_s=3600)

    task_a = asyncio.create_task(send_system_alert("user-1", "credits", **kwargs))
    while not be.rows:  # A has claimed the window but is still mid-send
        await asyncio.sleep(0.01)
    # Second delivery lands on another container: no in-process window there.
    notifications._LOCAL_WINDOWS.clear()
    assert not await send_system_alert("user-1", "credits", **kwargs)

    release.set()
    assert await task_a
    assert len(be.sends) == 1
    assert len(be.rows) == 1
    assert be.rows[0]["suppressed_count"] == 1 and be.rows[0]["email_sent"] is True


@pytest.mark.asyncio
async def test_send_system_alert_never_raises(monkeypatch):
    async def boom(pool, query, *args):
        raise RuntimeError("db down")

    monkeypatch.setattr(notifications, "_fetch_row", boom)
    assert await send_system_alert("user-1", "credits", **ALERT_KWARGS) is False


# ── Daily caps (per category; digest uncapped) ───────────────────────────────

CREDITS_CAP = ALERT_DAILY_CAPS["credits"]
RUN_FAILURE_CAP = ALERT_DAILY_CAPS["run_failure"]


@pytest.mark.asyncio
async def test_daily_alert_cap_records_overflow(monkeypatch):
    be = _FakeBackend().install(monkeypatch)
    for _ in range(CREDITS_CAP + 2):
        await send_system_alert("user-1", "credits", **ALERT_KWARGS)
    assert len(be.sends) == CREDITS_CAP
    # Capped alerts are still recorded for the in-app feed, just not emailed.
    assert len(be.rows) == CREDITS_CAP + 2
    assert sum(1 for r in be.rows if r["email_sent"]) == CREDITS_CAP


@pytest.mark.asyncio
async def test_daily_cap_exempts_digest(monkeypatch):
    """The digest neither counts toward nor is blocked by any cap, so a noisy
    failure day can't squeeze it out."""
    be = _FakeBackend().install(monkeypatch)
    # Digest first: must not consume cap slots.
    assert await send_system_alert("user-1", "digest", **ALERT_KWARGS)
    for _ in range(CREDITS_CAP):
        assert await send_system_alert("user-1", "credits", **ALERT_KWARGS)
    # Cap exhausted for credits alerts...
    assert not await send_system_alert("user-1", "credits", **ALERT_KWARGS)
    # ...but the digest still goes out.
    assert await send_system_alert("user-1", "digest", **ALERT_KWARGS)
    assert len(be.sends) == CREDITS_CAP + 2


@pytest.mark.asyncio
async def test_credits_alert_survives_failure_capped_day(monkeypatch):
    """Caps are per category: a day of run-failure noise exhausting its own
    budget must not starve the credits alert that explains those failures."""
    be = _FakeBackend().install(monkeypatch)
    for _ in range(RUN_FAILURE_CAP + 3):
        await send_system_alert("user-1", "run_failure", **ALERT_KWARGS)
    assert len(be.sends) == RUN_FAILURE_CAP
    # The credits alert spends its own budget, unaffected by the failure spam.
    assert await send_system_alert("user-1", "credits", **ALERT_KWARGS)
    assert len(be.sends) == RUN_FAILURE_CAP + 1


# ── Run-failure alert: suppression window + folded count ────────────────────

RUN_KWARGS = dict(
    user_id="user-1", workflow_id="wf-1", execution_id="ex-1",
    trigger_source="cron", error="boom", node_label="HTTP Request",
    node_type="http", duration_s=1.0,
)


@pytest.mark.asyncio
async def test_run_failure_suppression_folds_count(monkeypatch):
    be = _FakeBackend().install(monkeypatch)
    assert await send_run_failure_alert(**RUN_KWARGS)
    # Inside the window: suppressed, folded onto the row, no email.
    assert not await send_run_failure_alert(**RUN_KWARGS)
    assert not await send_run_failure_alert(**RUN_KWARGS)
    assert len(be.sends) == 1
    assert len(be.rows) == 1 and be.rows[0]["suppressed_count"] == 2

    # Window expires → next failure sends and folds the suppressed count in.
    be.rows[0]["created_at"] -= notifications.RUN_FAILURE_SUPPRESS_S + 1
    notifications._LOCAL_WINDOWS.clear()
    assert await send_run_failure_alert(**RUN_KWARGS)
    assert len(be.sends) == 2
    assert "2 more" in be.sends[1]["html"]


@pytest.mark.asyncio
async def test_run_failure_delegates_credit_exhaustion(monkeypatch):
    """A run blocked by the credit gate sends the CREDITS alert — not a
    per-workflow failure email — carrying the blocked workflow + node, since
    this path is the only one that knows them. Deduped 24h like any credits
    alert, however many cron workflows are affected."""
    be = _FakeBackend().install(monkeypatch)
    ok = await send_run_failure_alert(
        user_id="user-1", workflow_id="wf-1", execution_id="ex-1",
        trigger_source="cron", node_label="Enrich with Apollo",
        error="Node n1 failed: Insufficient credits: 0.05 < 0.20 required",
    )
    assert ok and len(be.sends) == 1
    sent = be.sends[0]
    assert sent["subject"] == "You're out of credits on NoClick"
    assert "My Flow" in sent["html"]           # blocked workflow named
    assert "Enrich with Apollo" in sent["html"]  # blocked node named
    assert "0.05" in sent["html"]              # remaining parsed from the error
    assert be.rows[0]["category"] == "credits"

    # A second blocked workflow inside the window folds into the same alert.
    ok2 = await send_run_failure_alert(
        user_id="user-1", workflow_id="wf-2", execution_id="ex-2",
        trigger_source="cron",
        error="Node n9 failed: Insufficient credits: 0.05 < 0.20 required",
    )
    assert not ok2 and len(be.sends) == 1


async def test_credential_revoked_alert_targets_owner(monkeypatch):
    """The revoked-credential alert emails the credential OWNER — resolved
    from the credentials row, never the workflow runner (who already gets the
    downstream run-failure emails but can't reconnect someone else's account)."""
    be = _FakeBackend().install(monkeypatch)
    ok = await notifications.send_credential_revoked_alert(
        "cred-1", provider="google", revoked_reason="F29_user_revoked",
    )
    assert ok and len(be.sends) == 1
    assert be.rows[0]["user_id"] == "owner-1"
    assert be.rows[0]["category"] == "credential_revoked"
    sent = be.sends[0]
    assert sent["subject"] == "Your Google Gmail credential needs to be reconnected"
    assert "credential@example.com" in sent["html"]
    assert "tab=settings&section=credentials" in sent["text"]

    # A repeat inside the 24h window folds — one email per revocation.
    ok2 = await notifications.send_credential_revoked_alert(
        "cred-1", provider="google", revoked_reason="F29_user_revoked",
    )
    assert not ok2 and len(be.sends) == 1


async def test_credential_revoked_alert_missing_row_skips(monkeypatch):
    """Slack installation ids aren't credentials rows — no single owner to
    alert, so nothing is sent or recorded."""
    be = _FakeBackend().install(monkeypatch)
    be.credential_row = None
    ok = await notifications.send_credential_revoked_alert("install-1", provider="slack")
    assert not ok and not be.sends and not be.rows


@pytest.mark.asyncio
async def test_run_failure_alert_escapes_error_html(monkeypatch):
    be = _FakeBackend().install(monkeypatch)
    await send_run_failure_alert(
        user_id="user-1", workflow_id="wf-1", execution_id="ex-1",
        trigger_source="webhook", error="<script>alert(1)</script>",
    )
    assert len(be.sends) == 1
    assert "<script>" not in be.sends[0]["html"]
    assert "&lt;script&gt;" in be.sends[0]["html"]


# ── Headless-only predicate on the execution handler ────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("trigger_source,expects_alert", [
    (None, False),          # defaults to manual
    ("manual", False),
    ("builder_event", False),  # internal wake-turn plumbing — never email users
    ("webhook", True),
    ("cron", True),
    ("email", True),
])
async def test_maybe_alert_run_failure_headless_only(monkeypatch, trigger_source, expects_alert):
    from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler

    queued = asyncio.Event()

    async def fake_alert(**kwargs):
        queued.set()

    monkeypatch.setattr(notifications, "send_run_failure_alert", fake_alert)
    request = SimpleNamespace(workflow_id="wf-1", trigger_source=trigger_source)
    # The method never touches self — call unbound to skip handler construction.
    WorkflowExecutionHandler._maybe_alert_run_failure(
        None, request, "ex-1", "user-1", "boom",
    )
    await asyncio.sleep(0.05)
    assert queued.is_set() == expects_alert


def test_bar_fill_corners_rounded():
    """Partial fills must carry the track's corner radius — square fills
    inside rounded tracks was a reported visual bug."""
    from utils.notification_templates import credit_bars, workflow_bars

    split = workflow_bars([("Flow", 10, 3), ("Quiet", 2, 0)])
    assert "border-top-left-radius:3px" in split
    assert "border-bottom-right-radius:3px" in split
    single = credit_bars([("Flow", 12.5), ("Other", 1.0)])
    assert "border-top-left-radius:3px" in single and "12.5 cr" in single


# ── Prefs store contract ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_prefs_defaults_and_overrides(monkeypatch):
    async def fake_fetch_row(pool, query, *args):
        return {"prefs": '{"digest": false}'}  # plain pool: jsonb as text

    monkeypatch.setattr(notifications, "_fetch_row", fake_fetch_row)
    prefs = await notifications.get_prefs("user-1")
    assert prefs == {
        "channel_disconnected": True,
        "credential_revoked": True,
        "credits": True,
        "digest": False,
        "run_failure": True,
    }
    assert set(prefs) == set(CATEGORIES)


@pytest.mark.asyncio
async def test_get_prefs_no_row(monkeypatch):
    async def fake_fetch_row(pool, query, *args):
        return None

    monkeypatch.setattr(notifications, "_fetch_row", fake_fetch_row)
    prefs = await notifications.get_prefs("user-1")
    assert all(prefs.values())


@pytest.mark.asyncio
async def test_credit_cta_defaults_to_the_dashboard(monkeypatch):
    """Without a platform-provided CTA the alert still has somewhere honest
    to send the user, and never invents a purchase flow."""
    from utils import capabilities

    monkeypatch.setattr(capabilities, "_providers", {})
    label, url = await notifications._credit_cta("user-1")
    assert label == "Open Dashboard"
    assert url.endswith("/dashboard")

"""
System notification emails — THE choke point for every alert NoClick sends a
user about their own account/workflows (run failures, credit exhaustion, low
balance, weekly digest, auto-revoked credentials).

Every alert flows through send_system_alert(), which owns the four concerns no
call site should re-implement:
  1. per-category opt-out (user_notification_preferences; absent = enabled)
  2. rate limiting backed by the user_notifications log in Postgres — dedupe
     windows (repeats bump suppressed_count on the window's row) and
     per-category daily caps (ALERT_DAILY_CAPS), with an in-process window as
     the DB-blip backstop
  3. recipient resolution (auth.users email by user_id)
  4. branded render + category-scoped one-click unsubscribe (HMAC, no expiry,
     same EMAIL_RELAY_SECRET scheme as utils/email_unsubscribe.py) + RFC 8058
     List-Unsubscribe headers.

Every non-suppressed alert is RECORDED in user_notifications whether or not
the email went out (email_sent says which) — that table is the audit log, the
rate-limit state, and the backing store for a future in-app notification feed.

Transport uses the email provider and sender configured in utils/email.py.
All database access takes an optional asyncpg pool so maintenance processes
can supply one; otherwise the runtime database manager is used.
"""

import asyncio
import hashlib
import hmac
import html as html_lib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode

from billing.exceptions import match_insufficient_credits
from utils.email import FRONTEND_URL, _send_email
from utils.email_unsubscribe import DISABLE_LINK_BASE, _relay_secret
from repositories.users import USER_EMAIL_SQL
from utils.notification_templates import (
    AMBER,
    RED,
    build_alert_html,
    credit_bars,
    day_bars,
    error_panel,
    kv_rows,
    para,
    progress_bar,
    section_label,
    stat_tiles,
    strong,
    workflow_bars,
)

logger = logging.getLogger(__name__)

CATEGORIES = frozenset({
    "run_failure", "credits", "digest", "credential_revoked", "channel_disconnected",
})
CATEGORY_LABELS = {
    "run_failure": "workflow failure alerts",
    "credits": "credit balance alerts",
    "digest": "the weekly activity digest",
    "credential_revoked": "credential disconnection alerts",
    "channel_disconnected": "channel connection alerts",
}

# Suppression window after a run-failure email per workflow — a cron flow
# failing every 5 minutes sends one email, not 288/day. Failures inside the
# window are counted and folded into the next email.
RUN_FAILURE_SUPPRESS_S = 6 * 3600
CREDITS_EXHAUSTED_SUPPRESS_S = 24 * 3600
# Low-balance fires once per plan window (key includes the window), TTL is
# just a safety bound past the longest month.
LOW_BALANCE_TTL_S = 40 * 24 * 3600
LOW_BALANCE_FRACTION = 0.8


# ── Unsubscribe links (HMAC, category-scoped, never expire) ─────────────────

def mint_unsubscribe_sig(user_id: str, category: str) -> str:
    msg = f"notify|{user_id}|{category}"
    return hmac.new(_relay_secret().encode(), msg.encode(), hashlib.sha256).hexdigest()


def verify_unsubscribe_sig(user_id: str, category: str, sig: str) -> bool:
    if not user_id or category not in CATEGORIES or not sig:
        return False
    return hmac.compare_digest(mint_unsubscribe_sig(user_id, category), str(sig))


def build_unsubscribe_url(user_id: str, category: str) -> str:
    query = urlencode({
        "uid": user_id,
        "cat": category,
        "sig": mint_unsubscribe_sig(user_id, category),
    })
    return f"{DISABLE_LINK_BASE}/email/notifications/unsubscribe?{query}"


# ── DB access (optional explicit pool for cron containers) ──────────────────

def _resolve_pool(pool):
    if pool is not None:
        return pool
    from utils.database_pool import get_native_pool
    return get_native_pool()


async def _fetch_row(pool, query: str, *args):
    return await _resolve_pool(pool).fetchrow(query, *args)


async def _execute(pool, query: str, *args):
    return await _resolve_pool(pool).execute(query, *args)


async def get_prefs(user_id: str, pool=None) -> dict:
    """Resolved {category: enabled} for every known category (absent = True)."""
    import json

    row = await _fetch_row(
        pool, "SELECT prefs FROM user_notification_preferences WHERE user_id = $1", user_id
    )
    stored = row["prefs"] if row else {}
    if isinstance(stored, str):  # plain pools without the jsonb codec return text
        stored = json.loads(stored)
    return {cat: stored.get(cat, True) is not False for cat in sorted(CATEGORIES)}


async def is_category_enabled(user_id: str, category: str, pool=None) -> bool:
    """Absent row or absent key = enabled; only an explicit false disables."""
    row = await _fetch_row(
        pool,
        "SELECT prefs ->> $2 AS value FROM user_notification_preferences WHERE user_id = $1",
        user_id, category,
    )
    return row is None or row["value"] != "false"


async def set_category_enabled(user_id: str, category: str, enabled: bool, pool=None) -> None:
    await _execute(
        pool,
        """INSERT INTO user_notification_preferences (user_id, prefs)
           VALUES ($1, jsonb_build_object($2::text, $3::boolean))
           ON CONFLICT (user_id) DO UPDATE
           SET prefs = user_notification_preferences.prefs || jsonb_build_object($2::text, $3::boolean),
               updated_at = now()""",
        user_id, category, enabled,
    )


# ── Notification log: Postgres is the system of record ──────────────────────
# Every alert lands in user_notifications — sent or capped (email_sent says
# which) — so one table is the audit log, the rate-limit state, AND the store
# a future in-app notification feed reads. Suppressed repeats inside a dedupe
# window bump the existing row's suppressed_count/last_seen_at instead of
# inserting, keeping the feed compact ("failed 38 times" = one row).

# Per-container backstop windows ({key: monotonic expiry}) for when the DB
# window query itself errors — without it a DB blip turns an every-minute cron
# failure into an email per minute (if the rest of the send path still works).
_LOCAL_WINDOWS: dict = {}
_LOCAL_WINDOWS_MAX = 4096

# Hard daily email ceilings per user, PER CATEGORY — each category spends its
# own budget, so a day of failure noise can't starve the credits alert that
# often explains it (these used to share one pool, and run failures could
# squeeze the low-balance email out). The weekly digest is deliberately
# uncapped (None): weekly by construction, it must never be squeezed out.
# Capped alerts are still recorded (email_sent=false) for the in-app feed.
# Bounds the cross-workflow worst case: N broken cron flows × their
# per-workflow windows can't exceed the run_failure cap.
ALERT_DAILY_CAPS = {
    "run_failure": 3, "credits": 2, "digest": None, "credential_revoked": 3,
    "channel_disconnected": 3,
}
assert set(ALERT_DAILY_CAPS) == CATEGORIES  # every category decides its cap explicitly


def _local_acquire(key: str, ttl_s: int) -> bool:
    """In-process SET NX EX equivalent. True = window acquired."""
    now = time.monotonic()
    if len(_LOCAL_WINDOWS) > _LOCAL_WINDOWS_MAX:
        for k, exp in list(_LOCAL_WINDOWS.items()):
            if exp <= now:
                del _LOCAL_WINDOWS[k]
    expiry = _LOCAL_WINDOWS.get(key)
    if expiry is not None and expiry > now:
        return False
    _LOCAL_WINDOWS[key] = now + ttl_s
    return True


async def _window_acquire(
    user_id: str,
    category: str,
    dedupe_key: str,
    ttl_s: int,
    *,
    title: str = "",
    body: str = "",
    cta_text: Optional[str] = None,
    cta_url: Optional[str] = None,
    metadata: Optional[dict] = None,
    pool=None,
) -> tuple:
    """Returns (acquired, prior_suppressed_count, claim_id).

    If a row with this dedupe_key exists inside the window, bump its
    suppressed_count/last_seen_at and return (False, 0, None) — the repeat is
    folded into that row, no new email. Otherwise the window is ours: the
    window's row is INSERTED here (email_sent=false; `_record_notification`
    fills it in after the send), and we return True, the previous (expired)
    window's suppressed_count so the caller can say 'N more since the last
    alert', and the claimed row's id.

    Check and insert run in ONE transaction under a per-(user, key) advisory
    xact lock — check-now-insert-later let two concurrent alerts (one provider
    event delivered to two webhooks, landing on different containers) both
    pass the check and double-email (2026-08-21: duplicate
    channel_disconnected emails 184ms apart). xact-scoped locks are the
    PgBouncer-transaction-mode-safe variant; session locks are not.

    Falls back to the in-process window when the DB errors: (local_acquired,
    0, None) — the caller's `_record_notification` then INSERTs as before."""
    import json

    local_acquired = _local_acquire(dedupe_key, ttl_s)
    try:
        pool = _resolve_pool(pool)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1 || '|' || $2, 0))",
                    user_id, dedupe_key,
                )
                bumped = await conn.fetchrow(
                    """WITH recent AS (
                         SELECT id FROM user_notifications
                          WHERE user_id = $1 AND dedupe_key = $2
                            AND created_at > now() - make_interval(secs => $3)
                          ORDER BY created_at DESC LIMIT 1
                       )
                       UPDATE user_notifications n
                          SET suppressed_count = n.suppressed_count + 1, last_seen_at = now()
                        WHERE n.id IN (SELECT id FROM recent)
                       RETURNING n.id""",
                    user_id, dedupe_key, float(ttl_s),
                )
                if bumped:
                    return False, 0, None
                prior = await conn.fetchrow(
                    """SELECT suppressed_count FROM user_notifications
                        WHERE user_id = $1 AND dedupe_key = $2
                        ORDER BY created_at DESC LIMIT 1""",
                    user_id, dedupe_key,
                )
                claimed = await conn.fetchrow(
                    """INSERT INTO user_notifications
                           (user_id, category, dedupe_key, title, body, cta_text, cta_url, metadata, email_sent)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, ($8::text)::jsonb, false)
                       RETURNING id""",
                    user_id, category, dedupe_key, title, body, cta_text, cta_url,
                    json.dumps(metadata or {}),
                )
        return True, int(prior["suppressed_count"] or 0) if prior else 0, claimed["id"]
    except Exception as e:
        logger.warning(f"[Notify] window check failed for {dedupe_key}: {e}")
        return local_acquired, 0, None


async def _emails_sent_today(user_id: str, category: str, pool=None) -> int:
    """Emails sent today in this category. Fail-open (0) on error: a DB blip
    must not eat an alert — the dedupe windows (incl. the in-process backstop)
    still bound repeats."""
    try:
        row = await _fetch_row(
            pool,
            """SELECT COUNT(*) AS n FROM user_notifications
                WHERE user_id = $1 AND category = $2 AND email_sent
                  AND created_at >= date_trunc('day', now())""",
            user_id, category,
        )
        return int(row["n"]) if row else 0
    except Exception as e:
        logger.warning(f"[Notify] daily cap count failed for {user_id}: {e}")
        return 0


async def _record_notification(
    user_id: str,
    category: str,
    *,
    title: str,
    body: str,
    cta_text: Optional[str],
    cta_url: Optional[str],
    dedupe_key: Optional[str],
    metadata: Optional[dict],
    email_sent: bool,
    claim_id=None,
    pool=None,
) -> None:
    import json

    # metadata rides as text + server-side cast: runtime pools register a
    # jsonb codec (dict-encoding) while plain pools want str — ($8::text)::jsonb
    # behaves identically on both and sidesteps the double-encode landmine.
    # Best-effort: the email (if any) already went out; losing the log row is
    # the cheaper failure.
    try:
        if claim_id is not None:
            # The window claim already inserted this alert's row (that insert
            # is what makes the window atomic) — fill it in rather than
            # inserting a second one.
            await _execute(
                pool,
                """UPDATE user_notifications
                      SET title = $2, body = $3, cta_text = $4, cta_url = $5,
                          metadata = ($6::text)::jsonb, email_sent = $7
                    WHERE id = $1""",
                claim_id, title, body, cta_text, cta_url,
                json.dumps(metadata or {}), email_sent,
            )
            return
        await _execute(
            pool,
            """INSERT INTO user_notifications
                   (user_id, category, dedupe_key, title, body, cta_text, cta_url, metadata, email_sent)
               VALUES ($1, $2, $3, $4, $5, $6, $7, ($8::text)::jsonb, $9)""",
            user_id, category, dedupe_key, title, body, cta_text, cta_url,
            json.dumps(metadata or {}), email_sent,
        )
    except Exception as e:
        logger.error(f"[Notify] failed to record {category} notification for {user_id}: {e}")


# ── The choke point ──────────────────────────────────────────────────────────

async def send_system_alert(
    user_id: str,
    category: str,
    *,
    subject: str,
    heading: str,
    eyebrow: str,
    blocks_html: str,
    text_body: str,
    cta_text: str,
    cta_url: str,
    preheader: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    dedupe_ttl_s: Optional[int] = None,
    claim_id=None,
    metadata: Optional[dict] = None,
    pool=None,
) -> bool:
    """Render + send one system alert. Returns True iff an email went out.

    Every non-suppressed alert is recorded in user_notifications even when the
    daily cap blocks the email (email_sent=false) — the future in-app feed
    shows it, the inbox doesn't. Pass dedupe_ttl_s to have the window acquired
    here; pass dedupe_key + claim_id when the caller already acquired it via
    `_window_acquire` (the claimed row is filled in after the send instead of
    inserting a second one).

    blocks_html is raw HTML built from notification_templates components —
    callers must html-escape any user-controlled values they interpolate
    (workflow names, error text).
    """
    assert category in CATEGORIES, f"unknown notification category {category}"
    try:
        if dedupe_key and dedupe_ttl_s:
            acquired, _, claim_id = await _window_acquire(
                user_id, category, dedupe_key, dedupe_ttl_s,
                title=subject, body=text_body,
                cta_text=cta_text, cta_url=cta_url,
                metadata=metadata, pool=pool,
            )
            if not acquired:
                logger.info(f"[Notify] suppressed {dedupe_key} (window active)")
                return False

        if not await is_category_enabled(user_id, category, pool=pool):
            logger.info(f"[Notify] {category} disabled for user {user_id}, skipping")
            return False

        # Each category spends its own daily budget (digest: None = uncapped),
        # so failure noise can't squeeze out the credits alert that explains it.
        cap = ALERT_DAILY_CAPS[category]
        capped = (
            cap is not None
            and await _emails_sent_today(user_id, category, pool=pool) >= cap
        )

        sent = False
        if capped:
            logger.info(f"[Notify] daily cap reached for user {user_id} — recording {category} without email")
        else:
            row = await _fetch_row(pool, USER_EMAIL_SQL, user_id)
            to_email = row["email"] if row else None
            if to_email:
                unsubscribe_url = build_unsubscribe_url(user_id, category)
                label = CATEGORY_LABELS[category]
                html_content = build_alert_html(
                    # Preheader is plain text by definition — escape it here so
                    # callers can pass raw workflow names / error snippets.
                    preheader=html_lib.escape(preheader or text_body[:140]),
                    eyebrow=eyebrow,
                    heading=heading,
                    blocks_html=blocks_html,
                    cta_text=cta_text,
                    cta_url=cta_url,
                    unsubscribe_url=unsubscribe_url,
                    unsubscribe_label=label,
                    frontend_url=FRONTEND_URL,
                )
                text_content = (
                    f"{text_body}\n\n{cta_text}: {cta_url}\n\n"
                    f"Unsubscribe from {label}: {unsubscribe_url}\n\n---\nNoClick\n"
                )
                headers = {
                    "List-Unsubscribe": f"<{unsubscribe_url}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                }
                # _send_email is a blocking HTTP call — keep it off the event loop.
                sent = await asyncio.to_thread(
                    _send_email, to_email, subject, html_content, text_content, headers
                )
            else:
                logger.warning(f"[Notify] no email for user {user_id} — recording {category} without email")

        await _record_notification(
            user_id, category,
            title=subject, body=text_body,
            cta_text=cta_text, cta_url=cta_url,
            dedupe_key=dedupe_key, metadata=metadata,
            email_sent=sent, claim_id=claim_id, pool=pool,
        )
        return sent
    except Exception as e:
        # Alerts are best-effort everywhere they're hooked (run completion,
        # credit gate) — never let one bubble into the caller's path.
        logger.error(f"[Notify] failed to send {category} alert to user {user_id}: {e}", exc_info=True)
        return False


# ── Run failure ──────────────────────────────────────────────────────────────

TRIGGER_SOURCE_LABELS = {
    "webhook": "Webhook",
    "cron": "Schedule",
    "email": "Inbound email",
    "mcp": "MCP call",
    "api": "API call",
}


async def send_run_failure_alert(
    *,
    user_id: str,
    workflow_id: str,
    execution_id: str,
    trigger_source: str,
    error: Optional[str],
    node_label: Optional[str] = None,
    node_type: Optional[str] = None,
    duration_s: float = 0.0,
    organization_id: Optional[str] = None,
    pool=None,
) -> bool:
    """Alert the owner that a headless run failed. Per-workflow suppression:
    the first failure emails immediately; failures inside the window are
    counted and folded into the next email as 'N more failures'."""
    # A run blocked by the credit gate is a billing problem, not a workflow
    # bug — delegate to the credits-exhausted alert (deduped for 24h)
    # and hand it the blocked workflow/node so the email can say exactly what
    # stopped. This path is the only one that knows that context: the gate
    # itself is called from dozens of node handlers that don't. Detection is
    # anchored to the gate's exact message shape — a bare substring also
    # matched provider balance errors, incorrectly attributing a BYOK provider
    # failure to the instance credit policy.
    gate_match = match_insufficient_credits(error)
    if gate_match:
        from billing.usage_tracker import usage_tracker

        billing_user_id = await usage_tracker.resolve_billing_user_id(user_id, organization_id)
        remaining = float(gate_match.group(1))
        row = await _fetch_row(pool, "SELECT name FROM workflows WHERE id = $1", workflow_id)
        return await send_credits_exhausted_alert(
            billing_user_id, remaining,
            organization_id=organization_id,
            blocked_workflow=(row["name"] if row else None) or "Untitled workflow",
            blocked_node=node_label,
            blocked_workflow_id=workflow_id,
            pool=pool,
        )

    # Acquire the per-workflow window here (not in send_system_alert) because
    # the previous window's suppressed_count belongs in the email body.
    window_key = f"run_failure:{workflow_id}"
    acquired, suppressed_count, claim_id = await _window_acquire(
        user_id, "run_failure", window_key, RUN_FAILURE_SUPPRESS_S, pool=pool,
    )
    if not acquired:
        logger.info(f"[Notify] run-failure suppressed for workflow {workflow_id}")
        return False

    row = await _fetch_row(pool, "SELECT name FROM workflows WHERE id = $1", workflow_id)
    workflow_name = (row["name"] if row else None) or "Untitled workflow"
    wf_html = html_lib.escape(workflow_name)
    error_text = (error or "Unknown error").strip()
    if len(error_text) > 500:
        error_text = error_text[:500] + "…"
    failed_at = datetime.now(timezone.utc).strftime("%b %-d, %Y · %H:%M UTC")
    source = TRIGGER_SOURCE_LABELS.get(trigger_source, trigger_source)
    open_url = f"{FRONTEND_URL}/dashboard?tab=workflows&workflow={workflow_id}"

    node_value = ""
    if node_label:
        node_value = html_lib.escape(node_label)
        if node_type and node_type != node_label:
            node_value += f' <span style="color:#a1a1aa;font-weight:400;">({html_lib.escape(node_type)})</span>'

    details = [("Workflow", wf_html)]
    if node_value:
        details.append(("Failed at", node_value))
    details.extend([("Trigger", source), ("Time", failed_at)])

    blocks = (
        para(f"Your workflow {strong(wf_html)} hit an error and stopped.")
        + kv_rows(details)
        + error_panel(html_lib.escape(error_text))
    )
    if suppressed_count:
        blocks += para(
            f"It failed {strong(f'{suppressed_count} more time' + ('s' if suppressed_count != 1 else ''))} "
            "since your last alert."
        )

    text_body = (
        f'Your workflow "{workflow_name}" hit an error and stopped.\n'
        + (f"Failed at: {node_label}\n" if node_label else "")
        + f"Trigger: {source}\nTime: {failed_at}\nError: {error_text}\n"
        + (f"It failed {suppressed_count} more time(s) since your last alert.\n" if suppressed_count else "")
    )

    return await send_system_alert(
        user_id, "run_failure",
        subject=f'Your workflow "{workflow_name}" failed',
        heading=f"{wf_html} stopped" if len(workflow_name) <= 34 else "Workflow run failed",
        eyebrow="Workflow alert",
        blocks_html=blocks,
        text_body=text_body,
        preheader=f"Failed at {node_label} — {error_text[:90]}" if node_label else error_text[:120],
        cta_text="Open Workflow",
        cta_url=open_url,
        # Window already acquired above — its claimed row gets filled in.
        dedupe_key=window_key,
        claim_id=claim_id,
        metadata={
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "trigger_source": trigger_source,
            "node_label": node_label,
            "node_type": node_type,
        },
        pool=pool,
    )


# ── Credits ──────────────────────────────────────────────────────────────────

async def _credit_cta(_billing_user_id: str, pool=None) -> tuple:
    """Community builds have no managed purchase flow."""
    del pool
    return "Open Dashboard", f"{FRONTEND_URL}/dashboard"


async def send_credits_exhausted_alert(
    billing_user_id: str,
    remaining: float,
    organization_id: Optional[str] = None,
    *,
    blocked_workflow: Optional[str] = None,
    blocked_node: Optional[str] = None,
    blocked_workflow_id: Optional[str] = None,
    pool=None,
) -> bool:
    cta_text, cta_url = await _credit_cta(billing_user_id, pool=pool)
    remaining = max(remaining, 0)
    wf_html = html_lib.escape(blocked_workflow) if blocked_workflow else None

    if wf_html:
        intro = para(
            f"A run of {strong(wf_html)} was just blocked because your credit "
            "balance ran out. Runs and agents will keep failing until the instance limits are adjusted."
        )
    else:
        intro = para(
            "A workflow run was just blocked because your credit balance ran out. "
            "Runs and agents will keep failing until the instance limits are adjusted."
        )

    blocks = intro + progress_bar(
        100, "Monthly credits", f"{remaining:.2f} left", fill=RED,
    )
    details = []
    if wf_html:
        details.append(("Blocked workflow", wf_html))
    if blocked_node:
        details.append(("Stopped at", html_lib.escape(blocked_node)))
    details.append(("Balance", f"{remaining:.2f} credits"))
    blocks += kv_rows(details)
    if organization_id:
        blocks += para(
            "This run belongs to one of your organizations — as its owner, "
            "your credit pool funds the whole team's workflows."
        )

    text_body = (
        (f'A run of "{blocked_workflow}" was just blocked' if blocked_workflow
         else "A workflow run was just blocked")
        + " because your credit balance ran out.\n"
        + (f"Stopped at: {blocked_node}\n" if blocked_node else "")
        + f"Balance: {remaining:.2f} credits\n"
        + "Runs and agents will keep failing until the instance limits are adjusted."
    )

    return await send_system_alert(
        billing_user_id, "credits",
        subject="You're out of credits on NoClick",
        heading="You're out of credits",
        eyebrow="Billing alert",
        blocks_html=blocks,
        text_body=text_body,
        preheader=(
            f"{blocked_workflow} was blocked — check the instance limits to keep your workflows running"
            if blocked_workflow else "Check the instance limits to keep your workflows running"
        ),
        cta_text=cta_text,
        cta_url=cta_url,
        dedupe_key=f"credits_exhausted:{billing_user_id}",
        dedupe_ttl_s=CREDITS_EXHAUSTED_SUPPRESS_S,
        metadata={
            "remaining": round(remaining, 4),
            "organization_id": organization_id,
            "blocked_workflow_id": blocked_workflow_id,
            "blocked_node": blocked_node,
        },
        pool=pool,
    )


async def send_recurring_grace_alert(
    billing_user_id: str,
    *,
    credential_id: str,
    credential_name: str,
    charge_label: str,
    grace_ends_at,
    remaining: float,
    grace_ttl_s: int,
    pool=None,
) -> bool:
    """Warn that a recurring resource (e.g. a WhatsApp connection) can't be
    funded and will be disconnected when the grace window ends. Once per
    credential per grace window."""
    cta_text, cta_url = await _credit_cta(billing_user_id, pool=pool)
    name_html = html_lib.escape(credential_name)
    label_html = html_lib.escape(charge_label)
    ends_str = grace_ends_at.strftime("%b %-d, %H:%M UTC")

    blocks = para(
        f"Your credit balance can't cover the recurring charge for your "
        f"{label_html} {strong(name_html)}. It keeps working for now, but it "
        f"will be {strong('disconnected on ' + ends_str)} unless the instance limits are adjusted."
    ) + kv_rows([
        (charge_label, name_html),
        ("Balance", f"{max(remaining, 0):.2f} credits"),
        ("Disconnects", ends_str),
    ])
    text_body = (
        f"Your credit balance can't cover the recurring charge for your "
        f"{charge_label} \"{credential_name}\".\n"
        f"Balance: {max(remaining, 0):.2f} credits\n"
        f"It will be disconnected on {ends_str} unless the instance limits are adjusted."
    )
    return await send_system_alert(
        billing_user_id, "credits",
        subject=f"Your {charge_label} will be disconnected soon",
        heading=f"Your {charge_label} needs credits",
        eyebrow="Billing alert",
        blocks_html=blocks,
        text_body=text_body,
        preheader=f"Adjust the instance limits before {ends_str} to keep {credential_name} connected",
        cta_text=cta_text,
        cta_url=cta_url,
        dedupe_key=f"recurring_grace:{credential_id}",
        dedupe_ttl_s=grace_ttl_s,
        metadata={"credential_id": credential_id, "remaining": round(max(remaining, 0), 4)},
        pool=pool,
    )


async def send_recurring_disconnected_alert(
    billing_user_id: str,
    *,
    credential_id: str,
    credential_name: str,
    charge_label: str,
    pool=None,
) -> bool:
    """Tell the owner a recurring resource was disconnected after the grace
    window elapsed with the balance still exhausted."""
    cta_text, cta_url = await _credit_cta(billing_user_id, pool=pool)
    name_html = html_lib.escape(credential_name)
    label_html = html_lib.escape(charge_label)

    blocks = para(
        f"Your {label_html} {strong(name_html)} was disconnected because your "
        "credit balance stayed exhausted through the grace period. Workflows "
        "using it will fail until the instance limits are adjusted and reconnect it."
    )
    text_body = (
        f"Your {charge_label} \"{credential_name}\" was disconnected because your "
        "credit balance stayed exhausted through the grace period.\n"
        "Workflows using it will fail until the instance limits are adjusted and reconnect it."
    )
    return await send_system_alert(
        billing_user_id, "credits",
        subject=f"Your {charge_label} was disconnected",
        heading=f"{charge_label} disconnected",
        eyebrow="Billing alert",
        blocks_html=blocks,
        text_body=text_body,
        preheader=f"{credential_name} was disconnected — reconfigure the instance to reconnect",
        cta_text=cta_text,
        cta_url=cta_url,
        dedupe_key=f"recurring_disconnected:{credential_id}",
        dedupe_ttl_s=24 * 3600,
        metadata={"credential_id": credential_id},
        pool=pool,
    )


# ── Credential revoked ───────────────────────────────────────────────────────

def _credential_type_label(credential_type: Optional[str], provider: str) -> str:
    """Human label from a credential_type key: google_gmail_oauth → Google Gmail."""
    base = re.sub(r"_(oauth|api_key)$", "", credential_type or provider or "")
    return base.replace("_", " ").title() or "OAuth"


async def send_credential_revoked_alert(
    credential_id: str,
    *,
    provider: str,
    revoked_reason: Optional[str] = None,
    pool=None,
) -> bool:
    """Tell a credential's OWNER it was auto-revoked after the provider
    terminally rejected its refresh token (oauth_refresh._maybe_auto_revoke).
    Targets the owner — not the workflow runner — because only the owner can
    reconnect it; the runner just sees downstream run-failure emails."""
    row = await _fetch_row(
        pool,
        "SELECT owner_id, name, credential_type FROM credentials WHERE id = $1",
        credential_id,
    )
    if not row:
        # Slack installation ids (workspace bot chain) land here: the row of
        # record isn't a credentials row and has no single owner to alert.
        logger.info(f"[Notify] no credentials row for revoked {credential_id} — skipping alert")
        return False

    owner_id = str(row["owner_id"])
    label = _credential_type_label(row["credential_type"], provider)
    name = row["name"] or label
    name_html = html_lib.escape(name)
    label_html = html_lib.escape(label)
    reconnect_url = f"{FRONTEND_URL}/dashboard?tab=settings&section=credentials"

    blocks = (
        para(
            f"Your {label_html} credential {strong(name_html)} stopped working — "
            "the provider reported its access as expired or revoked. This usually "
            "means the account's password changed or access was removed in the "
            "provider's security settings."
        )
        + kv_rows([("Credential", name_html), ("Service", label_html)])
        + para("Workflows using it will keep failing until you reconnect it.")
    )
    text_body = (
        f'Your {label} credential "{name}" stopped working — the provider '
        "reported its access as expired or revoked.\n"
        "Workflows using it will keep failing until you reconnect it."
    )

    return await send_system_alert(
        owner_id, "credential_revoked",
        subject=f"Your {label} credential needs to be reconnected",
        heading=f"{label} disconnected",
        eyebrow="Credential alert",
        blocks_html=blocks,
        text_body=text_body,
        preheader=f"{name} stopped working — reconnect it to keep your workflows running",
        cta_text="Reconnect Credential",
        cta_url=reconnect_url,
        dedupe_key=f"credential_revoked:{credential_id}",
        dedupe_ttl_s=24 * 3600,
        metadata={
            "credential_id": credential_id,
            "provider": provider,
            "revoked_reason": revoked_reason,
        },
        pool=pool,
    )


async def send_channel_disconnected_alert(
    credential_id: str,
    *,
    provider_label: str,
    session_status: str,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    pool=None,
    hint: Optional[str] = None,
) -> bool:
    """Tell a connection-backed credential's OWNER its provider session died
    (phone unlinked, bot removed from a server, worker loss). Distinct from
    credential_revoked: the credential ROW is fine — the live connection
    behind it is gone and messages stop arriving silently. ``hint`` is the
    health registry's fix-it guidance for that credential type; without one
    the WhatsApp re-scan advice applies (the push path's caller). Fired from
    provider control events and the daily sweep backstop (shared dedupe key,
    so at most one email per credential per window either way)."""
    fix_text = hint or (
        f"Open the credential and re-scan the QR code to reconnect this same "
        f"{provider_label} connection. Don't create a second credential — "
        "repeated fresh scans can get all of the phone's links logged out."
    )
    row = await _fetch_row(
        pool,
        "SELECT owner_id, name, credential_type FROM credentials WHERE id = $1",
        credential_id,
    )
    if not row:
        return False

    owner_id = str(row["owner_id"])
    name = row["name"] or f"{provider_label} connection"
    name_html = html_lib.escape(name)
    label_html = html_lib.escape(provider_label)
    cta_url = (
        f"{FRONTEND_URL}/workflow/{workflow_id}" if workflow_id
        else f"{FRONTEND_URL}/dashboard?tab=settings&section=credentials"
    )

    rows = [("Connection", name_html), ("Service", label_html), ("Status", html_lib.escape(session_status))]
    if workflow_name:
        rows.append(("Workflow", html_lib.escape(workflow_name)))
    blocks = (
        para(
            f"Your {label_html} connection {strong(name_html)} has disconnected. "
            "Incoming messages are NOT reaching your workflows and sends will "
            "fail until you reconnect."
        )
        + kv_rows(rows)
        + para(f"To fix it: {html_lib.escape(fix_text)}")
    )
    text_body = (
        f'Your {provider_label} connection "{name}" has disconnected '
        f"(status {session_status}). Incoming messages are not reaching your "
        "workflows and sends will fail until you reconnect it.\n"
        f"To fix it: {fix_text}"
    )

    return await send_system_alert(
        owner_id, "channel_disconnected",
        subject=f"Your {provider_label} connection is disconnected",
        heading=f"{provider_label} disconnected",
        eyebrow="Connection alert",
        blocks_html=blocks,
        text_body=text_body,
        preheader=f"{name} disconnected — reconnect to keep your workflows running",
        cta_text="Reconnect Now",
        cta_url=cta_url,
        dedupe_key=f"channel_disconnected:{credential_id}",
        dedupe_ttl_s=24 * 3600,
        metadata={
            "credential_id": credential_id,
            "provider": provider_label,
            "session_status": session_status,
            "workflow_id": workflow_id,
        },
        pool=pool,
    )


def low_balance_state(
    base: float, plan_used: float, supplemental_quota: float, supplemental_used: float
) -> tuple:
    """Pure: (crossed_threshold, used_fraction) over the combined monthly pool."""
    pool_total = float(base) + float(supplemental_quota)
    if pool_total <= 0:
        return False, 0.0
    used = min(pool_total, float(plan_used) + float(supplemental_used))
    fraction = used / pool_total
    return fraction >= LOW_BALANCE_FRACTION, fraction


async def send_low_balance_alert(
    billing_user_id: str,
    *,
    remaining: float,
    used_fraction: float,
    window_key: str,
    pool=None,
) -> bool:
    """Once per plan window (window_key = the window's start date)."""
    import calendar
    from datetime import date

    cta_text, cta_url = await _credit_cta(billing_user_id, pool=pool)
    pct = int(used_fraction * 100)
    remaining = max(remaining, 0)

    # window_key is the current window's start date → next reset ≈ +1 month.
    reset_str = None
    try:
        start = date.fromisoformat(window_key)
        month = start.month % 12 + 1
        year = start.year + (start.month == 12)
        day = min(start.day, calendar.monthrange(year, month)[1])
        reset_str = date(year, month, day).strftime("%b %-d")
    except ValueError:
        pass

    details = [("Used", f"{pct}% of your monthly credits"), ("Remaining", f"{remaining:.1f} credits")]
    if reset_str:
        details.append(("Resets", reset_str))

    blocks = (
        para(
            "Your credits are running low. When they run out, workflow runs and "
            "agents will be blocked until the next reset."
        )
        + progress_bar(pct, "Monthly credits", f"{remaining:.1f} left", fill=AMBER)
        + kv_rows(details)
    )

    return await send_system_alert(
        billing_user_id, "credits",
        subject=f"You've used {pct}% of your NoClick credits",
        heading="Your credits are running low",
        eyebrow="Billing alert",
        blocks_html=blocks,
        text_body=(
            f"You've used {pct}% of your monthly NoClick credits ({remaining:.1f} left"
            + (f", resets {reset_str}" if reset_str else "") + "). "
            "When they run out, workflow runs and agents will be blocked until the next reset."
        ),
        preheader=f"{remaining:.1f} credits left this month",
        cta_text=cta_text,
        cta_url=cta_url,
        dedupe_key=f"low_balance:{billing_user_id}:{window_key}",
        dedupe_ttl_s=LOW_BALANCE_TTL_S,
        metadata={"remaining": round(remaining, 4), "used_fraction": round(used_fraction, 4)},
        pool=pool,
    )


# ── Weekly digest ────────────────────────────────────────────────────────────

async def send_weekly_digests(pool) -> int:
    """One digest per user with any workflow runs in the last 7 days. Called
    from the scheduled worker (scheduled_jobs) with its own pool. Returns sends."""
    users = await pool.fetch(
        """SELECT user_id, COUNT(*) AS runs,
                  COUNT(*) FILTER (WHERE status = 'error') AS failures
             FROM workflow_executions
            WHERE started_at >= now() - interval '7 days'
            GROUP BY user_id"""
    )
    sent = 0
    for u in users:
        user_id = str(u["user_id"])
        try:
            per_wf = await pool.fetch(
                """SELECT e.workflow_id, COALESCE(w.name, 'Untitled workflow') AS name,
                          COUNT(*) AS runs,
                          COUNT(*) FILTER (WHERE e.status = 'error') AS failures
                     FROM workflow_executions e
                     LEFT JOIN workflows w ON w.id = e.workflow_id
                    WHERE e.user_id = $1 AND e.started_at >= now() - interval '7 days'
                    GROUP BY e.workflow_id, w.name
                    ORDER BY COUNT(*) DESC
                    LIMIT 5""",
                u["user_id"],
            )
            spent = await pool.fetchval(
                """SELECT COALESCE(SUM(total_cost), 0) FROM user_usage_events
                    WHERE user_id = $1 AND user_resource = false
                      AND created_at >= now() - interval '7 days'""",
                u["user_id"],
            )
            credits_used = float(spent or 0)

            # Credit spend per workflow — attribution comes from the
            # metadata.workflow_id stamp (usage_tracker.CURRENT_WORKFLOW_ID);
            # chat/builder and pre-stamp events fold into one unattributed row.
            spend_rows = await pool.fetch(
                """SELECT COALESCE(w.name, 'Chat, builder & other') AS name,
                          SUM(e.total_cost) AS recorded_usage
                     FROM user_usage_events e
                     LEFT JOIN workflows w ON w.id::text = e.metadata->>'workflow_id'
                    WHERE e.user_id = $1 AND e.user_resource = false
                      AND e.created_at >= now() - interval '7 days'
                    GROUP BY 1
                    ORDER BY 2 DESC
                    LIMIT 5""",
                u["user_id"],
            )

            day_rows = await pool.fetch(
                """SELECT date_trunc('day', started_at) AS d, COUNT(*) AS runs
                     FROM workflow_executions
                    WHERE user_id = $1 AND started_at >= now() - interval '7 days'
                    GROUP BY 1""",
                u["user_id"],
            )
            by_day = {r["d"].date(): int(r["runs"]) for r in day_rows}
            today = datetime.now(timezone.utc).date()
            days = [today - timedelta(days=i) for i in range(6, -1, -1)]
            day_data = [(d.strftime("%a"), by_day.get(d, 0)) for d in days]

            runs, failures = int(u["runs"]), int(u["failures"])
            success_rate = int(round((runs - failures) / runs * 100)) if runs else 100
            date_range = f"{days[0].strftime('%b %-d')} – {days[-1].strftime('%b %-d, %Y')}"

            blocks = (
                para(f"Here's what your workflows did between {strong(date_range)}.")
                + stat_tiles([
                    (f"{runs:,}", "Runs"),
                    (f"{success_rate}%", "Success rate"),
                    (f"{credits_used:.1f}", "Credits used"),
                ])
                + section_label("Daily activity")
                + day_bars(day_data)
                + section_label("Most active workflows")
                + workflow_bars([
                    (html_lib.escape(w["name"]), int(w["runs"]), int(w["failures"]))
                    for w in per_wf
                ])
            )
            credit_rows = [
                (html_lib.escape(r["name"]), float(r["recorded_usage"] or 0))
                for r in spend_rows
            ]
            credit_rows = [r for r in credit_rows if r[1] >= 0.05]
            if credit_rows:
                blocks += section_label("Top credit consumers") + credit_bars(credit_rows)
            if failures:
                blocks += para(
                    f"{strong(str(failures))} run{'s' if failures != 1 else ''} failed this week — "
                    "the red segments above show where."
                )

            ok = await send_system_alert(
                user_id, "digest",
                subject="Your week on NoClick",
                heading="Your week on NoClick",
                eyebrow="Weekly digest",
                blocks_html=blocks,
                text_body=(
                    f"Your week on NoClick ({date_range}):\n"
                    f"Runs: {runs}\nSuccess rate: {success_rate}%\nCredits used: {credits_used:.1f}\n\n"
                    + "\n".join(
                        f"- {w['name']}: {w['runs']} run(s), {w['failures']} failed" for w in per_wf
                    )
                ),
                preheader=f"{runs} runs · {success_rate}% success · {credits_used:.1f} credits used",
                cta_text="Open Dashboard",
                cta_url=f"{FRONTEND_URL}/dashboard",
                metadata={
                    "runs": runs,
                    "failures": failures,
                    "success_rate": success_rate,
                    "credits_used": round(credits_used, 2),
                },
                pool=pool,
            )
            sent += 1 if ok else 0
        except Exception as e:
            logger.error(f"[Notify] digest failed for user {user_id}: {e}", exc_info=True)
    logger.info(f"[Notify] weekly digest: {sent}/{len(users)} sent")
    return sent

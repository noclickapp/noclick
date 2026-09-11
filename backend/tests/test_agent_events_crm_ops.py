"""``resolve_agent_event`` for the CRM / commerce / ops / mail trigger nodes.

Each node turns its fired delivery into a human-shaped agent turn: a header
naming provider + event + who/where, the content a person reads off the
record, and — where the node exposes a matching operation — a closing line
naming that operation with the exact ids it takes. Transport plumbing
(``_webhook`` headers, Mailgun's ``signature`` block, HMAC tokens) never rides
the turn; a shape the override does not recognise falls through to the base
bounded-JSON delivery, and the manual-run envelope never crashes it.

Fixtures are fictional throughout (``.example`` domains, "Casey Example").
"""

from urllib.parse import urlencode

from nodes.calendly_node import CalendlyNode
from nodes.datadog_node import DatadogNode
from nodes.honeycomb_node import HoneycombNode
from nodes.hubspot_node import HubSpotNode
from nodes.intercom_node import IntercomNode
from nodes.loops_node import LoopsNode
from nodes.mailgun_node import MailgunNode
from nodes.pagerduty_node import PagerDutyNode
from nodes.posthog_node import PostHogNode
from nodes.resend_node import ResendNode
from nodes.sentry_node import SentryNode
from nodes.shopify_node import ShopifyNode
from nodes.stripe_node import StripeNode
from nodes.zendesk_node import ZendeskNode

# The envelope every node's manual run produces and the hook-contract suite
# sends to every registered class: unrecognised by these overrides.
MANUAL_RUN = {
    "status": "success",
    "action": "on_event",
    "data": {"event": "$rageclick", "distinct_id": "u1", "properties": {"$current_url": "/x"}},
}


def _falls_through(node_cls, output=MANUAL_RUN):
    """The base delivery: bounded JSON of the unwrapped payload, no key."""
    ev = node_cls.resolve_agent_event(output)
    assert ev["conversation_key"] is None
    assert ev.get("title") is None
    assert "$rageclick" in ev["text"]


# ── HubSpot ───────────────────────────────────────────────────────────────────

def _hubspot(**over):
    base = {
        "portalId": 12345678, "subscriptionType": "deal.propertyChange", "objectId": 9001,
        "propertyName": "dealstage", "propertyValue": "closedwon", "changeSource": "CRM_UI",
        "occurredAt": 1757600000000, "eventId": 1, "appId": 42, "attemptNumber": 0,
    }
    return {**base, **over}


def test_hubspot_property_change_names_the_fetch_operation():
    ev = HubSpotNode.resolve_agent_event(_hubspot())
    assert ev["text"].startswith("HubSpot deal.propertyChange: deal 9001")
    assert "dealstage → closedwon" in ev["text"]
    assert "2025-09-11T14:13:20Z" in ev["text"]  # occurredAt is epoch ms
    assert "not included" in ev["text"]
    assert "get_deal deal_id=9001" in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "Deal 9001 updated"


def test_hubspot_generic_object_event_resolves_type_from_object_type():
    ev = HubSpotNode.resolve_agent_event(
        _hubspot(subscriptionType=None, eventType="object.creation", objectType="CONTACT", objectId=55, propertyName=None)
    )
    assert "contact 55" in ev["text"]
    assert "get_contact contact_id=55" in ev["text"]
    assert ev["title"] == "Contact 55 created"


def test_hubspot_deletion_and_unfetchable_types_say_so():
    gone = HubSpotNode.resolve_agent_event(_hubspot(subscriptionType="contact.deletion", objectId=55, propertyName=None))
    assert "deleted" in gone["text"] and "get_contact" not in gone["text"]
    ticket = HubSpotNode.resolve_agent_event(_hubspot(subscriptionType="ticket.creation", objectId=7, propertyName=None))
    assert "not included" in ticket["text"] and "fetch it with" not in ticket["text"]
    assert ticket["title"] == "Ticket 7 created"


def test_hubspot_unrecognised_shape_falls_through():
    _falls_through(HubSpotNode)


# ── Shopify ───────────────────────────────────────────────────────────────────

def _shopify_order():
    return {
        "id": 5551001, "name": "#1001", "order_number": 1001, "email": "casey@example.com",
        "total_price": "42.00", "currency": "USD", "financial_status": "paid", "fulfillment_status": None,
        "line_items": [{"title": "Blue Mug", "quantity": 2, "price": "21.00"}],
        "customer": {"first_name": "Casey", "last_name": "Example", "email": "casey@example.com"},
        "shipping_address": {"city": "Portland", "country": "United States"},
        "_webhook": {"headers": {
            "X-Shopify-Topic": "orders/create", "X-Shopify-Shop-Domain": "acme-example.myshopify.com",
            "X-Shopify-Hmac-Sha256": "hmac-secret-value",
        }},
    }


def test_shopify_order_reads_the_topic_header_and_names_the_get_op():
    ev = ShopifyNode.resolve_agent_event(_shopify_order())
    assert ev["text"].startswith("Shopify orders/create: Order #1001 at acme-example.myshopify.com")
    assert "Casey Example <casey@example.com>" in ev["text"]
    assert "$42.00" in ev["text"] and "paid" in ev["text"] and "Portland, United States" in ev["text"]
    assert "2 × Blue Mug @ 21.00" in ev["text"]
    assert "get_order_by_id order_id=5551001" in ev["text"]
    assert "hmac-secret-value" not in ev["text"] and "_webhook" not in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "Order #1001 · $42.00"


def test_shopify_product_and_customer_topics():
    product = ShopifyNode.resolve_agent_event({
        "id": 77, "title": "Blue Mug", "handle": "blue-mug", "status": "active",
        "variants": [{"title": "Default", "price": "21.00"}],
        "_webhook": {"headers": {"x-shopify-topic": "products/update"}},  # lower-cased headers
    })
    assert product["text"].startswith("Shopify products/update: Blue Mug (product 77)")
    assert "- Default: 21.00" in product["text"] and "get_product_by_id product_id=77" in product["text"]
    assert product["title"] == "Product: Blue Mug"
    customer = ShopifyNode.resolve_agent_event({
        "id": 88, "email": "casey@example.com", "first_name": "Casey", "last_name": "Example",
        "_webhook": {"headers": {"X-Shopify-Topic": "customers/create"}},
    })
    assert "Casey Example <casey@example.com> (customer 88)" in customer["text"]
    assert "get_customer_by_id customer_id=88" in customer["text"]


def test_shopify_unrecognised_shape_falls_through():
    _falls_through(ShopifyNode)


# ── Zendesk ───────────────────────────────────────────────────────────────────

def _zendesk(kind="ticket.comment_added", **event):
    return {
        "type": f"zen:event-type:{kind}", "subject": "zen:ticket:123", "time": "2026-09-12T10:00:00Z",
        "detail": {"subject": "Login broken", "status": "open", "priority": "high",
                   "requester_id": 401, "assignee_id": 402, "description": "I cannot log in."},
        "event": event,
    }


def test_zendesk_comment_event_threads_on_the_ticket():
    ev = ZendeskNode.resolve_agent_event(_zendesk(comment={"body": "Still broken after reset", "author_id": 401}))
    assert ev["text"].startswith("Zendesk ticket.comment_added: ticket #123 “Login broken”")
    assert "- status: open" in ev["text"] and "- priority: high" in ev["text"]
    assert "Comment from 401:\nStill broken after reset" in ev["text"]
    assert "add_comment ticket_id=123" in ev["text"]
    assert "update_ticket ticket_id=123" in ev["text"]
    assert "show_ticket ticket_id=123" in ev["text"]
    assert ev["conversation_key"] == "123"
    assert ev["title"] == "Ticket #123: Login broken"


def test_zendesk_status_change_renders_previous_and_current():
    ev = ZendeskNode.resolve_agent_event(_zendesk("ticket.status_changed", previous="open", current="pending"))
    assert "Changed: open → pending" in ev["text"]
    assert "Comment from" not in ev["text"]


def test_zendesk_non_ticket_event_falls_through():
    ev = ZendeskNode.resolve_agent_event({"type": "zen:event-type:user.created", "subject": "zen:user:9", "detail": {"name": "Casey Example"}})
    assert ev["conversation_key"] is None and "Casey Example" in ev["text"]
    _falls_through(ZendeskNode)


# ── Intercom (ticket / contact / company branches; conversations are covered
# in test_intercom_agent_event.py) ───────────────────────────────────────────

def _intercom(topic, item):
    return {"type": "notification_event", "topic": topic, "data": {"item": item}}


def test_intercom_ticket_threads_on_the_ticket_and_names_reply_ticket():
    ev = IntercomNode.resolve_agent_event(_intercom("ticket.created", {
        "type": "ticket", "id": "tk_1",
        "ticket_attributes": {"_default_title_": "Refund request", "_default_description_": "Please refund order 1001", "priority": "high"},
        "ticket_state": "submitted", "ticket_type": {"name": "Billing"},
        "contacts": {"contacts": [{"id": "c1", "external_id": "casey-example"}]},
        "ticket_parts": {"ticket_parts": [{"body": "<p>Any update?</p>", "author": {"name": "Casey Example"}}]},
    }))
    assert ev["text"].startswith("Intercom ticket.created: ticket tk_1 “Refund request”")
    assert "- state: submitted" in ev["text"] and "- type: Billing" in ev["text"] and "casey-example" in ev["text"]
    assert "Please refund order 1001" in ev["text"] and "- priority: high" in ev["text"]
    assert "Latest update from Casey Example:\n<p>Any update?</p>" in ev["text"]
    assert "reply_ticket ticket_id=tk_1" in ev["text"] and "update_ticket ticket_id=tk_1" in ev["text"]
    assert ev["conversation_key"] == "tk_1"
    assert ev["title"] == "Ticket tk_1: Refund request"


def test_intercom_contact_and_company_read_as_records():
    contact = IntercomNode.resolve_agent_event(_intercom("contact.user.created", {
        "type": "contact", "id": "c_9", "name": "Casey Example", "email": "casey@example.com", "role": "user",
    }))
    assert contact["text"].startswith("Intercom contact.user.created: Casey Example")
    assert "- email: casey@example.com" in contact["text"] and "- role: user" in contact["text"]
    assert "get_contact contact_id=c_9" in contact["text"]
    assert contact["conversation_key"] is None and contact["title"] == "Contact: Casey Example"
    company = IntercomNode.resolve_agent_event(_intercom("company.created", {
        "type": "company", "id": "co_1", "name": "Acme Example", "company_id": "acme-example", "plan": {"name": "Pro"},
    }))
    assert "Acme Example" in company["text"] and "- company id: acme-example" in company["text"] and "- plan: Pro" in company["text"]
    assert "get_company company_id=co_1" in company["text"]
    assert company["title"] == "Company: Acme Example"


def test_intercom_conversation_keeps_its_shape_and_gains_a_title():
    ev = IntercomNode.resolve_agent_event(_intercom("conversation.user.replied", {
        "type": "conversation", "id": "conv_1",
        "source": {"body": "<p>hello</p>", "author": {"name": "Casey Example"}},
        "conversation_parts": {"conversation_parts": []},
    }))
    assert "conversation_id=conv_1" in ev["text"] and "reply_conversation" in ev["text"]
    assert ev["conversation_key"] == "conv_1"
    assert ev["title"] == "Casey Example · conversation conv_1"


def test_intercom_unrecognised_shape_falls_through():
    _falls_through(IntercomNode)


# ── Stripe ────────────────────────────────────────────────────────────────────

def _stripe(kind, obj, previous=None):
    data = {"object": obj}
    if previous is not None:
        data["previous_attributes"] = previous
    return {"id": "evt_1", "object": "event", "type": kind, "data": data}


def test_stripe_invoice_formats_minor_units_with_currency():
    ev = StripeNode.resolve_agent_event(_stripe("invoice.paid", {
        "id": "in_1", "object": "invoice", "number": "ACME-0001", "customer_email": "casey@example.com",
        "customer_name": "Casey Example", "amount_paid": 4200, "amount_due": 4200, "currency": "usd",
        "status": "paid", "hosted_invoice_url": "https://invoice.stripe.example/i/1", "lines": {"data": [{"id": "il_1"}]},
    }))
    assert ev["text"].startswith("Stripe invoice.paid: invoice in_1")
    assert "- amount: 42.00 USD" in ev["text"] and "- number: ACME-0001" in ev["text"]
    assert "casey@example.com" in ev["text"] and "- status: paid" in ev["text"]
    assert "https://invoice.stripe.example/i/1" in ev["text"]
    assert "il_1" not in ev["text"]  # nothing beyond the named fields rides
    assert ev["conversation_key"] is None
    assert ev["title"] == "invoice.paid · $42.00"


def test_stripe_charge_card_and_failure_fields():
    ev = StripeNode.resolve_agent_event(_stripe("charge.failed", {
        "id": "ch_1", "object": "charge", "amount": 1999, "currency": "eur", "status": "failed",
        "billing_details": {"name": "Casey Example", "email": "casey@example.com"},
        "payment_method_details": {"card": {"brand": "visa", "last4": "4242"}},
        "failure_message": "Your card was declined.", "receipt_url": None,
    }))
    assert "- amount: 19.99 EUR" in ev["text"]
    assert "- card: visa …4242" in ev["text"]
    assert "- failure: Your card was declined." in ev["text"]
    assert ev["title"] == "charge.failed · €19.99"


def test_stripe_subscription_updated_lists_plan_and_diff():
    ev = StripeNode.resolve_agent_event(_stripe(
        "customer.subscription.updated",
        {"id": "sub_1", "object": "subscription", "customer": "cus_1", "status": "active",
         "current_period_end": 1760000000, "cancel_at_period_end": True,
         "items": {"data": [{"price": {"nickname": "Pro", "unit_amount": 2000, "currency": "usd", "recurring": {"interval": "month"}}}]}},
        previous={"cancel_at_period_end": False},
    ))
    assert "- plan: Pro (20.00 USD/month)" in ev["text"]
    assert "- period ends: 2025-10-09T08:53:20Z" in ev["text"]
    assert "Changed:\n- cancel_at_period_end: false → true" in ev["text"]
    assert ev["title"] == "customer.subscription.updated · sub_1"


def test_stripe_unknown_object_rides_as_bounded_json_and_envelope_falls_through():
    ev = StripeNode.resolve_agent_event(_stripe("payout.paid", {"id": "po_1", "object": "payout", "arrival_date": 1760000000, "amount": 500}))
    assert ev["text"].startswith("Stripe payout.paid: payout po_1")
    assert '"arrival_date": 1760000000' in ev["text"]
    _falls_through(StripeNode)


# ── Calendly ──────────────────────────────────────────────────────────────────

def _calendly(event="invitee.created", **payload):
    base = {
        "name": "Casey Example", "email": "casey@example.com", "status": "active", "timezone": "America/New_York",
        "uri": "https://api.calendly.example/scheduled_events/EV1/invitees/INV1",
        "questions_and_answers": [{"question": "Company", "answer": "Acme Example"}, {"question": "Notes", "answer": ""}],
        "scheduled_event": {
            "uri": "https://api.calendly.example/scheduled_events/EV1", "name": "30 Minute Meeting",
            "start_time": "2026-09-14T15:00:00Z", "end_time": "2026-09-14T15:30:00Z",
            "location": {"type": "zoom", "join_url": "https://zoom.example/j/1"},
        },
        "cancel_url": "https://calendly.example/cancellations/INV1", "reschedule_url": "https://calendly.example/reschedulings/INV1",
    }
    return {"event": event, "created_at": "2026-09-12T10:00:00Z", "payload": {**base, **payload}}


def test_calendly_booking_reads_as_a_sentence_with_answers():
    ev = CalendlyNode.resolve_agent_event(_calendly())
    assert ev["text"].startswith(
        "Calendly invitee.created: Casey Example <casey@example.com> booked 30 Minute Meeting "
        "at 2026-09-14T15:00:00Z–2026-09-14T15:30:00Z (America/New_York)"
    )
    assert "- location: zoom https://zoom.example/j/1" in ev["text"]
    assert "Answers:\n- Company: Acme Example" in ev["text"] and "Notes" not in ev["text"]
    assert "cancel_scheduled_event or get_event_invitee with scheduled_event=https://api.calendly.example/scheduled_events/EV1 invitee=https://api.calendly.example/scheduled_events/EV1/invitees/INV1" in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "Casey Example · 30 Minute Meeting"


def test_calendly_cancellation_carries_who_and_why():
    ev = CalendlyNode.resolve_agent_event(_calendly(
        "invitee.canceled", status="canceled", cancellation={"canceled_by": "Casey Example", "reason": "Conflict"},
    ))
    assert "canceled 30 Minute Meeting" in ev["text"]
    assert "Canceled by Casey Example: Conflict" in ev["text"]


def test_calendly_other_topics_and_envelope_fall_through():
    ev = CalendlyNode.resolve_agent_event({"event": "routing_form_submission.created", "payload": {"uri": "https://api.calendly.example/routing_form_submissions/1"}})
    assert ev["conversation_key"] is None and "routing_form_submissions/1" in ev["text"]
    _falls_through(CalendlyNode)


# ── PagerDuty ─────────────────────────────────────────────────────────────────

def _pagerduty(kind="incident.triggered", data=None):
    incident = {
        "id": "PABC123", "type": "incident", "number": 42, "title": "Checkout latency high", "status": "triggered",
        "urgency": "high", "html_url": "https://acme-example.pagerduty.example/incidents/PABC123",
        "service": {"summary": "Checkout API"}, "assignees": [{"summary": "Riley Example"}], "priority": {"summary": "P1"},
    }
    return {"event": {"event_type": kind, "occurred_at": "2026-09-12T10:00:00Z", "agent": {"summary": "Casey Example"}, "data": data or incident}}


def test_pagerduty_incident_threads_on_the_incident_id():
    ev = PagerDutyNode.resolve_agent_event(_pagerduty())
    assert ev["text"].startswith("PagerDuty incident.triggered: #42 Checkout latency high — triggered, high urgency, service Checkout API")
    assert "- by: Casey Example" in ev["text"] and "- assigned to: Riley Example" in ev["text"] and "- priority: P1" in ev["text"]
    assert "https://acme-example.pagerduty.example/incidents/PABC123" in ev["text"]
    assert "update_incident incident_id=PABC123 status=acknowledged|resolved" in ev["text"]
    assert "create_note incident_id=PABC123" in ev["text"]
    assert ev["conversation_key"] == "PABC123"
    assert ev["title"] == "#42 Checkout latency high"


def test_pagerduty_note_event_carries_the_note_and_its_incident():
    ev = PagerDutyNode.resolve_agent_event(_pagerduty("incident.annotated", {
        "type": "incident_note", "content": "Rolled back the deploy.",
        "incident": {"id": "PABC123", "summary": "Checkout latency high", "html_url": "https://acme-example.pagerduty.example/incidents/PABC123"},
    }))
    assert "Note:\nRolled back the deploy." in ev["text"]
    assert ev["conversation_key"] == "PABC123"


def test_pagerduty_unrecognised_shape_falls_through():
    _falls_through(PagerDutyNode)


# ── Sentry ────────────────────────────────────────────────────────────────────

def _sentry_event(**over):
    base = {
        "title": "TypeError: x is undefined", "event_id": "e1", "environment": "production", "release": "1.2.3",
        "metadata": {"type": "TypeError", "value": "x is undefined"},
        "exception": {"values": [{"type": "TypeError", "value": "x is undefined"}]},
        "user": {"email": "casey@example.com"},
    }
    return {**base, **over}


def test_sentry_service_hook_reads_level_project_and_title():
    ev = SentryNode.resolve_agent_event({
        "project_name": "acme-web", "project_slug": "acme-web", "culprit": "checkout.js in submit", "level": "error",
        "message": "x is undefined", "url": "https://sentry.example/acme/acme-web/events/e1/", "event": _sentry_event(),
    })
    assert ev["text"].startswith("Sentry error in acme-web: TypeError: x is undefined")
    assert "- culprit: checkout.js in submit" in ev["text"] and "- environment: production" in ev["text"] and "- release: 1.2.3" in ev["text"]
    assert "- exception: TypeError: x is undefined" in ev["text"] and "- user: casey@example.com" in ev["text"]
    assert "https://sentry.example/acme/acme-web/events/e1/" in ev["text"]
    assert ev["conversation_key"] is None  # no issue id in the payload → no thread
    assert ev["title"] == "TypeError: x is undefined"


def test_sentry_issue_alert_unwraps_data_and_threads_on_the_issue():
    ev = SentryNode.resolve_agent_event({
        "action": "triggered",
        "data": {"triggered_rule": "High error rate", "event": _sentry_event(
            issue_id="77", project="acme-web", level="error", culprit="checkout.js", web_url="https://sentry.example/issues/77/",
        )},
    })
    assert "Sentry error in acme-web: TypeError: x is undefined" in ev["text"]
    assert "- rule: High error rate" in ev["text"] and "- issue: 77" in ev["text"]
    assert "update_issue issue_id=77" in ev["text"]
    assert ev["conversation_key"] == "77"


def test_sentry_unrecognised_shape_falls_through():
    _falls_through(SentryNode)


# ── PostHog ───────────────────────────────────────────────────────────────────

def test_posthog_hog_delivery_names_explaining_properties_and_bounds_the_rest():
    ev = PostHogNode.resolve_agent_event({
        "event": "$exception", "distinct_id": "u_1", "timestamp": "2026-09-12T10:00:00Z",
        "properties": {"$current_url": "https://app.example/checkout", "$exception_type": "TypeError",
                       "$exception_message": "x is undefined", "$browser": "Chrome", "$set": {"plan": "pro"}},
    })
    assert ev["text"].startswith("PostHog $exception by u_1 at 2026-09-12T10:00:00Z")
    assert "- current url: https://app.example/checkout" in ev["text"]
    assert "- exception type: TypeError" in ev["text"] and "- exception message: x is undefined" in ev["text"]
    assert '"$browser": "Chrome"' in ev["text"] and "$set" not in ev["text"]
    assert "list_events distinct_id=u_1" in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "$exception · u_1"


def test_posthog_manual_envelope_and_web_vitals():
    ev = PostHogNode.resolve_agent_event({"status": "success", "action": "on_web_vitals", "data": {
        "event": "$web_vitals", "distinct_id": "u_2", "properties": {"$web_vitals_LCP_value": 1800.5},
    }})
    assert "PostHog $web_vitals by u_2" in ev["text"] and "- web vitals LCP value: 1800.5" in ev["text"]
    assert ev["title"] == "$web_vitals · u_2"


def test_posthog_shape_without_distinct_id_falls_through():
    ev = PostHogNode.resolve_agent_event({"status": "success", "action": "on_event", "data": {"event": "$rageclick", "properties": {}}})
    assert ev["conversation_key"] is None and ev.get("title") is None and "$rageclick" in ev["text"]


# ── Datadog (poll) ────────────────────────────────────────────────────────────

def _datadog(events):
    return {"status": "success", "operation": "on_new_event", "events": events, "new_count": len(events), "query": "service:checkout", "last_seen_id": "ev1"}


def _dd_event(i, **attrs):
    base = {"timestamp": "2026-09-12T10:00:00Z", "title": f"Monitor alert {i}", "message": "CPU is high on host-1",
            "tags": ["service:checkout", "env:prod"], "alert_type": "error", "priority": "normal", "host": "host-1", "service": "checkout"}
    return {"id": f"ev{i}", "type": "event", "attributes": {**base, **attrs}}


def test_datadog_events_render_one_block_each():
    ev = DatadogNode.resolve_agent_event(_datadog([_dd_event(1), _dd_event(2, alert_type="warning", message=None)]))
    assert ev["text"].startswith("Datadog: 2 new Datadog events matching “service:checkout”")
    assert "[error] Monitor alert 1 — CPU is high on host-1" in ev["text"]
    assert "[warning] Monitor alert 2\n" in ev["text"]
    assert "- host: host-1" in ev["text"] and "- tags: service:checkout, env:prod" in ev["text"] and "- id: ev1" in ev["text"]
    assert "get_event event_id=" in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "2 new Datadog events"


def test_datadog_caps_at_ten_and_bounds_the_turn():
    eleven = DatadogNode.resolve_agent_event(_datadog([_dd_event(i) for i in range(11)]))
    assert eleven["text"].count("Monitor alert") == 10
    assert "[… 1 more event on the trigger node]" in eleven["text"]
    # Long messages are clipped, and the block budget yields before 4000 chars.
    long = DatadogNode.resolve_agent_event(_datadog([_dd_event(i, message="x" * 900) for i in range(12)]))
    assert "[660 more chars]" in long["text"]
    assert 1 <= long["text"].count("Monitor alert") < 10
    assert "more events on the trigger node]" in long["text"]
    assert len(long["text"]) < 4000


def test_datadog_empty_poll_delivers_nothing_and_other_shapes_fall_through():
    assert DatadogNode.resolve_agent_event(_datadog([])) is None
    _falls_through(DatadogNode)


# ── Honeycomb ─────────────────────────────────────────────────────────────────

def test_honeycomb_trigger_reads_state_threshold_and_groups():
    ev = HoneycombNode.resolve_agent_event({
        "version": "v0.1.0", "name": "High latency", "trigger_description": "p99 over 2s", "status": "TRIGGERED",
        "operator": ">", "threshold": 2000, "summary": "p99 crossed", "trigger_url": "https://ui.honeycomb.example/t/1",
        "result_url": "https://ui.honeycomb.example/r/1", "result_groups_triggered": [{"Group": {"service": "api"}, "Result": 2400}],
        "dataset_name": "prod", "environment": "production",
    })
    assert ev["text"].startswith("Honeycomb trigger TRIGGERED: High latency")
    assert "- description: p99 over 2s" in ev["text"] and "- threshold: > 2000" in ev["text"]
    assert '- {"service": "api"}: 2400' in ev["text"]
    assert "- trigger: https://ui.honeycomb.example/t/1" in ev["text"] and "- results: https://ui.honeycomb.example/r/1" in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "TRIGGERED: High latency"


def test_honeycomb_burn_alert_inside_the_manual_envelope():
    ev = HoneycombNode.resolve_agent_event({"status": "success", "action": "on_burn_alert", "data": {
        "alert_type": "exhaustion_time", "exhaustion_minutes": 240, "slo": {"name": "Checkout availability"},
        "dataset_name": "prod", "slo_url": "https://ui.honeycomb.example/slo/1",
    }})
    assert ev["text"].startswith("Honeycomb burn alert (exhaustion_time) for SLO Checkout availability")
    assert "- budget exhausted in: 240 min" in ev["text"] and "- url: https://ui.honeycomb.example/slo/1" in ev["text"]
    assert ev["title"] == "Burn alert: Checkout availability"


def test_honeycomb_unrecognised_shape_falls_through():
    _falls_through(HoneycombNode)


# ── Mailgun ───────────────────────────────────────────────────────────────────

def test_mailgun_event_webhook_drops_the_signature_block():
    ev = MailgunNode.resolve_agent_event({
        "signature": {"timestamp": "1757600000", "token": "tok-secret", "signature": "sig-secret"},
        "event-data": {
            "event": "failed", "recipient": "casey@example.com", "reason": "bounce", "severity": "permanent",
            "message": {"headers": {"subject": "Your invoice", "from": "billing@acme-example.com", "message-id": "m1@acme-example.com"}},
            "delivery-status": {"code": 550, "message": "5.1.1 mailbox unavailable", "description": "Not delivering"},
        },
    })
    assert ev["text"].startswith("Mailgun failed: to casey@example.com — Your invoice (550 5.1.1 mailbox unavailable)")
    assert "- from: billing@acme-example.com" in ev["text"] and "- severity: permanent" in ev["text"]
    assert "tok-secret" not in ev["text"] and "sig-secret" not in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "failed → casey@example.com"


def test_mailgun_inbound_route_forward_reads_as_the_email():
    raw = urlencode({
        "sender": "casey@example.com", "from": "Casey Example <casey@example.com>", "recipient": "support@mg.acme-example.com",
        "subject": "Refund please", "body-plain": "Hi, please refund order 1001.\n\n-- \nCasey", "stripped-text": "Hi, please refund order 1001.",
        "timestamp": "1757600000", "token": "tok-secret", "signature": "sig-secret",
    })
    ev = MailgunNode.resolve_agent_event({"raw": raw, "_webhook": {"headers": {"content-type": "application/x-www-form-urlencoded"}}})
    assert ev["text"].startswith("Email received at support@mg.acme-example.com\nFrom: Casey Example <casey@example.com>\nSubject: Refund please")
    assert "Hi, please refund order 1001." in ev["text"] and "-- \nCasey" not in ev["text"]
    assert "send_message with to=casey@example.com and subject=Re: Refund please" in ev["text"]
    assert "tok-secret" not in ev["text"] and "_webhook" not in ev["text"]
    assert ev["conversation_key"] == "casey@example.com"
    assert ev["title"] == "Casey Example <casey@example.com>: Refund please"


def test_mailgun_inbound_conversation_key_is_the_lowercased_address():
    raw = urlencode({"from": "Casey Example <Casey@Example.com>", "subject": "Hi", "body-plain": "hello"})
    assert MailgunNode.resolve_agent_event({"raw": raw})["conversation_key"] == "casey@example.com"


def test_mailgun_unrecognised_shapes_fall_through():
    _falls_through(MailgunNode)
    ev = MailgunNode.resolve_agent_event({"raw": "not=an-email"})
    assert ev["conversation_key"] is None and "not=an-email" in ev["text"]


# ── Resend ────────────────────────────────────────────────────────────────────

def _resend(kind, **data):
    base = {"email_id": "em_1", "from": "hello@acme-example.com", "to": ["casey@example.com"], "subject": "Welcome", "created_at": "2026-09-12T10:00:00Z"}
    return {"type": kind, "created_at": "2026-09-12T10:00:00Z", "data": {**base, **data}}


def test_resend_delivery_event_is_one_line_plus_the_get_op():
    ev = ResendNode.resolve_agent_event(_resend("email.delivered"))
    assert ev["text"].startswith("Resend email.delivered: to casey@example.com from hello@acme-example.com — Welcome")
    assert "get_email email_id=em_1" in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "email.delivered · Welcome"


def test_resend_bounce_and_click_details_ride():
    bounced = ResendNode.resolve_agent_event(_resend("email.bounced", bounce={"message": "mailbox full", "subType": "MailboxFull"}))
    assert "- bounce: mailbox full" in bounced["text"] and "- bounce type: MailboxFull" in bounced["text"]
    clicked = ResendNode.resolve_agent_event({"status": "success", "action": "receive_webhook", "data": {**_resend("email.clicked", click={"link": "https://app.example/start"}), "webhook_url": "https://x.example/hook"}})
    assert "- clicked: https://app.example/start" in clicked["text"]
    assert "webhook_url" not in clicked["text"]


def test_resend_unrecognised_shape_falls_through():
    _falls_through(ResendNode)


# ── Loops ─────────────────────────────────────────────────────────────────────

def test_loops_event_is_one_line_plus_find_contact():
    ev = LoopsNode.resolve_agent_event({
        "eventName": "email.clicked", "contactIdentity": {"email": "casey@example.com", "userId": "u_9"},
        "email": {"subject": "Welcome aboard"}, "campaignName": "Onboarding", "linkUrl": "https://app.example/start", "time": "2026-09-12T10:00:00Z",
    })
    assert ev["text"].startswith("Loops email.clicked: casey@example.com (campaign “Onboarding”)")
    assert "- subject: Welcome aboard" in ev["text"] and "- link: https://app.example/start" in ev["text"] and "- user id: u_9" in ev["text"]
    assert "find_contact email=casey@example.com" in ev["text"]
    assert ev["conversation_key"] is None
    assert ev["title"] == "email.clicked · casey@example.com"


def test_loops_contact_event_with_only_a_user_id():
    ev = LoopsNode.resolve_agent_event({"status": "success", "action": "on_loops_event", "data": {"eventName": "contact.created", "contactIdentity": {"userId": "u_9"}}})
    assert ev["text"].startswith("Loops contact.created: u_9")
    assert "find_contact user_id=u_9" in ev["text"]


def test_loops_unrecognised_shape_falls_through():
    _falls_through(LoopsNode)

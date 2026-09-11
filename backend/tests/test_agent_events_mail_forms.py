"""resolve_agent_event overrides for the mail, calendar, form, sheet, drive,
cron and webhook triggers.

The base hook delivers a fired trigger's output as bounded JSON. These nodes
override it into the turn a person would read — sender/subject/body, an
invite, "Question: answer" lines, one line per row — with the routing
envelope (``_webhook``, headers, clientState) left out and a last line naming
the node's REAL operation for acting on the event. Fixtures are fictional
(``.example`` domains, 555-01xx numbers): the repository is published.
"""

import json

from nodes.cron_trigger_node import CronTriggerNode
from nodes.gmail_node import GmailNode
from nodes.google_calendar_node import GoogleCalendarNode
from nodes.google_drive_node import GoogleDriveNode
from nodes.google_forms_node import GoogleFormsNode
from nodes.google_sheets_node import GoogleSheetsNode
from nodes.outlook_mail_node import OutlookMailNode
from nodes.typeform_node import TypeformNode
from nodes.webhook_trigger_node import WebhookTriggerNode

# The shape test_node_class_hook_contract feeds every node — none of these
# readers recognise it, so it must reach the base (an "Event:" header or JSON).
UNRECOGNIZED = {
    "status": "success",
    "action": "on_event",
    "data": {"event": "$rageclick", "distinct_id": "u1"},
}

WEBHOOK_META = {
    "id": "wh-1",
    "method": "post",
    "headers": {"authorization": "Bearer top-secret-token", "x-signature": "sig"},
    "query_params": {},
}


def _is_base_shape(event):
    text = event["text"]
    if text.startswith("Event: "):
        return True
    json.loads(text)
    return True


def _gmail_email(i=1, **over):
    email = {
        "id": f"msg-{i}",
        "thread_id": f"thread-{i}",
        "internal_date": "1700000000000",
        "snippet": f"Snippet {i}",
        "from": f"Casey Example <casey{i}@example-manufacturing.example>",
        "to": "sales@example.com",
        "subject": f"Order {i} question",
        "date": "Fri, 12 Sep 2026 09:00:00 +0000",
        "labels": ["INBOX", "UNREAD"],
        "body": f"Hi, is order {i} shipping this week?\n\nOn Thu, Sam wrote:\n> earlier quoted text",
        "reply_text": f"Hi, is order {i} shipping this week?",
    }
    email.update(over)
    return email


class TestGmail:
    def test_single_email_reads_like_mail_and_threads_on_thread_id(self):
        output = {
            "type": "gmail",
            "operation": "poll_for_new_emails",
            "status": "triggered",
            "email_count": 1,
            "emails": [_gmail_email(attachments=[
                {"filename": "po-4471.pdf", "mime_type": "application/pdf",
                 "size_bytes": 20480, "extractable": True, "attachment_id": "att-1", "source": "gmail"},
            ])],
            "query": "is:unread",
            "timestamp": 1.0,
            "_webhook": {"headers": {"x-secret": "never"}},
        }
        event = GmailNode.resolve_agent_event(output)
        text = event["text"]
        assert text.startswith("New email in Gmail")
        assert "From: Casey Example <casey1@example-manufacturing.example>" in text
        assert "Subject: Order 1 question" in text
        assert "Hi, is order 1 shipping this week?" in text
        assert "earlier quoted text" not in text, "reply_text wins over the quoted body"
        assert "po-4471.pdf" in text and "attachment_id=att-1" in text
        assert "reply_to_email_message with message_id=msg-1" in text
        assert "fetch_email_attachment" in text
        assert "x-secret" not in text and "is:unread" not in text
        assert event["conversation_key"] == "thread-1"
        assert event["title"] == "Order 1 question"

    def test_batch_renders_five_blocks_and_lists_the_rest_by_subject(self):
        emails = [_gmail_email(i) for i in range(1, 8)]
        event = GmailNode.resolve_agent_event({"email_count": 7, "emails": emails})
        text = event["text"]
        assert text.startswith("7 new emails in Gmail")
        assert text.count("From: ") == 5
        assert "Message id: msg-3" in text
        assert "…and 2 more: Order 6 question; Order 7 question" in text
        assert "reply_to_email_message" in text
        assert event["conversation_key"] is None
        assert event["title"] == "7 new emails"

    def test_rehearsal_flat_single_email_resolves(self):
        # The Test Run path delivers one email flat, not the poll envelope.
        flat = {
            "id": "example-message-qualified",
            "thread_id": "example-thread-qualified",
            "from": "Casey Example <casey@example-manufacturing.example>",
            "to": "sales@example.com",
            "subject": "Routing purchase-order approvals into Slack",
            "snippet": "Hi — we're evaluating options",
            "body": "Hi there,\n\nI'd like new requests to land in Slack.\n\nThanks,\nCasey",
            "internal_date": "1700000000000",
            "label_ids": ["INBOX", "UNREAD"],
        }
        event = GmailNode.resolve_agent_event(flat)
        assert "I'd like new requests to land in Slack." in event["text"]
        assert not event["text"].lstrip().startswith("{")
        assert event["conversation_key"] == "example-thread-qualified"
        assert event["title"] == "Routing purchase-order approvals into Slack"
        assert "message_id=example-message-qualified" in event["text"]

    def test_long_body_is_clipped_with_a_note(self):
        event = GmailNode.resolve_agent_event(_gmail_email(reply_text="x" * 2000))
        assert "x" * 1500 + "… [500 more chars]" in event["text"]
        assert "x" * 1501 not in event["text"]

    def test_empty_poll_delivers_nothing(self):
        assert GmailNode.resolve_agent_event({"email_count": 0, "emails": [], "status": "triggered"}) is None

    def test_unrecognized_shape_falls_through_to_base(self):
        assert _is_base_shape(GmailNode.resolve_agent_event(UNRECOGNIZED))


class TestOutlook:
    def test_mail_notification_hands_over_the_id_and_the_fetch_operation(self):
        output = {
            "value": [{
                "subscriptionId": "sub-1",
                "changeType": "created",
                "clientState": "signing-secret-value",
                "resource": "Users/u-1/mailFolders('inbox')/Messages/AAMkAGI2",
                "resourceData": {"@odata.type": "#Microsoft.Graph.Message", "id": "AAMkAGI2"},
            }],
            "_webhook": WEBHOOK_META,
        }
        event = OutlookMailNode.resolve_agent_event(output)
        text = event["text"]
        assert text.startswith("Outlook: 1 change notification")
        assert "Email received: id AAMkAGI2" in text
        assert "get_email_message (message_id=AAMkAGI2)" in text
        assert "reply_to_email_message" in text
        assert "signing-secret-value" not in text and "top-secret-token" not in text
        assert "sub-1" not in text
        assert event["conversation_key"] is None
        assert event["title"] == "Email received"

    def test_calendar_and_deleted_notifications_are_listed_without_a_body(self):
        output = {"value": [
            {"changeType": "updated", "resource": "/me/calendars/cal-1/events/evt-9",
             "resourceData": {"id": "evt-9"}},
            {"changeType": "deleted", "resource": "/me/mailFolders/inbox/messages/msg-7",
             "resourceData": {"id": "msg-7"}},
        ]}
        event = OutlookMailNode.resolve_agent_event(output)
        text = event["text"]
        assert "2 change notifications" in text
        assert "Calendar event updated: id evt-9 — fetch it with get_calendar_event (event_id=evt-9)" in text
        assert "Email deleted: id msg-7 (no longer fetchable)" in text
        assert "get_email_message" not in text, "a deleted message cannot be fetched"
        assert event["title"] == "2 Outlook changes"

    def test_unrecognized_shape_falls_through_to_base(self):
        assert _is_base_shape(OutlookMailNode.resolve_agent_event(UNRECOGNIZED))
        assert _is_base_shape(OutlookMailNode.resolve_agent_event({"value": [{"resource": "/me/contacts/c1"}]}))


def _gcal_event(i=1, **over):
    event = {
        "kind": "calendar#event",
        "etag": '"33"',
        "id": f"evt-{i}",
        "status": "confirmed",
        "htmlLink": f"https://calendar.example/event?eid=evt-{i}",
        "updated": "2026-09-12T08:00:00.000Z",
        "summary": f"Design review {i}",
        "description": "Agenda: onboarding flow",
        "location": "Room 4B",
        "start": {"dateTime": "2026-09-14T10:00:00+02:00", "timeZone": "Europe/Berlin"},
        "end": {"dateTime": "2026-09-14T11:00:00+02:00", "timeZone": "Europe/Berlin"},
        "organizer": {"email": "casey@example.com"},
        "attendees": [{"email": "casey@example.com", "organizer": True}, {"email": "sam@example.com"}],
        "hangoutLink": "https://meet.example/abc-defg",
        "reminders": {"useDefault": True},
    }
    event.update(over)
    return event


class TestGoogleCalendar:
    def test_event_reads_like_an_invite(self):
        event = GoogleCalendarNode.resolve_agent_event(
            {"events": [_gcal_event()], "event_count": 1, "_webhook": WEBHOOK_META}
        )
        text = event["text"]
        assert text.startswith("Google Calendar: event changed")
        assert "Event: Design review 1" in text
        assert "- When: 2026-09-14T10:00:00+02:00 → 2026-09-14T11:00:00+02:00" in text
        assert "- Where: Room 4B" in text
        assert "- Attendees: casey@example.com, sam@example.com" in text
        assert "- Organizer: casey@example.com" in text
        assert "- Link: https://calendar.example/event?eid=evt-1" in text
        assert "- Meet: https://meet.example/abc-defg" in text
        assert "Description:\nAgenda: onboarding flow" in text
        assert "fetch_calendar_event / update_calendar_event with event_id=evt-1" in text
        assert "etag" not in text and "top-secret-token" not in text
        assert event["title"] == "Design review 1"
        assert event["conversation_key"] is None

    def test_all_day_and_batch_cap(self):
        events = [_gcal_event(i) for i in range(1, 7)]
        events[0].update(start={"date": "2026-09-20"}, end={"date": "2026-09-21"}, description="d" * 2000)
        event = GoogleCalendarNode.resolve_agent_event({"events": events, "event_count": 6})
        text = event["text"]
        assert "- When: 2026-09-20 (all day)" in text
        assert "d" * 300 + "… [1700 more chars]" in text, "a batch clips each description tighter than a single event"
        assert text.count("Event: ") == 5
        assert "…and 1 more: Design review 6" in text
        assert event["title"] == "6 calendar events changed"

    def test_empty_variants_deliver_nothing(self):
        for output in (
            {"events": [], "event_count": 0, "deduped": True},
            {"events": [], "event_count": 0, "resynced": True},
            {"events": [], "event_count": 0, "message": "Save the workflow to activate it."},
        ):
            assert GoogleCalendarNode.resolve_agent_event(output) is None

    def test_unrecognized_shape_falls_through_to_base(self):
        assert _is_base_shape(GoogleCalendarNode.resolve_agent_event(UNRECOGNIZED))


class TestGoogleForms:
    def test_answers_render_by_question_id_with_the_title_lookup_named(self):
        output = {
            "responses": [{
                "responseId": "resp-1",
                "createTime": "2026-09-12T09:30:00Z",
                "lastSubmittedTime": "2026-09-12T09:30:00Z",
                "respondentEmail": "casey@example.com",
                "answers": {
                    "q-name": {"questionId": "q-name", "textAnswers": {"answers": [{"value": "Casey Example"}]}},
                    "q-topics": {"questionId": "q-topics", "textAnswers": {"answers": [{"value": "Billing"}, {"value": "Onboarding"}]}},
                    "q-file": {"questionId": "q-file", "fileUploadAnswers": {"answers": [{"fileId": "f-1", "fileName": "resume.pdf"}]}},
                },
            }],
            "new_response_count": 1,
            "_webhook": WEBHOOK_META,
        }
        event = GoogleFormsNode.resolve_agent_event(output)
        text = event["text"]
        assert text.startswith("Google Forms: new response")
        assert "Response resp-1 from casey@example.com at 2026-09-12T09:30:00Z" in text
        assert "- q-name: Casey Example" in text
        assert "- q-topics: Billing; Onboarding" in text
        assert "- q-file: file: resume.pdf" in text
        assert "get_form_metadata" in text and "get_form_response" in text
        assert "top-secret-token" not in text
        assert event["title"] == "New form response"
        assert event["conversation_key"] is None

    def test_anonymous_batch_is_capped(self):
        responses = [{"responseId": f"r-{i}", "answers": {"q": {"textAnswers": {"answers": [{"value": str(i)}]}}}} for i in range(7)]
        event = GoogleFormsNode.resolve_agent_event({"responses": responses, "new_response_count": 7})
        text = event["text"]
        assert text.startswith("Google Forms: 7 new responses")
        assert "from an anonymous respondent" in text
        assert text.count("Response r-") == 5
        assert "…and 2 more responses" in text
        assert event["title"] == "7 new form responses"

    def test_empty_delivers_nothing_and_unrecognized_falls_through(self):
        assert GoogleFormsNode.resolve_agent_event({"responses": [], "new_response_count": 0}) is None
        assert _is_base_shape(GoogleFormsNode.resolve_agent_event(UNRECOGNIZED))


class TestTypeform:
    def test_titles_are_zipped_with_answers_by_field_id(self):
        output = {
            "event_id": "01ABC",
            "event_type": "form_response",
            "form_response": {
                "form_id": "frm-1",
                "token": "tok-1",
                "submitted_at": "2026-09-12T09:45:00Z",
                "definition": {
                    "id": "frm-1",
                    "title": "Demo request",
                    "fields": [
                        {"id": "f1", "title": "Your name", "type": "short_text", "ref": "name"},
                        {"id": "f2", "title": "Work email", "type": "email", "ref": "email"},
                        {"id": "f3", "title": "Team size", "type": "number", "ref": "size"},
                        {"id": "f4", "title": "Which products?", "type": "multiple_choice", "ref": "products"},
                        {"id": "f5", "title": "Plan", "type": "multiple_choice", "ref": "plan"},
                        {"id": "f6", "title": "Book a call?", "type": "yes_no", "ref": "call"},
                        {"id": "f7", "title": "Phone", "type": "phone_number", "ref": "phone"},
                    ],
                },
                "answers": [
                    {"type": "text", "text": "Casey Example", "field": {"id": "f1", "type": "short_text", "ref": "name"}},
                    {"type": "email", "email": "casey@example.com", "field": {"id": "f2", "type": "email"}},
                    {"type": "number", "number": 12, "field": {"id": "f3", "type": "number"}},
                    {"type": "choices", "choices": {"labels": ["Agents", "Workflows"]}, "field": {"id": "f4", "type": "multiple_choice"}},
                    {"type": "choice", "choice": {"label": "Pro"}, "field": {"id": "f5", "type": "multiple_choice"}},
                    {"type": "boolean", "boolean": True, "field": {"id": "f6", "type": "yes_no"}},
                    {"type": "phone_number", "phone_number": "+1 555 0142", "field": {"id": "f7", "type": "phone_number"}},
                    {"type": "date", "date": "2026-09-20", "field": {"id": "f-unknown", "type": "date", "ref": "when"}},
                ],
                "hidden": {"utm_source": "newsletter"},
            },
            "_webhook": WEBHOOK_META,
        }
        event = TypeformNode.resolve_agent_event(output)
        text = event["text"]
        assert text.startswith('Typeform: new response to "Demo request" submitted at 2026-09-12T09:45:00Z')
        assert "- Your name: Casey Example" in text
        assert "- Work email: casey@example.com" in text
        assert "- Team size: 12" in text
        assert "- Which products?: Agents, Workflows" in text
        assert "- Plan: Pro" in text
        assert "- Book a call?: True" in text
        assert "- Phone: +1 555 0142" in text
        assert "- when: 2026-09-20" in text, "an answer with no definition entry falls back to its ref"
        assert "Hidden fields:\n- utm_source: newsletter" in text
        assert "get_form_responses (form_id=frm-1)" in text
        assert "01ABC" not in text and "top-secret-token" not in text
        assert event["title"] == "Demo request"
        assert event["conversation_key"] is None

    def test_manual_run_notice_and_unrecognized_fall_through_to_base(self):
        assert _is_base_shape(TypeformNode.resolve_agent_event(
            {"message": "This trigger fires when a new response is submitted.", "form_id": "frm-1"}
        ))
        assert _is_base_shape(TypeformNode.resolve_agent_event(UNRECOGNIZED))


class TestGoogleSheets:
    def test_rows_are_labelled_by_header(self):
        output = {
            "rows": [
                {"row_number": 2, "values": ["Casey Example", "casey@example.com", ""],
                 "row": {"Name": "Casey Example", "Email": "casey@example.com", "Notes": ""}},
                {"row_number": 3, "values": ["Sam Example", "sam@example.com", "call back"],
                 "row": {"Name": "Sam Example", "Email": "sam@example.com", "Notes": "call back"}},
            ],
            "new_row_count": 2,
            "headers": ["Name", "Email", "Notes"],
            "_webhook": WEBHOOK_META,
        }
        event = GoogleSheetsNode.resolve_agent_event(output)
        text = event["text"]
        assert text.startswith("Google Sheets: 2 new rows")
        assert "Row 2: Name=Casey Example, Email=casey@example.com" in text
        assert "Row 3: Name=Sam Example, Email=sam@example.com, Notes=call back" in text
        assert "Notes=\n" not in text and "Notes=," not in text, "empty cells are dropped"
        assert "read_sheet_data / write_sheet_data" in text
        assert "top-secret-token" not in text
        assert event["title"] == "2 new rows"
        assert event["conversation_key"] is None

    def test_headerless_rows_and_the_cap(self):
        rows = [{"row_number": i, "values": [f"v{i}", "x"], "row": {}} for i in range(2, 15)]
        event = GoogleSheetsNode.resolve_agent_event({"rows": rows, "new_row_count": 13, "headers": []})
        text = event["text"]
        assert "Row 2: v2, x" in text
        assert text.count("Row ") == 10
        assert "…and 3 more rows" in text

    def test_single_row_title_empty_and_unrecognized(self):
        one = GoogleSheetsNode.resolve_agent_event({"rows": [{"row_number": 9, "values": ["a"], "row": {"H": "a"}}], "new_row_count": 1, "headers": ["H"]})
        assert one["title"] == "New row 9"
        assert GoogleSheetsNode.resolve_agent_event({"rows": [], "new_row_count": 0, "headers": ["H"]}) is None
        assert _is_base_shape(GoogleSheetsNode.resolve_agent_event(UNRECOGNIZED))


class TestGoogleDrive:
    def test_one_line_per_change_with_folders_and_removals_told_apart(self):
        output = {
            "changes": [
                {"kind": "drive#change", "type": "file", "fileId": "f-1", "removed": False,
                 "file": {"id": "f-1", "name": "Q3 plan.docx", "mimeType": "application/vnd.google-apps.document",
                          "modifiedTime": "2026-09-12T09:00:00.000Z", "parents": ["p-1"], "trashed": False}},
                {"kind": "drive#change", "type": "file", "fileId": "d-1", "removed": False,
                 "file": {"id": "d-1", "name": "Archive", "mimeType": "application/vnd.google-apps.folder",
                          "modifiedTime": "2026-09-12T09:01:00.000Z", "trashed": True}},
                {"kind": "drive#change", "type": "file", "fileId": "gone-1", "removed": True},
            ],
            "change_count": 3,
            "_webhook": WEBHOOK_META,
        }
        event = GoogleDriveNode.resolve_agent_event(output)
        text = event["text"]
        assert text.startswith("Google Drive: 3 changes")
        assert "- File changed: Q3 plan.docx (id f-1, application/vnd.google-apps.document, modified 2026-09-12T09:00:00.000Z)" in text
        assert "- Folder trashed: Archive (id d-1" in text
        assert "- Item removed: id gone-1 (no metadata" in text
        assert "get_file_metadata / download_file" in text
        assert "drive#change" not in text and "top-secret-token" not in text
        assert event["title"] == "3 Drive changes"
        assert event["conversation_key"] is None

    def test_single_change_title_and_cap(self):
        one = GoogleDriveNode.resolve_agent_event({"changes": [{"fileId": "f-2", "file": {"id": "f-2", "name": "notes.txt", "mimeType": "text/plain"}}], "change_count": 1})
        assert one["title"] == "File changed: notes.txt"
        many = [{"fileId": f"f-{i}", "file": {"id": f"f-{i}", "name": f"n{i}", "mimeType": "text/plain"}} for i in range(12)]
        text = GoogleDriveNode.resolve_agent_event({"changes": many, "change_count": 12})["text"]
        assert text.count("- File changed") == 10 and "…and 2 more changes" in text

    def test_empty_variants_deliver_nothing_and_unrecognized_falls_through(self):
        assert GoogleDriveNode.resolve_agent_event({"changes": [], "change_count": 0, "deduped": True}) is None
        assert GoogleDriveNode.resolve_agent_event({"changes": [], "change_count": 0, "message": "Save the workflow to activate it."}) is None
        assert _is_base_shape(GoogleDriveNode.resolve_agent_event(UNRECOGNIZED))


class TestCron:
    def test_raw_scheduler_tick_is_one_line_with_no_ids(self):
        output = {
            "schedule_id": "sched-1",
            "workflow_id": "wf-1",
            "user_id": "user-1",
            "node_id": "cron-1",
            "triggered_at": "2026-09-12T09:00:00.000Z",
            "payload": {"source": "cron_trigger", "node_id": "cron-1"},
            "_webhook": {**WEBHOOK_META, "headers": {"X-Cron-Schedule-Id": "sched-1"}},
        }
        event = CronTriggerNode.resolve_agent_event(output)
        assert event["text"] == "Scheduled run fired at 2026-09-12T09:00:00.000Z"
        assert event["title"] == "Scheduled run"
        assert event["conversation_key"] is None

    def test_execute_envelope_resolves_even_without_a_time(self):
        event = CronTriggerNode.resolve_agent_event(
            {"type": "cron-trigger", "status": "triggered", "timestamp": 1.0, "schedule_id": None,
             "workflow_id": "wf-1", "triggered_at": None, "webhook_id": "wh-1", "payload": {}}
        )
        assert event["text"] == "Scheduled run fired"
        assert "wf-1" not in event["text"]
        assert event["title"] == "Scheduled run"

    def test_unrecognized_shape_falls_through_to_base(self):
        assert _is_base_shape(CronTriggerNode.resolve_agent_event(UNRECOGNIZED))


class TestWebhook:
    def test_json_body_rides_with_method_and_query_but_never_headers(self):
        output = {
            "event": "order.created",
            "order": {"id": 4471, "customer": "Casey Example", "total": 129.5, "notes": None, "tags": []},
            "_webhook": {**WEBHOOK_META, "query_params": {"source": "crm", "empty": ""}},
        }
        event = WebhookTriggerNode.resolve_agent_event(output)
        text = event["text"]
        assert text.startswith("Webhook POST received\nQuery: source=crm\n")
        assert "empty=" not in text
        body = json.loads(text.split("\n\n", 1)[1])
        assert body == {"event": "order.created", "order": {"id": 4471, "customer": "Casey Example", "total": 129.5}}
        assert "top-secret-token" not in text and "x-signature" not in text and "wh-1" not in text
        assert event["title"] == "order.created"
        assert event["conversation_key"] is None

    def test_raw_text_body_is_clipped_and_titled_generically(self):
        event = WebhookTriggerNode.resolve_agent_event({"raw": "y" * 2000, "_webhook": {**WEBHOOK_META, "method": "PUT"}})
        assert event["text"].startswith("Webhook PUT received\n\n" + "y" * 1500 + "… [500 more chars]")
        assert event["title"] == "Webhook request"
        empty = WebhookTriggerNode.resolve_agent_event({"_webhook": {**WEBHOOK_META, "method": "GET"}})
        assert empty["text"] == "Webhook GET received\n(empty body)"

    def test_execute_envelope_and_unrecognized_fall_through_to_base(self):
        envelope = {
            "type": "webhook-trigger", "status": "triggered", "method": "POST",
            "headers": {"authorization": "secret"}, "query_params": {},
            "payload": {"hello": "world"},
        }
        event = WebhookTriggerNode.resolve_agent_event(envelope)
        assert json.loads(event["text"]) == {"hello": "world"}
        assert _is_base_shape(WebhookTriggerNode.resolve_agent_event(UNRECOGNIZED))


class TestTurnBudget:
    """A turn is bounded by construction: the worst realistic batch stays well
    under 4000 chars and the act hint is the last thing the agent reads."""

    CASES = [
        (GmailNode, lambda: {"emails": [_gmail_email(i, reply_text="w" * 5000, subject="s" * 200) for i in range(40)]}, "reply_to_email_message"),
        (OutlookMailNode, lambda: {"value": [{"changeType": "created", "resource": f"/me/mailFolders/inbox/messages/{'m' * 150}{i}"} for i in range(60)]}, "reply_to_email_message"),
        (GoogleCalendarNode, lambda: {"events": [_gcal_event(i, description="d" * 5000, attendees=[{"email": f"p{j}@example.com"} for j in range(80)]) for i in range(30)]}, "fetch_calendar_event"),
        (GoogleFormsNode, lambda: {"responses": [{"responseId": f"r-{i}", "answers": {f"q{j}": {"textAnswers": {"answers": [{"value": "a" * 3000}]}} for j in range(40)}} for i in range(10)]}, "get_form_metadata"),
        (TypeformNode, lambda: {"form_response": {"form_id": "frm", "definition": {"title": "t", "fields": []}, "answers": [{"type": "text", "text": "t" * 3000, "field": {"id": f"f{i}", "ref": f"r{i}"}} for i in range(40)]}}, "get_form_responses"),
        (GoogleSheetsNode, lambda: {"rows": [{"row_number": i, "values": [], "row": {f"col{j}": "v" * 500 for j in range(40)}} for i in range(30)]}, "read_sheet_data"),
        (GoogleDriveNode, lambda: {"changes": [{"fileId": f"f{i}", "file": {"id": f"f{i}", "name": "n" * 255, "mimeType": "m" * 100, "modifiedTime": "2026-09-12T00:00:00Z"}} for i in range(50)]}, "get_file_metadata"),
        (WebhookTriggerNode, lambda: {"items": [{"k": "v" * 200} for _ in range(200)], "_webhook": {**WEBHOOK_META, "query_params": {f"q{i}": "x" * 300 for i in range(20)}}}, "Webhook POST received"),
    ]

    def test_worst_case_batches_stay_bounded_with_the_hint_intact(self):
        for node_cls, build, hint in self.CASES:
            text = node_cls.resolve_agent_event(build())["text"]
            assert len(text) < 4000, f"{node_cls.__name__}: {len(text)} chars"
            assert hint in text, node_cls.__name__
            if node_cls is not WebhookTriggerNode:
                assert hint in text[-400:], f"{node_cls.__name__}: the act hint was cut off"

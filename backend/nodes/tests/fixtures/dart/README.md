# Dart contract evidence

Provider OpenAPI: https://app.dartai.com/api/v0/public/schema/, version 1.0.0.
SHA-256: `1f9acd5f5a47ddd2bc58c8c6e969ffb99c076c1de26c9837ef98da71e84224d2`.
The catalog pins the provider document unchanged. No existing working account or
API token was available to this run; no provider sign-in or live writes were made.

`on_event` uses POST /webhooks (wrapped item with url, eventKinds, enabled and
title) and DELETE /webhooks/{id}. The nine event types and payload fields are
in the contract's webhooks section. The user's workspace signing secret comes
from Dart Settings > Webhooks, as documented at
https://help.dartai.com/en/articles/9024895-webhooks.

The provider's official SDK documents Dart-Signature and HMAC-SHA256 hex over
the raw body, with the entire secret encoded as UTF-8 (no prefix stripping):
- https://github.com/its-dart/dart-tools/blob/3bb2e3514d63c95157bfed8753cc48e183befaf3/dart/server.py
- https://github.com/its-dart/dart-tools/blob/3bb2e3514d63c95157bfed8753cc48e183befaf3/dart/webhook.py

The current SDK server uses data.model even for create/delete/comment events;
the OpenAPI specifies direct data for these events. The parser accepts both
published shapes, and uses data.model for update, status and assignee events.
No spec exception is necessary because both shapes work.

`conformance-manifest.json`, `conformance-report.json` and
`conformance-verdict.json` record 18 existing operations plus the new trigger,
registration/unregistration, and delivery of all nine contract events (only the
selected event proceeds). The verdict is ready with no blocking findings and
on_event passed. Four generated-response parser advisories remain: get_me
correctly rejects isLoggedIn=false; list operations reject unrelated next-page
URLs. These are generated fixture limitations, not documented API failures.

`events.json` contains values generated from the pinned webhook schemas,
explicitly synthetic rather than provider-authored examples or live recordings.
The tests cover every schema event and the SDK's documented model wrapper,
selection, signatures (including altered body and wrong/missing secret),
registration and cleanup, and human-readable agent context with action IDs.
`transport.json` contains the existing synthetic operation regressions.
No input overrides, response witnesses or spec exceptions were used.

The icon is the company's app icon from its official brand kit, with its own
purple tile retained. Its source and unchanged drawing are recorded in
frontend/public/icons/dart.svg.provenance.json; icon_check passes.

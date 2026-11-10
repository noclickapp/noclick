# Mateo contract evidence

The integration targets the provider-published legacy API v1 OpenAPI 3.1 document,
version `1.0.0`: https://docs.getmateo.com/openapi.json.
The pinned document's SHA-256 is
`73106df45bd352e0f27b4b59740ca182d15d504b35a0370291220e1d35ce93fe`.

`events.json` copies the complete JSON examples for `contact.created`,
`contact_details.updated`, `contact.deleted`, and `form_submission.completed`
from https://docs.getmateo.com/webhooks/webhook-events-reference.
Each fixture includes its source URL. Conversation event examples on that page
contain prose placeholders instead of complete JSON; this integration does not
invent replacements for them.

Webhook registration uses `POST /webhook`, passing a client-generated UUID so
that a documented empty acknowledgement still leaves a known ID for cleanup.
Unregistration uses `DELETE /webhook` with an exact `id=eq.<uuid>` filter.
https://docs.getmateo.com/webhooks/setting-up-webhooks documents optional
user-configured headers and no delivery signature. This integration uses the
unsigned mode and the platform's private webhook URL as a capability.

The provider now marks this API deprecated:
https://docs.getmateo.com/introduction. This implementation deliberately matches
the pinned legacy contract. Conformance is offline OpenAPI evidence, not a live
account test. API-key authentication and filtering semantics are documented at
https://docs.getmateo.com/introduction and
https://docs.getmateo.com/concepts/read.

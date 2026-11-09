# Follow Up Boss documented fixtures

`webhook_events.json` copies the provider's webhook guide payloads and the
`webhookEvents/:id` example for `peopleUpdated`; every entry carries its source.
`documented_responses.json` copies published API response examples. JSON syntax
is normalized for trailing commas, the ellipsis after the first listed person,
and the mismatched closing braces in the note's reactions. No documented keys
or values are replaced or rebound to test inputs.

The pinned contract's `PUT /tasks/{id}` example contains `"completed:" null`
(invalid JSON). Its current docs show the same typo:
https://docs.followupboss.com/reference/tasks-id-put
The node rejects that malformed response. The conformance report records this
as parser advisories for `update_task` and `complete_task`; no task-update
response witness is invented to remove them.

Webhook signing follows:
https://docs.followupboss.com/reference/webhooks-guide#verify-the-request
It is hex HMAC-SHA256 over **base64(raw body)** with the registered X-System-Key,
not an HMAC over the raw body. The harness's signature template cannot express
that body transform. Integration tests verify the documented algorithm for all
five copied events and reject modified bodies, wrong secrets and raw-body HMACs.

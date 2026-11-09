These are Shipmondo's decoded webhook examples copied from
https://shipmondo.dev/docs/webhooks/resources-and-actions on 2026-11-10.
All actions for a resource share its documented payload format.

The transport is `{ "data": "<JWT>" }`, verified with HS256 using the key supplied
at registration, as documented at
https://shipmondo.dev/docs/webhooks/requirements-and-structure.
The tests sign these provider examples with a test-only key, check both object
and JSON-string JWT claims, and reject tampered tokens and unsigned payloads.

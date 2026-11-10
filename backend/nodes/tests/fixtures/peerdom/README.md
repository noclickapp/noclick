The response bodies in `published_examples.json` were copied verbatim from the
JSON samples rendered at each entry's official `source` URL on 2026-11-10.
They are published documentation examples, not live account recordings. The
null response for delete_peer denotes the contract's 200 with no response body;
the documentation renders error-response samples but no success body there.

Contract: Peerdom Public API 0.10.0, https://api.peerdom.org/v1/docs,
SHA-256 `6a0b5469d5c5dbc4189ad2838cdd0968877e2cc36b6bcaa2577bd6cff52391db`.
The API contract's server is https://api.peerdom.app/v1.

Known contract defect: the 201 response for `assignRole`
(`POST /roles/{roleId}/peers`) is a `oneOf` between `Holder` and a bulk-summary
object. Both object schemas allow arbitrary extra properties and neither
requires any field. Every single-holder response shown in the documentation
therefore matches both alternatives, violating `oneOf`. The node accepts the
published single-holder object unchanged; its request is contract-valid, and
the mock test exercises the exact published body. See:
https://api.peerdom.org/v1/docs#operation/assignRole.
The external conformance catalog contains that same response as a docs witness;
the immutable contract is left intact.

No trigger is offered: the pinned contract and current official API docs have
no webhook/callback registration API and no list endpoint with a creation/update
time filter or sort parameter. Although some response objects contain timestamps,
list pagination is only limit/offset (plus entity-specific filters). No event
payload or time ordering is inferred from the presence of those fields.

# ISN JSON API contract evidence

Source: https://json.inspectionsupport.net/openapi.json
Version: 1.1.0
SHA-256: 71bc636a50eecc3dfd0284ed033f12a0027cbe167ed1b40f7e348528915e24c8

The pinned document and the freshly downloaded official document have identical
bytes. All endpoints reference `UserSecurity`, but `components.securitySchemes`
is absent. The conformance request validator therefore raises
`KeyError: 'UserSecurity'` for every operation. Its introduction documents
Basic authentication with API keys as username and password. The integration
sends exactly that scheme over HTTPS; it does not amend the specification or
bypass validation. This is a provider contract defect (category d).

The specification also gives `POST /order_notes/{oid}` and
`POST /order_notes/{id}` different create/update semantics even though their
URLs are indistinguishable. Note mutations are omitted until ISN resolves this
ambiguity; reading order notes is supported.

The transport fixture `requests.json` is synthetic regression data, not a claim
of provider-authored responses or live-account testing. Each of the 22 actions
maps to one documented operation. Lists preserve the API arrays without
inventing pagination. Writes report provider acknowledgment with
`readback_verified: false`; transport failures leave the write outcome unverified.

## Webhook trigger evidence

Registration and deletion use the provider's REST API OpenAPI version 8665:
https://developer.inspectionsupport.com/specs/isn/openapi.json
The REST surface uses the same Basic access/secret keys and company as JSON;
webhook management requires OWNER privilege. `rest-openapi.json` retains the
unchanged relevant operations and their referenced components from that pin,
with its full-document SHA-256. The conformance catalog holds the full document.

The delivery examples in `webhook-events.json` are copied verbatim from
https://developer.inspectionsupport.com/webhooks/ (order completion, status
change, and rescheduling). That page documents the common order-event shape,
the API subscription names versus payload actions, and `X-ISN-Signature`:
HMAC-SHA256 over `{timestamp}.{raw body}`, using the secret string as UTF-8,
with a five-minute tolerance. Registration explicitly requests signed, tracked
POST deliveries and stores the create-only secret. The trigger returns the
event ID for consumers to identify redeliveries; it does not promise exactly-once
delivery. Manual runs report no event. No live account was used.

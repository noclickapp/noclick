# Statuspage deterministic evidence

Official API reference and published OpenAPI: https://developer.statuspage.io/
API version: 1.0.0; OpenAPI 3.0.0.
Pinned spec SHA-256: `af2c43256acebe55cf9de199d19531273669eb6651b2b8e760643a62158a6dde`.

The provider publishes the spec in `spec.data` of the reference page's
`const __redoc_state` JSON. The catalog at `/root/fanout/catalog/statuspage`
contains `openapi.json`, `manifest.json`, the source `docs.html`, inputs,
witnesses, report, verdict and extraction/audit scripts. The spec is unmodified.

`responses.json` copies the complete displayed JSON response samples verbatim,
with a source URL for each operation. The documented HTTP 204 component deletion
has no response body. `operations.json` records documented inputs and independently
expected requests (including the API's top-level subscriber update body).

The unmodified provider spec rejects 14 of its own published samples:

- `Incident.metadata.type` is `Object` (capitalized), which is not an OpenAPI type.
- `Subscriber.components.type` is `string`, while its own example and displayed
  response are arrays of component IDs.

These defects are preserved. The conformance harness falls back to spec-valid
generated responses for those 14 operations; its empty HTTP 204 response has no
body source. Five operations use the documented response in the harness. The
mock tests additionally execute **all 20 operations** with the unchanged provider
responses, including the incident metadata and subscriber component arrays.

Connection evidence runs `list_pages`, which needs only the pasted API key,
and shows account-specific page names. A non-list response or missing/blank
page identity is an error, never an empty successful proof.

Each operation makes one provider request. List operations return a named
collection and `count` for that returned page, not the whole account. Callers
control pagination; subscriber pages start at zero. Other paginated lists start
at one. No automatic retries are made, including after rate limits or writes.

Maintenance uses `create_incident` with `status=scheduled` and both ISO 8601
timestamps. `update_incident` supports `in_progress`, `verifying` and `completed`.
The optional `deliver_notifications` is sent only when supplied; Statuspage's
default is true. Subscriber creation may send confirmation notifications.

The icon is the unchanged `statuspage/SVG/Statuspage_icon.svg` from the official
brand archive linked at https://atlassian.design/foundations/logos:
https://atlassian.design/assets/d7aacc201c59/logos/statuspage_app.zip . Its exact
SHA-256 and attribution are in `oss/overrides/scripts/asset-provenance.json`.

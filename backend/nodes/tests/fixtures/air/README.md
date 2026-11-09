# Air contract evidence

`openapi.json` is the unmodified provider document pinned by the integration
catalog (version 1.0.0, SHA-256 in `source.json`). Its original `servers` entry
is deliberately preserved. The provider publishes `api.air.inc` without an
HTTPS scheme, which OpenAPI interprets as a relative server path. The main
conformance harness consequently reports `No spec operation` for requests to
the documented origin. Air's own upload guide uses
`https://api.air.inc/v1/uploads`:
https://developer.air.inc/docs/upload-assets.md

The request tests independently match every action against the original
published method/path and validate query names and JSON bodies against those
schemas. They do not rewrite the pinned document or claim that the main
harness passed. The polling fixtures exercise fields declared by the two list
response schemas; they are schema-based test data, not live recordings or
provider-authored example responses.

The asset list is sorted by `coverVersion.updatedAt`, according to its
published description, but its response schema omits that field. Polling
fingerprints the returned metadata instead. Board polling also fingerprints
the returned row. A complete snapshot replaces the previous fingerprints in
one atomic state update; reverted edits, new items and scope changes are
covered. These triggers observe list-visible changes between polls, not every
intermediate edit or deletion. Neither schema identifies the person who made
an edit, so agent summaries do not invent an actor.

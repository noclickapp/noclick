# Personio contract evidence

The catalog is pinned by `manifest.json`: the original official v1 personnel,
v2 persons, v2 absences and v2 attendance specs, plus a deterministic combined
OpenAPI file. Bundling only namespaces local references, preserves security
requirements and prefixes v1 paths; it does not change provider constraints.
The complete catalog, its reproducible bundler, realistic inputs and witnesses
are in the run's `catalog/personio` directory.

`responses.json` records each request configuration, documented response and
provider source URL. `report.json` is the offline conformance harness result;
`verdict.json` is the audited deterministic verdict. No provider account was
used. The harness itself is intentionally not vendored.

There are 16 operations and 29 node tests. Every operation is tested with the
provider's documented response, including examples the official schema rejects:
the persons example uses lowercase `string` where its custom-attribute enum
requires uppercase, and the v1 create-time-off schema adds an extra envelope
around the documented response. The harness falls back to spec-valid generated
responses for these two; the node tests retain the original documented examples.
Attendance update/delete are documented HTTP 204 responses with no body.

List operations return one page and expose the provider's pagination metadata.
Person listing and absence listing use v2, avoiding contradictory v1 list schemas
that require `data` to be both an object and an array. Get Time-Off accepts the
v2 UUID returned by the list. Create/Delete Time-Off use the documented v1
write endpoints, whose numeric IDs are distinct from v2 UUIDs. Attendance uses
v2 because v1 attendance endpoints retire on 31 January 2027.

Authentication is a user-pasted bearer token, supported by both versions and
valid for 24 hours. Credential instructions explain replacement after expiry.
Connection evidence lists account-specific persons with no required arguments.

## Asset source limitation

The requested official press/brand-page asset
https://www.personio.com/marketplace/personio-footer.svg returns HTTP 429 to curl.
The included unmodified wordmark instead comes from Personio's official
Developer Hub, with its exact URL and hash in asset-provenance.json. Acceptance
of that alternate official source, or replacement with an accessible press-page
asset, remains necessary to meet the requested merge bar exactly.

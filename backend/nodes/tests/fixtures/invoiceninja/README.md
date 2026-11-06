Invoice Ninja conformance evidence
=================================

The official OpenAPI spec is pinned by URL, revision, version, and SHA-256 in
`spec_manifest.json`. The unmodified spec and catalog live outside the repository
at the requested `catalog/invoiceninja` location. `inputs.json` and
`witnesses.json` record their official source URLs.

Response fixtures project the provider-published OpenAPI response property
examples (fields without published examples are omitted). They are documented
example values, not live-account captures. The additional full legacy clients
response is copied from the developer guide; its trailing display glyph falls
outside the JSON object and is excluded. Every operation is tested for its
actual method, URL, header authentication, query/body serialization and output.

`report.json` is the unedited full-witness harness report. `verdict.json` is the
source-audited verdict: ready, 20/20 requests and documented-example parsers,
zero skips, fixture errors, generated-only responses or advisories. The spec
expresses authentication as required header parameters rather than OpenAPI
security schemes, so auth_checked is zero; the harness checks required headers
and the mock tests assert X-API-TOKEN and X-Requested-With explicitly.

Lists return one page and preserve provider metadata. `updated_at` supports
incremental sync; callers follow meta.pagination explicitly. Creates/updates do
not retry writes automatically. Payment creation records an existing payment;
it does not initiate a charge. Quote conversion calls the documented POST bulk
operation with one quote ID. No live credentials are needed for these tests.

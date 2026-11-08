# Dart contract evidence

Provider contract: https://app.dartai.com/api/v0/public/schema/, version 1.0.0.
SHA-256: `1f9acd5f5a47ddd2bc58c8c6e969ffb99c076c1de26c9837ef98da71e84224d2`.

The conformance manifest, report and verdict capture the 18 implemented operations
against that pinned provider contract. Every operation maps to one provider operation
and makes one request. All 18 requests, authentication placements and response schemas
were checked; none were skipped. The verdict is ready with no blocking findings.

The report contains four advisory generated-response parser failures: the generated
`/me` object has `isLoggedIn: false`, and generated list continuation URLs use the
schema's unrelated example.org host. The node refuses these as an unconfirmed account
or an invalid continuation. These are recorded advisories, not spec defect claims.
No authored provider-response witnesses, input overrides or spec exceptions are used.
All response witnesses in this run are generated from the provider schema.

`transport.json` and the node tests use explicitly synthetic data to exercise the
real dispatch and connection-evidence seams, wrapped writes, ID consistency,
boolean filters, empty-array clearing, pagination and provider errors. They are
local regressions, not provider-authored examples or live-account evidence.

Authentication follows https://www.dartai.com/features/api-libraries-and-cli:
paste the existing API token from Dart settings; requests use Bearer authorization.
No OAuth registration, sign-in or live provider writes were performed.

The icon is the unmodified apple-touch-icon linked by https://www.dartai.com/;
its exact asset URL and hash are in the integration's provenance sidecar.

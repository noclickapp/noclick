# Polygon contract evidence

The original `spec.json` is Polygon's Swagger 2.0 contract, version 1.0.0,
SHA-256 `98450e2e355d55da6ad72c699d04e166e330cf8292c0d72d2804ab90acb0cffb`,
published at https://api.apis.guru/v2/specs/polygon.io/1.0.0/swagger.json.
Its declared original source is https://polygon.io/docs/swagger.json.

`openapi.json` is the lossless OpenAPI 3 conversion produced solely by:

```sh
npx -y swagger2openapi@7.0.8 spec.json -o openapi.json
```

`manifest.json` retains the original pin and pins the converted bytes used by
openapi-core. All ten paths in this contract are GET operations. There is no
write operation or account identity endpoint. Connection evidence lists the
available currencies with `proves="reachability"`.

The full-witness harness report and audited verdict show eleven passing requests (including the poll trigger),
eleven authentication checks, no skipped operations, no fixture errors and no
blockers or advisories. All eleven response witnesses were generated from the
contract: there are no provider-authored examples in this contract. This is an
offline contract-conformance verdict, not live API or plan-entitlement testing.
The sibling `synthetic_cases.json` is explicitly synthetic regression-test data.

The original provider Swagger URL redirects to Massive and returns 404 as of
2026-11-09. No current-docs response override or spec-defect waiver was used.

## Company polling trigger

`on_new_or_updated_company` uses `GET /v1/companies?sort=-updated&page=1&perpage=100`.
The pinned contract documents generic field sorting with a `-` descending prefix,
pagination, and Company `symbol`, `name`, and `updated` properties. The trigger
watches a configurable recent window (1–1,000 records), baselines on arming,
and identifies versions by the pair `(symbol, updated)`. It emits no historical
records on the first poll and no repeat events for unchanged versions. More
updates between polls than fit in the selected window can be missed; choose
an appropriate window and schedule. The contract contains no webhook API.

The poll response is the documented Company array, not an invented webhook
payload. The conformance harness generates its witness from that response
schema. Unit-test values remain explicitly synthetic regression data; neither
these tests nor the offline verdict establish live legacy-endpoint availability.

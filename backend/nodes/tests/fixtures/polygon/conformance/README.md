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

The full-witness harness report and audited verdict show ten passing requests,
ten authentication checks, no skipped operations, no fixture errors and no
blockers or advisories. All ten response witnesses were generated from the
contract: there are no provider-authored examples in this contract. This is an
offline contract-conformance verdict, not live API or plan-entitlement testing.
The sibling `synthetic_cases.json` is explicitly synthetic regression-test data.

The original provider Swagger URL redirects to Massive and returns 404 as of
2026-11-09. No current-docs response override or spec-defect waiver was used.

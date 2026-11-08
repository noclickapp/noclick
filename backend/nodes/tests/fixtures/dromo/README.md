# Dromo conformance evidence

`openapi.json` is the unmodified provider contract from
https://developer.dromo.io/api-reference/openapi.json, version 1.0. Its SHA-256
and synthetic credential are in `manifest.json`. `inputs.json` contains the
provider's documented JSON examples for the three write operations that need
curated inputs. `report.json` and `verdict.json` record 14 checked operations,
14 passing requests, no blockers and no advisories.

With the staging conformance suite available under `backend/tests/conformance`,
reproduce from `backend/`:

```sh
CONFORMANCE_WITNESS=full CONFORMANCE_CATALOG=nodes/tests/fixtures/dromo \
  python -m tests.conformance.harness --provider dromo --output /tmp/dromo-report.json
python -m tests.conformance.verdict /tmp/dromo-report.json nodes/tests/fixtures/dromo
```

This is offline request/authentication-placement and generated-response parser
coverage; no live account or live write was used. `contract_cases.json` contains
request/response regression cases for the node's transport tests. Import creation
returns a job; deletion output acknowledges the provider response, and does not
claim a follow-up read verified absence.

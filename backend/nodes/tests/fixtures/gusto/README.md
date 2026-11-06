# Gusto response provenance

`responses.json` preserves the official response examples without replacing their values. Each entry records the endpoint's source URL, HTTP status, and the documented values used to exercise it. Delete Employee documents HTTP 204 with no response body.

The OpenAPI catalog is pinned outside the repository at `/root/fanout/catalog/gusto`: `openapi.json`, its SHA-256 manifest, the untouched source endpoint Markdown files, and reproducible lossless-union script. It uses Gusto API version `2026-06-15`. The catalog also contains `inputs.json`, `witnesses.json`, `report.json`, and the deterministic verdict.

The official examples have these inconsistencies with their own response schemas:

- Employee responses use `jobs[0].state_wc_covered: ""`; the schema permits a boolean or null.
- List Payrolls uses `partner_owned_disbursement: ""`; the schema permits a boolean or null.
- List Time Off Requests uses `approver: ""` for a pending request; the schema permits an object or null.
- Some payroll examples also contain the incompatible empty-string disbursement value; other official payroll examples validate.

These examples remain unchanged in the mock tests and catalog witnesses. The conformance harness checks every actual request against the official operation. It uses a spec-valid generated response when no authored example validates, and a different authored example where one validates. Its verdict reports the exact authored/generated counts. The mock tests independently confirm that every operation parses the provider's documented responses, including these inconsistent examples.

Authentication is a pasted company-level Bearer access token, with demo and production origins selected explicitly. These tokens expire after two hours. NoClick does not perform OAuth authorization or refresh for this integration; each operation declares its required token scopes and the credential instructions explain replacement.

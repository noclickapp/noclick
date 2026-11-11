# WeGA contract evidence

These files retain the offline request/response conformance result for the new integration.
The harness supplies schema-generated response witnesses; this is OpenAPI evidence, not live-recorded account evidence.

- Provider contract: https://weber-gesamtausgabe.de/api/v1/openapi.json
- OpenAPI 3.0.1, API version 1.1.0
- Pinned contract SHA-256: `2a86f36875ae55a05e0b0da0bd201fab6b5cdaebcfaffce2ac6f26eb853e3e4b`
- Verdict: ready, 15/15 operations checked; no skipped operations, blocking items or spec defects.
- Authentication: none, explicitly stated by the contract. The empty credential object in the external catalog is only the harness's public-API input; no credential class or account connection is created.
- Connection evidence: `get_application_status`, public reachability only.

The provider's [API documentation](https://weber-gesamtausgabe.de/en/Help/API_Documentation.html) links this REST contract. Neither defines webhook registration or document-created/updated time filtering. `/documents/findByDate`, `/documents/otd`, and repository-item `sortdate` concern historical source/event dates, not when a record entered or changed in WeGA. No new/updated-record trigger is asserted.

All fifteen published operations are exposed, including fresh ID allocation and the session-preferences POST. ID allocation does not create a document. Preferences are local to the request's HTTP session; no saved browser session or account preferences are promised.

Run with the externally supplied conformance suite and immutable catalog:

```sh
CONFORMANCE_WITNESS=full CONFORMANCE_CATALOG="$C" python -m tests.conformance.harness \
  --provider weber-gesamtausgabe --output "$C/report.json"
python3 verdict.py "$C/report.json" "$C"
```

SumUp deterministic contract evidence
====================================

Contract: [official SumUp OpenAPI 1.0.0](https://raw.githubusercontent.com/sumup/sumup-developer/240a391e1c6c2b1d55d3803b0a22ba09958ef877/openapi.json)

- Provider repository commit: `240a391e1c6c2b1d55d3803b0a22ba09958ef877`
- Spec SHA-256: `38138e18acd16cdebb52a6e8dc309380c9f185109eb2e3ce845090fbd957ba1f`
- Authentication: API key in `Authorization: Bearer …`, created at https://me.sumup.com/settings/api-keys
- Connection evidence: authenticated memberships expose each merchant resource's ID and account name. The same call populates the merchant picker. No OAuth scopes are requested.

`responses.json` records each operation's documented inputs, independently specified request method/path/query/body, response status/body and immutable source URL. Whole response examples are copied from the pinned specification. Where it has no whole-response example, customer and merchant fixtures assemble its property examples; memberships use its required property examples and documented `accepted` status. Saved payment instruments use the component example. Deactivating a payment instrument has the documented empty HTTP 204 response.

The external conformance catalog contains the pinned spec, manifest (with `<token>`), inputs, witnesses and full report. The temporary harness is not vendored. With `CONFORMANCE_WITNESS=full`, all 18 operations made spec-valid authenticated requests, no operation was skipped, and all 18 responses were checked. `verdict.py` returned `ready: true`, zero blocking findings and zero advisories: 17 authored parser witnesses plus the documented empty response (reported as `generated_only: 1`).

Offline tests also exercise full and partial refunds, nested customer updates, hosted-checkout boolean handling, repeated query filters, escaped path segments, merchant picker pagination, the connection-evidence seam, error envelopes, provider rejections, secret redaction, transport failures and invalid inputs. These are contract and mock checks; they do not claim live SumUp account validation.

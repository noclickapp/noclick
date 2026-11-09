Bloom Growth v1 evidence

- `requests.json` contains synthetic offline fixtures for the 25 implemented operations, with exact methods, paths, JSON bodies and case-sensitive query names.
- `conformance/openapi.json` is the unmodified provider contract from https://app-next.bloomgrowth.com/swagger/v1/swagger.json, version v1, SHA-256 `b7c9f4dfefa9790a7fee0a4d636330aa41917a7297cbb89390a60112722f5ad7`.
- `conformance/manifest.json` supplies a fake manual token, the node type and the contract's origin. No account credentials are stored here.
- `conformance/report.json` and `conformance/verdict.json` record 25 checked operations, 25 accepted requests, no skips, blockers or advisories. Responses are generated from the contract; this is offline contract conformance, not live-account testing.

Run the separately supplied conformance harness from `backend/` with:

```sh
CONFORMANCE_WITNESS=full CONFORMANCE_CATALOG=nodes/tests/fixtures/bloom-growth/conformance python -m tests.conformance.harness --provider bloom-growth --output /tmp/bloom-growth-report.json
python -m tests.conformance.verdict /tmp/bloom-growth-report.json nodes/tests/fixtures/bloom-growth/conformance
```

The node accepts an existing bearer token as documented at https://help.bloomgrowth.com/en/all-about-the-bloom-growth-api and https://app-next.bloomgrowth.com/faq/GenerateTokenInstruction. Tokens expire after two weeks. The integration does not request or store a person's login password, generate tokens, or refresh them. All node operations target the origin hosting the pinned v1 contract, `https://app-next.bloomgrowth.com`.

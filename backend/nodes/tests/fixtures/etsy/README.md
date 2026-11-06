# Etsy deterministic evidence

The node exposes 20 one-request operations against Etsy Open API v3. The pinned
provider contract is `https://www.etsy.com/openapi/generated/oas/3.0.0.json`,
version `3.0.0`, SHA-256
`e77a9b2a4ed4c2e1230b2de7cd474cfb3f64772fe8bae7b481440a2493d310e0`.
The downloaded official spec was fetched again when resuming; its hash matched.

`responses.json` has a fixture for every operation. Every entry links its exact
response schema and explicitly marks its body as **schema-generated**, not a
provider-authored response or live capture. The official spec has no literal
response examples. Conformance reports therefore correctly count 20
`generated_only` operations and zero `authored_parser_ok` operations.

Realistic request examples come from Etsy's own tutorials:

- https://developers.etsy.com/markdown/tutorials/listings.md
- https://developers.etsy.com/markdown/tutorials/shopmanagement.md
- https://developers.etsy.com/markdown/tutorials/fulfillment.md

The external catalog retains the immutable spec, manifest with fake credentials,
inputs, empty authored witnesses, reports and verdicts. The conformance overlay
is temporary and is not committed. Run the mock tests with:

```sh
cd backend
python -m pytest nodes/tests/test_etsy_node_mock.py -q
```

The normal harness enriches failing request inputs and reruns the provider. A
second run with `run_provider("etsy", enrich=False)` keeps the tutorial inputs
unchanged. Both reports must be read together; a single-image enrichment is not
evidence that the documented multi-image request matches Etsy's spec.

The two known form-array encoding discrepancies are recorded in
`spec-mistakes.json`, with current official documentation URLs. Neither the node
nor the pinned provider spec is altered to conceal these discrepancies.

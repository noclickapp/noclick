Remote fixture sources

- `operations.json` pins each action's single HTTP method, route and provider operation ID. Config values are examples copied from Remote's published OpenAPI, version 0.1.0, SHA-256 `8971e29d7e4da53934d57ad44e6e452367eddc4b8ca5c10b94282e90f7478836`: https://gateway.remote.com/v1/docs/openapi.json. The timeoff_days array is serialized as JSON for the workflow's text editor; the request sends the original array.
- `events.json` contains the eight unmodified webhook request examples from that document's `webhooks` section.
- The signature regression in `test_remote_node_mock.py` copies the raw request, timestamp, public example signing key and expected digest from https://developer.remote.com/docs/verifying-webhooks.

The customer token is entered manually following https://developer.remote.com/docs/authorization-for-customers. ra_test_ tokens select the documented sandbox host. All tests use HTTP mocks; no live Remote account or token is used. List operations return one page and preserve Remote's full response, including pagination metadata. Trigger deliveries contain resource IDs, so agent turns describe the event and name the read operation that retrieves its details.

Pinned-spec caveat: `CreateApprovedTimeoffParams` sets `additionalProperties: false` at its root while declaring all request properties only in `allOf`. A standards-based validator therefore rejects even Remote's own example as additional properties. The node sends the documented fields unchanged; the official endpoint reference lists those fields as accepted/required: https://developer.remote.com/reference/post_v1_timeoff. This is recorded as the sole conformance spec defect, rather than changing the pinned contract.

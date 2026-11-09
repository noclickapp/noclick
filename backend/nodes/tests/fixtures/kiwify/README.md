# Kiwify contract fixtures

`responses.json` preserves the successful response examples from Kiwify's
published public API contract, version 1.0.0:
https://docs.kiwify.com.br/api-reference/openapi.json
SHA-256: c377e7efc7e6de91c587c946a60a9c12dfaf53c286cd985f68e9b73557deaa98

Each case records its provider reference URL and the expected native request.
Tests exercise all 22 operations through the node factory with an offline HTTP
transport; they do not use a real account or claim live account verification.
The pasted bearer token needs the permissions recorded in `kiwify_operations.py`
and must be replaced after it expires. No browser OAuth flow is involved.

The following published examples contradict the same contract's response schema:

- https://docs.kiwify.com.br/api-reference/products/single:
  `links[0].custom_name` and `event_settings` are null, but the schema declares
  non-null string and object types respectively.
- https://docs.kiwify.com.br/api-reference/events/list:
  `data` is an object containing ticket totals and `participants`, but the
  shared `PaginatedResponse` schema declares `data` as an array.

The node preserves both published shapes. Tests use these exact examples even
where the conformance harness must fall back to generated schema-valid data.
The node returns the provider payload under `data`, preserving provider status
and pagination, and removes webhook tokens from outputs. Each list call fetches
one page; `page_number` explicitly selects subsequent pages.

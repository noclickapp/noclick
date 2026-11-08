# E2B control-plane contract cases

`contract.json` records the selected methods, routes, completed status codes and
response top-level shapes from E2B's published OpenAPI 0.1.0:
https://raw.githubusercontent.com/e2b-dev/E2B/main/spec/openapi.yml

Pinned contract SHA-256:
`4408a23242fca56488097027e3c2648bca511ad5acb59708044f96c80cdeac00`.

The mock suite uses synthetic responses to exercise transport, paging, redaction
and failure handling. The independent conformance harness validates outgoing
requests and provider-authored examples against the full pinned contract.
Authentication is a personal dashboard API key in `X-API-Key`:
https://docs.e2b.dev/quickstart

Sandbox code execution, commands and files use the separate sandbox API and are
outside this integration's pinned control-plane contract.

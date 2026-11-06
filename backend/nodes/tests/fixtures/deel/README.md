# Deel documentation fixtures

`documented_responses.json` copies the response JSON from each operation's official Deel stable documentation, without editing the response to fit our parser. Every entry records its response and input source URLs. The personal-information PATCH returns HTTP 204 with no body; the test supplies an empty HTTP response for that endpoint.

The pinned upstream contract is the unchanged [HRIS OpenAPI](https://developer.deel.com/openapi/hris-endpoints.yaml), OpenAPI 3.1.0, info version 1.0.0 (stable API 2026-01-01). SHA-256: `609773fb4d24a2ca0ebf23dc3459403cd5aee1475e87a66adbda9f7210fe45c9`.

The independent conformance catalog is stored outside the repository. The full harness validates all 17 requests and authentication against that contract. Fourteen operations use documentation responses in the harness. The upstream examples for list people, get person, and get person custom fields disagree with their response schemas, so the unmodified harness falls back to generated responses for those three; these mock tests additionally exercise their complete, unmodified documentation responses.

Custom-field updates are excluded: the upstream request schema's overlapping `oneOf` object branches reject its documented text value. The integration does not alter that schema or construct artificial values to bypass it.

For a manual connection check, generate an organization or personal API token in Deel under More → Developer → Access Tokens. Grant `people:read` for connection evidence and the endpoint scopes for actions being used, then paste it in the Deel credential form. Connecting reads the account's people and displays their names; no live account was used by these tests.

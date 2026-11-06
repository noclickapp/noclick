# Kajabi documented fixtures

These response bodies and write-request bodies are copied from Kajabi's own endpoint descriptions in its [OpenAPI 1.2.0](https://raw.githubusercontent.com/Kajabi/public_api_docs/1f378e1a90f07fbf12202e9c36852183aed00763/openapi.yaml).

Spec SHA-256: `03e632777e488824c9bcce3933d132f38c9d11b5d534a0db378e2204243c05fd`.

Each `responses.json` entry records its source, operation inputs, wire method/path, write body and documented response. Offer relationship mutations return a resource-identifier list; their response fixture is the provider's GET relationship example. The tests check HTTP serialization and parsing for all 20 operations without calling Kajabi.

The spec declares OpenAPI 3.1.1 but retains 3.0 `nullable: true` on several fields. Its full contact examples have `external_user_id: null`, and its full customer example has null `socials`, `last_request_at`, `last_sign_in_at` and `bounced_at`. These examples conflict with the published 3.1 response schemas. Keep them unchanged: mock tests exercise the documented bodies, and the conformance harness explicitly reports its generated response fallback for those four operations. The other sixteen responses validate directly from the provider examples. No schema or harness changes are needed.

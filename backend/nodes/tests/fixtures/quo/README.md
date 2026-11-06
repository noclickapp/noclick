# Quo contract fixtures

`responses.json` contains verbatim JSON from the success-response code blocks on
Quo’s rendered reference pages. Each entry records its source URL. No response
was constructed from the schema or modified to satisfy the node. Delete Contact
returns HTTP 204 with no body, so it has no response fixture.

`inputs.json` uses values documented on those pages. Its operation field is
NoClick’s discriminator. `contract.json` pins the official OpenAPI source,
version, SHA-256, operation mapping, and the audited readiness result.

Authentication is a raw API key in `Authorization`, without a Bearer prefix.
The API key shown in the manifest is a placeholder, not a live credential.
The offline tests exercise all 19 operations with httpx’s real serialization.
The external conformance harness and downloaded spec are intentionally unvendored.

Update Contact uses PATCH but replaces email, phone-number, and custom-field
lists. Supply each complete list to retain it; use an empty array to clear it.
The config help text repeats this provider-documented behavior.

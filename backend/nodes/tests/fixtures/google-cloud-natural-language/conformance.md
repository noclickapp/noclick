# Google Cloud Natural Language evidence

Evidence rung: **openapi** (Google Discovery converted to OpenAPI 3).

- Provider contract: https://language.googleapis.com/$discovery/rest?version=v1
- Version: v1
- Pinned OpenAPI SHA-256: `e33c77de8d62258de94ce44d2eb23959f75dccaa5e3b325c5d2037b920eab13b`
- Original Discovery SHA-256: `9ec326080ee7cc5947fa5d82d63de4f66049bebd433487e58caf3d89a5d4a4dd`
- Converter: google-discovery-to-swagger 2.1.0 + swagger2openapi 7.0.8.

All seven published endpoints are implemented, each with pasted-text and Cloud Storage variants. A fifteenth operation checks key acceptance through analyzeSentiment with fixed text. All operations make exactly one POST and preserve the provider JSON. Analysis consumes quota; these APIs expose no persistent document writes.

## Contract defect

The conversion declares only OAuth2 security and scopes. The original Discovery declares a `key` parameter, and Google's current authentication documentation explicitly supports API keys for Natural Language and recommends sending REST keys in `x-goog-api-key`:
https://cloud.google.com/docs/authentication/api-keys-use

The node follows that documented contract. OAuth consent scopes do not apply to API-key credentials. The conformance harness therefore reports authentication placement and scope mismatches; these are documented contract defects, not suppressed passes. Request body, route, method and response checks report no other defects. The published sentiment response is checked as a docs-authored witness; other responses use schema-generated witnesses. No working account/key was available to record live calls.

## Triggers

No triggers: the v1 documents resource exposes only seven synchronous analysis POST methods. It has no webhook registration, events or list endpoint that could be polled by created/updated time:
https://cloud.google.com/natural-language/docs/reference/rest/v1/documents

## Connection and icon

Manual connection requires only an API key and supplies its credential type by default. The fixed-text probe proves reachability, not an identity. API-key mode provides no principal for private Storage objects.

The icon is Google's current AI / Machine Learning mark, assigned to Cloud Natural Language API in the official product icon guide:
https://services.google.com/fh/files/misc/google-cloud-product-icons.pdf

The SVG comes from Google's category-icons.zip linked at https://cloud.google.com/icons; provenance records the archive entry, exact hash and viewBox crop.

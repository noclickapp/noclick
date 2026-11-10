# Domains-Index v1 evidence

The provider publishes a Swagger 2.0 contract at https://api.domains-index.com/v1/swagger.json.
`conformance/openapi.json` preserves the pinned original bytes. `openapi3.json` is a mechanical conversion using `npx -y swagger2openapi@7.0.8 openapi.json -o openapi3.json`; no patches were needed. The manifest pins both hashes and binds the relative server to the provider host.

The API has no write operations or webhook-registration endpoints. The node exposes 11 JSON reads, omitting the three download endpoints whose success media/schema the contract does not describe. Two scheduled triggers watch the date-filtered added/deleted feeds, establish a baseline, exhaust at most 20 pages of 50 domains, and deduplicate by domain plus the documented creation/update dates. Oversized feeds or repeated cursors fail before changing seen state; use list operations for bulk extraction. Omitted date watches the provider's latest update feed. This is a bounded poll, not a durable replay or delivery guarantee across missed update batches.

The harness uses generated schema responses, not a live license. Its repeated `next_page` fixture produces parser advisories on both poll operations: the node deliberately rejects cursor loops. The verdict accepts them as generated-only advisories. No response witness or event payload was invented or substituted. Local mock tests independently cover baseline, new-item delivery, pagination, deduplication, error handling and agent event text.

The contract declares api_key as a query parameter rather than a security scheme, so auth_checked is zero. Transport tests independently assert the key is sent only to documented endpoints and never appears in successful output or raised HTTP errors.

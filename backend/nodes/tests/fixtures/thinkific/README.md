Thinkific fixtures use the response property examples and request examples in the
provider's [official Admin API v1 OpenAPI](https://developers.thinkific.com/openapi/thinkific-admin-api-v1.yaml).
`requests.json` records the expected wire contract separately from the node's
route table. `responses.json` keeps the source URL with each operation.

Collection wrappers follow the documented `Get*Response`, `Meta`, and `Pagination`
schemas. Required numeric identifiers without an example reuse the documented ID
1; scalar arrays without examples remain empty. Empty update, bundle enrollment,
and purchase acknowledgements follow the documented status-only responses.

The provider's `ProductPriceResponse` examples contain null values for fields
that its schema does not mark nullable. The mock tests retain these documented
values to exercise parsing. The conformance harness rejects those example bodies
and uses its schema-generated product responses instead. Neither the published
spec nor these documented null values have been modified to make validation pass.

Authentication follows the provider's [API Access Token guide](https://support.thinkific.dev/hc/en-us/articles/38357676036887-Authorization-using-API-Access-Token):
`Authorization: Bearer <token>`, with no subdomain or additional API key.

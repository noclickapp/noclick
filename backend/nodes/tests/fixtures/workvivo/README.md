These response bodies are copied without changes from the Workvivo OpenAPI
examples at https://developer.workvivo.com/openapi/api-reference.json. The
`source` and `operation` fields identify their origin. `documented-inputs.json`
uses the corresponding documented list, page and draft identifiers/content.

The six conformance failures are contradictions in these fixed response examples:

- `list_spaces` and `list_articles`: the published examples are strings containing
  literal `{...}` placeholders, rather than valid JSON collection envelopes.
  https://developer.workvivo.com/guides/reading-data specifies a data array for
  successful list responses and an object envelope containing pagination.
- `find_page`, `update_draft_page` and `delete_draft_page`: the valid request uses
  `take=100`, but the fixed example reports `meta.pagination.take=10`.
  https://developer.workvivo.com/guides/reading-data documents take values 1–100,
  recommends take=100 for collection scans, and describes the response pagination
  as the current offset/page size. The draft inputs use page 1 in space 15 from
  the draft write examples. The fixed collection example instead contains published
  page 301 in space 112, so it cannot authorize those draft mutations even after
  correcting its page size. The API reference specifies that `space_id` filters
  the collection to that space.
- `create_draft_page`: the documented draft lives in space 15, but the fixed space
  detail response returns ID 1 for `GET /v1/spaces/15`.
  https://developer.workvivo.com/guides/reading-data explains that a detail read
  addresses the resource ID in its path. The draft location and the need to read
  current state before replacement/deletion are documented at
  https://developer.workvivo.com/guides/writing-data.

The regression tests assert rejection and no mutation for these exact examples.
They do not rewrite provider responses or relax tenant, pagination or draft checks.

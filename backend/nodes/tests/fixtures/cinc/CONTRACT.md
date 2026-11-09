# CINC contract and response evidence

Pinned API contract: https://public.cincapi.com/v2/docs/swagger/swagger.json,
`info.version: v1`, SHA-256
`bdabb295f36327d6e11de996f6b23fe0497c62c43f5dad1cf6bd03f01ae27d89`.

`documented_examples.json` contains the published response examples and input
values, with a source URL per operation. The transport tests replay every example
through the registered node and check the method, URL, authentication, query,
request body and parsed output. They also check paging, empty acknowledgements,
HTTP failures, malformed envelopes, route injection and the shared refresh seam.
These are offline contract tests; they do not establish a live connection.

## Published-contract contradictions

- `GET /site/me` has no response content or schema in Swagger, while the
  [account example](https://public.cincapi.com/v2/docs/#get-site-me) returns
  `body.id`, `body.username` and `body.roles`. The conformance harness therefore
  returns an empty body and reports a generated-response parser advisory. The
  node rejects an empty identity and parses the published account example.
- Swagger describes lists as bare arrays. Published examples instead wrap the
  records and paging in `body`: [leads](https://public.cincapi.com/v2/docs/#get-site-leads-2),
  [agents](https://public.cincapi.com/v2/docs/#get-site-agents),
  [notes](https://public.cincapi.com/v2/docs/#get-site-leads-lead_id-notes-2),
  [labels](https://public.cincapi.com/v2/docs/#get-site-leads-labels-all-2).
  The node accepts both shapes and preserves paging from the documented envelope.
  A bare array has no pagination metadata, so the output does not claim completion.
- Swagger describes bare resource objects with `additionalProperties: false`,
  whereas the published [lead](https://public.cincapi.com/v2/docs/#get-site-leads-lead_id),
  [agent](https://public.cincapi.com/v2/docs/#get-site-agents-agent_id-2),
  [note](https://public.cincapi.com/v2/docs/#get-site-leads-notes-note_id-2) and
  [label](https://public.cincapi.com/v2/docs/#get-site-leads-labels-label_id-2)
  responses use `body.<resource>` wrappers and sometimes include newer fields.
  Both bare records and documented envelopes are accepted without dropping fields.
- The [lead upsert](https://public.cincapi.com/v2/docs/#post-site-leads-2) and
  [label creation](https://public.cincapi.com/v2/docs/#post-site-leads-labels-2)
  examples wrap the identifier in `body`, unlike Swagger's bare identifier schema.
  Swagger also declares bodyless success for lead upsert (200), label apply/remove
  and label deletion, despite the examples' identifier/message responses.
  The node accepts empty acknowledgements and documented bodies; it does not
  interpret acknowledgement as a verified downstream side effect.

The harness may fall back to generated responses when these published examples
fail Swagger response validation. The direct example-replay tests exercise the
prose examples independently. No pinned contract bytes are altered.

## OAuth

CINC documents authorization-code OAuth and app registration through its
[integrations team](https://public.cincapi.com/v2/docs/#cinc-developer-sign-up).
The declaration uses the published
[authorize](https://public.cincapi.com/v2/docs/#cinc-obtain-users-consent),
[token](https://public.cincapi.com/v2/docs/#cinc-obtain-an-access-token) and
[identity](https://public.cincapi.com/v2/docs/#get-site-me) endpoints.
Scopes are declared per operation from the endpoint documentation. No client
credentials, account sign-in or live API access is included in this evidence.

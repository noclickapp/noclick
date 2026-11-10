# JSON2Video contract evidence

The integration targets the provider's published OpenAPI 2.0.0 document:
https://json2video.com/docs/v2/openapi.json
SHA-256: `2c2b3c17f4fe260d59e65421f7cf3a0024071e4c456b27a5850520e42e5a854b`.
No live account was used. Authentication is tested as `x-api-key`, as the
[official quickstart](https://json2video.com/docs/v2/getting-started/quickstart) documents;
the OpenAPI document does not declare a security scheme.

`responses.json` contains the provider's published response examples and their
source URLs. `movies.json` retains both the single-project and list examples.
The list example's literal `"movie object as above"` reference is expanded with
the preceding single-project movie object verbatim; no fields or values were
invented. Its original illustrative count of 25 is preserved.

## Documented contract contradiction

The [Create Movie page](https://json2video.com/docs/v2/reference/api-endpoints/movies-create)
shows `scenes: [{elements: [{type: "video", src: "https://example.com/video.mp4"}]}]`.
The pinned schema rejects `type` and `src` as additional properties through its
closed element `allOf` members. The node preserves the documented request. The
conformance catalog also exercises the page's template-and-variables request,
which passes request validation. This is a provider schema defect, not a reason
to remove documented rendering fields from the integration.

The media-folder schema's overlapping `oneOf` branches prevent generation of
an unambiguous synthetic response. Supplying the provider's documented response
resolves that fixture error; the node preserves both folder and tree responses.
Some media example URLs contain illustrative placeholders and cannot be used as
URI-valid conformance witnesses. Unit tests still parse those examples verbatim.
The subtitles endpoint has no published response example in the pinned contract.

## Triggers

[Movie status](https://json2video.com/docs/v2/reference/api-endpoints/movies-status)
documents date filtering, cursor pagination, `project`, `status`, `created_at`
and `url`. Polls traverse every page before recording seen project IDs; a short
page with `has_next: true` continues. A missing/repeated cursor stops without
advancing the baseline. First polls baseline rather than emitting history.

`on_new_movie` emits new project IDs, including pending renders.
`on_movie_finished` filters `done`, `error` and `timeout` before deduplication,
so a previously running render emits when it finishes. Both use a configurable
1–90 day creation lookback (default seven days); older projects are outside
that declared scope. Existing finished renders baseline on activation.

[Webhooks](https://json2video.com/docs/v2/reference/webhooks) are unsigned,
per-render export destinations or dashboard-saved URLs. No documented API exists to
register and unregister an account-wide subscription independently of creating
a movie, so these triggers use the documented date-filtered list instead.

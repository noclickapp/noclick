# Integration conformance harness

Runs every operation of a registered node with fake credentials against its
provider's pinned OpenAPI description, offline. Each outgoing request is
captured and validated by openapi-core (route, parameters, body, media type,
auth placement, OAuth scopes); the node then gets a response that is valid for
the spec and must parse it without an error envelope. No node code changes and
no socket opens. A pass is evidence that the requests match the published
contract, not that the integration works against the live service.

## Run it

Provider specs are never vendored in this repository. `CONFORMANCE_CATALOG`
names a catalog folder that supplies them. From `backend/`:

```sh
CONFORMANCE_CATALOG=/path/to/catalog python -m tests.conformance.harness \
  --provider example --output /tmp/example.json            # report mode
CONFORMANCE_CATALOG=/path/to/catalog python -m tests.conformance.harness \
  --provider example --output /tmp/example.json --strict   # fail on any finding
CONFORMANCE_WITNESS=full ...                                # also replay documented responses
python -m pytest tests/conformance -q                       # the harness's own tests
```

`--provider` is repeatable; without it every provider in the catalog runs.
Report mode exits nonzero on fixture errors (the harness could not build a
valid input or response); `--strict` also exits nonzero on node findings.
Without a catalog the CLI refuses to start. The harness's own tests use the
made-up API in `fixtures/catalog`, never a provider's spec.

## A catalog

```
catalog/
  manifest.json     provider -> node type, fake credential(s), spec pins
  <spec files>      the pinned bytes the manifest names
  inputs.json       optional: documented configs per operation or scenario
  witnesses.json    optional: documented responses per route
```

A manifest entry:

```json
{
  "example": {
    "node_type": "automation-example",
    "credential": {"credential_type": "example_api_key", "api_key": "<token>"},
    "file": "openapi.yaml",
    "sha256": "<sha256 of the unchanged file>",
    "version": "<the file's info.version>",
    "source_url": "https://provider.example/openapi.yaml"
  }
}
```

- Every load checks the file's sha256 and `info.version` against the entry.
  Remote `$ref`s are refused. Paths must stay inside the catalog folder.
- `<token>` anywhere in a credential becomes the harness's fixed fake token.
- `specs`, a list of `{file, sha256, version, source_url}`, replaces the single
  pin when an API family publishes several documents (a server API and an
  account API). Each keeps its own components and security.
- `server_url` binds a spec that declares no servers, or a whole-URL server
  variable with an empty default (`{apiBaseUrl}`), to the documented absolute
  URL, in memory only. The catalog credential's field of the same name
  (`api_base_url`) can bind the variable instead; a request never supplies its
  own server. Matching still checks scheme, host, port and base path.
- `auth_override`, `{"scheme": "basic"|"bearer"|"token", "source": "<docs URL>"}`,
  replaces the spec's security for placement checks only, where the spec
  declares none or the wrong one. The docs URL is required and recorded.
- `credentials` (named credential objects) with `operation_credentials`
  (operation -> name) gives exact operations their own credential; unmapped
  operations use `credential`. Unknown operations or names fail before any
  request, and the harness never retries with another credential.
- `includes` pins further files a spec references, below.

## Documented inputs and responses

`inputs.json` maps an operation to `{"config": {...}, "source": "<docs URL>"}`,
a whole documented config. It is applied on every pass and never enriched with
synthetic values. Without one, the harness generates a minimal config from the
node's Pydantic model and, when the spec rejects a request, reruns once with
spec-valid values in same-named config fields or `extra_params`.

`witnesses.json` maps `METHOD /spec/path` to `{"body", "source"}` (optional
`headers`, and a 2xx `status` where the spec's only success is `default`).
With `CONFORMANCE_WITNESS=full`, documented
witnesses and spec examples are tried before generated responses, and each
request records its `response_source` (`docs`, `spec_example`, `generated`).
Every response is validated against the spec before the node sees it.

### Query-specific responses

Keys may add a query, `METHOD /spec/path?query`, beside the bare-path fallback.
The query is an exact decoded multimap match: order and percent encoding may
differ, but extra parameters, repeated values and blank values matter. A
trailing `?` matches only an empty query. Equivalent selectors are rejected as
ambiguous, and an invalid explicitly selected example is a fixture error that
never falls back to another body.

### Independent scenarios

An `inputs.json` entry can name its node `operation` explicitly, so several
entries exercise one operation with independent inputs, fake credential
identities and response selections:

```json
{
  "get-project-page-a": {
    "operation": "get_project",
    "config": {"project_id": "project-a"},
    "source": "https://provider.example/docs/page-a",
    "credential": {"account_name": "account-a", "token": "<token>"},
    "witnesses": {
      "GET /projects": "page-a-project-catalog",
      "GET /projects/{projectId}": "page-a-project-detail"
    }
  }
}
```

The referenced entries must exist in `witnesses.json`, with unmodified
documented bodies and public `source` URLs. With an explicit `witnesses` map,
every request needs a selected witness and every selected body must validate:
no generated response fills a missing prerequisite, and documented bodies are
never rebound to a captured request's ids. Each scenario builds a fresh node
and reports as its own operation result with its `scenario` name.

## Pinned multi-file specifications

An entry (or one in `specs`) may add `includes`:

```json
{
  "includes": [
    {
      "file": "includes/groups.yaml",
      "sha256": "<sha256 of the unchanged file>",
      "source_url": "https://provider.example/openapi/groups.yaml"
    }
  ]
}
```

A relative `$ref` resolves against the referring document's `source_url`,
which must exactly match a pin; local filenames need not mirror the published
layout. Every include is hash-checked before bundling. Nested refs and JSON
pointer fragments resolve offline, recursive references become local pointers,
and a description's reference to a pinned Markdown or text file becomes its
text. HTTP(S), protocol-relative, absolute-path, unpinned and malformed
references stay forbidden. The main spec's bytes are never rewritten.

## Synthetic strings

`sample()` and `input_sample()` share bounded, deterministic string generation:
patterns are full matches within `minLength`/`maxLength`; URL, email, UUID,
date, date-time, hostname, IPv4, base64 (`byte`) and binary formats get values
of that shape. The validator sees an equivalent pattern for BMP `\u{...}`
escapes and ECMAScript named captures; Unicode property escapes, non-BMP
escapes, named backreferences, invalid syntax and exhausted synthesis budgets
are explicit blockers. Config generation also reads Pydantic field formats and
metadata (URL, email and date widgets, `x-code-language=json`, JSON-string
`contentMediaType`/`contentSchema`). Field names never imply a provider's
identifier format. A matching string cannot prove cross-field ordering, a
signed receipt or a coherent readback; those need documented inputs and
scenarios.

## Synthetic files

Inline file fields get the checked-in [minimal files](fixtures/README.md). The
generator recognizes `format: byte/binary`, `contentEncoding: base64`,
`contentMediaType`, `json_schema_extra` metadata, `*_base64`, and file or
content fields with filename or MIME siblings; multipart `encoding.contentType`
is evidence during enrichment. `format: data-url` or a `^data:` pattern asks
for a data URL, `byte` for encoded bytes, `binary` for bytes, literal string
content for UTF-8 text; hosted URL fields keep their URL shape. Only types the
declarations allow are chosen. Encoded content without type evidence,
conflicting filename/MIME declarations and unsatisfied constraints are fixture
errors: the harness never guesses an image, audio or document type. These files
make an input executable; they are never evidence of a provider's response.

## Merge verdict

`verdict.py` turns a report and its catalog into the verdict the integration
merge gate reads: a re-cut integration PR merges only when the verdict is ready
(or `postman-checked`, once Postman evidence lands), its CI is green and its
scope check passes. It blocks on any operation without a checked request, a
request the contract rejects, a fixture error, or a parser failure on a
provider-authored response; failures on generated responses are advisory.
JSON held in string fields counts by its values, and docs pages match by their
rendered text and JSON-escaped values.

```sh
cd backend
python -m tests.conformance.verdict "$CONFORMANCE_CATALOG/report.json" "$CONFORMANCE_CATALOG"
python -m tests.conformance.verdict REPORT.json CATALOG --no-audit   # offline
```

The source audit fetches each documented input's and witness's source page
(cached under `$CONFORMANCE_PAGES`, default `~/.cache/noclick-conformance/pages`)
and checks its values appear there. It is a command-line step: the tests use
fixed pages and never touch the network.

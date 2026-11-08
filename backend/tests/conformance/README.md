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

## Scalar parameter unions

Parameter `oneOf`/`anyOf` alternatives and OpenAPI 3.1 type lists may contain
several non-null scalar types (string, integer, number, boolean). Input sampling
uses the documented example or default when available, then the first member
deterministically. After normal
style deserialization, casting tries each member and validates the candidate
against the complete original schema, including enum, bounds and patterns.
Mixed scalar/object/array and unconstrained parameter unions remain blockers.
JSON request bodies are never parameter-cast. Wildcard request content keys select their
schema through openapi-core; decoding uses the captured concrete Content-Type,
so application/json under application/* is still checked against that schema.

Multipart decoding preserves each part's bytes and Content-Type, including
repeated file parts. Binary fields validate as bytes; structured and text parts
use their actual media type and charset, with declared `encoding.contentType`
constraints checked. OpenAPI 3.1 `string/binary` schemas use the same bytes
convention as openapi-core's OpenAPI 3.0 validator for request files and binary
responses. Other string schemas remain strict, and the original schema still
checks constraints on the decoded body.

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

## Postman example replay

Collections use `format: postman` and the same immutable file, hash, version
and source pins. Every saved response is replayed as published UTF-8 text,
without JSON reserialization or variable substitution, including error statuses
and invalid JSON. Since the saved text is already decoded, replay drops
`Content-Encoding` and any `Content-Length` that differs from the replayed byte
length. HTTP clients frame the resulting body; all other headers retain their
published values and duplicates. A node still has to parse every saved example
and pass its own response guards.

Only `:name` and `{{name}}` path segments are variable matches. Single braces
are literal URL text, encoded in a path, and a `{dc_id}` host cannot be bound by
catalog server overrides or by the outgoing request. See Postman's
[path-variable matching](https://learning.postman.com/docs/tests-and-scripts/write-scripts/postman-sandbox-reference/pm-mock/),
[variable substitution](https://learning.postman.com/docs/sending-requests/variables/variables/)
and [URL encoding](https://blog.postman.com/introducing-the-next-generation-postman-url-processor/).
Unmatched Postman requests retain the contract's diagnostic in the report.

## Postman collection evidence

A pin with `"format": "postman"` accepts only Postman Collection v2.0/v2.1.
The unchanged file must match its SHA-256 and `info.version` (including an
explicit `null` pin when the collection publishes no version), and the pin must
name an absolute HTTP(S) `source_url`. Both single pins and `specs` lists work;
an undeclared collection cannot masquerade as OpenAPI.

Postman contracts match method, exact literal path segments, variable path
segments (`:name` and `{{name}}`), and the collection's host. Base-URL variables
bind to values published in the collection, or the explicit provider-docs
binding below, never catalog credentials or the intercepted request.
Enabled query keys, required collection headers,
authentication placement/scheme and media declarations are checked. JSON field
paths (including nested array objects) and form fields must occur in the item
or its saved examples' original request bodies. Scripts are never executed.

Dhruv approved: "Allow it, only from the provider's own docs page". A collection
pin may declare `host_bindings` for a host variable the collection never defines,
or defines only with disabled, null or empty values:

```json
{
  "format": "postman",
  "host_bindings": {
    "base_url": {
      "value": "https://api.provider.com/v1",
      "source": "https://docs.provider.com/api/reference"
    }
  }
}
```

Bindings belong to each pin (including each entry in `specs`), never to all
collections implicitly. A non-empty enabled definition at any collection or
item scope refuses a binding; a defined host is never overridden. Only host
variables are eligible, including variables embedded in a host such as
`api-{{IdBusiness}}.provider.com`. For an embedded variable, `value` names the
complete base URL and must preserve the host's literal characters. A whole base
variable can carry the documented base path; every request's remaining path
stays exactly as published. An embedded host cannot introduce a path.

Both URLs must be absolute HTTPS URLs. Their registrable domains (eTLD+1) must
match, using the pinned library's bundled public suffix list, including private
suffixes, offline. Third-party domains, lookalikes, and shared docs/mirror hosts
(including APIs.guru, Postman/getpostman, readme.io, github.io, gitbook.io,
stoplight.io and SwaggerHub) are refused. The unchanged collection remains
hash-pinned; no bound collection is written back to it.

The run lists its catalog bindings with their pin indexes; every request
matched through one records its variable, value and source. The verdict names
these weaker host attestations in `host_bindings`, and with source audit on
fetches each source through the existing `page()` cache and blocks unless it
shows the bound URL. `--no-audit` skips this fetch, just as for other documented
evidence. Bindings retain the Postman bar: at most `postman-checked`, never
`ready`, and never a replacement for saved example responses.

Every saved response is replayed with its published status, headers and exact
body text, without schema inference, response generation, placeholder changes,
or rewriting IDs. Each replay constructs a fresh node and runs its complete
operation, preserving guards, ancestry checks and readback. An item without a
saved response is blocked as `no published example response`; a parser failure
on a success replay also blocks. Reports identify Postman items, example indexes
and published response counts so the verdict can require complete replay coverage.

A published non-2xx response must produce the node's error envelope or a provider
rejection: an HTTP-status exception tied to that response, or an explicit raise
inside a status guard on that response. Unrelated exceptions (including JSON or
shape errors of the same type) still fail, as does returning success or no
output. A published 2xx response must still parse successfully. OpenAPI response
selection remains unchanged; its documented error examples are not replayed.

Postman evidence supports only `postman-checked`, with `ready: false`. Mixed
catalogs retain each OpenAPI operation's existing bar and identify the verdict
per operation. Existing OpenAPI contracts and report formats are unchanged.

## Trigger checks

A trigger operation (`x-is-trigger: true`) is verified, not just present (`triggers.py`):

- **Webhook triggers** (`ExternalWebhookTriggerMixin`): `_register_external_webhook` and
  `_unregister_external_webhook` run against the contract like any request. Each event the contract documents (the
  spec's `webhooks`, operations' `callbacks`, else the catalog's `events.json`, `{"<event>": {"body", "source",
  optional "headers", optional "webhook": a spec webhook whose schema it takes}}`) is delivered the node's own way:
  `verify_webhook_signature` with a signature computed as the catalog entry's `webhook_signature` (or the spec's
  `x-webhook-signature`) declares, which must also refuse the same body tampered with; then the control, filter, drop
  and transform hooks, `resolve_trigger_payload` and `resolve_agent_event`. At least one event must reach the trigger.
- **Poll triggers** (`PollTriggerConfigBase`): the list call is checked as any operation; the poll starts from state
  that has seen nothing, so its new-item detection must emit what the response lists, and `resolve_agent_event` must
  deliver it.
- **Field reads**: every key the node's own code reads from an event or a listed response must be in its schema, or
  in the provider's documented example where the published schema leaves it out. Reads by shared plumbing
  (`nodes/core`) don't count, nor do reads of a copy the node made.

`webhook_signature` is `{"header", "algorithm": sha1|sha256|sha512, "encoding": hex|base64, "message"
(default "{body}"; also {timestamp} {id} {url}), "format" (e.g. "t={timestamp},v1={signature}"), "prefix",
"timestamp_header", "id_header", "secret_field" (default signing_secret), "secret_encoding": utf-8|base64,
"secret_prefix", "source": "<docs URL>"}`, or `{"scheme": "none", "source"}` for unsigned deliveries, or
`{"scheme": "unsupported", "reason", "source"}` (advisory: RSA or a provider key can't be reproduced offline).
Trigger failures always block; the verdict reports each trigger as passed, failed, or not checked (another family,
such as app-event subscriptions) under `triggers`, and the source audit covers `events.json` like `witnesses.json`.

## Merge verdict

`verdict.py` turns a report and its catalog into the verdict the integration
merge gate reads: a re-cut integration PR merges only when the verdict is ready
(or `postman-checked` for a Postman-only provider), its CI is green and its
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

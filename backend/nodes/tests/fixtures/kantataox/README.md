These fixtures copy the provider’s handwritten response examples. They exercise indexed results and associations without treating generated examples as live responses.

Source: https://app.mavenlink.com/oas/specification version 1.0.0, `info.description`, Response Format (projects) and Includes (post). No live account was used.

`task-sdk.json` copies the response fixture at https://github.com/mavenlink/mavenlink_gem/blob/master/spec/lib/mavenlink/story_spec.rb . `time-entry-sdk.json` instantiates the official shared model fixture (https://github.com/mavenlink/mavenlink_gem/blob/master/spec/support/shared_examples/model.rb) with `time_entries` as passed by its time_entry_spec.rb. These are provider-authored SDK test fixtures, not recorded API responses.

The conformance artifacts record the final offline run against the hash-pinned, published contract. `contract-pin.json` records the original Swagger pin, audited conversion and known schema limits; `conformance-witnesses.json` cites the exact provider sources for the handwritten examples and official SDK fixtures. The ready verdict has no blocking items, all four triggers pass, and fourteen advisories remain for synthetic responses with noncanonical result references. No live API account was exercised.

Local validation: registry import; 44 hook/discovery/node tests; 29 integration tests selected across the full backend suite; 40 complete autofill/scope/evidence coverage tests; 82 credential-request/generic OAuth tests; hosted connect-catalog check with no Kantata violations; locked TypeScript check; 14 frontend tests including category and credential audits; 3 vendored provenance tests. The only hosted connect-catalog violation was the existing Bookeo credential type default.

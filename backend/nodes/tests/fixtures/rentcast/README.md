# RentCast contract evidence

`contract_manifest.json` identifies the unchanged provider contract (v1.0 and SHA-256).
`published_examples.json` copies each of its ten success examples verbatim, with the matching documented inputs. The node tests replay all ten examples through the real node factory and preserve the complete returned JSON, including nulls.

`conformance_verdict.json` is the supplied verdict on the requested full harness run: ready, 10 request/auth checks, no blockers. Its responses are schema-generated because the provider-authored examples fail the provider's own response schemas.

`conformance_strict_verdict.json` records a second replay with explicit witness selection: all ten blockers occur before node parsing and are schema-only fixture errors. `spec_defects.json` lists every conflicting field path and the current official documentation demonstrating that null is valid. No contract or example was corrected to obtain a pass.

The external catalog also retains the complete normal and strict reports, inputs and witnesses. No live RentCast key or account was used.

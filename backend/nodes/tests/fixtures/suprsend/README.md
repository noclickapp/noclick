# SuprSend conformance evidence

Contract: [SuprSend OpenAPI](https://docs.suprsend.com/openapi.yaml), version 1.2.2,
SHA-256 `f7f5eaaf6d6dbd4ea994f2b7eec02a9ca3159eac4673b549a781aa3a7e7bdf53`.
Evidence rung: `openapi`. No live account or test key was used.

`provider_examples.json` preserves the pinned contract's successful JSON response
examples and records their source. `request_cases.json` pairs workflow inputs
with independently specified HTTP methods, paths, queries and bodies from that
contract. Plain-text event acknowledgement (`202 OK`) and empty user deletion
(`204`) are covered directly in the test module.

The polling tests use documented message records. Their terminal-page metadata
and changing visible set simulate pagination and a new item arriving, rather
than claiming to be captured live traffic. The poll baselines existing messages,
then deduplicates message IDs. It traverses at most ten 1,000-message pages and
refuses to advance state when pagination is incomplete or repeats a cursor.
Use the tenant, workflow, channel and creation-date filters to bound busy logs.

`conformance_verdict.json` records the independently run staging conformance
harness and source audit result for all 24 actions and the new-message trigger.

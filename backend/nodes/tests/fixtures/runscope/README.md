# Runscope contract evidence

The provider-owned Swagger 2.0 contract is pinned at version 1.0.0:
https://raw.githubusercontent.com/Runscope/runscope-api-examples/master/schemas/runscope-swagger-v2.json
SHA-256: `0ff6b2b7f40e40cd29d05463dc2d05f2181b2aad595c64ad9caefd959f912a1f`.
A lossless `swagger2openapi@7.0.8` conversion is used only by the external conformance harness; the original contract is preserved.
No live account was used. The evidence rung is `openapi`.

The JSON fixtures are unmodified examples copied from the URLs in `sources.json`.
The callback trigger adds/removes only its URL on an existing shared environment, preserving the full current configuration for the documented replacement PUT. Callback URLs from shared environments also notify for inheriting test environments, so the child's environment UUID is intentionally not compared against the shared environment's ID. An optional test ID narrows deliveries.
Standard callbacks document no signature header or signing secret. The provider describes optional Basic authentication and custom headers separately for Advanced Webhooks; this integration registers standard environment callbacks. Its unique NoClick callback URL must be treated as secret.

## Published contract defects

1. `POST /buckets` requires a `NewBucket` JSON body with `team_id` in the old Swagger. The current provider example sends `name` and `team_uuid` as query parameters, with no body. The node follows the current example: https://help.blazemeter.com/apidocs/api-monitoring/buckets_create.htm
2. The `Environment` schema types `auth` and `webhooks` as strings and `parent_environment_id` as a nonnullable string. The provider's complete create/update examples use an auth object, an array of callback URLs, and a null parent. All four environment write operations preserve those documented types: https://help.blazemeter.com/apidocs/api-monitoring/environments_modify.htm and https://help.blazemeter.com/apidocs/api-monitoring/environments_create.htm
3. `GET /buckets/{bucketKey}/environments` declares a 200 response without any body schema. The current docs show a JSON environment response: https://help.blazemeter.com/apidocs/api-monitoring/environments_shared_list.htm . The unmodified conformance harness interprets the missing content schema as an empty HTTP response and ignores its documented witness. Consequently it cannot simulate registration/unregistration against this endpoint. The trigger unit tests execute both hooks against the provider's exact documented response; the event delivery checks use the provider's exact notification example and reach the agent event.

These defects are recorded without editing the published schema or weakening node behavior to match an empty fabricated response. The machine report and verdict are in the external pipeline catalog and recut record.

## Final local conformance result

The unmodified harness checked all 25 operations (24 actions and one webhook trigger), including authentication and scope checks for all 25. The verdict retains six blockers: bucket creation, four environment writes, and callback registration, covered by the three documented defects above. Event delivery passes. Four parser advisories arise from schema-less step/shared-environment responses. The literal machine verdict is `ready: false`; this PR uses the explicitly permitted documented-spec-defect exception, not a claim that the machine verdict is green. Local lifecycle, wire, discovery and hook tests pass (62 tests).

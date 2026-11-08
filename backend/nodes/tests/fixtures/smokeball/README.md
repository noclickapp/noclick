# Smokeball offline fixtures

`operations.json` exercises the 20 fixed v1 routes. Names, IDs, descriptions,
subjects and memo text use examples from the provider's published contract:
https://docs.smokeball.com/openapi.json (version 1.0).

These are request fixtures, not a record of live account access. Transport tests
use synthetic responses, exercise both required authentication headers, and
verify that accepted writes are never described as completed writes.

The event example intentionally preserves `2000-01-01T20:00:00` for both event
times and `Australia/Sydney` from the provider's EventDto examples. The official
field descriptions explicitly correlate these local times with `timeZone`:
https://docs.smokeball.com/api-reference/events/create-event

The OpenAPI `date-time` format on those fields contradicts the documented
suffix-free local values: RFC 3339 validation requires an offset. Conformance
records this provider specification defect rather than changing the documented
wire representation. An end before the start or an unknown IANA zone is
refused locally; a zero-duration event is allowed by the published contract.

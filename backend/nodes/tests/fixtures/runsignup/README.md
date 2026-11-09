# RunSignup fixtures

JSON examples copied from the official provider API documentation. These use published example identities, not live account data.

- `participants.json`: https://runsignup.com/API/race/:race_id/participants/POST
- `coupons.json`: https://runsignup.com/API/race/:race_id/coupons/POST
- `assignments.json`: https://runsignup.com/API/race/:race_id/assign-bib-chip/POST
- `entity.json`: https://runsignup.com/API/v2/auth-info/entity-info.json/GET
- `race-race_id-participants-GET.json`: https://runsignup.com/API/race/:race_id/participants/GET
- `race-race_id-participant-counts-GET.json`: https://runsignup.com/API/race/:race_id/participant-counts/GET
- `race-race_id-donations-list-GET.json`: https://runsignup.com/API/race/:race_id/donations/list/GET
- `race-race_id-removed-participants-GET.json`: https://runsignup.com/API/race/:race_id/removed-participants/GET
- `v2-volunteers-get-race-volunteer-tasks.json-GET.json`: https://runsignup.com/API/v2/volunteers/get-race-volunteer-tasks.json/GET

The entity example returns a numeric `entity_specific_id`; the OpenAPI schema incorrectly types it as a string. Both are preserved by the node. Tests also use small synthetic envelopes to exercise transport failures and empty pages.

The OpenAPI security schemes name legacy `api_key` / `api_secret` query parameters, while the official API key guide and endpoint parameter tables support v2 `rsu_api_key` plus `X-RSU-API-SECRET`. The node follows https://runsignup.com/API/ApiKeys and https://runsignup.com/API/v2/auth-info/entity-info.json/GET.

RunSignup documents boolean wire values as `T` / `F` at https://runsignup.com/API/DocOverview. The participant write schema incorrectly combines boolean type with string enums and defaults; the node sends the documented wire strings. See https://runsignup.com/API/race/:race_id/participants/POST.

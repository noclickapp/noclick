`requests.json` contains synthetic offline request/response cases for every
implemented operation. They pin methods, routes, query/body placement, project
API-key authentication, false values, and rename behavior against the published
contract at https://api.simplelocalize.io/openapi/docs.

`translations-response.json` is the verbatim response example from
https://simplelocalize.io/docs/api/read-translations/. That guide shows a flat
`data` array. The pinned OpenAPI instead puts two paged object alternatives
under the outer `data` property, and neither makes its properties required.
The node accepts the guide's flat response and the contract's nested objects,
preserving pagination metadata whenever present. It refuses an empty object
without translation data. Consequently a generated empty OpenAPI response is
an advisory parser failure, while the guide example passes the native test.

Authentication and account-specific project evidence:
https://simplelocalize.io/docs/api/get-started/.
Language examples: https://simplelocalize.io/docs/api/language-api/.
Customer examples: https://simplelocalize.io/docs/api/customer-specific-api/.

All tests use synthetic credentials and an intercepted HTTP transport.

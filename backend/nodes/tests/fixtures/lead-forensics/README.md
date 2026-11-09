Lead Forensics examples copied from the provider-published OpenAPI 1.0 contract:
https://leadforensics-api.readme.io/openapi/59970b303013510019572b1e

`responses.json` contains each selected operation's documented 200 response.
`inputs.json` uses documented request values, with ISO dates for the endpoints
whose contract declares the date format. The conversion filter uses an ID from the published conversion reference list,
because its request example erroneously names businessid. The GetVisit test
uses the ID in the documented response, which differs from its request example.
Tests use synthetic credentials and do not contact the API.

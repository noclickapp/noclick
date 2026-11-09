# BatchDialer public API conformance

Pinned documents are BatchDialer Public API 1.0.0 and Campaigns, Contacts,
Phone-numbers, Recent-contacts, Tasks and Transcriptions 1.0.
No published contract bytes are modified.

The offline harness checks 16 implemented operations. Its only four blocking
findings are provider contract defects:

- `GET`, `PUT` and `DELETE /contact/{contactID}`: Contacts declares path-level
  `parameters` as an object with keys `0` and `undefined` instead of an array.
  The `undefined` entry has a required empty parameter name absent from the
  route. The named `contactID` parameter is supplied by each operation. An
  additional unnamed path component cannot be sent on this published route.
  Source: https://developer.batchdialer.com/api/v1/projects/batchdialer/batchdialer/nodes/reference/Contacts.yaml
- `GET /cdrs/{cdrID}/transcription`: Transcriptions declares an optional query
  parameter with `in: query` and a string schema, but omits its `name`.
  The node sends the documented `cdrID` path parameter and API-key header;
  there is no documented query parameter to supply.
  Source: https://developer.batchdialer.com/api/v1/projects/batchdialer/batchdialer/nodes/reference/Transcriptions.yaml

Tests replay the published response examples and assert exact requests,
including JSON request bodies on the two documented GET routes. This is
contract evidence, not a live-account test. Tasks publishes no operations.
The JSON transcription endpoint is supported; HTML transcription and phone
number purchase/replacement/deletion are outside this integration's operations.

The recent-calls example is also internally inconsistent: `GET /cdrs` declares
`comments.items` as strings but its example includes a comment object. The mock
suite replays that unchanged example successfully. The conformance harness uses
a generated schema-valid response for that operation instead; the other 15
operations parse provider-authored examples.
Source: https://developer.batchdialer.com/api/v1/projects/batchdialer/batchdialer/nodes/reference/Recent-contacts.yaml

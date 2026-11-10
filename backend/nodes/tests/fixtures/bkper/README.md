# Bkper v5 response fixtures

`responses.json` copies the provider's 200 JSON examples for the 23 implemented
operations from https://bkper.com/docs/api/rest/openapi.json (version v5).
Original contract SHA-256:
`5dc2ac07bcf8c73ce2c5d56321309819cdab049163d2495ef353fa4ce73eea1f`.

The Event example is the first `listEvents` item (FILE_CREATED). Enum dispatch
tests substitute each value of the published Event.type enum into that structure;
these variants are tests of the published schema, not recorded live deliveries.
JWT tests use a generated local RSA key, never a provider token or private key.

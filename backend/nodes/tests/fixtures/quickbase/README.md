Quickbase conformance evidence
=============================

The OpenAPI document is the provider-published contract, version 1.0.0, pinned by
SHA-256 in manifest.json. Its source is https://developer.quickbase.com/qb-openapi-v3.json.
The downloaded current document matches that pin. All credentials here are fake.

inputs.json translates the contract's Insert record request example and query
schema example into complete NoClick configs. Array fields use JSON editors;
the node validates and decodes them before sending native JSON to Quickbase.
responses.json contains provider examples, with schema-generated values for
response properties that have no example.

report.json and verdict.json record offline contract conformance for all 20
operations. No live Quickbase account, token or OAuth app was used. Read access
to the credential's app supplies connection evidence; it does not prove write access.

Checkfront request fixtures exercise all 25 native operation mappings through httpx.
They are offline test inputs, not captured account data or provider response witnesses.

Provider contract: https://storage.googleapis.com/cf-apiv4-docs-bucket/v4.0-Management.json
API version: 4.0. Authentication uses the documented API-key/API-secret token pair.
The published contract describes migrated tenant hosts and the global limit/offset
pagination convention. Tests preserve trailing slashes where the contract uses them.

The Customer schema root is marked readOnly even though POST /customers and
PATCH /customers/{customerId} use it for request bodies. Their endpoint descriptions
and the 2021-07-12 Customers changelog explicitly document nested fields for create
and update. These operations intentionally follow those documented write semantics.

The conformance catalog and report are maintained outside this branch in
/root/fanout/catalog/checkfront; no harness implementation is vendored here.
